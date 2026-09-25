"""
前後端 API 合約。

每個 Field(description=...) 都會出現在 /docs 與 /redoc，
前端工程師只需看 /docs 就能知道每個欄位的意義。

注意：所有可省略的欄位一律寫成 Field(default=None, ...)。
若寫成 Field(None, ...)，Pylance 會把該欄位當成必填而在編輯器裡誤報。
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

Technique = Literal["mask", "generalize", "suppress", "differential_privacy"]


class Purpose(str, Enum):
    INTERNAL = "內部使用"
    CROSS_DEPARTMENT = "跨部門提供"
    PUBLIC_RESEARCH = "對外公開研究"
    OTHER = "其他"


# ===========================================================================
# 請求
# ===========================================================================
class FieldSpecInput(BaseModel):
    """使用者在前端表單輸入的單一欄位規格。"""

    id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "欄位唯一識別碼，**由前端產生**（例如 `f1`、`crypto.randomUUID()`）。"
            "同一次請求內不可重複。欄位名稱允許重複，後端與 LLM 一律以此 id 對應。"
        ),
        examples=["f1"],
    )
    name: str = Field(
        ..., min_length=1, max_length=50, description="欄位名稱", examples=["手機號碼"]
    )
    data_type: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="欄位型態，建議使用「文字 / 數字 / 金額 / 日期」；後端會依關鍵字判斷要套哪一種公式",
        examples=["文字"],
    )
    format_hint: Optional[str] = Field(
        default=None,
        max_length=200,
        description="格式規則或用途補充（選填）。收到 need_clarification 時，把使用者的補充說明填在這裡再重送",
        examples=["09XX-XXX-XXX"],
    )
    is_key_field: bool = Field(default=False, description="是否為關鍵分析欄位")


class AnalyzeRequest(BaseModel):
    fields: List[FieldSpecInput] = Field(..., min_length=1, max_length=30)
    sample_count: Literal[5, 10, 20] = Field(5, description="要生成幾筆範例假資料")
    purpose: Purpose = Field(..., description="資料使用目的")
    purpose_detail: Optional[str] = Field(
        default=None, max_length=200, description="purpose 為「其他」時必填的自訂說明"
    )

    @model_validator(mode="after")
    def _check(self) -> "AnalyzeRequest":
        ids = [f.id for f in self.fields]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"欄位 id 重複：{duplicated}")
        if self.purpose is Purpose.OTHER and not (self.purpose_detail or "").strip():
            raise ValueError("purpose 為「其他」時必須填寫 purpose_detail")
        return self


# ===========================================================================
# 回應
# ===========================================================================
class SliderParam(BaseModel):
    """前端控制元件的設定。

    連續參數用滑桿（control_type=slider）；離散層級改用下拉選單
    （control_type=select，選項就是 excel_formulas 的各個 variant，此處欄位皆為 null）。
    """

    control_type: Literal["slider", "select", "none"] = Field(
        ...,
        description="前端要顯示哪種控制元件。\n"
        "`slider`：連續數值參數（遮蔽位數、數值區間、epsilon），用 min/max/step/default\n"
        "`select`：離散層級（產業別要分大類還是中類、日期要保留到年還是年月）——"
        "選項就是 excel_formulas 的每一條，用 label 渲染下拉選單，"
        "初始選 ProcessedField.default_variant；此時 min/max/step/default 皆為 null\n"
        "`none`：沒有可調參數（抑制，或公式產生失敗）",
    )
    param_name: Optional[str] = Field(
        default=None,
        description="滑桿的參數代碼，由 LLM 命名（常見值：mask_length、interval、epsilon）。"
        "僅供前端識別，不要用它來決定計算邏輯 —— 計算一律交給公式。"
        "control_type 不是 slider 時為 null",
    )
    min: Optional[float] = Field(default=None, description="滑桿最小值")
    max: Optional[float] = Field(default=None, description="滑桿最大值")
    step: Optional[float] = Field(default=None, description="滑桿間距")
    default: Optional[float] = Field(
        default=None, description="平台建議值（畫面初始值）"
    )
    unit: Optional[str] = Field(
        default=None, description="單位或說明文字，直接顯示在滑桿旁"
    )
    value_when_none: Optional[str] = Field(
        default=None, description='control_type 為 none 時固定為 "none"，其餘為 null'
    )


class ExcelFormulaTemplate(BaseModel):
    """一條由 LLM 產生、並通過後端安全檢查的 Excel 公式。

    後端不內建任何公式，所有公式都由 Task C 依 Task B 的建議撰寫。
    沒通過檢查的公式不會出現在這裡（見 ProcessedField.formula_error）。
    """

    variant: str = Field(
        ...,
        description="這條公式的代碼，也是 control_type=select 時下拉選單的值。"
        "**mask 保證有 left / middle / right 三條**"
        "（讓使用者切換遮蔽位置，後端會檢查缺一就要求 LLM 補上）；"
        "其他技術的 variant 由 LLM 命名、條數不固定"
        "（例如日期可能有文字格式與 Excel 日期格式兩條），請用 label 渲染選單",
        examples=["middle"],
    )
    label: str = Field(
        ..., description="給使用者看的公式名稱", examples=["遮蔽中間 N 位"]
    )
    formula_template: str = Field(
        ...,
        description="公式樣板，含 {cell} 與 {param} 佔位符，以字串取代即可使用",
        examples=[
            '=REPLACE({cell},1,MIN({param},LEN({cell})),REPT("*",MIN({param},LEN({cell}))))'
        ],
    )
    cell_placeholder: str = Field(
        "{cell}",
        description="原始資料儲存格的佔位符，**要代入哪一格由前端決定**。"
        "畫面預覽時代入前端暫存試算表中放 sample_before[r] 的那一格；"
        "提供給使用者複製時代入該欄位在他自己 Excel 中的儲存格",
    )
    param_placeholder: Optional[str] = Field(
        default="{param}",
        description="滑桿值的佔位符。control_type=select 的公式沒有可調參數，此欄為 null，"
        "前端只需取代 cell_placeholder",
    )
    description: str = Field("", description="使用說明")


class ProcessedField(BaseModel):
    field_id: str = Field(..., description="與請求中的 fields[].id 完全相同")
    field_name: str = Field(..., description="欄位名稱（原樣回傳，方便直接顯示）")
    is_key_field: bool = Field(
        ..., description="是否為關鍵分析欄位（原樣回傳，方便直接顯示）"
    )
    technique: Technique = Field(..., description="LLM 判斷的隱私保護技術")
    reason: str = Field(
        "",
        description="給非技術背景使用者看的白話說明。"
        "若請求的 purpose 為「其他」，LLM 會在這段文字裡註明它把 purpose_detail "
        "判讀成哪一種情境，並提醒使用者確認",
    )
    param: SliderParam = Field(
        ...,
        description="滑桿設定。min/max/step/default 由 LLM 依範例資料決定，後端只做合理性檢查",
    )
    sample_before: List[str] = Field(
        ..., description="處理前的合成假資料（非真人資料）"
    )
    excel_formulas: List[ExcelFormulaTemplate] = Field(
        ...,
        description="通過檢查的公式清單。抑制（suppress）固定為空陣列；"
        "若為空陣列但技術不是 suppress，表示公式產生失敗，請看 formula_error",
    )
    default_variant: Optional[str] = Field(
        default=None,
        description="初始要選用哪一條公式的 variant。control_type=select 時就是下拉選單的預設選項；"
        "mask 則是 LLM 建議的遮蔽位置。沒有公式時為 null。使用者可自行切換到其他條",
    )
    formula_error: Optional[str] = Field(
        default=None,
        description="公式產生失敗的原因（LLM 修正後仍未通過安全檢查，或 LLM 未提供）。"
        "前端請顯示「這個欄位的公式產生失敗，請重新分析」，不要顯示技術細節給一般使用者",
    )
    dp_sensitivity: Optional[float] = Field(
        default=None,
        description="差分隱私的敏感度 Δf（已代入公式中的數字）。"
        "technique 為 differential_privacy 時屬於主要技術；"
        "否則搭配下方 dp_* 欄位，屬於額外提供的選項",
    )

    # --- 額外的差分隱私選項（與主要技術並存）------------------------------
    # 例如「年薪」主要建議泛化成區間，但使用者若要對外公布平均年薪這類彙總值，
    # 可以另外套用差分隱私。作用對象不是單筆資料，而是使用者自己算好的彙總值。
    dp_param: Optional[SliderParam] = Field(
        default=None,
        description="額外差分隱私選項的 epsilon 滑桿（control_type 固定為 slider）。"
        "為 null 表示這個欄位沒有提供額外的差分隱私選項"
        "（technique 本身就是 differential_privacy 時也是 null —— 那時看 param）",
    )
    dp_excel_formulas: List[ExcelFormulaTemplate] = Field(
        default_factory=list,
        description="額外差分隱私選項的公式。**`{cell}` 要代入的不是原始資料那一格，"
        "而是使用者自己算好的彙總值（例如平均年薪）所在的儲存格**；"
        "`{param}` 是 epsilon。空陣列表示沒有提供這個選項",
    )
    dp_default_variant: Optional[str] = Field(
        default=None, description="dp_excel_formulas 初始要選用哪一條的 variant"
    )
    dp_sensitivity_basis: Optional[str] = Field(
        default=None,
        description="敏感度 Δf 是怎麼算出來的：彙總方式、**平台生成的範例假資料**的"
        "最大值／最小值／筆數、代入後的算式。"
        "**這是用範例假資料算的，不是使用者的真實資料** —— "
        "請顯示在敏感度數字旁邊，讓使用者知道要依自己的資料重算"
        "（平均值查詢的 Δf 與筆數成反比，筆數差一個數量級、Δf 就差一個數量級）",
    )
    dp_explanation: Optional[str] = Field(
        default=None,
        description="差分隱私計算方法的白話說明（LLM 產生），可直接顯示給使用者，"
        "讓他理解 M(x)=f(x)+Lap(Δf/ε) 這件事在做什麼",
    )
    dp_input_hint: Optional[str] = Field(
        default=None,
        description="要請使用者把什麼值填進 `{cell}`，例如「請填入你自己算好的全體平均年薪」。"
        "後端不計算這個值",
    )
    dp_formula_error: Optional[str] = Field(
        default=None,
        description="差分隱私公式未完全通過檢查時的原因。"
        "**只要 LLM 判定這個欄位適用差分隱私，dp_param 與相關說明就一定會回傳**，"
        "不會因為公式有問題就整個消失。此欄不是 null 時分兩種情況：\n"
        "一、`dp_excel_formulas` 仍有公式 —— 公式通過安全檢查但沒通過語意驗算，"
        "可以顯示但請提醒使用者核對結果\n"
        "二、`dp_excel_formulas` 是空陣列 —— 公式沒通過安全檢查（例如夾帶會外送資料的函數），"
        "不能交給使用者執行，請顯示「差分隱私公式產生失敗」",
    )
    warnings: List[str] = Field(
        default_factory=list, description="此欄位的提醒事項，建議顯示給使用者"
    )


class ClarificationNeeded(BaseModel):
    field_id: str = Field(
        ..., description="需要澄清的欄位 id；LLM 未正確回傳 id 時為空字串"
    )
    field_name: str = Field("", description="欄位名稱")
    clarification_question: str = Field(..., description="要顯示給使用者的追問")


class AnalyzeResponse(BaseModel):
    status: Literal["ok", "need_clarification"] = Field(
        ...,
        description="`ok`：看 fields｜`need_clarification`：看 clarifications_needed，fields 為空陣列",
    )
    fields: List[ProcessedField] = Field(
        default_factory=list, description="順序與請求的 fields 相同"
    )
    clarifications_needed: List[ClarificationNeeded] = Field(
        default_factory=list,
        description="需要使用者補充的欄位。目前一次只會回報一個（遇到第一個就停止後續任務）",
    )


# ===========================================================================
# 錯誤回應
# ===========================================================================
ErrorCode = Literal[
    "llm_refused",
    "llm_invalid_output",
    "quota_exceeded",
    "llm_timeout",
    "llm_unavailable",
]


class ErrorDetail(BaseModel):
    """400 / 502 的回應格式。

    前端只需依狀態碼決定要顯示什麼；`error_code` 供需要細分時使用
    （例如想對配額用盡顯示不同文案），不細分時可以忽略。
    """

    detail: str = Field(..., description="可直接顯示給使用者的錯誤說明")
    error_code: ErrorCode = Field(
        ...,
        description=(
            "機器可讀的原因代碼。\n"
            "`llm_refused`：LLM 判定輸入與本功能無關（400）\n"
            "`llm_invalid_output`：LLM 回傳內容不符預期（502）\n"
            "`quota_exceeded`：Google 端回報配額已用盡（502）\n"
            "`llm_timeout`：LLM 重試後仍逾時（502）\n"
            "`llm_unavailable`：Gemini 其他錯誤，例如金鑰無效（502）"
        ),
    )


class ValidationErrorItem(BaseModel):
    loc: List[Union[str, int]] = Field(
        ...,
        description='出錯位置，例如 ["body", "fields", 0, "name"] 代表第 1 個欄位的 name',
    )
    msg: str = Field(..., description="錯誤訊息（由 Pydantic 產生）")
    type: str = Field(
        ..., description="錯誤類型代碼，例如 missing、literal_error、value_error"
    )


class ValidationErrorResponse(BaseModel):
    """422：請求格式驗證失敗。由 FastAPI 在進入函式前產生，不會呼叫 LLM。"""

    detail: List[ValidationErrorItem]
