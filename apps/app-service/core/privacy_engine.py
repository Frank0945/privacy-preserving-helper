"""
純演算法層（不呼叫 LLM）。

這一層刻意做得很薄。技術判斷（Task B）、Excel 公式與滑桿規格（Task C）全部由 LLM 決定，
後端不內建公式、也不自行推算滑桿範圍，只做兩件無法交給 LLM 的事：

1. 型態判斷（resolve_data_type）：純粹用來提示 Task C，以及讓前端知道該欄位是否為數值，
   在預覽時要把 sample_before 當數字還是文字餵進公式引擎。
2. 夾限（clamp_slider）：LLM 給的滑桿值若在合理範圍邊緣，做最小幅度的修正，
   避免出現「遮蔽位數上限 50，但範例資料只有 12 個字」這種拖到底就失效的滑桿。
   明顯不合理（min >= max 等）不在這裡處理，而是由 core.formula_guard.validate_slider 擋掉。
"""

from __future__ import annotations

import math
from typing import Literal, Optional

ResolvedType = Literal["text", "integer", "decimal", "date"]

_DATE_KEYWORDS = ("日期", "date", "生日", "出生", "年月日", "時間")
_DECIMAL_KEYWORDS = ("小數", "decimal", "float", "比率", "比例", "百分")
_NUMERIC_KEYWORDS = (
    "金額",
    "money",
    "價格",
    "薪",
    "收入",
    "消費",
    "總計",
    "小計",
    "費用",
    "元",
    "數字",
    "整數",
    "int",
    "number",
    "數值",
    "年齡",
    "次數",
    "數量",
)


def resolve_data_type(data_type: str, field_name: str = "") -> ResolvedType:
    """把使用者自由輸入的型態字串（中英文皆可）對應到四種實際型態。"""
    text = f"{data_type} {field_name}".lower()
    if any(k in text for k in _DATE_KEYWORDS):
        return "date"
    if any(k in text for k in _DECIMAL_KEYWORDS):
        return "decimal"
    if any(k in text for k in _NUMERIC_KEYWORDS):
        return "integer"
    return "text"


def shortest_sample_length(samples: list[str]) -> Optional[int]:
    lengths = [len(s) for s in samples if s]
    return min(lengths) if lengths else None


def clamp_slider(
    param_name: str,
    minimum: float,
    maximum: float,
    step: float,
    default: float,
    technique: str,
    samples: list[str],
) -> tuple[float, float, float, float, list[str]]:
    """回傳夾限後的 (min, max, step, default, 說明訊息)。

    只處理一種情況：以「字元位置」為單位的參數（遮蔽位數、保留前幾個字）
    不應該超過範例資料中最短的字串長度，否則滑桿拉到底時公式會失效或整格變成 *。
    """
    notes: list[str] = []
    is_length_param = technique == "mask" or "length" in param_name.lower()
    if is_length_param:
        shortest = shortest_sample_length(samples)
        if shortest is not None and maximum > shortest:
            notes.append(
                f"LLM 建議的滑桿上限為 {_fmt(maximum)}，但範例資料中最短只有 {shortest} 個字元，"
                f"已把上限調整為 {shortest}。"
            )
            maximum = float(shortest)
            minimum = min(minimum, maximum)
            default = min(default, maximum)
    return minimum, maximum, step, default, notes


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def is_numeric_type(resolved_type: ResolvedType) -> bool:
    return resolved_type in ("integer", "decimal")


def looks_numeric(value: str) -> bool:
    try:
        return math.isfinite(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return False
