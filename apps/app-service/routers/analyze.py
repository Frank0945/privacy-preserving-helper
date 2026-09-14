"""
API 路由層。所有輸入/輸出皆使用 Pydantic model，
FastAPI 會依此自動產生 /docs（Swagger UI）與 /redoc 文件。

只有一支 /api/analyze。使用者拖動滑桿後的「處理後」對照表由前端執行
後端回傳的 Excel 公式取得，不需要再呼叫後端。

錯誤回應刻意只有三種狀態碼，因為前端對每一種的處理不同：
  400 顯示 LLM 給的訊息｜422 標出出錯的欄位｜502 顯示「稍後再試」
配額用盡、逾時、Gemini 故障都歸在 502（前端做的事一樣），
需要細分時看 body 的 error_code。
"""

from __future__ import annotations

import logging

from core.llm_client import LLMOutputError, LLMRefusedError, LLMUpstreamError
from core.orchestrator import analyze as run_analyze
from core.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ErrorDetail,
    ValidationErrorResponse,
)
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["privacy-analysis"])

_DESCRIPTION = """
**流程**

1. 呼叫 LLM Task B 判斷每個欄位適合的隱私保護技術與建議參數
2. 呼叫 LLM Task A 產生合成假資料（`sample_before`）
3. 呼叫 LLM Task C 產生 Excel 公式與滑桿規格（會拿到 Task A 的範例資料以便驗算）
4. 後端做安全檢查；沒通過就把原因回饋給 Task C 重寫一次，
   仍不通過則該欄位回報 `formula_error`，不替換成其他公式
5. 回傳滑桿設定、假資料與公式

後端不內建任何公式。技術判斷與公式全部由 LLM 決定。

**欄位對應**

`fields[].id` 由前端產生，後端與三個 LLM 任務全程使用同一組 id。
回應中的 `field_id` 與請求完全相同，可直接對回前端表單的那一列。

"""


def _error(status_code: int, detail: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorDetail(detail=detail, error_code=error_code).model_dump(),  # type: ignore[arg-type]
    )


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="分析欄位規格，產生合成假資料、隱私保護技術建議與 Excel 公式",
    description=_DESCRIPTION,
    responses={
        400: {
            "model": ErrorDetail,
            "description": "LLM 判定輸入與本功能無關而拒絕。請顯示 detail 給使用者",
        },
        422: {
            "model": ValidationErrorResponse,
            "description": "請求格式不符。由 FastAPI 在進入函式前檢查，不會呼叫 LLM",
        },
        502: {
            "model": ErrorDetail,
            "description": (
                "LLM 相關失敗，請顯示「服務暫時無法使用，請稍後再試」。"
                "細分原因看 `error_code`：`llm_invalid_output`／`quota_exceeded`／"
                "`llm_timeout`／`llm_unavailable`"
            ),
        },
    },
)
async def analyze(payload: AnalyzeRequest):
    try:
        return await run_analyze(
            payload.fields,
            payload.sample_count,
            payload.purpose.value,
            payload.purpose_detail,
        )
    except LLMRefusedError as exc:
        return _error(400, exc.message, "llm_refused")
    except LLMOutputError as exc:
        # 這類訊息含 LLM 原始輸出片段，是調提示詞的主要線索，只記在 log
        logger.error("LLM invalid output: %s", exc)
        return _error(502, "LLM 回傳格式不正確，請稍後再試", "llm_invalid_output")
    except LLMUpstreamError as exc:
        if exc.status_code == 429:
            return _error(502, "配額已用盡，請稍後再試", "quota_exceeded")
        if exc.status_code == 504:
            return _error(502, "LLM 回應逾時，請稍後再試", "llm_timeout")
        # 金鑰無效等設定問題的細節不往外送
        logger.error("Gemini upstream error (%s): %s", exc.status_code, exc.message)
        return _error(502, "LLM 服務暫時無法使用，請稍後再試", "llm_unavailable")
