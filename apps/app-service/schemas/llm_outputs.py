"""
這個檔案的每個 class 都是「照著 system instruction 裡規定的 JSON 格式」逐字翻譯過來的。

這裡有兩組 model，分工不同：

1. 嚴格版（TaskA_Ok / TaskA_NeedClarification / TaskA_Refused，以及 TaskB 的對應版本）
   用在「services/ 拿到 Gemini 回應之後，最終要回傳給 router 使用」的地方。

2. 合併版（TaskA_Merged / TaskB_Merged）
   專門用在「呼叫 Gemini API 時，當作 response_schema 傳進去」的地方。
   Gemini 的結構化輸出一次只能吃「單一固定形狀」的 schema，沒辦法描述
   「status=ok 用這個形狀、status=refused 用那個形狀」這種聯合型別，
   所以把所有可能欄位攤平、設成 Optional，再用 model_validator 補一致性檢查。

本次修改（與你上傳的版本相比），三處：

(1) TechniqueField 新增 mask_position 欄位。
    原本的設計有一個斷裂：system instruction 要求 LLM「判斷建議遮蔽位置（左/中/右）」，
    而且明講遮蔽位置固定、不做成滑桿，但這個判斷結果沒有任何欄位可以裝，
    只隱含在 excel_formula_template 的公式寫法裡。結果就是：
    Excel 公式可能是「遮左邊」，後端算出來的「處理後」示範資料卻永遠是「遮右邊」
    （因為 apply_mask 的預設值是 right），畫面跟公式對不起來。
    現在明確要求 LLM 輸出 mask_position，後端示範資料與 Excel 公式才會一致。

(2) 用 Field(description=...) 取代原本純文字的欄位說明。
    原本寫在欄位下方那種「三引號字串」對 Python 而言只是沒有作用的字面值，
    不會進到 JSON Schema，等於 Gemini 完全看不到這些說明。改用 description
    之後，這些說明會一起被送進 response_schema，也會出現在 FastAPI 的 /docs。

(3) 補強 categorical 的一致性檢查：
    原本只檢查 param_options 有沒有值，但沒有檢查 default_param_value
    是否真的存在於 param_options 裡。LLM 若給了 default="day" 而選項只有
    year/month，前端會找不到對應選項而顯示空白。現在會自動修正為第一個選項。
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ============ Task A：假資料生成 ============


class RecordField(BaseModel):
    """
    對應 system instruction 裡強調的格式：
    「須寫成 {"field": "姓名", "value": "林冠宇"}，不可直接以欄位名稱當 key」

    value 用 field_validator 強制轉字串：Gemini 遇到 number 型態的欄位
    （例如「年齡」）時，很自然地回傳 JSON 數字（28）而不是字串（"28"），
    不轉的話 Pydantic 會直接驗證失敗。
    """

    field: str
    value: str

    @field_validator("value", mode="before")
    @classmethod
    def coerce_value_to_string(cls, v):
        if v is None:
            return ""
        return str(v)


class Record(BaseModel):
    row_index: int
    fields: list[RecordField]


class TaskA_Ok(BaseModel):
    status: Literal["ok"]
    records: list[Record]


class TaskA_NeedClarification(BaseModel):
    status: Literal["need_clarification"]
    clarification_field: str
    clarification_question: str


class TaskA_Refused(BaseModel):
    status: Literal["refused"]
    refused_message: str


class TaskA_Merged(BaseModel):
    """專供 Gemini response_schema 使用的合併版，見檔案開頭說明。"""

    status: Literal["ok", "need_clarification", "refused"]
    records: list[Record] | None = None
    clarification_field: str | None = None
    clarification_question: str | None = None
    refused_message: str | None = None

    @model_validator(mode="after")
    def check_consistency(self):
        if self.status == "ok" and self.records is None:
            raise ValueError("status=ok 時 records 不能為空")
        if self.status == "need_clarification" and (
            self.clarification_field is None or self.clarification_question is None
        ):
            raise ValueError(
                "status=need_clarification 時必須提供 clarification_field 與 clarification_question"
            )
        if self.status == "refused" and self.refused_message is None:
            raise ValueError("status=refused 時必須提供 refused_message")
        return self


# ============ Task B：技術判斷 ============


class ParamOption(BaseModel):
    """
    給「類別型」參數用的單一選項，例如日期泛化只有「年份」跟「年-月」兩種選擇，
    不是連續數值，不適合用滑桿，適合讓前端顯示成下拉選單或按鈕組。
    """

    value: str = Field(description='機器可讀的值，日期泛化固定只能是 "year" 或 "month"')
    label: str = Field(description="給使用者看的顯示文字，例如「僅年份」")
    excel_formula: str = Field(
        description="這個選項對應的完整 Excel 公式，不含任何佔位符，可直接複製使用"
    )


class TechniqueField(BaseModel):
    field: str
    is_key_field: bool
    technique: Literal[
        "mask", "generalize", "k_anonymity_group", "suppress", "differential_privacy"
    ]
    purpose_used: str
    purpose_interpreted_as: str | None = None
    suggested_param: str
    reason: str

    # ---- 以下是滑桿與 Excel 公式相關欄位，由 Task B 的 LLM 直接產生 ----

    param_type: Literal["numeric_slider", "categorical", "none"] = Field(
        description=(
            "numeric_slider：連續數值型參數（遮罩位數、泛化區間、k值、epsilon），前端畫滑桿；"
            "categorical：少數固定選項（例如日期泛化的年 / 年-月），前端畫下拉選單；"
            "none：沒有可調參數（suppress 一定是這個），前端不畫任何控制項"
        )
    )

    default_param_value: str | None = Field(
        default=None,
        description=(
            "滑桿或選項的預設值，一律以字串儲存。這個值不只給前端當初始位置，"
            "後端也會直接用它計算第一次的『處理後』示範資料，所以必須是合理可用的值。"
            'param_type="none" 時固定為 null'
        ),
    )

    param_min: float | None = Field(default=None, description="滑桿最小值")
    param_max: float | None = Field(default=None, description="滑桿最大值")
    param_step: float | None = Field(default=None, description="滑桿刻度間隔")

    mask_position: Literal["left", "middle", "right"] | None = Field(
        default=None,
        description=(
            "只有 technique=mask 時需要填：判斷出的遮蔽位置（左/中/右）。"
            "這個值是固定的、不做成滑桿，但必須與 excel_formula_template 的公式寫法一致，"
            "後端會用它產生畫面上的『處理後』示範資料。其他技術一律填 null"
        ),
    )

    excel_formula_template: str | None = Field(
        default=None,
        description=(
            'param_type="numeric_slider"：公式裡用文字 "{value}" 當佔位符代表滑桿目前的數值，'
            "前端拖動滑桿時直接做字串取代即可，不需要重新呼叫後端；"
            'param_type="none"：完整、不含佔位符的固定公式或操作說明'
        ),
    )

    param_options: list[ParamOption] | None = Field(
        default=None,
        description='只有 param_type="categorical" 時才填，列出所有選項各自完整的公式',
    )

    @field_validator("suggested_param", mode="before")
    @classmethod
    def coerce_suggested_param_to_string(cls, v):
        if v is None:
            return ""
        return str(v)

    @field_validator("default_param_value", mode="before")
    @classmethod
    def coerce_default_param_value_to_string(cls, v):
        # LLM 可能回傳數字（4）而不是字串（"4"），跟 suggested_param 一樣的防護
        if v is None:
            return None
        return str(v)

    @model_validator(mode="after")
    def enforce_param_consistency(self):
        """
        三件事：
        1. 防禦性覆寫：只要 technique 是 suppress，在後端這一層強制清空所有
           滑桿相關欄位，確保前端拿到的一定是 none，不會因為 LLM 沒完全照規則走而露餡。
           （對應需求 2：使用抑制技術就回傳 none，告訴前端不需要有滑桿。）
        2. 一致性檢查：numeric_slider / categorical 該有的欄位不能缺漏。
        3. mask_position 的補值：LLM 沒給的話補 "right"，
           而不是讓整筆資料驗證失敗、害使用者看到一次 500。
        """
        if self.technique == "suppress":
            self.param_type = "none"
            self.default_param_value = None
            self.param_min = None
            self.param_max = None
            self.param_step = None
            self.param_options = None
            self.mask_position = None
            return self

        if self.technique == "mask" and self.mask_position is None:
            # 遮右側是最常見、也最不容易破壞欄位辨識度的做法，當作保底值
            self.mask_position = "right"
        if self.technique != "mask":
            self.mask_position = None

        if self.param_type == "numeric_slider":
            missing = [
                name
                for name, val in [
                    ("default_param_value", self.default_param_value),
                    ("param_min", self.param_min),
                    ("param_max", self.param_max),
                    ("param_step", self.param_step),
                    ("excel_formula_template", self.excel_formula_template),
                ]
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"param_type=numeric_slider 時，以下欄位不能為空：{missing}"
                )

            if (
                self.param_min is not None
                and self.param_max is not None
                and self.param_min > self.param_max
            ):
                raise ValueError("param_min 不能大於 param_max")

        if self.param_type == "categorical":
            if not self.param_options:
                raise ValueError("param_type=categorical 時必須提供 param_options")

            allowed = [opt.value for opt in self.param_options]
            if self.default_param_value not in allowed:
                # 不擋下整筆資料，直接修正成第一個選項，避免前端找不到對應選項而空白
                self.default_param_value = allowed[0]
            # categorical 的公式放在各選項裡，模板欄位保持空值，避免前端誤用
            self.excel_formula_template = None

        return self


class TaskB_Ok(BaseModel):
    status: Literal["ok"]
    fields: list[TechniqueField]


class TaskB_NeedClarification(BaseModel):
    status: Literal["need_clarification"]
    clarification_field: str
    clarification_question: str


class TaskB_Refused(BaseModel):
    status: Literal["refused"]
    refused_message: str


class TaskB_Merged(BaseModel):
    """專供 Gemini response_schema 使用的合併版，見檔案開頭說明。"""

    status: Literal["ok", "need_clarification", "refused"]
    fields: list[TechniqueField] | None = None
    clarification_field: str | None = None
    clarification_question: str | None = None
    refused_message: str | None = None

    @model_validator(mode="after")
    def check_consistency(self):
        if self.status == "ok" and self.fields is None:
            raise ValueError("status=ok 時 fields 不能為空")
        if self.status == "need_clarification" and (
            self.clarification_field is None or self.clarification_question is None
        ):
            raise ValueError(
                "status=need_clarification 時必須提供 clarification_field 與 clarification_question"
            )
        if self.status == "refused" and self.refused_message is None:
            raise ValueError("status=refused 時必須提供 refused_message")
        return self
