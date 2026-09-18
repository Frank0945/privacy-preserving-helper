"""
公式語意檢查。

formula_guard 檢查「用了哪些函數」，這裡檢查「算出來的東西合不合理」——
拿範例資料與滑桿的 min / default / max 實際跑一遍，看輸出長什麼樣。

會擋下的真實案例：

    =CONCATENATE(LEFT({cell},4),"-",TEXT(ROUNDDOWN(VALUE(MID({cell},6,2))/12*{param},0)*{param},"00"))

函數全部合法，但月份 1~11 除以 12 無條件捨去一律是 0，param=1 時所有資料都變成
「YYYY-00」，param=5 時算出「YYYY-20」這種不存在的月份。
只有實際算過才看得出來。

檢查不到的仍然很多（例如區間邊界差一、分類歸錯類），所以「處理前 / 處理後」
對照表還是最終的把關 —— 這一層只是把明顯壞掉的公式先攔下來。

另外，函數沒有白名單（LLM 可自由使用 Excel 函數），若公式用了求值器沒實作的函數，
就無法驗算 —— 這時放行，並由 orchestrator 在該欄位的 warnings 註記「未經語意檢查」。
"""

from __future__ import annotations

import re
from typing import Optional

from core.formula_eval import FormulaError, evaluate, unsupported_functions
from core.privacy_engine import ResolvedType

# RAND() 的極端值組合。Excel 的 RAND() 可能回傳 0，LN(0) 會變成 #NUM!，
# 所以差分隱私公式一定要用 MAX(...,極小值) 之類的方式保護。
_RAND_STRESS = [
    [0.0, 0.0],
    [0.0, 1.0],
    [1.0, 0.0],
    [1.0, 1.0],
    [0.5, 0.5],
    [0.999999, 0.000001],
]

# 輸出形如「1985-06」或「1985/6」時，後面那段視為月份
_YEAR_MONTH_RE = re.compile(r"^(\d{4})\s*[-/]\s*(\d{1,2})$")
_LEADING_YEAR_RE = re.compile(r"(\d{4})")
MAX_SAMPLES_TO_CHECK = 20


def _params_to_probe(
    minimum: float, maximum: float, step: float, default: float
) -> list[float]:
    """檢查用的參數：最小、建議、最大各一個就夠看出趨勢。"""
    candidates = {minimum, default, maximum}
    middle = minimum + (maximum - minimum) / 2
    if step > 0:
        middle = minimum + round((middle - minimum) / step) * step
    candidates.add(middle)
    return sorted(v for v in candidates if minimum <= v <= maximum)


def _run(template: str, samples: list[str], param: float) -> list[str]:
    return [evaluate(template, value, param) for value in samples]


def _param_means_detail(param_name: str, technique: str) -> bool:
    """參數變大代表「保留更多」還是「分得更粗」？

    多數泛化參數（區間寬度、幾年一組）是越大越粗；
    但「保留前 N 個字」剛好相反 —— N 越大保留越多、分得越細。
    方向判斷錯了會把正確的公式擋下來，所以要分開處理。
    """
    if technique == "mask":
        return False
    return any(
        k in param_name.lower() for k in ("length", "prefix", "keep", "digit", "char")
    )


def check_formula(
    template: str,
    technique: str,
    resolved_type: ResolvedType,
    samples: list[str],
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    step: Optional[float] = None,
    default: Optional[float] = None,
    param_name: str = "",
) -> Optional[str]:
    """通過回傳 None；不通過回傳中文原因（會回饋給 LLM 讓它重寫）。

    沒有滑桿的欄位（下拉選單型，每個 variant 一條完整公式）把 min/max 留空即可，
    這時只檢查「算得出結果」與技術專屬規則，不檢查參數的影響。
    """
    usable = [s for s in samples if s != ""][:MAX_SAMPLES_TO_CHECK]
    if not usable:
        return None  # 沒有範例資料可驗，只能放行
    if unsupported_functions(template):
        # 函數沒有白名單，LLM 可以自由使用。求值器沒實作的函數無法驗算，
        # 這時放行並由 orchestrator 在 warnings 註記「未經語意檢查」。
        return None

    has_slider = None not in (minimum, maximum, default)
    if has_slider:
        probes = _params_to_probe(minimum, maximum, step or 1.0, default)  # type: ignore[arg-type]
    else:
        probes = [1.0]  # 沒有滑桿：{param} 不會出現在公式裡，隨便代一個值
    results: dict[float, list[str]] = {}

    # --- 1. 每個參數、每筆範例都要算得出來 ---
    for param in probes:
        try:
            results[param] = _run(template, usable, param)
        except FormulaError as exc:
            return (
                f"用範例資料實際計算時失敗（參數={_fmt(param)}）：{exc}。"
                "請改寫成對所有範例值都算得出結果的公式。"
            )

    # --- 1b. 差分隱私：RAND() 取到極端值時不可算出 #NUM! ---
    if technique == "differential_privacy":
        problem = _check_rand_robustness(template, usable, probes)
        if problem:
            return problem

    # --- 2. 滑桿必須真的影響結果 ---
    if len(probes) > 1:
        distinct_outputs = {tuple(results[p]) for p in probes}
        if len(distinct_outputs) == 1:
            return (
                f"滑桿從 {_fmt(min(probes))} 調到 {_fmt(max(probes))}，所有範例的輸出完全沒變，"
                "代表 {param} 沒有實際作用。請讓公式的處理強度真的隨 {param} 改變，"
                '不要寫 IF({param}=0,"","") 這種沒有作用的片段。'
            )

    # --- 3. 輸出不可全空 ---
    for param in probes:
        if all(value.strip() == "" for value in results[param]):
            return (
                f"參數={_fmt(param)} 時所有範例都算出空字串，這不是有意義的處理結果。"
            )

    # --- 4. 技術專屬檢查 ---
    if technique == "mask":
        problem = _check_mask(usable, results, probes)
        if problem:
            return problem
    elif technique == "generalize":
        problem = _check_generalize(
            usable,
            results,
            probes,
            resolved_type,
            _param_means_detail(param_name, technique),
        )
        if problem:
            return problem
    return None


# ---------------------------------------------------------------------------
def _check_rand_robustness(
    template: str, samples: list[str], probes: list[float]
) -> Optional[str]:
    """RAND() 在 Excel 可能回傳 0，未加保護的 LN(0) 會變成 #NUM!。

    後端平常用隨機值檢查，幾乎不可能碰到這個邊界，所以要主動餵極端值。
    """
    for rand_values in _RAND_STRESS:
        for param in probes:
            try:
                evaluate(template, samples[0], param, rand_values=rand_values)
            except FormulaError as exc:
                return (
                    f"當 RAND() 回傳極端值 {rand_values} 時公式失敗：{exc}。"
                    "Excel 的 RAND() 可能回傳 0，LN(0) 會變成 #NUM!。"
                    "請用 MAX(RAND(),0.000000000001) 之類的寫法保護 LN 的引數。"
                )
    return None


def check_noise_magnitude(
    template: str, samples: list[str], default_param: float
) -> Optional[str]:
    """差分隱私的雜訊量是否大到讓資料失去意義（回傳提醒文字，不是拒絕原因）。

    敏感度取得過大時（例如直接用資料最大值），雜訊會蓋掉原始數值，
    甚至讓「消費總計」出現負數。這是參數選擇問題，不是公式寫錯，所以只提醒。
    """
    numbers = []
    for value in samples:
        try:
            numbers.append(abs(float(str(value).replace(",", "").strip())))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return None
    data_scale = max(numbers)

    deviations, negatives = [], 0
    for value in samples:
        try:
            original = float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        for _ in range(40):
            try:
                result = float(evaluate(template, value, default_param))
            except (FormulaError, ValueError):
                continue
            deviations.append(abs(result - original))
            negatives += result < 0
    if not deviations:
        return None

    average = sum(deviations) / len(deviations)
    negative_rate = negatives / len(deviations)
    if average > data_scale:
        return (
            f"在建議的 epsilon 下，平均雜訊量約 {average:,.0f}，已超過範例資料的最大值 "
            f"{data_scale:,.0f}，處理後的數字幾乎失去分析價值"
            f"（約 {negative_rate:.0%} 會變成負數）。"
            "敏感度可能取得太大 —— 它應該是「單一個體最多能影響此數值多少」，"
            "不是整欄的最大值。請調整敏感度或提高 epsilon。"
        )
    if negative_rate > 0.2 and min(numbers) >= 0:
        return (
            f"原始資料都是非負數，但處理後約 {negative_rate:.0%} 會變成負數。"
            "若這個欄位在語意上不可能為負（例如金額、次數），請調整敏感度或 epsilon。"
        )
    return None


def _check_mask(
    samples: list[str], results: dict[float, list[str]], probes: list[float]
) -> Optional[str]:
    for param in probes:
        outputs = results[param]
        if not any("*" in value for value in outputs):
            return (
                f"參數={_fmt(param)} 時沒有任何範例被遮蔽（輸出不含 *）。"
                "遮罩公式必須把字元換成 *。"
            )
        for original, masked in zip(samples, outputs):
            if masked.count("*") > len(original):
                return (
                    f"「{original}」在參數={_fmt(param)} 時算出 {masked.count('*')} 個星號，"
                    f"超過原字串長度 {len(original)}。請用 MIN({{param}},LEN({{cell}})) 保護。"
                )

    # 遮蔽位數變大，星號不可變少
    ordered = sorted(probes)
    for earlier, later in zip(ordered, ordered[1:]):
        before = sum(v.count("*") for v in results[earlier])
        after = sum(v.count("*") for v in results[later])
        if after < before:
            return (
                f"參數從 {_fmt(earlier)} 調到 {_fmt(later)}，星號總數反而從 {before} 減為 {after}。"
                "遮蔽位數越大，被遮蔽的字元應該越多。"
            )
    return None


def _check_generalize(
    samples: list[str],
    results: dict[float, list[str]],
    probes: list[float],
    resolved_type: ResolvedType,
    param_means_detail: bool,
) -> Optional[str]:
    # 區間類參數：越大分得越粗，相異結果不可變多
    # 保留長度類參數（prefix_length）：越大保留越多，相異結果不可變少
    ordered = sorted(probes)
    for earlier, later in zip(ordered, ordered[1:]):
        before = len(set(results[earlier]))
        after = len(set(results[later]))
        if param_means_detail and after < before:
            return (
                f"參數從 {_fmt(earlier)} 調到 {_fmt(later)}，範例的相異結果反而從 {before} 變成 {after}。"
                f"參數名稱看起來是「保留長度」，數值越大應該保留越多細節、相異結果越多或持平。"
            )
        if not param_means_detail and after > before:
            return (
                f"參數從 {_fmt(earlier)} 調到 {_fmt(later)}，範例的相異結果反而從 {before} 變成 {after}。"
                "泛化的參數越大代表分組越粗，相異結果應該越少或持平。"
            )

    if resolved_type == "date":
        return _check_date_output(samples, results, probes)
    return None


def _check_date_output(
    samples: list[str], results: dict[float, list[str]], probes: list[float]
) -> Optional[str]:
    """日期泛化最常見的錯誤：算出不存在的月份、或年份跑掉。"""
    for param in probes:
        for original, output in zip(samples, results[param]):
            match = _YEAR_MONTH_RE.match(output.strip())
            if match:
                month = int(match.group(2))
                if not 1 <= month <= 12:
                    return (
                        f"「{original}」在參數={_fmt(param)} 時算出「{output}」，"
                        f"後半段的 {month} 不是合法月份（1~12）。"
                        "請確認月份的分組算式，或改成只輸出年份／年份區間。"
                    )

            original_year = _LEADING_YEAR_RE.search(original)
            output_year = _LEADING_YEAR_RE.search(output)
            if original_year and output_year:
                actual, generalized = int(original_year.group(1)), int(
                    output_year.group(1)
                )
                if not (actual - max(param, 1) < generalized <= actual):
                    return (
                        f"「{original}」在參數={_fmt(param)} 時算出「{output}」，"
                        f"年份 {generalized} 不在合理範圍內"
                        f"（泛化後的年份應該落在 {actual - int(max(param, 1)) + 1}~{actual}）。"
                    )
    return None


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
