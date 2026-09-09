"""
這是整個系統的「總指揮」：收到前端請求 → 依序問 Task A、Task B →
把兩邊的結果比對整合 → 套用對應演算法算出「處理前後對照」 → 回傳給前端。

資料流：
    前端表單
      → Task A（LLM）產生合成假資料
      → Task B（LLM）判斷技術 + 給滑桿預設值/範圍 + 給 Excel 公式模板
      → 後端用「Task B 給的預設值」跑一次確定性演算法，算出處理後示範資料
      → 一起回傳給前端（含 session_id）
    之後使用者拖滑桿：
      Excel 公式 → 前端自己字串取代，不打後端
      示範資料   → 打 POST /recalculate（純程式運算，不重新呼叫 LLM）

本次修改（與你上傳的版本相比），四處：

(1) 【最重要】示範資料改用 LLM 給的 default_param_value 計算。
    原本 _apply_technique 裡把參數寫死成 k=5、epsilon=1.0、bucket_size=5、
    level="month"、遮罩用 apply_mask 的預設（右側 4 碼）。
    這代表：LLM 說「信用卡建議遮 8 碼」，滑桿初始位置顯示 8，
    但畫面上的「處理後」示範資料卻是遮 4 碼 —— 滑桿跟資料從一開始就對不上，
    使用者要先動一下滑桿才會看到正確結果。
    你的需求寫明「LLM 必須先給定一個預設值」，這個預設值就應該是
    第一次示範資料的計算依據，現在改成如此。

(2) k-匿名改成「所有被判為 k_anonymity_group 的欄位一起分組」。
    原本是每個欄位各自呼叫 apply_k_anonymity_group(quasi_identifiers=[單一欄位])，
    但 k-匿名保護的是「年齡＋地區＋性別」這種組合的不可辨識性，
    逐欄分開算在定義上就不成立（也跟 system instruction 寫的
    「多個可組合識別個人的欄位 → k_anonymity_group」矛盾）。

(3) 新增 param_key，並把 mask_position 一併回傳給前端（見 schemas/responses.py 說明）。

(4) _session_cache 加上筆數上限。原本是無上限的 dict，每次 /analyze 都塞一筆、
    永遠不刪，服務跑久了會持續吃記憶體（雖然只存假資料，仍是資源洩漏）。
    改用 OrderedDict 做簡易 LRU，超過上限就丟掉最舊的。
"""

import logging
import uuid
from collections import OrderedDict

from core.logging_config import safe_log_context
from core.param_utils import coerce_float, coerce_int
from fastapi import APIRouter
from schemas.requests import AnalyzeRequest
from schemas.responses import AnalyzeResponse, FieldResult
from services.k_anonymity import apply_k_anonymity_group, check_k_anonymity_feasibility
from services.privacy_techniques import (
    TECHNIQUE_HANDLERS,
    apply_generalize_date,
    apply_mask,
)
from services.synthetic_data import generate_synthetic_data
from services.technique_selector import select_techniques

router = APIRouter(prefix="/analyze", tags=["analyze"])
logger = logging.getLogger(__name__)

# 記憶體暫存區：session_id → session（結構見 _build_session）
# 純粹放在 process 記憶體裡，不寫檔、不進資料庫，符合「不落地儲存」的要求。
# 用 OrderedDict 做簡易 LRU，避免長時間運行後無上限成長。
_SESSION_CACHE_MAX_ENTRIES = 200
_session_cache: "OrderedDict[str, dict]" = OrderedDict()

# 技術代碼 → /recalculate 的 params 該用哪個 key。
# 這是固定規則，由後端決定，不交給 LLM 判斷。
_PARAM_KEY_BY_TECHNIQUE = {
    "mask": "length",
    "k_anonymity_group": "k",
    "differential_privacy": "epsilon",
    # generalize 依 data_type 分成兩種，另外處理
    "suppress": None,
}


@router.post("", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    if not request.fields:
        raise ValueError("至少需要提供一個欄位規格")

    # --- 第一步：呼叫 Task A 生成合成假資料 ---
    task_a_result = await generate_synthetic_data(request.fields)

    if task_a_result.status == "need_clarification":
        logger.info(
            "Task A 需要澄清",
            extra=safe_log_context(endpoint="analyze", status="need_clarification"),
        )
        return {
            "status": "need_clarification",
            "source": "synthetic_data",
            "field": task_a_result.clarification_field,
            "question": task_a_result.clarification_question,
        }

    if task_a_result.status == "refused":
        logger.warning(
            "Task A 拒絕請求",
            extra=safe_log_context(endpoint="analyze", status="refused"),
        )
        raise ValueError(task_a_result.refused_message)

    # --- 第二步：呼叫 Task B 判斷技術，同時取得 Excel 公式與滑桿設定 ---
    task_b_result = await select_techniques(request.fields)

    if task_b_result.status == "need_clarification":
        logger.info(
            "Task B 需要澄清",
            extra=safe_log_context(endpoint="analyze", status="need_clarification"),
        )
        return {
            "status": "need_clarification",
            "source": "technique_selection",
            "field": task_b_result.clarification_field,
            "question": task_b_result.clarification_question,
        }

    if task_b_result.status == "refused":
        logger.warning(
            "Task B 拒絕請求",
            extra=safe_log_context(endpoint="analyze", status="refused"),
        )
        raise ValueError(task_b_result.refused_message)

    # --- 第三步：兩邊都成功，開始整合 ---
    field_values = _pivot_records_to_columns(task_a_result.records)
    row_records = _records_to_row_dicts(task_a_result.records)
    technique_map = {f.field: f for f in task_b_result.fields}

    # 「欄位名稱 → 使用者當初填的 data_type」對照表，
    # generalize 技術要靠這個分辨是日期泛化還是數值泛化。
    field_type_map = {f.name: f.data_type for f in request.fields}

    # k-匿名要整組準識別欄位一起看，所以先獨立算好，迴圈裡再取用
    k_group_fields = [
        name
        for name in field_values
        if name in technique_map
        and technique_map[name].technique == "k_anonymity_group"
    ]
    k_rows: list[dict[str, str]] = []
    k_notice: str | None = None
    k_default = 5
    if k_group_fields:
        # 同一組準識別欄位共用一個 k；若 LLM 對不同欄位給了不同建議值，
        # 取最大的那個（保護強度較高的一邊），避免出現「同一組資料兩種 k」的矛盾
        k_default = max(
            coerce_int(technique_map[name].default_param_value, fallback=5)
            for name in k_group_fields
        )
        k_rows = apply_k_anonymity_group(row_records, k_group_fields, k_default)
        feasibility = check_k_anonymity_feasibility(
            row_records, k_group_fields, k_default
        )
        if feasibility["groups_merged_to_other"] > 0:
            k_notice = (
                f"目前示範資料共 {len(row_records)} 筆，依 k={k_default} 分組後有 "
                f"{feasibility['merged_bucket_size']} 筆的組合筆數不足，已歸併為「其他」。"
                "示範資料筆數偏少時這是正常現象，實際套用時請以完整資料集評估。"
            )

    results: list[FieldResult] = []
    session_fields: dict[str, dict] = {}

    for field_name, raw_values in field_values.items():
        tech_info = technique_map.get(field_name)
        if tech_info is None:
            logger.warning(
                f"欄位「{field_name}」在 Task B 結果中找不到對應判斷，已跳過"
            )
            continue

        data_type = field_type_map.get(field_name, "text")
        param_key = _param_key_for(tech_info.technique, data_type)

        if tech_info.technique == "k_anonymity_group":
            processed_values = [row.get(field_name, "") for row in k_rows]
            notice = k_notice
            param_group = list(k_group_fields)
            # 整組共用同一個 k，所以把滑桿預設值一併對齊成實際採用的 k，
            # 避免出現「滑桿顯示 2、但畫面上的資料其實是用 3 算的」
            default_param_value = str(k_default)
        else:
            processed_values = _apply_technique(
                technique=tech_info.technique,
                raw_values=raw_values,
                field_name=field_name,
                data_type=data_type,
                param_value=tech_info.default_param_value,
                mask_position=tech_info.mask_position,
            )
            notice = None
            param_group = None
            default_param_value = tech_info.default_param_value

        # Task B 的滑桿與公式欄位原封不動搬進 FieldResult，後端不再自己組公式。
        # param_type 若是 "none"（suppress），其餘欄位已在
        # schemas/llm_outputs.py 的 model_validator 裡被強制清成 None。
        results.append(
            FieldResult(
                field_name=field_name,
                original_samples=raw_values,
                processed_samples=processed_values,
                technique=tech_info.technique,
                suggested_param=tech_info.suggested_param,
                reason=tech_info.reason,
                param_type=tech_info.param_type,
                param_key=param_key,
                param_group=param_group,
                default_param_value=default_param_value,
                param_min=tech_info.param_min,
                param_max=tech_info.param_max,
                param_step=tech_info.param_step,
                mask_position=tech_info.mask_position,
                excel_formula_template=tech_info.excel_formula_template,
                param_options=tech_info.param_options,
                notice=notice,
            )
        )

        session_fields[field_name] = {
            "raw_values": raw_values,
            "technique": tech_info.technique,
            "data_type": data_type,
            "param_key": param_key,
            "default_param_value": default_param_value,
            "mask_position": tech_info.mask_position,
        }

    session_id = str(uuid.uuid4())
    _store_session(
        session_id,
        {
            "fields": session_fields,
            "row_records": row_records,
            "k_group_fields": k_group_fields,
        },
    )

    logger.info(
        "analyze 完成",
        extra=safe_log_context(
            endpoint="analyze",
            status="ok",
            session_id=session_id,
            field_count=len(results),
        ),
    )

    return {
        "status": "ok",
        "session_id": session_id,
        "results": results,
    }


# ============ 內部輔助函式 ============


def _store_session(session_id: str, session: dict) -> None:
    """寫入 session 並維持快取大小上限（超過就丟掉最舊的一筆）。"""
    _session_cache[session_id] = session
    _session_cache.move_to_end(session_id)
    while len(_session_cache) > _SESSION_CACHE_MAX_ENTRIES:
        evicted_id, _ = _session_cache.popitem(last=False)
        logger.info(
            "session 快取已達上限，淘汰最舊的工作階段",
            extra=safe_log_context(
                endpoint="analyze", status="evicted", session_id=evicted_id
            ),
        )


def _param_key_for(technique: str, data_type: str) -> str | None:
    """依技術種類決定 /recalculate 的 params 該用哪個 key。"""
    if technique == "generalize":
        return "level" if data_type == "date" else "bucket_size"
    return _PARAM_KEY_BY_TECHNIQUE.get(technique)


def _pivot_records_to_columns(records) -> dict[str, list[str]]:
    """把 row-based 資料轉成「欄位名稱 → 該欄位所有值的清單」，順序即列的順序。"""
    columns: dict[str, list[str]] = {}
    for record in records:
        for f in record.fields:
            columns.setdefault(f.field, []).append(f.value)
    return columns


def _records_to_row_dicts(records) -> list[dict[str, str]]:
    """把 row-based 資料轉成 [{"姓名": "...", "電話": "..."}, ...]，供 k-匿名使用。"""
    return [{f.field: f.value for f in record.fields} for record in records]


def _apply_technique(
    technique: str,
    raw_values: list[str],
    field_name: str,
    data_type: str,
    param_value,
    mask_position: str | None,
) -> list[str]:
    """
    依技術種類分派到對應的處理邏輯，回傳「處理後」的值清單。
    純粹用於畫面上的示範對照，跟 Excel 公式的產生完全無關。

    param_value 是 LLM 給的 default_param_value（字串），
    這裡負責把它轉成各演算法需要的型別；轉不動就退回各技術的保守預設值。
    k_anonymity_group 不走這裡（需要整批記錄，由呼叫端另外處理）。
    """

    if technique == "mask":
        length = coerce_int(param_value, fallback=4)
        position = mask_position or "right"
        return [apply_mask(v, position=position, length=length) for v in raw_values]

    if technique == "suppress":
        handler = TECHNIQUE_HANDLERS["suppress"]
        return [handler(v) for v in raw_values]

    if technique == "differential_privacy":
        handler = TECHNIQUE_HANDLERS["differential_privacy"]
        epsilon = coerce_float(param_value, fallback=1.0)
        if epsilon <= 0:
            logger.warning(
                f"欄位「{field_name}」的 epsilon 不合法（{epsilon}），改用 1.0"
            )
            epsilon = 1.0
        processed = []
        for index, v in enumerate(raw_values):
            try:
                # seed 固定為列索引：同一個 epsilon 重算兩次結果一致，
                # 使用者拖滑桿時看到的變化才確定是 epsilon 造成的
                processed.append(str(handler(float(v), epsilon=epsilon, seed=index)))
            except (TypeError, ValueError):
                logger.warning(f"欄位「{field_name}」差分隱私失敗（非數值），值：{v}")
                processed.append(v)
        return processed

    if technique == "generalize":
        if data_type == "date":
            level = str(param_value) if param_value in ("year", "month") else "month"
            return [apply_generalize_date(v, level=level) for v in raw_values]

        handler = TECHNIQUE_HANDLERS["generalize"]
        bucket_size = coerce_int(param_value, fallback=5)
        if bucket_size <= 0:
            logger.warning(
                f"欄位「{field_name}」的區間大小不合法（{bucket_size}），改用 5"
            )
            bucket_size = 5
        processed = []
        for v in raw_values:
            try:
                processed.append(handler(float(v), bucket_size=bucket_size))
            except (TypeError, ValueError):
                logger.warning(f"欄位「{field_name}」數值泛化失敗（非數值），值：{v}")
                processed.append(v)
        return processed

    logger.warning(f"未知的技術代碼: {technique}")
    return raw_values


def get_session_cache() -> "OrderedDict[str, dict]":
    """讓 routers/recalculate.py 可以匯入同一份 session 暫存區。"""
    return _session_cache
