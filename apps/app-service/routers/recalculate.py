"""
這支路由對應「使用者調整滑桿參數 → 前端 → 後端：POST /recalculate（純程式運算，
不重新呼叫 LLM）」的需求，而且只重算「處理前後對照」的實際資料範例。

Excel 公式不由這支路由負責：/analyze 階段就已經由 LLM 提供
excel_formula_template（含 {value} 佔位符）或 param_options（類別型選項），
前端拖動滑桿時直接用字串取代或查表就能算出新公式，不需要打這支 API。

錯誤處理風格：
- 「session 找不到」用 HTTPException(404)，這是「資源不存在」，
  跟 main.py 的 domain_exception_handler 固定回 400 的語意不同。
- 其他商業邏輯錯誤才用 ValueError，交給 main.py 統一處理。

本次修改（與你上傳的版本相比），三處：

(1) 參數改用 param_key 通用取值，並以「/analyze 當時的 LLM 預設值」當回退，
    而不是像原本那樣每種技術各自寫死一組 fallback（position="right"、
    length=4、bucket_size=5、k=5、epsilon=1.0）。
    原本的寫法有一個實際會出錯的情況：前端只送了滑桿的值、沒送 position，
    遮罩就會退回 "right"，但 LLM 判斷的是 "middle" —— 使用者一動滑桿，
    遮蔽位置就自己跳掉了。

(2) k-匿名改成整組準識別欄位一起重算（與 /analyze 的處理方式一致），
    原本是單一欄位自己分組，在定義上不成立。

(3) 回傳值多了 field_name 與 applied_param（見 schemas/responses.py）。
"""

import logging

from core.param_utils import coerce_float, coerce_int
from fastapi import APIRouter, HTTPException
from routers.analyze import get_session_cache
from schemas.requests import RecalculateRequest
from schemas.responses import RecalculateResponse
from services.k_anonymity import apply_k_anonymity_group
from services.privacy_techniques import (
    TECHNIQUE_HANDLERS,
    apply_generalize_date,
    apply_mask,
)

router = APIRouter(prefix="/recalculate", tags=["recalculate"])
logger = logging.getLogger(__name__)


@router.post("", response_model=RecalculateResponse)
async def recalculate(request: RecalculateRequest):
    session_cache = get_session_cache()
    session = session_cache.get(request.session_id)

    if session is None:
        # session 只存在記憶體，服務重啟或被 LRU 淘汰後就會不見。
        # 明確回 404 並告訴前端「請重新分析」，而不是回一個模糊的 500。
        raise HTTPException(404, "此工作階段已過期或不存在，請重新執行分析")

    field_data = session["fields"].get(request.field_name)
    if field_data is None:
        raise HTTPException(404, f"欄位「{request.field_name}」不存在於此工作階段中")

    processed_values, applied_param = _recompute(
        session=session,
        field_name=request.field_name,
        field_data=field_data,
        params=request.params,
    )

    return RecalculateResponse(
        field_name=request.field_name,
        applied_param=applied_param,
        processed_samples=processed_values,
    )


def _recompute(
    session: dict,
    field_name: str,
    field_data: dict,
    params: dict,
) -> tuple[list[str], str | None]:
    """
    跟 routers/analyze.py 裡的 _apply_technique 邏輯相同，
    差別是參數來自使用者的滑桿，而不是 LLM 的預設值。

    取參數的順序：
      1. 前端送來的 params[param_key]
      2. /analyze 當時 LLM 給的 default_param_value
      3. 各技術的保守內建值

    回傳 (處理後的值清單, 這次實際採用的參數字串)。
    """
    technique = field_data["technique"]
    raw_values = field_data["raw_values"]
    data_type = field_data.get("data_type", "text")
    param_key = field_data.get("param_key")

    raw_param = params.get(param_key) if param_key else None
    if raw_param is None:
        raw_param = field_data.get("default_param_value")

    if technique == "mask":
        length = coerce_int(raw_param, fallback=4)
        # 遮蔽位置不是滑桿參數，固定沿用 LLM 在 /analyze 階段的判斷；
        # 但仍允許前端明確覆寫（例如未來想做成可切換的按鈕組）。
        position = params.get("position") or field_data.get("mask_position") or "right"
        processed = [
            apply_mask(v, position=position, length=length) for v in raw_values
        ]
        return processed, str(length)

    if technique == "suppress":
        # 抑制沒有可調參數（param_type 一定是 "none"），前端理論上不會呼叫這裡，
        # 但真的呼叫了也要有合理行為，而不是丟例外。
        handler = TECHNIQUE_HANDLERS["suppress"]
        return [handler(v) for v in raw_values], None

    if technique == "differential_privacy":
        handler = TECHNIQUE_HANDLERS["differential_privacy"]
        epsilon = coerce_float(raw_param, fallback=1.0)
        if epsilon <= 0:
            logger.warning(
                f"欄位「{field_name}」收到不合法的 epsilon（{epsilon}），改用 1.0"
            )
            epsilon = 1.0
        processed = []
        for index, v in enumerate(raw_values):
            try:
                processed.append(str(handler(float(v), epsilon=epsilon, seed=index)))
            except (TypeError, ValueError):
                processed.append(v)
        return processed, str(epsilon)

    if technique == "generalize":
        if data_type == "date":
            level = raw_param if raw_param in ("year", "month") else "month"
            return [apply_generalize_date(v, level=level) for v in raw_values], level

        handler = TECHNIQUE_HANDLERS["generalize"]
        bucket_size = coerce_int(raw_param, fallback=5)
        if bucket_size <= 0:
            logger.warning(
                f"欄位「{field_name}」收到不合法的區間大小（{bucket_size}），改用 5"
            )
            bucket_size = 5
        processed = []
        for v in raw_values:
            try:
                processed.append(handler(float(v), bucket_size=bucket_size))
            except (TypeError, ValueError):
                processed.append(v)
        return processed, str(bucket_size)

    if technique == "k_anonymity_group":
        k = coerce_int(raw_param, fallback=5)
        if k < 1:
            k = 1
        row_records = session["row_records"]
        # 與 /analyze 一致：整組準識別欄位一起分組，而不是單一欄位自己分
        quasi_identifiers = session.get("k_group_fields") or [field_name]
        grouped = apply_k_anonymity_group(row_records, quasi_identifiers, k)
        return [row.get(field_name, "") for row in grouped], str(k)

    logger.warning(f"recalculate 遇到未知技術代碼: {technique}")
    return raw_values, None
