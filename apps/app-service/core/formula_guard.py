"""
Excel 公式安全檢查。

前端會執行這些公式，使用者也會把公式複製進自己的 Excel（裡面是真實個資），
所以公式在送出前必須檢查。這裡**不產生任何公式** —— 公式一律由 LLM（Task C）撰寫，
本模組只負責判斷「這條公式能不能放行」。

檢查的是結構與安全，不是計算語意：
- 佔位符必須是 {cell} 與 {param}，不可寫死儲存格
- 函數白名單（依技術不同）
- 不可引用其他工作表、外部活頁簿
- 不可使用 LET 或科學記號（前端的 HyperFormula 無法解析，會讓整條公式失效）
- 不可使用 IFS、SWITCH 等新版函數（HyperFormula 可用，但 LibreOffice 與 Excel 2019
  以前不支援；使用者貼進自己的 Excel 會顯示 #NAME?）
- 不可使用 DATEVALUE、NOW、TODAY（前端引擎與 Excel 行為不一致），
  DATE(...) 必須用 TEXT(...) 包起來，否則預覽會顯示日期序號

沒通過的公式會把原因回饋給 Task C 讓它自己修正；修正後仍不通過就回報錯誤，
不會替換成其他公式 —— 寧可沒有公式，也不要給一條語意不明的公式。
"""

from __future__ import annotations

import math
import re
from typing import Optional

_ALLOWED_FUNCTIONS: dict[str, set[str]] = {
    # 文字處理函數（REPT、SUBSTITUTE、SEARCH…）兩種技術都放行：
    # 泛化文字欄位（地址只留縣市、產業別歸大類）同樣需要它們。
    "mask": {
        "REPLACE",
        "REPT",
        "LEN",
        "LEFT",
        "RIGHT",
        "MID",
        "MIN",
        "MAX",
        "INT",
        "IF",
        "AND",
        "OR",
        "NOT",
        "TEXT",
        "CONCATENATE",
        "SUBSTITUTE",
        "TRIM",
        "ROUND",
        "SEARCH",
        "FIND",
        "ISNUMBER",
        "EXACT",
        "VALUE",
    },
    "generalize": {
        "INT",
        "ROUND",
        "ROUNDDOWN",
        "ROUNDUP",
        "FLOOR",
        "CEILING",
        "TRUNC",
        "ABS",
        "YEAR",
        "MONTH",
        "DAY",
        "DATE",
        "IF",
        "AND",
        "OR",
        "NOT",
        "CHOOSE",
        "LEFT",
        "RIGHT",
        "MID",
        "LEN",
        "REPT",
        "SUBSTITUTE",
        "TRIM",
        "SEARCH",
        "FIND",
        "ISNUMBER",
        "EXACT",
        "MIN",
        "MAX",
        "TEXT",
        "VALUE",
        "CONCATENATE",
    },
    "differential_privacy": {
        "RAND",
        "SIGN",
        "LN",
        "LOG",
        "SQRT",
        "ABS",
        "MAX",
        "MIN",
        "ROUND",
        "INT",
        "IF",
        "TRUNC",
    },
}

# IFS 與 SWITCH 在 HyperFormula 可用，但 LibreOffice 與 Excel 2019 以前不支援（顯示 #NAME?）。
# 使用者會把公式貼進自己的 Excel，所以一律擋下，改用巢狀 IF（所有版本都支援）。
# 新版 Excel 才有的函數：HyperFormula 可用，但 LibreOffice 與 Excel 2019 以前
# 會顯示 #NAME?。使用者會把公式貼進自己的 Excel，所以擋下。
_TOO_NEW_FUNCTIONS = {"IFS", "SWITCH", "LET", "TEXTJOIN", "XLOOKUP", "TEXTSPLIT"}

# 兩個引擎行為不一致的函數：DATEVALUE 在 HyperFormula 依賴 dateFormats 設定，
# 實測解析 "1985-06-15" 會得到 #VALUE!，但在 Excel 正常。預覽與實際結果會對不上。
_INCONSISTENT_FUNCTIONS = {"DATEVALUE", "TIMEVALUE", "NOW", "TODAY"}

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")
_STRING_LITERAL_RE = re.compile(r'"(?:[^"]|"")*"')
_FUNCTION_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_CELL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])\$?[A-Za-z]{1,3}\$?\d+(?![A-Za-z0-9_(])")
_SCIENTIFIC_RE = re.compile(r"\d\s*[eE]\s*[+-]?\s*\d")
_FORBIDDEN_CHARS = ("!", "[", "]", "'", ":", ";", "|", "\n", "\r")
MAX_TEMPLATE_LENGTH = 500


def validate_template(template: str, technique: str) -> Optional[str]:
    """通過回傳 None；不通過回傳中文原因（會原樣回饋給 LLM 讓它修正）。"""
    if not isinstance(template, str) or not template.strip():
        return "公式為空"
    text = template.strip()
    if not text.startswith("="):
        return "公式必須以 = 開頭"
    if len(text) > MAX_TEMPLATE_LENGTH:
        return f"公式超過 {MAX_TEMPLATE_LENGTH} 字元"
    if text.count('"') % 2 != 0:
        return "引號不成對"

    placeholders = set(_PLACEHOLDER_RE.findall(text))
    unknown = placeholders - {"cell", "param"}
    if unknown:
        return f"含未允許的佔位符 {sorted(unknown)}，只能使用 {{cell}} 與 {{param}}"
    if "cell" not in placeholders:
        return "缺少 {cell} 佔位符，不可寫死儲存格位址"
    if "param" not in placeholders:
        return "缺少 {param} 佔位符，公式必須能隨滑桿調整"

    # 以下檢查排除字串常值（例如 "*"、"-"）與佔位符後才做
    code = _STRING_LITERAL_RE.sub('""', text)
    code = _PLACEHOLDER_RE.sub("0", code)

    for ch in _FORBIDDEN_CHARS:
        if ch in code:
            return f"含禁止字元 {ch!r}，不可引用其他工作表、外部來源或使用非預期分隔符"

    depth = 0
    for ch in code:
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            return "括號不成對"
    if depth != 0:
        return "括號不成對"

    functions = {name.upper() for name in _FUNCTION_RE.findall(code)}
    too_new = functions & _TOO_NEW_FUNCTIONS
    if too_new:
        return (
            f"不可使用 {sorted(too_new)}：LibreOffice 與 Excel 2019 以前的版本不支援，"
            "使用者貼進自己的 Excel 會顯示 #NAME?。請改用巢狀 IF。"
        )
    inconsistent = functions & _INCONSISTENT_FUNCTIONS
    if inconsistent:
        return (
            f"不可使用 {sorted(inconsistent)}：前端預覽引擎與 Excel 對它的行為不一致，"
            "畫面上看到的結果會和使用者實際貼進 Excel 的結果不同。"
            "要取年份請改用 LEFT({cell},4) 或 YEAR({cell})。"
        )
    if "DATE" in functions and "TEXT" not in functions:
        return (
            "DATE(...) 的結果是日期序號（例如 31048），前端預覽會顯示成一串數字。"
            '請用 TEXT(DATE(...),"yyyy") 之類的寫法包成文字，'
            "或直接用 LEFT({cell},4) 取年份。"
        )
    allowed = _ALLOWED_FUNCTIONS.get(technique, set())
    not_allowed = functions - allowed
    if not_allowed:
        return (
            f"使用了未允許的函數 {sorted(not_allowed)}；"
            f"{technique} 可用的函數為 {sorted(allowed)}"
        )
    if technique == "differential_privacy" and not {"RAND", "LN"} <= functions:
        return "差分隱私公式必須用 RAND 與 LN 產生拉普拉斯雜訊"
    if technique != "differential_privacy" and "RAND" in functions:
        return "只有差分隱私的公式可以使用 RAND"

    if _SCIENTIFIC_RE.search(code):
        return "不可使用科學記號（例如 1E-12），前端公式引擎無法解析，請改寫成完整小數"
    if _CELL_REF_RE.search(code):
        return "公式不可直接寫死儲存格，請改用 {cell} 佔位符"
    return None


# ---------------------------------------------------------------------------
# 滑桿規格的合理性檢查（滑桿也由 LLM 決定，這裡只擋明顯不合理的值）
# ---------------------------------------------------------------------------
def validate_slider(
    minimum: object, maximum: object, step: object, default: object
) -> Optional[str]:
    values = {"min": minimum, "max": maximum, "step": step, "default": default}
    numbers: dict[str, float] = {}
    for key, raw in values.items():
        try:
            number = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return f"滑桿的 {key} 不是數字：{raw!r}"
        if not math.isfinite(number):
            return f"滑桿的 {key} 不是有限數值"
        numbers[key] = number

    if numbers["step"] <= 0:
        return "滑桿的 step 必須大於 0"
    if numbers["min"] >= numbers["max"]:
        return "滑桿的 min 必須小於 max"
    if not (numbers["min"] <= numbers["default"] <= numbers["max"]):
        return "滑桿的 default 必須落在 min 與 max 之間"
    if (numbers["max"] - numbers["min"]) / numbers["step"] > 1000:
        return "滑桿的級距過多（(max-min)/step 超過 1000），請加大 step"
    return None
