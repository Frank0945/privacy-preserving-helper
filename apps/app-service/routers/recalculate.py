"""
這支路由對應需求裡的：
「使用者調整滑桿參數 → 前端 → 後端：POST /api/recalculate（純程式運算，不重新呼叫LLM）」

這裡完全不 import core.llm_client，不會打任何 API，
只是拿 analyze 階段存在記憶體裡的原始假資料，重新跑一次
services/privacy_techniques.py 或 services/k_anonymity.py 裡的函式。

錯誤處理風格說明：
- 「session 找不到」用 HTTPException(404, ...)，因為這是「資源不存在」，
  跟 main.py 的 domain_exception_handler 固定回 400 的語意不同，
  維持用 HTTPException 讓 FastAPI 用內建方式回傳 404，狀態碼比較精確。
- 其他理論上不太會發生的商業邏輯錯誤才用 ValueError，交給 main.py 統一處理。
"""

import logging

from fastapi import APIRouter, HTTPException
from routers.analyze import get_session_cache
from schemas.requests import RecalculateRequest
from schemas.responses import RecalculateResponse
from services.excel_formula import generate_excel_formula
from services.k_anonymity import apply_k_anonymity_group
from services.privacy_techniques import TECHNIQUE_HANDLERS

router = APIRouter(prefix="/recalculate", tags=["recalculate"])
logger = logging.getLogger(__name__)


@router.post("", response_model=RecalculateResponse)
async def recalculate(request: RecalculateRequest):
    session_cache = get_session_cache()
    session = session_cache.get(request.session_id)

    if session is None:
        # session 可能是服務重啟後遺失（因為只存在記憶體），
        # 明確回 404 並告訴前端「請重新分析」，而不是回一個模糊的 500 錯誤。
        raise HTTPException(404, "此工作階段已過期或不存在，請重新執行分析")

    field_data = session.get(request.field_name)
    if field_data is None:
        raise HTTPException(404, f"欄位「{request.field_name}」不存在於此工作階段中")

    technique = field_data["technique"]
    raw_values = field_data["raw_values"]
    params = request.params

    processed_values = _recompute(
        technique, raw_values, field_data, request.field_name, params
    )
    excel_formula = generate_excel_formula(technique, params=params)

    return RecalculateResponse(
        processed_samples=processed_values, excel_formula=excel_formula
    )


def _recompute(
    technique: str,
    raw_values: list[str],
    field_data: dict,
    field_name: str,
    params: dict,
) -> list[str]:
    """
    跟 routers/analyze.py 裡的 _apply_technique 邏輯相似，
    差別是這裡的參數（position、length、bucket_size、k、epsilon...）
    是使用者透過滑桿即時傳進來的，而不是固定的預設值。
    """

    if technique == "mask":
        handler = TECHNIQUE_HANDLERS["mask"]
        position = params.get("position", "right")
        length = params.get("length", 4)
        return [handler(v, position=position, length=length) for v in raw_values]

    if technique == "generalize":
        data_type = field_data.get("data_type", "text")

        if data_type == "date":
            from services.privacy_techniques import apply_generalize_date

            level = params.get("level", "month")  # 滑桿可切換 "year" 或 "month"
            processed = []
            for v in raw_values:
                try:
                    processed.append(apply_generalize_date(v, level=level))
                except (ValueError, IndexError):
                    processed.append(v)
            return processed
        else:
            handler = TECHNIQUE_HANDLERS["generalize"]
            bucket_size = params.get("bucket_size", 5)
            processed = []
            for v in raw_values:
                try:
                    processed.append(handler(float(v), bucket_size=bucket_size))
                except ValueError:
                    processed.append(v)
            return processed

    if technique == "suppress":
        handler = TECHNIQUE_HANDLERS["suppress"]
        return [handler(v) for v in raw_values]

    if technique == "differential_privacy":
        handler = TECHNIQUE_HANDLERS["differential_privacy"]
        epsilon = params.get("epsilon", 1.0)
        processed = []
        for v in raw_values:
            try:
                processed.append(str(handler(float(v), epsilon=epsilon)))
            except ValueError:
                processed.append(v)
        return processed

    if technique == "k_anonymity_group":
        k = params.get("k", 5)
        row_records = field_data["row_records"]
        grouped = apply_k_anonymity_group(
            row_records, quasi_identifiers=[field_name], k=k
        )
        return [row.get(field_name, "") for row in grouped]

    logger.warning(f"recalculate 遇到未知技術代碼: {technique}")
    return raw_values
