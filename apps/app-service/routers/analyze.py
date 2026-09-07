"""
這是整個系統的「總指揮」：收到前端請求 → 依序問 Task A、Task B →
把兩邊的結果比對整合 → 套用對應演算法 → 產生 Excel 公式 → 回傳給前端。

這個版本配合你 main.py 既有的錯誤處理慣例：
- 「LLM 拒絕請求」這類商業邏輯錯誤，改丟 ValueError，
  讓 main.py 的 domain_exception_handler 自動接住，統一轉成
  {"status": "error", "message": "..."} 格式的 400 回應。
- 不再需要在這個檔案裡 import HTTPException 或自己組 JSONResponse，
  錯誤處理完全交給 main.py 集中管理，router 只需要專心處理正常流程。
"""

import logging
import re
import uuid

from core.logging_config import safe_log_context
from fastapi import APIRouter
from schemas.requests import AnalyzeRequest
from schemas.responses import FieldResult
from services.excel_formula import generate_excel_formula
from services.privacy_techniques import TECHNIQUE_HANDLERS
from services.synthetic_data import generate_synthetic_data
from services.technique_selector import select_techniques

router = APIRouter(prefix="/analyze", tags=["analyze"])
logger = logging.getLogger(__name__)

# 記憶體暫存區：session_id → {欄位名稱: {"raw_values": [...], "technique": "..."}}
# 純粹放在 process 記憶體裡，不寫檔、不進資料庫，符合「不落地儲存」的要求。
_session_cache: dict[str, dict] = {}


@router.post("")
async def analyze(request: AnalyzeRequest):
    if not request.fields:
        # 用 ValueError 而不是自己組 400 回應，讓 main.py 的
        # domain_exception_handler 統一處理，格式跟其他商業邏輯錯誤一致。
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

    # --- 第二步：呼叫 Task B 判斷隱私保護技術 ---
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

    results: list[FieldResult] = []
    session_data: dict[str, dict] = {}

    for field_name, raw_values in field_values.items():
        tech_info = technique_map.get(field_name)
        if tech_info is None:
            logger.warning(
                f"欄位「{field_name}」在 Task B 結果中找不到對應判斷，已跳過"
            )
            continue

        data_type = "date" if _is_date_field(raw_values) else "text"

        processed_values = _apply_technique(
            technique=tech_info.technique,
            raw_values=raw_values,
            row_records=row_records,
            field_name=field_name,
            data_type=data_type,
        )

        adjustable_params = _default_params_for_technique(
            tech_info.technique, data_type
        )
        excel_formula = generate_excel_formula(
            tech_info.technique, params=adjustable_params
        )

        results.append(
            FieldResult(
                field_name=field_name,
                original_samples=raw_values,
                processed_samples=processed_values,
                technique=tech_info.technique,
                suggested_param=tech_info.suggested_param,
                reason=tech_info.reason,
                excel_formula=excel_formula,
                adjustable_params=adjustable_params,
            )
        )

        session_data[field_name] = {
            "raw_values": raw_values,
            "technique": tech_info.technique,
            "row_records": row_records,
            "data_type": data_type,  # 新增：讓 recalculate.py 拿得到正確型別
        }
    session_id = str(uuid.uuid4())
    _session_cache[session_id] = session_data

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
        "results": [r.model_dump() for r in results],
    }


# ============ 內部輔助函式 ============


_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date_field(raw_values: list[str]) -> bool:
    """
    用抽樣的方式判斷欄位是不是日期型態：檢查前幾筆非空值是否都符合
    YYYY-MM-DD 格式。故意做成跟 privacy_techniques.py 一樣的純規則判斷，
    不靠 LLM，確保同樣輸入永遠得到同樣判斷結果。
    """
    sample = [v for v in raw_values[:5] if v]
    if not sample:
        return False
    return all(bool(_DATE_PATTERN.match(v)) for v in sample)


def _pivot_records_to_columns(records) -> dict[str, list[str]]:
    """把 row-based 資料轉成「欄位名稱 → 該欄位所有值的清單」。"""
    columns: dict[str, list[str]] = {}
    for record in records:
        for f in record.fields:
            columns.setdefault(f.field, []).append(f.value)
    return columns


def _records_to_row_dicts(records) -> list[dict[str, str]]:
    """把 row-based 資料轉成 [{"姓名": "...", "電話": "..."}, ...]，供 k-匿名使用。"""
    rows = []
    for record in records:
        row = {f.field: f.value for f in record.fields}
        rows.append(row)
    return rows


def _apply_technique(
    technique: str,
    raw_values: list[str],
    row_records: list[dict[str, str]],
    field_name: str,
    data_type: str = "text",
) -> list[str]:
    """依技術種類分派到對應的處理邏輯，回傳處理後的值清單。"""

    if technique == "k_anonymity_group":
        from services.k_anonymity import apply_k_anonymity_group

        grouped = apply_k_anonymity_group(
            row_records, quasi_identifiers=[field_name], k=5
        )
        return [row.get(field_name, "") for row in grouped]

    if technique == "differential_privacy":
        handler = TECHNIQUE_HANDLERS["differential_privacy"]
        processed = []
        for v in raw_values:
            try:
                processed.append(str(handler(float(v), epsilon=1.0)))
            except ValueError:
                processed.append(v)
        return processed

    if technique == "generalize":
        if data_type == "date":
            from services.privacy_techniques import apply_generalize_date

            processed = []
            for v in raw_values:
                try:
                    processed.append(apply_generalize_date(v, level="year"))
                except (ValueError, IndexError):
                    processed.append(v)
            return processed

        handler = TECHNIQUE_HANDLERS["generalize"]
        processed = []
        for v in raw_values:
            try:
                processed.append(handler(float(v), bucket_size=5))
            except ValueError:
                processed.append(v)
        return processed

    if technique in ("mask", "suppress"):
        handler = TECHNIQUE_HANDLERS[technique]
        return [handler(v) for v in raw_values]

    logger.warning(f"未知的技術代碼: {technique}")
    return raw_values


def _default_params_for_technique(technique: str, data_type: str = "text") -> dict:
    """每種技術給前端一組預設的可調參數，前端依這個字典動態畫出滑桿。"""
    if technique == "generalize" and data_type == "date":
        return {"level": "year"}

    defaults = {
        "mask": {"position": "right", "length": 4},
        "generalize": {"bucket_size": 5},
        "k_anonymity_group": {"k": 5},
        "suppress": {},
        "differential_privacy": {"epsilon": 1.0},
    }
    return defaults.get(technique, {})


def get_session_cache() -> dict[str, dict]:
    """讓 routers/recalculate.py 可以匯入同一份 session 暫存區。"""
    return _session_cache
