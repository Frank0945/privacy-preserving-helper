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
from core.formula_guard import validate_slider, validate_template
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

_VALID_TECHNIQUES = {"mask", "generalize", "suppress", "differential_privacy"}
# 傳給 Task C 的範例筆數。
# 曾經設成 3 來省 token，結果 LLM 寫值對照公式時只涵蓋看得到的那 3 筆
# （10 個縣市只對照到 3 個，其餘全部落到「其他地區」）。
# 範例最多 20 筆，整份送過去的成本可以接受。
SAMPLES_FOR_TASK_C = 20
# mask 必須提供這三個位置的公式，使用者介面才能讓使用者自行切換遮蔽位置。
# LLM 少給任何一個，就當成未通過檢查（會回饋原因讓它補上）。
REQUIRED_MASK_VARIANTS = ("left", "middle", "right")


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
        self.slider: Optional[SliderParam] = None
        self.sensitivity: Optional[float] = None
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
            "technique": r.technique,
            "resolved_data_type": r.resolved_type,
            "suggested_param": r.suggested_param,
            "format_hint": r.spec.format_hint,
            "samples": r.sample_before[:SAMPLES_FOR_TASK_C],
        }
        if rejected and r.field_id in rejected:
            entry["rejected"] = rejected[r.field_id]
        fields.append(entry)
    return {"fields": fields}


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
        problem = validate_template(template, record.technique)
        if problem is not None:
            rejected.append({"variant": variant, "reason": problem})
            continue
        accepted.append(
            ExcelFormulaTemplate(
                variant=variant.strip(),
                label=formula.get("label") or variant.strip(),
                formula_template=template.strip(),
                cell_placeholder="{cell}",
                param_placeholder="{param}",
                description=formula.get("description") or "",
            )
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


def _apply_slider(item: dict[str, Any], record: _FieldRecord) -> Optional[str]:
    """把 LLM 的滑桿規格寫進 record，回傳錯誤原因（None 表示通過）。"""
    raw = item.get("slider")
    if not isinstance(raw, dict):
        return "沒有回傳 slider 物件"
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


def _apply_sensitivity(item: dict[str, Any], record: _FieldRecord) -> Optional[str]:
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

            slider_problem = _apply_slider(item, record)
            if slider_problem:
                problems.append({"variant": "(slider)", "reason": slider_problem})

            sensitivity_problem = _apply_sensitivity(item, record)
            if sensitivity_problem:
                problems.append(
                    {"variant": "(sensitivity)", "reason": sensitivity_problem}
                )

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

            if problems:
                logger.warning(
                    "Task C 第 %d 次：欄位 %s(%s) 有 %d 項未通過：%s",
                    attempt + 1,
                    record.spec.name,
                    record.field_id,
                    len(problems),
                    problems,
                )
                rejected[record.field_id] = problems
                still_pending.append(record)

        if not still_pending:
            return
        pending = still_pending

    # 修正次數用完：回報錯誤，不替換成其他公式
    for record in pending:
        reasons = rejected.get(record.field_id, []) if rejected else []
        detail = (
            "；".join(f"{p['variant']}：{p['reason']}" for p in reasons) or "未知原因"
        )
        record.formula_error = (
            f"公式產生失敗（已讓 LLM 修正 {max_repairs} 次）：{detail}"
        )
        if record.slider is None:
            # 沒有滑桿規格就無法顯示滑桿，但仍要回傳一個合法的 param 物件
            record.slider = SliderParam(control_type="none", value_when_none="none")
    _ = expected_ids  # 僅用於說明預期範圍，實際檢查在 _index_by_field_id


# ---------------------------------------------------------------------------
# 組裝
# ---------------------------------------------------------------------------
_QUOTED_LITERAL_RE = re.compile(r'"([^"]{2,})"')


def _looks_like_value_mapping(record: _FieldRecord) -> bool:
    """公式裡若出現多個「兩個字以上的字串常值」，表示它在做值對照而非截斷／計算。

    例如 IF({cell}="餐飲業","服務業",…)。這種公式只涵蓋 LLM 看得到的範例值，
    真實資料的其他值會落到預設類別，必須提醒使用者。
    """
    if record.technique != "generalize":
        return False
    for formula in record.formulas:
        literals = _QUOTED_LITERAL_RE.findall(formula.formula_template)
        if len(literals) >= 2:
            return True
    return False


def _extra_warnings(record: _FieldRecord) -> list[str]:
    warnings: list[str] = []
    if record.technique == "suppress":
        warnings.append("建議直接刪除整欄；此欄位沒有可調參數，也沒有 Excel 公式。")
    if record.technique == "differential_privacy":
        warnings.append(
            "Excel 的 RAND() 每次重新計算都會產生新的雜訊，等同重複發布、累積消耗隱私預算，"
            "套用後請立刻「複製 → 選擇性貼上 → 值」把結果固定下來。"
        )
        warnings.append(
            "多個欄位同時採用差分隱私時，總隱私預算會累加，本平台未計算這件事。"
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
                technique=r.technique,
                reason=r.reason,
                param=param,
                sample_before=r.sample_before,
                excel_formulas=r.formulas,
                default_variant=r.default_variant,
                formula_error=r.formula_error,
                dp_sensitivity=r.sensitivity,
                warnings=r.warnings + _extra_warnings(r),
            )
        )

    return AnalyzeResponse(status="ok", fields=processed, clarifications_needed=[])
