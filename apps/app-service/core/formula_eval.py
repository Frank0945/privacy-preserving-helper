"""
Excel 公式求值器（只支援 core.formula_guard 白名單內的函數）。

為什麼需要它
------------
formula_guard 只檢查「用了哪些函數」，不檢查函數組合出來的數學邏輯。
實際遇過的案例：

    =CONCATENATE(LEFT({cell},4),"-",TEXT(ROUNDDOWN(VALUE(MID({cell},6,2))/12*{param},0)*{param},"00"))

所有函數都在白名單內，公式「合法」通過檢查，但月份 1~11 除以 12 再無條件捨去一律等於 0，
param=5 時甚至算出 -10、-20、-25 這種不存在的月份。語意完全是錯的。

要擋下這種錯誤，只有一個辦法：**真的把公式算一遍，看輸出長什麼樣**。
這個模組就是後端自己的公式引擎，讓 formula_check 能拿範例資料實際跑過再決定放不放行。

範圍與限制
----------
- 只支援白名單內的函數與 + - * / & 比較運算，夠用於本平台產生的公式
- 不支援儲存格範圍、陣列、參照（本來就被 formula_guard 擋掉了）
- 數值一律用 float，字串轉數字的規則模擬 Excel（空字串視為 0、純數字文字可轉）
- 求值失敗會丟 FormulaError，呼叫端把它當成「這條公式不能用」
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Optional, Union

Value = Union[float, str, bool, "ExcelError"]

EXCEL_EPOCH = date(1899, 12, 30)  # Excel 的第 1 天是 1900-01-01，序號 1

# 差分隱私公式含 RAND()。檢查時需要可重現的結果，因此用固定種子的亂數產生器。
# 這只影響後端的公式檢查，使用者的 Excel 仍然是真正的隨機。
_rng = random.Random(20260101)

# 壓力測試用：evaluate(rand_values=[...]) 會讓 RAND() 依序回傳這些值（用完循環），
# 用來檢查公式在 RAND() 取到 0、1 這種極端值時會不會算出 #NUM!。
_forced_rand: Optional[list[float]] = None
_forced_index = 0


def _next_rand() -> float:
    global _forced_index
    if _forced_rand:
        value = _forced_rand[_forced_index % len(_forced_rand)]
        _forced_index += 1
        return value
    return _rng.random()


class FormulaError(Exception):
    """公式無法求值（語法錯誤、型別錯誤、除以零、未知函數等）。"""


class UnsupportedFunction(FormulaError):
    """公式用了求值器沒實作的函數。

    這不代表公式有錯 —— 函數白名單已經移除，LLM 可以自由使用 Excel 函數。
    碰到這種公式時，語意檢查會跳過（無法驗算），並在回應的 warnings 註記。
    """

    def __init__(self, name: str):
        super().__init__(f"求值器未實作的函數：{name}")
        self.name = name


class ExcelError:
    """Excel 的錯誤值（#VALUE! 之類）。

    它不等於「公式壞掉」—— `ISNUMBER(SEARCH(...))` 這種寫法就靠
    SEARCH 找不到時回傳錯誤值、ISNUMBER 再把它轉成 FALSE。
    只有錯誤值最後成為公式的結果時，才代表這格算不出東西。
    """

    __slots__ = ("code",)

    def __init__(self, code: str = "#VALUE!"):
        self.code = code

    def __repr__(self) -> str:  # pragma: no cover - 只用於除錯訊息
        return self.code


# ===========================================================================
# 詞法分析
# ===========================================================================
_TOKEN_RE = re.compile(
    r"""
    (?P<string>"(?:[^"]|"")*")
  | (?P<number>\d+(?:\.\d+)?|\.\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
  | (?P<op><=|>=|<>|[+\-*/&=<>(),])
  | (?P<space>\s+)
""",
    re.VERBOSE,
)


@dataclass
class _Token:
    kind: str
    text: str


def _tokenize(formula: str) -> list[_Token]:
    text = formula.strip()
    if text.startswith("="):
        text = text[1:]
    tokens: list[_Token] = []
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None:
            raise FormulaError(f"無法解析的字元：{text[position]!r}（位置 {position}）")
        position = match.end()
        kind = match.lastgroup or ""
        if kind == "space":
            continue
        tokens.append(_Token(kind, match.group()))
    return tokens


# ===========================================================================
# 語法分析（遞迴下降）
# ===========================================================================
_COMPARISONS = {"=", "<>", "<", ">", "<=", ">="}


class _ErrorSignal(Exception):
    """內部用：把錯誤值一路往上拋，讓它成為整條公式的結果。"""

    def __init__(self, error: ExcelError):
        super().__init__(error.code)
        self.error = error


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[_Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> _Token:
        token = self.peek()
        if token is None:
            raise FormulaError("公式結尾不完整")
        self.pos += 1
        return token

    def expect(self, text: str) -> None:
        token = self.take()
        if token.text != text:
            raise FormulaError(f"預期 {text!r}，實際是 {token.text!r}")

    def parse(self) -> Any:
        node = self.parse_comparison()
        if self.peek() is not None:
            raise FormulaError(f"公式尾端有多餘的內容：{self.peek().text!r}")  # type: ignore[union-attr]
        return node

    def parse_comparison(self) -> Any:
        node = self.parse_concat()
        while (token := self.peek()) and token.text in _COMPARISONS:
            self.take()
            node = ("cmp", token.text, node, self.parse_concat())
        return node

    def parse_concat(self) -> Any:
        node = self.parse_additive()
        while (token := self.peek()) and token.text == "&":
            self.take()
            node = ("concat", node, self.parse_additive())
        return node

    def parse_additive(self) -> Any:
        node = self.parse_multiplicative()
        while (token := self.peek()) and token.text in ("+", "-"):
            self.take()
            node = ("arith", token.text, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self) -> Any:
        node = self.parse_unary()
        while (token := self.peek()) and token.text in ("*", "/"):
            self.take()
            node = ("arith", token.text, node, self.parse_unary())
        return node

    def parse_unary(self) -> Any:
        token = self.peek()
        if token and token.text in ("-", "+"):
            self.take()
            operand = self.parse_unary()
            return ("neg", operand) if token.text == "-" else operand
        return self.parse_primary()

    def parse_primary(self) -> Any:
        token = self.take()
        if token.kind == "number":
            return ("const", float(token.text))
        if token.kind == "string":
            return ("const", token.text[1:-1].replace('""', '"'))
        if token.kind == "name":
            name = token.text.upper()
            following = self.peek()
            if following is None or following.text != "(":
                raise FormulaError(
                    f"未知的名稱：{token.text}（本平台不支援儲存格參照或具名範圍）"
                )
            self.expect("(")
            args: list[Any] = []
            if (nxt := self.peek()) and nxt.text == ")":
                self.take()
                return ("call", name, args)
            while True:
                args.append(self.parse_comparison())
                nxt = self.take()
                if nxt.text == ")":
                    break
                if nxt.text != ",":
                    raise FormulaError(f"函數引數之間預期 ','，實際是 {nxt.text!r}")
            return ("call", name, args)
        if token.text == "(":
            node = self.parse_comparison()
            self.expect(")")
            return node
        raise FormulaError(f"非預期的符號：{token.text!r}")


# ===========================================================================
# 型別轉換（模擬 Excel）
# ===========================================================================
def _to_number(value: Value) -> float:
    if isinstance(value, ExcelError):
        raise _ErrorSignal(value)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return 0.0
    try:
        number = float(text.replace(",", ""))
    except ValueError as exc:
        raise FormulaError(
            f"無法把 {value!r} 當成數字運算（Excel 會顯示 #VALUE!）"
        ) from exc
    if not math.isfinite(number):
        raise FormulaError("運算結果不是有限數值")
    return number


def excel_round(value: float, digits: int) -> float:
    """Excel 的 ROUND 是四捨五入（.5 遠離 0），Python 內建 round 是銀行家捨入。"""
    quantum = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def format_number(value: float) -> str:
    """模擬 Excel 把數字接成文字時的樣子。"""
    rounded = excel_round(value, 10) + 0.0
    if rounded == int(rounded) and abs(rounded) < 1e15:
        return str(int(rounded))
    return f"{rounded:.10f}".rstrip("0").rstrip(".")


def _to_text(value: Value) -> str:
    if isinstance(value, ExcelError):
        raise _ErrorSignal(value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return format_number(float(value))
    return str(value)


def _serial_to_date(serial: float) -> date:
    return EXCEL_EPOCH + timedelta(days=int(serial))


def _as_date(value: Value) -> date:
    """日期函數的引數：可以是序號，也可以是 YYYY-MM-DD 之類的文字。"""
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                from datetime import datetime

                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return _serial_to_date(_to_number(value))


# ===========================================================================
# 函數實作
# ===========================================================================
def _arg(args: list[Value], index: int, default: Optional[Value] = None) -> Value:
    if index < len(args):
        return args[index]
    if default is not None:
        return default
    raise FormulaError(f"函數缺少第 {index + 1} 個引數")


def _fn_text(args: list[Value]) -> Value:
    value, fmt = _arg(args, 0), _to_text(_arg(args, 1))
    if fmt.lower() in ("yyyy", "yy"):
        year = _as_date(value).year
        return str(year) if fmt.lower() == "yyyy" else f"{year % 100:02d}"
    if fmt.lower() in ("mm", "m"):
        return f"{_as_date(value).month:02d}"
    if fmt.lower() in ("dd", "d"):
        return f"{_as_date(value).day:02d}"
    if fmt.lower() in ("yyyy-mm", "yyyy/mm"):
        parsed = _as_date(value)
        sep = "-" if "-" in fmt else "/"
        return f"{parsed.year}{sep}{parsed.month:02d}"
    if set(fmt) <= {"0"}:  # "00"、"0000" 之類的補零格式
        return f"{int(excel_round(_to_number(value), 0)):0{len(fmt)}d}"
    if fmt in ("0.0", "0.00", "0.000"):
        digits = len(fmt.split(".")[1])
        return f"{excel_round(_to_number(value), digits):.{digits}f}"
    if fmt == "General":
        return _to_text(value)
    raise FormulaError(f"不支援的 TEXT 格式字串：{fmt!r}")


def _substring(text: str, start: int, length: int) -> str:
    if length < 0:
        raise FormulaError("字串長度不可為負數")
    return text[max(start, 0) : max(start, 0) + length]


_FUNCTIONS: dict[str, Callable[[list[Value]], Value]] = {
    # --- 文字 ---
    "LEN": lambda a: float(len(_to_text(_arg(a, 0)))),
    "LEFT": lambda a: _substring(
        _to_text(_arg(a, 0)), 0, int(_to_number(_arg(a, 1, 1.0)))
    ),
    "RIGHT": lambda a: (
        _to_text(_arg(a, 0))[
            len(_to_text(_arg(a, 0))) - int(_to_number(_arg(a, 1, 1.0))) :
        ]
        if int(_to_number(_arg(a, 1, 1.0))) > 0
        else ""
    ),
    "MID": lambda a: _substring(
        _to_text(_arg(a, 0)),
        int(_to_number(_arg(a, 1))) - 1,
        int(_to_number(_arg(a, 2))),
    ),
    "REPT": lambda a: _to_text(_arg(a, 0)) * max(0, int(_to_number(_arg(a, 1)))),
    "TRIM": lambda a: re.sub(r"\s+", " ", _to_text(_arg(a, 0)).strip()),
    "CONCATENATE": lambda a: "".join(_to_text(x) for x in a),
    "SUBSTITUTE": lambda a: _to_text(_arg(a, 0)).replace(
        _to_text(_arg(a, 1)), _to_text(_arg(a, 2))
    ),
    "REPLACE": lambda a: (
        lambda text, start, count, new: text[: max(start - 1, 0)]
        + new
        + text[max(start - 1, 0) + max(count, 0) :]
    )(
        _to_text(_arg(a, 0)),
        int(_to_number(_arg(a, 1))),
        int(_to_number(_arg(a, 2))),
        _to_text(_arg(a, 3)),
    ),
    "EXACT": lambda a: _to_text(_arg(a, 0)) == _to_text(_arg(a, 1)),
    "TEXT": _fn_text,
    "VALUE": lambda a: _to_number(_arg(a, 0)),
    # --- 搜尋 ---
    "SEARCH": lambda a: _search(a, case_sensitive=False),
    "FIND": lambda a: _search(a, case_sensitive=True),
    "ISNUMBER": lambda a: isinstance(_arg(a, 0), (int, float))
    and not isinstance(_arg(a, 0), bool),
    "ISERROR": lambda a: isinstance(_arg(a, 0), ExcelError),
    # --- 數值 ---
    "INT": lambda a: float(math.floor(_to_number(_arg(a, 0)))),
    "TRUNC": lambda a: float(math.trunc(_to_number(_arg(a, 0)))),
    "ABS": lambda a: abs(_to_number(_arg(a, 0))),
    "ROUND": lambda a: excel_round(
        _to_number(_arg(a, 0)), int(_to_number(_arg(a, 1, 0.0)))
    ),
    "ROUNDDOWN": lambda a: _round_dir(a, down=True),
    "ROUNDUP": lambda a: _round_dir(a, down=False),
    "FLOOR": lambda a: _floor_ceiling(a, floor=True),
    "CEILING": lambda a: _floor_ceiling(a, floor=False),
    "MIN": lambda a: min(_to_number(x) for x in a),
    "MAX": lambda a: max(_to_number(x) for x in a),
    "SIGN": lambda a: float(
        (_to_number(_arg(a, 0)) > 0) - (_to_number(_arg(a, 0)) < 0)
    ),
    "SQRT": lambda a: math.sqrt(_to_number(_arg(a, 0))),
    "LN": lambda a: _safe_log(_to_number(_arg(a, 0))),
    "LOG": lambda a: math.log(_to_number(_arg(a, 0)), _to_number(_arg(a, 1, 10.0))),
    # --- 邏輯 ---
    "IF": lambda a: _arg(a, 1) if _truthy(_arg(a, 0)) else _arg(a, 2, ""),
    "AND": lambda a: all(_truthy(x) for x in a),
    "OR": lambda a: any(_truthy(x) for x in a),
    "NOT": lambda a: not _truthy(_arg(a, 0)),
    "CHOOSE": lambda a: _arg(a, int(_to_number(_arg(a, 0)))),
    # RAND 用可重現的亂數；檢查時可透過 evaluate(rand_values=...) 指定極端值
    "RAND": lambda a: _next_rand(),
    # --- 日期 ---
    "YEAR": lambda a: float(_as_date(_arg(a, 0)).year),
    "MONTH": lambda a: float(_as_date(_arg(a, 0)).month),
    "DAY": lambda a: float(_as_date(_arg(a, 0)).day),
    "DATE": lambda a: _fn_date(a),
}


def _search(args: list[Value], case_sensitive: bool) -> Value:
    needle, haystack = _to_text(_arg(args, 0)), _to_text(_arg(args, 1))
    if not case_sensitive:
        needle, haystack = needle.lower(), haystack.lower()
    index = haystack.find(needle)
    if index < 0:
        return ExcelError("#VALUE!")  # Excel 的行為，ISNUMBER(...) 會得到 FALSE
    return float(index + 1)


def _round_dir(args: list[Value], down: bool) -> float:
    value = _to_number(_arg(args, 0))
    digits = int(_to_number(_arg(args, 1, 0.0)))
    factor = 10.0**digits
    scaled = value * factor
    result = math.floor(abs(scaled)) if down else math.ceil(abs(scaled))
    return math.copysign(result, value) / factor


def _floor_ceiling(args: list[Value], floor: bool) -> float:
    value = _to_number(_arg(args, 0))
    significance = _to_number(_arg(args, 1, 1.0))
    if significance == 0:
        raise FormulaError("FLOOR/CEILING 的 significance 不可為 0")
    quotient = value / significance
    return (math.floor(quotient) if floor else math.ceil(quotient)) * significance


def _safe_log(value: float) -> float:
    if value <= 0:
        raise FormulaError("LN 的引數必須大於 0（Excel 會顯示 #NUM!）")
    return math.log(value)


def _fn_date(args: list[Value]) -> float:
    year = int(_to_number(_arg(args, 0)))
    month = int(_to_number(_arg(args, 1)))
    day = int(_to_number(_arg(args, 2)))
    # Excel 允許月份、日期溢位（DATE(2000,13,1) = 2001-01-01）
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    try:
        base = date(year, month, 1)
    except ValueError as exc:
        raise FormulaError(f"DATE 的年份超出範圍：{year}") from exc
    result = base + timedelta(days=day - 1)
    return float((result - EXCEL_EPOCH).days)


def _truthy(value: Value) -> bool:
    if isinstance(value, ExcelError):
        raise _ErrorSignal(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().upper() == "TRUE"


# ===========================================================================
# 求值
# ===========================================================================
def _evaluate(node: Any) -> Value:
    kind = node[0]
    if kind == "const":
        return node[1]
    if kind == "neg":
        return -_to_number(_evaluate(node[1]))
    if kind == "concat":
        return _to_text(_evaluate(node[1])) + _to_text(_evaluate(node[2]))
    if kind == "arith":
        _, op, left_node, right_node = node
        left, right = _to_number(_evaluate(left_node)), _to_number(
            _evaluate(right_node)
        )
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if right == 0:
            raise FormulaError("除以零（Excel 會顯示 #DIV/0!）")
        return left / right
    if kind == "cmp":
        _, op, left_node, right_node = node
        left, right = _evaluate(left_node), _evaluate(right_node)
        return _compare(op, left, right)
    if kind == "call":
        _, name, arg_nodes = node
        function = _FUNCTIONS.get(name)
        if function is None:
            raise UnsupportedFunction(name)
        if name == "IF":  # 短路：只算被選中的那一支
            condition = _truthy(_evaluate(arg_nodes[0]))
            if condition:
                return _evaluate(arg_nodes[1])
            return _evaluate(arg_nodes[2]) if len(arg_nodes) > 2 else ""
        return function([_evaluate(child) for child in arg_nodes])
    raise FormulaError(f"未知的節點型別：{kind}")


def _compare(op: str, left: Value, right: Value) -> bool:
    both_numeric = isinstance(left, (int, float)) and isinstance(right, (int, float))
    if not both_numeric and (isinstance(left, str) or isinstance(right, str)):
        left_key: Any = _to_text(left).upper()
        right_key: Any = _to_text(right).upper()
    else:
        left_key, right_key = _to_number(left), _to_number(right)
    if op == "=":
        return left_key == right_key
    if op == "<>":
        return left_key != right_key
    if op == "<":
        return left_key < right_key
    if op == ">":
        return left_key > right_key
    if op == "<=":
        return left_key <= right_key
    return left_key >= right_key


def evaluate(
    formula: str,
    cell_value: str,
    param: float,
    rand_values: Optional[list[float]] = None,
) -> str:
    """把 {cell} 與 {param} 代入後求值，回傳 Excel 會顯示的文字。

    rand_values 可指定 RAND() 依序回傳的值（用完循環），用於極端值壓力測試。
    求值失敗一律丟 FormulaError，呼叫端視為「這條公式不能用」。
    """
    global _forced_rand, _forced_index
    _forced_rand, _forced_index = rand_values, 0
    try:
        return _evaluate_rendered(formula, cell_value, param)
    finally:
        _forced_rand, _forced_index = None, 0


def _evaluate_rendered(formula: str, cell_value: str, param: float) -> str:
    rendered = formula.replace("{cell}", "__CELL__").replace(
        "{param}", format_number(param)
    )
    tokens = _tokenize(rendered)
    for token in tokens:
        if token.kind == "name" and token.text == "__CELL__":
            token.kind = "cellref"
    parsed = _Parser(_substitute_cell(tokens, cell_value)).parse()
    try:
        result = _evaluate(parsed)
    except _ErrorSignal as signal:
        raise FormulaError(
            f"公式算出 {signal.error.code}（這格在 Excel 會顯示錯誤）"
        ) from signal
    if isinstance(result, ExcelError):
        raise FormulaError(f"公式算出 {result.code}（這格在 Excel 會顯示錯誤）")
    return _to_text(result)


def unsupported_functions(formula: str) -> set[str]:
    """列出公式中求值器沒實作的函數（用來判斷能不能做語意檢查）。"""
    rendered = formula.replace("{cell}", "__CELL__").replace("{param}", "1")
    try:
        tokens = _tokenize(rendered)
    except FormulaError:
        return set()
    names = set()
    for index, token in enumerate(tokens):
        if token.kind != "name" or token.text == "__CELL__":
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if following is not None and following.text == "(":
            name = token.text.upper()
            if name not in _FUNCTIONS:
                names.add(name)
    return names


def _substitute_cell(tokens: list[_Token], cell_value: str) -> list[_Token]:
    """把儲存格佔位符換成字串常值（Excel 的儲存格內容在本平台一律是文字）。"""
    out: list[_Token] = []
    for token in tokens:
        if token.kind == "cellref":
            escaped = cell_value.replace('"', '""')
            out.append(_Token("string", f'"{escaped}"'))
        else:
            out.append(token)
    return out
