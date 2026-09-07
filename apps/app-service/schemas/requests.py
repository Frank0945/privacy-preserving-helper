"""
這個檔案定義「前端會傳什麼資料進來」。
用 Pydantic BaseModel 的好處：FastAPI 會自動幫你做型別檢查與錯誤訊息，
如果前端漏填欄位或型態不對，會在進到你的商業邏輯之前就被擋下來，
不需要自己寫一堆 if 判斷。
"""

from typing import Literal

from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    """對應表單裡「一個欄位」的規格：名稱、型態、用途等"""

    name: str = Field(..., description="欄位名稱，例如「身分證字號」")
    data_type: str = Field(..., description="欄位型態，例如 text/number/date")
    format_rule: str | None = Field(
        default=None, description="使用者選填的格式說明，例如「英文字母+9碼數字」"
    )
    purpose: Literal["內部使用", "跨部門提供", "對外公開研究", "其他"]
    purpose_detail: str | None = Field(
        default=None, description="當 purpose='其他' 時，使用者填的補充說明"
    )
    is_key_field: bool = Field(
        default=False, description="是否為關鍵分析欄位，會影響保護強度的判斷"
    )
    sample_count: Literal[5, 10, 20] = Field(
        default=10, description="下拉選單選擇要產生幾筆範例資料"
    )


class AnalyzeRequest(BaseModel):
    """POST /api/analyze 的請求主體：一次可以送多個欄位"""

    fields: list[FieldSpec]


class RecalculateRequest(BaseModel):
    """
    POST /api/recalculate 的請求主體。
    滑桿調整參數後，前端只需要送 session_id + 欄位名稱 + 新參數，
    後端用純程式運算重跑演算法，不重新呼叫 LLM。
    """

    session_id: str
    field_name: str
    params: dict = Field(default_factory=dict)
