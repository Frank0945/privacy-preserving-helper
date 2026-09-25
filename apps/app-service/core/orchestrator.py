"""
把三個 LLM 任務串起來，組成 /api/analyze 的回應。

分工
----
Task B（LLM）：決定每個欄位用哪種技術、建議參數
Task A（LLM）：產生合成假資料
Task C（LLM）：依 Task B 的建議撰寫 Excel 公式，並決定滑桿規格
後端：欄位對應、安全檢查、把結果組成回應

後端不內建任何公式，也不自行推算滑桿範圍。公式沒通過 core.formula_guard 的安全檢查時，
把原因回饋給 Task C 讓它自己修一次；修正後仍不通過就在該欄位回報 formula_error，
不替換成其他公式 —— 寧可沒有公式，也不要給一條語意不明的公式。

欄位對應
--------
欄位 id 由前端產生並隨請求送進來，後端與三個任務全程使用同一組 id，
不用欄位名稱、也不做「照順序比對」的保底。名稱可以重複，靠名稱比對會把值配到錯的欄位；
位置保底更糟，它會在 LLM 少回、多回或亂序時安靜地產生一份錯位的資料。
因此改為嚴格檢查：每個 id 都必須恰好出現一次，對不上就丟 LLMOutputError（router 轉成 502）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from core.config import get_settings
from core.formula_check import check_formula, check_noise_magnitude
from core.formula_eval import unverifiable_reason
from core.formula_guard import normalize_formula, validate_slider, validate_template
from core.llm_client import LLMOutputError, generate_json
from core.privacy_engine import (
    ResolvedType,
    clamp_slider,
    resolve_data_type,
)
from core.prompts import (
    TASK_A_SYSTEM_PROMPT,
    TASK_B_SYSTEM_PROMPT,
    TASK_C_SYSTEM_PROMPT,
)
from core.schemas import (
    AnalyzeResponse,
    ClarificationNeeded,
    ExcelFormulaTemplate,
    FieldSpecInput,
    ProcessedField,
    SliderParam,
    Technique,
)

logger = logging.getLogger(__name__)

# Task B 可選的技術。差分隱私不在其中 —— 它作用於「使用者自己算好的彙總值」，
# 不是原始資料的每一格，改由 Task C 在 generalize 的數值欄位上「額外」提供（dp_option）。
_VALID_TECHNIQUES = {"mask", "generalize", "suppress"}
# 傳給 Task C 的範例筆數。
# 曾經設成 3 來省 token，結果 LLM 寫值對照公式時只涵蓋看得到的那 3 筆
# （10 個縣市只對照到 3 個，其餘全部落到「其他地區」）。
# 範例最多 20 筆，整份送過去的成本可以接受。
SAMPLES_FOR_TASK_C = 20
# mask 必須提供這三個位置的公式，使用者介面才能讓使用者自行切換遮蔽位置。
# LLM 少給任何一個，就當成未通過檢查（會回饋原因讓它補上）。
REQUIRED_MASK_VARIANTS = ("left", "middle", "right")
# LLM 給的 epsilon 滑桿不合理時的備用範圍（min, max, step, default）。
# 差分隱私選項一定要回傳給前端，所以滑桿不能因為 LLM 寫錯就變成 null。
DP_FALLBACK_EPSILON = (0.1, 5.0, 0.1, 1.0)


class ClarificationRequired(Exception):
    def __init__(self, field_id: str, question: str):
        self.field_id = field_id
        self.question = question


class _FieldRecord:
    def __init__(
        self,
        index: int,
        spec: FieldSpecInput,
        purpose: str,
        purpose_detail: Optional[str],
    ):
        self.field_id = spec.id  # 前端給的 id，後端不自行產生
        self.index = index
        self.spec = spec
        self.resolved_type: ResolvedType = resolve_data_type(spec.data_type, spec.name)
        self.purpose = purpose
        self.purpose_detail = purpose_detail
        # Task A
        self.sample_before: list[str] = []
        # Task B
        self.technique: Technique = "suppress"
        self.reason: str = ""
        self.suggested_param: str = ""
        # Task C
        self.formulas: list[ExcelFormulaTemplate] = []
        self.default_variant: Optional[str] = None
        self.control_type: str = "slider"  # Task C 決定：slider 或 select
        self.slider: Optional[SliderParam] = None
        self.sensitivity: Optional[float] = None
        # 額外的差分隱私選項（與主要技術並存，作用於使用者自己算好的彙總值）
        self.dp_slider: Optional[SliderParam] = None
        self.dp_formulas: list[ExcelFormulaTemplate] = []
        self.dp_default_variant: Optional[str] = None
        self.dp_explanation: Optional[str] = None
        self.dp_input_hint: Optional[str] = None
        self.dp_sensitivity_basis: Optional[str] = None
        self.dp_formula_error: Optional[str] = None
        self.formula_error: Optional[str] = None
        self.warnings: list[str] = []


# ---------------------------------------------------------------------------
# 共用：檢查 LLM 是否把每個 field_id 都回了剛好一次
# ---------------------------------------------------------------------------
def _index_by_field_id(
    items: Any, expected_ids: list[str], task_name: str
) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise LLMOutputError(f"{task_name} 沒有回傳 fields 陣列")
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise LLMOutputError(f"{task_name} 的 fields 內含非物件元素")
        field_id = item.get("field_id")
        if field_id not in expected_ids:
            raise LLMOutputError(f"{task_name} 回傳了不存在的 field_id：{field_id!r}")
        if field_id in seen:
            raise LLMOutputError(f"{task_name} 的 field_id 重複：{field_id!r}")
        seen[field_id] = item

    missing = [fid for fid in expected_ids if fid not in seen]
    if missing:
        raise LLMOutputError(f"{task_name} 漏掉這些 field_id：{missing}")
    return seen


def _raise_if_clarification(data: dict[str, Any], expected_ids: list[str]) -> None:
    if data.get("status") != "need_clarification":
        return
    field_id = data.get("clarification_field_id") or ""
    raise ClarificationRequired(
        field_id if field_id in expected_ids else "",
        data.get("clarification_question")
        or "這個欄位的格式不太明確，可以再說明一下嗎？",
    )


# ---------------------------------------------------------------------------
# Task B：隱私保護技術判斷
# ---------------------------------------------------------------------------
async def _run_task_b(records: list[_FieldRecord]) -> None:
    expected_ids = [r.field_id for r in records]
    payload = {
        "purpose": records[0].purpose,
        "purpose_detail": records[0].purpose_detail,
        "fields": [
            {
                "field_id": r.field_id,
                "field_name": r.spec.name,
                "data_type": r.spec.data_type,
                "is_key_field": r.spec.is_key_field,
                "format_hint": r.spec.format_hint,
            }
            for r in records
        ],
    }
    data = await generate_json(
        TASK_B_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False)
    )
    _raise_if_clarification(data, expected_ids)
    indexed = _index_by_field_id(data.get("fields"), expected_ids, "Task B")

    by_id = {r.field_id: r for r in records}
    for field_id, item in indexed.items():
        record = by_id[field_id]
        technique = item.get("technique")
        if technique == "differential_privacy":
            raise LLMOutputError(
                f"Task B 對欄位「{record.spec.name}」選了 differential_privacy，"
                "但差分隱私不是 Task B 的可選技術（它作用於使用者自己算好的彙總值，"
                "不是原始資料的每一格）。彙總統計欄位請選 generalize，"
                "後續流程會再判斷是否額外提供差分隱私選項。"
            )
        if technique not in _VALID_TECHNIQUES:
            raise LLMOutputError(
                f"Task B 對欄位「{record.spec.name}」給了無效的技術：{technique!r}"
            )
        record.technique = technique  # type: ignore[assignment]
        record.suggested_param = item.get("suggested_param") or ""
        record.reason = item.get("reason") or ""
        # is_key_field 一律以使用者的勾選為準，不採用 LLM 的回填值


# ---------------------------------------------------------------------------
# Task A：合成假資料
# ---------------------------------------------------------------------------
async def _run_task_a(records: list[_FieldRecord], sample_count: int) -> None:
    expected_ids = [r.field_id for r in records]
    payload = {
        "sample_count": sample_count,
        "fields": [
            {
                "field_id": r.field_id,
                "field_name": r.spec.name,
                "data_type": r.spec.data_type,
                "format_hint": r.spec.format_hint,
            }
            for r in records
        ],
    }
    data = await generate_json(
        TASK_A_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False)
    )
    _raise_if_clarification(data, expected_ids)

    rows = data.get("records")
    if not isinstance(rows, list) or not rows:
        raise LLMOutputError("Task A 沒有回傳任何 records")
    rows = rows[:sample_count]

    by_id = {r.field_id: r for r in records}
    for row_number, row in enumerate(rows, start=1):
        cells = row.get("fields") if isinstance(row, dict) else None
        # 每一列都必須完整覆蓋所有欄位，才不會出現錯位
        indexed = _index_by_field_id(cells, expected_ids, f"Task A 第 {row_number} 筆")
        for field_id, cell in indexed.items():
            value = cell.get("value")
            by_id[field_id].sample_before.append("" if value is None else str(value))


# ---------------------------------------------------------------------------
# Task C：Excel 公式 + 滑桿規格（含一次自我修正）
# ---------------------------------------------------------------------------
def _task_c_payload(
    targets: list[_FieldRecord],
    rejected: Optional[dict[str, list[dict[str, str]]]] = None,
) -> dict[str, Any]:
    fields = []
    for r in targets:
        entry: dict[str, Any] = {
            "field_id": r.field_id,
            "field_name": r.spec.name,
            "is_key_field": r.spec.is_key_field,
            "technique": r.technique,
            "resolved_data_type": r.resolved_type,
            "suggested_param": r.suggested_param,
            "format_hint": r.spec.format_hint,
            "samples": r.sample_before[:SAMPLES_FOR_TASK_C],
            # 數值欄位可以額外提供差分隱私選項（作用於使用者自己算好的彙總值）
            "may_offer_differential_privacy": _may_offer_dp(r),
            # 敏感度要拿 samples 實際算，先把統計值算好避免 LLM 自己加減出錯
            **(
                {"sample_stats": _sample_stats(r.sample_before)}
                if _may_offer_dp(r)
                else {}
            ),
        }
        if rejected and r.field_id in rejected:
            entry["rejected"] = rejected[r.field_id]
        fields.append(entry)
    return {"fields": fields}


def _may_offer_dp(record: _FieldRecord) -> bool:
    """這個欄位適不適合額外提供差分隱私選項。

    條件是「技術為 generalize」且「欄位是數值」：這類欄位（年薪、月收入總計）
    除了泛化成區間之外，使用者若要對外公布平均值、總和這類彙總結果，
    可以另外對那個彙總值套差分隱私。

    遮罩與抑制的欄位不適用 —— 前者是固定格式的識別資料、後者整欄要刪掉，
    都不會拿去算彙總統計。
    """
    return record.technique == "generalize" and record.resolved_type in (
        "integer",
        "decimal",
    )


def _sample_numbers(samples: list[str]) -> list[float]:
    numbers = []
    for value in samples:
        try:
            numbers.append(float(str(value).replace(",", "").strip()))
        except (TypeError, ValueError):
            continue
    return numbers


def _sample_stats(samples: list[str]) -> Optional[dict[str, float]]:
    """samples 的最大值、最小值、筆數與平均，供 Task C 計算敏感度用。

    自己算好給它，是因為敏感度必須以實際的範例資料為依據；
    讓 LLM 自己從一串字串裡挑最大最小再相減，很容易算錯。
    """
    numbers = _sample_numbers(samples)
    if not numbers:
        return None
    return {
        "max": max(numbers),
        "min": min(numbers),
        "count": float(len(numbers)),
        "mean": sum(numbers) / len(numbers),
    }


def _aggregate_probe(samples: list[str]) -> Optional[float]:
    """用範例資料算一個代表性的彙總值，只用於驗算 DP 公式（不回傳給前端）。

    使用者真正要套用的彙總值由他自己計算，後端不需要也不應該算。
    """
    numbers = []
    for value in samples:
        try:
            numbers.append(float(str(value).replace(",", "").strip()))
        except (TypeError, ValueError):
            continue
    return sum(numbers) / len(numbers) if numbers else None


def _collect_formulas(
    item: dict[str, Any], record: _FieldRecord
) -> tuple[list[ExcelFormulaTemplate], list[dict[str, str]]]:
    """回傳（通過檢查的公式, 被拒的公式與原因）。"""
    accepted: list[ExcelFormulaTemplate] = []
    rejected: list[dict[str, str]] = []
    raw_formulas = item.get("formulas")
    if not isinstance(raw_formulas, list) or not raw_formulas:
        rejected.append({"variant": "(未提供)", "reason": "沒有回傳任何公式"})
        return accepted, rejected

    for formula in raw_formulas:
        if not isinstance(formula, dict):
            rejected.append(
                {"variant": "(格式錯誤)", "reason": "formulas 內含非物件元素"}
            )
            continue
        variant = formula.get("variant")
        template = formula.get("formula_template")
        if not isinstance(variant, str) or not variant.strip():
            rejected.append(
                {"variant": "(缺少 variant)", "reason": "每條公式都必須有 variant"}
            )
            continue
        if not isinstance(template, str):
            rejected.append({"variant": variant, "reason": "formula_template 不是字串"})
            continue
        # 先把 LLM 偶爾混進來的全形標點換成半角，否則 Excel 無法解析
        template, normalize_note = normalize_formula(template.strip())
        if normalize_note:
            record.warnings.append(normalize_note)

        requires_param = record.control_type == "slider"
        problem = validate_template(template, record.technique, requires_param)
        if problem is not None:
            rejected.append({"variant": variant, "reason": problem})
            continue
        # 結構檢查擋不住「語意錯誤但語法合法」的公式，所以再用範例資料實際算一次
        problem = _check_semantics(template, record)
        if problem is not None:
            rejected.append({"variant": variant, "reason": problem})
            continue

        first_sample = next((v for v in record.sample_before if v), "")
        unverifiable = (
            unverifiable_reason(template, first_sample) if first_sample else None
        )
        if unverifiable:
            record.warnings.append(
                f"這條公式（{variant}）含{unverifiable}，後端**未經語意檢查**。"
                "公式在 Excel 裡可能正常，但後端無法先幫你驗算，"
                "請務必核對「處理前／處理後」對照表。"
            )
        accepted.append(
            ExcelFormulaTemplate(
                variant=variant.strip(),
                label=formula.get("label") or variant.strip(),
                formula_template=template,
                cell_placeholder="{cell}",
                param_placeholder="{param}" if requires_param else None,
                description=formula.get("description") or "",
            )
        )

    if record.control_type == "select" and len(accepted) == 1 and not rejected:
        rejected.append(
            {
                "variant": "(select options)",
                "reason": (
                    "這個欄位用下拉選單，但只給了一個選項，使用者沒得選。"
                    "請至少給兩個層級（例如日期：只到年／到年月；"
                    "文字分類：大分類／中分類），每個層級一條完整公式。"
                ),
            }
        )

    if record.technique == "mask":
        got = {f.variant for f in accepted}
        missing = [v for v in REQUIRED_MASK_VARIANTS if v not in got]
        if missing:
            rejected.append(
                {
                    "variant": "(mask variants)",
                    "reason": (
                        f"mask 必須提供 left、middle、right 三條公式，目前缺少 {missing}。"
                        "平台的使用者介面要讓使用者自行切換遮蔽位置，三條缺一不可。"
                    ),
                }
            )
    return accepted, rejected


def _check_semantics(template: str, record: _FieldRecord) -> Optional[str]:
    """拿範例資料實際跑公式，檢查輸出是否合理。

    滑桿型欄位會用 min / 建議值 / max 各試一次；下拉選單型沒有參數，
    只檢查「算得出結果」與技術專屬規則。
    """
    slider = record.slider
    if slider is None:
        return None
    if slider.control_type != "slider":
        return check_formula(
            template=template,
            technique=record.technique,
            resolved_type=record.resolved_type,
            samples=record.sample_before,
        )
    if slider.min is None or slider.max is None:
        return None
    return check_formula(
        template=template,
        technique=record.technique,
        resolved_type=record.resolved_type,
        samples=record.sample_before,
        minimum=slider.min,
        maximum=slider.max,
        step=slider.step or 1.0,
        default=slider.default if slider.default is not None else slider.min,
        param_name=slider.param_name or "",
    )


def _apply_control(item: dict[str, Any], record: _FieldRecord) -> Optional[str]:
    """讀取 Task C 決定的控制元件，回傳錯誤原因（None 表示通過）。

    control_type 由 LLM 判斷（處理強度是一個數字還是幾種層級）。後端不覆寫它的決定，
    只檢查它有沒有自相矛盾 —— 說 slider 卻沒給滑桿規格、說 select 卻附了滑桿，
    這類不一致會退回讓它重寫。公式裡能不能用 {param} 也跟著這個值決定。
    """
    raw_type = item.get("control_type")
    if raw_type not in ("slider", "select"):
        return (
            f"control_type 必須是 slider 或 select，收到 {raw_type!r}。"
            "處理強度是一個連續數字就填 slider，是幾種層級就填 select。"
        )
    record.control_type = raw_type

    if raw_type == "select":
        if isinstance(item.get("slider"), dict):
            return "control_type 是 select，slider 請填 null，並改為每個層級各給一條完整公式"
        record.slider = SliderParam(control_type="select")
        return None

    raw = item.get("slider")
    if not isinstance(raw, dict):
        return (
            "control_type 是 slider，必須回傳 slider 物件（min／max／step／default／unit）。"
            "若這個欄位其實是「幾種層級」而不是「一個數字」，請改用 select。"
        )
    problem = validate_slider(
        raw.get("min"), raw.get("max"), raw.get("step"), raw.get("default")
    )
    if problem is not None:
        return problem

    minimum, maximum, step, default, notes = clamp_slider(
        param_name=str(raw.get("param_name") or ""),
        minimum=float(raw["min"]),
        maximum=float(raw["max"]),
        step=float(raw["step"]),
        default=float(raw["default"]),
        technique=record.technique,
        samples=record.sample_before,
    )
    record.warnings.extend(notes)
    record.slider = SliderParam(
        control_type="slider",
        param_name=str(raw.get("param_name") or "param"),
        min=minimum,
        max=maximum,
        step=step,
        default=default,
        unit=str(raw.get("unit") or ""),
        value_when_none=None,
    )
    return None


def _apply_dp_option(
    item: dict[str, Any], record: _FieldRecord
) -> list[dict[str, str]]:
    """解析額外的差分隱私選項，回傳被拒項目（空 list 表示沒問題或沒提供）。

    重要原則：**只要 LLM 判定這個欄位適用差分隱私，就一定要把 DP 區塊回傳給前端**，
    不因為公式有問題而整個消失。所以這裡把能解析的部分（敏感度、epsilon 滑桿、
    說明文字）一律寫進 record，公式則分兩層處理：

    - 沒通過 formula_guard 的**安全**檢查（例如夾帶 WEBSERVICE）→ 不回傳那條公式。
      公式會被複製進使用者的真實 Excel，這種東西不能交出去。
    - 通過安全檢查但沒通過**語意**驗算 → 照樣回傳，並記在 dp_formula_error，
      讓前端提醒使用者核對結果。

    兩種情況都會把原因回饋給 Task C 重寫；修正次數用完後由 _run_task_c 收尾。
    """
    record.dp_slider = None
    record.dp_formulas = []
    record.dp_default_variant = None
    record.dp_explanation = None
    record.dp_input_hint = None
    record.dp_sensitivity_basis = None
    record.dp_formula_error = None

    raw = item.get("dp_option")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return [{"variant": "(dp_option)", "reason": "dp_option 必須是物件或 null"}]
    if not _may_offer_dp(record):
        return [
            {
                "variant": "(dp_option)",
                "reason": "這個欄位不適合額外的差分隱私選項（僅數值欄位、且主要技術不是"
                " differential_privacy 時才需要），dp_option 請填 null",
            }
        ]

    problems: list[dict[str, str]] = []
    semantic_notes: list[str] = []

    # --- 敏感度 ---
    try:
        sensitivity = float(raw.get("sensitivity"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        sensitivity = 0.0
    if sensitivity > 0:
        record.sensitivity = sensitivity
    else:
        problems.append(
            {
                "variant": "(dp_option.sensitivity)",
                "reason": "差分隱私的敏感度 Δf 必須是正數，代表「單一筆資料改變時最多會讓"
                "這個彙總值變動多少」",
            }
        )

    # Δf 取決於使用者真實資料的上下界與筆數，LLM 都不知道、只能假設。
    # 所以硬性要求它寫出算式與假設，並檢查算式裡真的出現那個數字 ——
    # 否則使用者拿到一個看起來精確但無從檢查的隱私保證。
    basis = raw.get("sensitivity_basis")
    basis_problem = None
    if not isinstance(basis, str) or len(basis.strip()) < 30:
        basis_problem = (
            "sensitivity_basis 要寫出 Δf 的算式與假設（彙總方式、假設的數值上下界與筆數、"
            "代入後算出的數字），至少 30 字。使用者要靠它判斷這個 Δf 適不適合他的資料"
        )
    elif sensitivity > 0 and not _mentions_number(basis, sensitivity):
        basis_problem = (
            f"sensitivity_basis 沒有出現 sensitivity 的數字 {_fmt_sensitivity(sensitivity)}，"
            "請把算式完整寫出來（例如「(1580000-640000)÷5 = 188000」），"
            "讓使用者看得出這個數字是怎麼來的"
        )
    else:
        # 敏感度必須以實際的範例資料為依據，不能是憑空假設的上下界。
        # 檢查算式裡有沒有出現 samples 的最大值或最小值。
        stats = _sample_stats(record.sample_before)
        if stats and not (
            _mentions_number(basis, stats["max"])
            or _mentions_number(basis, stats["min"])
        ):
            basis_problem = (
                "sensitivity_basis 要用輸入的 samples 實際舉例計算，"
                f"但算式裡沒有出現範例資料的最大值 {_fmt_sensitivity(stats['max'])} "
                f"或最小值 {_fmt_sensitivity(stats['min'])}。"
                "請寫成「範例資料共 N 筆，最高 X、最低 Y，Δf =（X − Y）÷ N = Z」的形式，"
                "並提醒使用者真實資料的筆數不同時要重算"
            )
    if basis_problem:
        problems.append(
            {"variant": "(dp_option.sensitivity_basis)", "reason": basis_problem}
        )
    else:
        record.dp_sensitivity_basis = str(basis).strip()

    # --- epsilon 滑桿（不合理時仍給一組可用的預設，前端才有滑桿可畫）---
    slider_raw = raw.get("slider") if isinstance(raw.get("slider"), dict) else None
    slider_problem = (
        validate_slider(
            slider_raw.get("min"),
            slider_raw.get("max"),
            slider_raw.get("step"),
            slider_raw.get("default"),
        )
        if slider_raw
        else "缺少 epsilon 的 slider 物件"
    )
    if slider_raw and slider_problem is None:
        record.dp_slider = SliderParam(
            control_type="slider",
            param_name=str(slider_raw.get("param_name") or "epsilon"),
            min=float(slider_raw["min"]),
            max=float(slider_raw["max"]),
            step=float(slider_raw["step"]),
            default=float(slider_raw["default"]),
            unit=str(slider_raw.get("unit") or "epsilon"),
            value_when_none=None,
        )
    else:
        problems.append(
            {"variant": "(dp_option.slider)", "reason": slider_problem or ""}
        )
        record.dp_slider = SliderParam(
            control_type="slider",
            param_name="epsilon",
            min=DP_FALLBACK_EPSILON[0],
            max=DP_FALLBACK_EPSILON[1],
            step=DP_FALLBACK_EPSILON[2],
            default=DP_FALLBACK_EPSILON[3],
            unit="隱私預算 epsilon（值越小保護越強、誤差越大）",
        )
        record.warnings.append(
            "差分隱私的 epsilon 滑桿範圍由 LLM 給的值不合理，已改用平台預設的 0.1~5.0。"
        )

    # --- 說明文字 ---
    explanation = raw.get("explanation")
    input_hint = raw.get("input_hint")
    if isinstance(explanation, str) and len(explanation.strip()) >= 20:
        record.dp_explanation = explanation.strip()
    else:
        problems.append(
            {
                "variant": "(dp_option.explanation)",
                "reason": "explanation 要用白話說明 M(x)=f(x)+Lap(Δf/ε) 在做什麼"
                "（至少 20 字），這段會直接顯示給非技術背景的使用者",
            }
        )
    if isinstance(input_hint, str) and input_hint.strip():
        record.dp_input_hint = input_hint.strip()
    else:
        problems.append(
            {
                "variant": "(dp_option.input_hint)",
                "reason": "input_hint 要說明使用者該把什麼值填進儲存格"
                "（例如「請填入你自己算好的全體平均年薪」）",
            }
        )

    # --- 公式：安全檢查不通過就不回傳，語意檢查不通過仍回傳 ---
    probe = _aggregate_probe(record.sample_before)
    accepted: list[ExcelFormulaTemplate] = []
    raw_formulas = raw.get("formulas")
    if not isinstance(raw_formulas, list) or not raw_formulas:
        problems.append(
            {"variant": "(dp_option.formulas)", "reason": "沒有回傳任何差分隱私公式"}
        )
        raw_formulas = []

    for formula in raw_formulas:
        if not isinstance(formula, dict):
            problems.append(
                {"variant": "(dp_option.formulas)", "reason": "formulas 內含非物件元素"}
            )
            continue
        variant = formula.get("variant")
        template = formula.get("formula_template")
        if (
            not isinstance(variant, str)
            or not variant.strip()
            or not isinstance(template, str)
        ):
            problems.append(
                {
                    "variant": "(dp_option.formulas)",
                    "reason": "每條差分隱私公式都要有 variant 與 formula_template",
                }
            )
            continue

        template, normalize_note = normalize_formula(template.strip())
        if normalize_note:
            record.warnings.append(normalize_note)

        safety_problem = validate_template(
            template, "differential_privacy", requires_param=True
        )
        if safety_problem is not None:
            # 安全檢查沒過的公式不能交給使用者執行
            problems.append(
                {"variant": f"(dp_option.{variant})", "reason": safety_problem}
            )
            continue

        if probe is not None and record.dp_slider is not None:
            semantic_problem = check_formula(
                template=template,
                technique="differential_privacy",
                resolved_type=record.resolved_type,
                samples=[_fmt_probe(probe)],
                minimum=record.dp_slider.min,
                maximum=record.dp_slider.max,
                step=record.dp_slider.step,
                default=record.dp_slider.default,
                param_name="epsilon",
            )
            if semantic_problem is not None:
                problems.append(
                    {"variant": f"(dp_option.{variant})", "reason": semantic_problem}
                )
                semantic_notes.append(
                    f"公式「{variant}」未通過語意驗算：{semantic_problem}"
                )

        # 語意沒過也照樣回傳 —— 前端要有公式可顯示
        accepted.append(
            ExcelFormulaTemplate(
                variant=variant.strip(),
                label=formula.get("label") or variant.strip(),
                formula_template=template,
                cell_placeholder="{cell}",
                param_placeholder="{param}",
                description=formula.get("description") or "",
            )
        )

    record.dp_formulas = accepted
    if accepted:
        raw_default = raw.get("default_variant")
        variants = [f.variant for f in accepted]
        record.dp_default_variant = (
            raw_default
            if isinstance(raw_default, str) and raw_default in variants
            else variants[0]
        )
        if (
            probe is not None
            and record.dp_slider
            and record.dp_slider.default is not None
        ):
            note = check_noise_magnitude(
                accepted[0].formula_template,
                [_fmt_probe(probe)],
                record.dp_slider.default,
                record.dp_slider.min,
            )
            if note:
                record.warnings.append(f"差分隱私選項：{note}")
    if semantic_notes:
        record.dp_formula_error = "；".join(semantic_notes)
    return problems


def _fmt_sensitivity(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _mentions_number(text: str, value: float) -> bool:
    """算式裡有沒有出現這個數字（容許千分位逗號與全形逗號）。"""
    plain = _fmt_sensitivity(value)
    normalized = text.replace(",", "").replace("，", "").replace(" ", "")
    return plain in normalized


def _fmt_probe(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.2f}"


def _apply_sensitivity(item: dict[str, Any], record: _FieldRecord) -> Optional[str]:
    """主要技術的敏感度。

    差分隱私已經不是 Task B 的可選技術，所以這裡實際上不會被觸發；
    保留是為了萬一日後把它加回主要技術時流程還在。
    額外的差分隱私選項走 _apply_dp_option。
    """
    if record.technique != "differential_privacy":
        return None
    raw = item.get("sensitivity")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "differential_privacy 必須在 sensitivity 填入正數"
    if not (value > 0):
        return "sensitivity 必須大於 0"
    record.sensitivity = value
    record.warnings.append(
        f"公式中的敏感度 {value} 是 LLM 依範例資料判斷的建議值，不是正式的隱私保證。"
        "請依「單一個體最多能影響此數值多少」確認後再用於真實資料。"
    )
    return None


async def _run_task_c(records: list[_FieldRecord], max_repairs: int) -> None:
    targets = [r for r in records if r.technique != "suppress"]
    if not targets:
        return

    expected_ids = [r.field_id for r in targets]
    rejected: Optional[dict[str, list[dict[str, str]]]] = None
    pending = targets

    for attempt in range(max_repairs + 1):
        payload = _task_c_payload(pending, rejected)
        data = await generate_json(
            TASK_C_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False)
        )
        indexed = _index_by_field_id(
            data.get("fields"),
            [r.field_id for r in pending],
            f"Task C（第 {attempt + 1} 次）",
        )

        rejected = {}
        still_pending: list[_FieldRecord] = []
        for record in pending:
            item = indexed[record.field_id]
            problems: list[dict[str, str]] = []
            # 這一輪重新累積，否則重試時會出現重複的警告
            record.warnings.clear()

            control_problem = _apply_control(item, record)
            if control_problem:
                problems.append({"variant": "(control)", "reason": control_problem})

            sensitivity_problem = _apply_sensitivity(item, record)
            if sensitivity_problem:
                problems.append(
                    {"variant": "(sensitivity)", "reason": sensitivity_problem}
                )

            # 額外的差分隱私選項：失敗只丟掉這個選項，不影響主要公式
            dp_problems = _apply_dp_option(item, record)

            if control_problem:
                # 控制元件不明時無法判斷公式該不該含 {param}，這一輪先不收公式
                accepted, formula_problems = [], []
            else:
                accepted, formula_problems = _collect_formulas(item, record)
            problems.extend(formula_problems)
            record.formulas = accepted
            raw_default = item.get("default_variant")
            variants = [f.variant for f in accepted]
            record.default_variant = (
                raw_default
                if isinstance(raw_default, str) and raw_default in variants
                else (variants[0] if variants else None)
            )

            if (
                not problems and record.technique == "differential_privacy"
            ):  # pragma: no cover
                slider = record.slider
                if slider and slider.default is not None and record.formulas:
                    note = check_noise_magnitude(
                        record.formulas[0].formula_template,
                        record.sample_before,
                        slider.default,
                        slider.min,
                    )
                    if note:
                        record.warnings.append(note)

            if problems or dp_problems:
                logger.warning(
                    "Task C 第 %d 次：欄位 %s(%s) 有 %d 項未通過（其中差分隱私選項 %d 項）：%s",
                    attempt + 1,
                    record.spec.name,
                    record.field_id,
                    len(problems) + len(dp_problems),
                    len(dp_problems),
                    problems + dp_problems,
                )
                rejected[record.field_id] = problems + dp_problems
                still_pending.append(record)
                record.formula_error = None  # 還有機會修好，先不留上一輪的錯誤

        if not still_pending:
            return
        pending = still_pending

    # 修正次數用完：回報錯誤，不替換成其他公式
    for record in pending:
        reasons = rejected.get(record.field_id, []) if rejected else []
        dp_reasons = [p for p in reasons if p["variant"].startswith("(dp_option")]
        main_reasons = [p for p in reasons if not p["variant"].startswith("(dp_option")]

        if dp_reasons and not main_reasons and record.formulas:
            # 主要公式是好的，只有「額外」的差分隱私選項有問題。
            # DP 區塊照樣回傳（LLM 判定這個欄位適用差分隱私就該讓使用者看到），
            # 把原因寫進 dp_formula_error 讓前端決定怎麼呈現。
            detail = "；".join(f"{p['variant']}：{p['reason']}" for p in dp_reasons)
            logger.warning(
                "欄位 %s 的差分隱私選項最終未完全通過：%s", record.field_id, detail
            )
            record.dp_formula_error = detail
            if record.dp_formulas:
                record.warnings.append(
                    "差分隱私公式沒有通過後端的語意驗算，仍然提供給你參考，"
                    "但請務必自己核對算出來的數字是否合理。"
                )
            else:
                record.warnings.append(
                    "這個欄位適用差分隱私，但公式沒有通過安全檢查，因此沒有提供公式。"
                    "主要的處理方式仍然可用。"
                )
            continue

        detail = (
            "；".join(
                f"{p['variant']}：{p['reason']}" for p in (main_reasons or reasons)
            )
            or "未知原因"
        )
        record.formula_error = (
            f"公式產生失敗（已讓 LLM 修正 {max_repairs} 次）：{detail}"
        )
        if record.slider is None or record.slider.control_type == "select":
            # 沒有可用的控制元件時，讓前端知道這個欄位沒有可調參數
            record.slider = SliderParam(control_type="none", value_when_none="none")
    _ = expected_ids  # 僅用於說明預期範圍，實際檢查在 _index_by_field_id


# ---------------------------------------------------------------------------
# 組裝
# ---------------------------------------------------------------------------
# 逐一配對引號，才不會把「兩個常值之間的程式碼」誤當成常值。
# 例如 TEXT(...,"0"),"-",TEXT(...,"0") 用 {2,} 的寫法會抓到 `),` 這種東西。
_QUOTED_LITERAL_RE = re.compile(r'"([^"]*)"')
# 純數字、標點、格式字串（"0"、"0.00"、"-"、"yyyy"）不算「分類標籤」
_NOT_A_LABEL_RE = re.compile(r"^[\d.,\-/:#%\s]*$|^[yYmMdD]+$")


def _looks_like_value_mapping(record: _FieldRecord) -> bool:
    """公式裡若出現多個「分類標籤」字串，表示它在做值對照而非截斷／計算。

    例如 IF({cell}="餐飲業","服務業",…)。這種公式只涵蓋 LLM 看得到的範例值，
    真實資料的其他值會落到預設類別，必須提醒使用者。

    分隔符號與 TEXT 的格式字串（"-"、"0"、"yyyy"）不算，否則
    年份區間公式會被誤判。
    """
    if record.technique != "generalize":
        return False
    for formula in record.formulas:
        labels = [
            literal
            for literal in _QUOTED_LITERAL_RE.findall(formula.formula_template)
            if len(literal) >= 2 and not _NOT_A_LABEL_RE.match(literal)
        ]
        if len(labels) >= 2:
            return True
    return False


def _extra_warnings(record: _FieldRecord) -> list[str]:
    warnings: list[str] = []
    if record.technique == "suppress":
        warnings.append("建議直接刪除整欄；此欄位沒有可調參數，也沒有 Excel 公式。")
    if record.dp_formulas:
        warnings.append(
            "Excel 的 RAND() 每次重新計算都會產生新的雜訊，等同重複發布、累積消耗隱私預算，"
            "套用後請立刻「複製 → 選擇性貼上 → 值」把結果固定下來。"
        )
        warnings.append(
            "多個欄位同時採用差分隱私時，總隱私預算會累加，本平台未計算這件事。"
        )
    if record.dp_formulas:
        warnings.append(
            "差分隱私選項的公式作用在「你自己算好的彙總值」上，不是原始資料的每一格。"
            f"敏感度 Δf 目前是 {record.sensitivity}，是用平台生成的"
            f"{len(record.sample_before)} 筆範例假資料算出來的"
            + (
                "（算式見 dp_sensitivity_basis）。"
                if record.dp_sensitivity_basis
                else "。"
            )
            + "**你的真實資料筆數幾乎一定不同** —— 平均值查詢的 Δf 與筆數成反比，"
            "筆數差一個數量級、Δf 就差一個數量級，套用前請依實際資料重算。"
        )
    if _looks_like_value_mapping(record):
        warnings.append(
            "這條公式是用「值對照」的方式分類（把特定文字換成另一種說法），"
            "而它只看得到平台生成的範例資料。真實資料若出現範例以外的值，"
            "會被歸到公式裡的預設類別，套用前請先確認對照表涵蓋你所有的資料。"
        )
    if len(record.formulas) > 1:
        warnings.append(
            f"這個欄位有 {len(record.formulas)} 條公式可選，請確認選到的是符合需求的那一條。"
        )
    if not record.reason:
        warnings.append("LLM 沒有提供選擇理由，建議重新分析一次。")
    return warnings


async def analyze(
    fields: list[FieldSpecInput],
    sample_count: int,
    purpose: str,
    purpose_detail: Optional[str],
) -> AnalyzeResponse:
    settings = get_settings()
    records = [
        _FieldRecord(i, spec, purpose, purpose_detail) for i, spec in enumerate(fields)
    ]

    try:
        # 先跑 B：B 最常要求澄清。若 A 先跑完才被 B 擋下，A 那次請求的每日配額就浪費了。
        await _run_task_b(records)
        await _run_task_a(records, sample_count)
        # C 需要 A 的範例資料來驗算公式與決定滑桿範圍，所以排在 A 之後
        await _run_task_c(records, settings.formula_repair_attempts)
    except ClarificationRequired as exc:
        matched = next((r for r in records if r.field_id == exc.field_id), None)
        return AnalyzeResponse(
            status="need_clarification",
            fields=[],
            clarifications_needed=[
                ClarificationNeeded(
                    field_id=exc.field_id,
                    field_name=matched.spec.name if matched else "",
                    clarification_question=exc.question,
                )
            ],
        )

    processed: list[ProcessedField] = []
    for r in records:
        param = r.slider or SliderParam(control_type="none", value_when_none="none")
        processed.append(
            ProcessedField(
                field_id=r.field_id,
                field_name=r.spec.name,
                is_key_field=r.spec.is_key_field,
                technique=r.technique,
                reason=r.reason,
                param=param,
                sample_before=r.sample_before,
                excel_formulas=r.formulas,
                default_variant=r.default_variant,
                formula_error=r.formula_error,
                dp_sensitivity=r.sensitivity,
                dp_param=r.dp_slider,
                dp_excel_formulas=r.dp_formulas,
                dp_default_variant=r.dp_default_variant,
                dp_explanation=r.dp_explanation,
                dp_input_hint=r.dp_input_hint,
                dp_sensitivity_basis=r.dp_sensitivity_basis,
                dp_formula_error=r.dp_formula_error,
                warnings=r.warnings + _extra_warnings(r),
            )
        )

    return AnalyzeResponse(status="ok", fields=processed, clarifications_needed=[])
