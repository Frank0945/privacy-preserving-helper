"""
Excel 公式安全檢查。

前端會執行這些公式，使用者也會把公式複製進自己的 Excel（裡面是真實個資），
所以公式在送出前必須檢查。這裡**不產生任何公式** —— 公式一律由 LLM（Task C）撰寫，
本模組只負責判斷「這條公式能不能放行」。

函數不設白名單 —— LLM 可以自由使用 Excel 函數。只擋三類：
- 危險函數（WEBSERVICE、HYPERLINK、INDIRECT…）：會外送真實個資或讀取公式外的資料
- 新版函數（IFS、SWITCH、LET…）：LibreOffice 與 Excel 2019 以前會顯示 #NAME?
- 行為不一致的函數（DATEVALUE、NOW…）：前端預覽與使用者的 Excel 結果會不同

其餘檢查的是結構，不是計算語意：
- 佔位符必須是 {cell} 與 {param}，不可寫死儲存格
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

# 危險函數：會把使用者 Excel 裡的真實個資送出去，或讀取公式外的資料。
# 使用者會複製公式貼進自己的檔案，在那個環境這些函數是真的會動的。
_DANGEROUS_FUNCTIONS = {
    "WEBSERVICE",
    "FILTERXML",
    "ENCODEURL",  # 對外送出資料
    "HYPERLINK",  # 產生可點擊的外連
    "INDIRECT",
    "OFFSET",
    "INDEX",
    "VLOOKUP",
    "HLOOKUP",
    "MATCH",
    "GETPIVOTDATA",
    "CELL",
    "INFO",  # 讀取公式以外的資料或環境資訊
    "CALL",
    "REGISTER.ID",
    "RTD",
    "EVALUATE",
    "EXEC",
    "IMPORTDATA",
    "IMPORTXML",
    "IMPORTRANGE",
    "IMPORTHTML",  # Google Sheets
}

# 新版 Excel 才有的函數：HyperFormula 可用，但 LibreOffice 與 Excel 2019 以前
# 會顯示 #NAME?。使用者會把公式貼進自己的 Excel，所以擋下。
_TOO_NEW_FUNCTIONS = {
    "IFS",
    "SWITCH",
    "LET",
    "TEXTJOIN",
    "XLOOKUP",
    "TEXTSPLIT",
    "TEXTBEFORE",
    "TEXTAFTER",
    "LAMBDA",
    "MAP",
    "REDUCE",
    "BYROW",
    "BYCOL",
}

# 兩個引擎行為不一致的函數：DATEVALUE 在 HyperFormula 依賴 dateFormats 設定，
# 實測解析 "1985-06-15" 會得到 #VALUE!，但在 Excel 正常。預覽與實際結果會對不上。
# NOW/TODAY 的結果隨時間變動，畫面與使用者實際貼上時也不會相同。
_INCONSISTENT_FUNCTIONS = {"DATEVALUE", "TIMEVALUE", "NOW", "TODAY"}

# 全形標點：LLM 產生中文公式時偶爾會混進來，Excel 無法解析。
# 字串常值「裡面」的全形字是正常內容（例如 "科技類（含軟體）"），只正規化程式碼部分。
_FULLWIDTH_MAP = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "，": ",",
        "、": ",",
        "＝": "=",
        "＆": "&",
        "＋": "+",
        "－": "-",
        "＊": "*",
        "／": "/",
        "“": '"',
        "”": '"',
        "＂": '"',
    }
)

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")
_STRING_LITERAL_RE = re.compile(r'"(?:[^"]|"")*"')
_FUNCTION_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_CELL_REF_RE = re.compile(r"(?<![A-Za-z0-9_])\$?[A-Za-z]{1,3}\$?\d+(?![A-Za-z0-9_(])")
_SCIENTIFIC_RE = re.compile(r"\d\s*[eE]\s*[+-]?\s*\d")
_FORBIDDEN_CHARS = ("!", "[", "]", "'", ":", ";", "|", "\n", "\r")
# 文字分類欄位（職業、產業別）需要把每個類別列進巢狀 IF，公式天生就長：
# 20 個職業的對照表實測約 500~900 字元，原本的 500 上限會把正常公式擋掉。
# Excel 本身的公式長度上限是 8192 字元，2000 對這個平台夠用且仍能防止失控的輸出。
MAX_TEMPLATE_LENGTH = 2000


def normalize_formula(template: str) -> tuple[str, Optional[str]]:
    """把程式碼部分的全形標點換成半角，回傳（正規化後的公式, 說明或 None）。

    字串常值內的全形字保持原樣 —— "科技類（含軟體）" 是正常的中文內容。
    """
    out: list[str] = []
    changed = False
    in_string = False
    for char in template:
        if char == '"':
            in_string = not in_string
            out.append(char)
            continue
        if in_string:
            out.append(char)
            continue
        converted = char.translate(_FULLWIDTH_MAP)
        changed = changed or converted != char
        out.append(converted)
    normalized = "".join(out)
    if not changed:
        return template, None
    return normalized, "公式中的全形標點（例如（）、）已自動換成半角，Excel 才能解析。"


def validate_template(
    template: str, technique: str, requires_param: bool = True
) -> Optional[str]:
    """通過回傳 None；不通過回傳中文原因（會原樣回饋給 LLM 讓它修正）。

    requires_param=False 用於下拉選單型欄位：每個選項各有一條完整公式，
    處理強度寫死在公式裡，不需要 {param}。
    """
    if not isinstance(template, str) or not template.strip():
        return "公式為空"
    text = template.strip()
    if not text.startswith("="):
        return "公式必須以 = 開頭"
    if len(text) > MAX_TEMPLATE_LENGTH:
        return (
            f"公式長度 {len(text)} 字元，超過上限 {MAX_TEMPLATE_LENGTH}。"
            "請改用更精簡的寫法：用 OR() 把同一類的值放在一起"
            '（例如 IF(OR({cell}="專案經理",{cell}="產品經理"),"管理類",…)），'
            '或用關鍵字比對取代逐一列舉（例如 IF(ISNUMBER(SEARCH("經理",{cell})),"管理類",…)）。'
        )
    if text.count('"') % 2 != 0:
        return "引號不成對"

    placeholders = set(_PLACEHOLDER_RE.findall(text))
    unknown = placeholders - {"cell", "param"}
    if unknown:
        return f"含未允許的佔位符 {sorted(unknown)}，只能使用 {{cell}} 與 {{param}}"
    if "cell" not in placeholders:
        return "缺少 {cell} 佔位符，不可寫死儲存格位址"
    if requires_param and "param" not in placeholders:
        return "缺少 {param} 佔位符，公式必須能隨滑桿調整"
    if not requires_param and "param" in placeholders:
        return (
            "這個欄位用下拉選單而不是滑桿，每個選項的公式應該把處理強度寫死，"
            "不可使用 {param} 佔位符"
        )

    # 以下檢查排除字串常值（例如 "*"、"-"）與佔位符後才做
    code = _STRING_LITERAL_RE.sub('""', text)
    code = _PLACEHOLDER_RE.sub("0", code)

    for ch in _FORBIDDEN_CHARS:
        if ch in code:
            return f"含禁止字元 {ch!r}，不可引用其他工作表、外部來源或使用非預期分隔符"

    opens, closes = code.count("("), code.count(")")
    if opens != closes:
        # LLM 很不會數括號，直接告訴它差幾個，修正成功率差很多
        missing = abs(opens - closes)
        side = "右括號 )" if opens > closes else "左括號 ("
        return (
            f"括號不成對：左括號 {opens} 個、右括號 {closes} 個，少了 {missing} 個{side}。"
            "巢狀 IF 很深時容易數錯，建議改用 OR() 把同一類的值合併，減少巢狀層數。"
        )
    depth = 0
    for ch in code:
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            return "括號順序錯誤：出現了沒有對應左括號的右括號。"

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
    dangerous = functions & _DANGEROUS_FUNCTIONS
    if dangerous:
        return (
            f"不可使用 {sorted(dangerous)}：這些函數會把使用者 Excel 中的真實個資送到外部，"
            "或讀取公式以外的資料。請只用 {cell} 這一格的內容做計算。"
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
