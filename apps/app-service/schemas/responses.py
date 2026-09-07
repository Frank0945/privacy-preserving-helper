"""
這裡定義的是「前端畫面實際要拿到什麼」，跟上一個檔案（LLM 原始輸出格式）分開，
是因為 LLM 回傳的資料還沒套用演算法、還沒有 Excel 公式，
中間會經過後端組合加工，所以需要一個獨立的「最終回應格式」。

把 LLM 輸出格式跟前端回應格式分開定義，還有一個好處：
未來如果你想換一個 LLM 供應商，或是 LLM 的輸出格式改了，
只需要改 llm_outputs.py 跟對應的 service 解析邏輯，
前端看到的 responses.py 格式完全不用動，前端也不用跟著改。
"""

from typing import Literal

from pydantic import BaseModel


class FieldResult(BaseModel):
    field_name: str
    original_samples: list[str]  # 處理前的合成假資料
    processed_samples: list[str]  # 套用隱私保護技術後的資料
    technique: str  # 使用的技術代碼
    suggested_param: str  # LLM 建議的參數（顯示給使用者看的原始建議）
    reason: str  # LLM 給的判斷理由（口語化說明）
    excel_formula: str  # 對應的 Excel 公式
    adjustable_params: dict  # 滑桿可調整的參數與其目前值，前端用這個畫滑桿


class AnalyzeOkResponse(BaseModel):
    status: Literal["ok"]
    session_id: str
    results: list[FieldResult]


class AnalyzeClarificationResponse(BaseModel):
    status: Literal["need_clarification"]
    source: Literal["synthetic_data", "technique_selection"]
    field: str
    question: str


class RecalculateResponse(BaseModel):
    processed_samples: list[str]
    excel_formula: str
