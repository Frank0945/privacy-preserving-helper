"""
這個檔案的每個 class 都是「照著你的 system instruction 裡規定的 JSON 格式」逐字翻譯過來的。

這裡有兩組 model，分工不同：

1. 嚴格版（TaskA_Ok / TaskA_NeedClarification / TaskA_Refused，以及 TaskB 的對應版本）
   用在「services/ 拿到 Gemini 回應之後，最終要回傳給 router 使用」的地方。
   這三個 class 各自的必填欄位不同（例如 TaskA_Ok 一定要有 records，
   TaskA_Refused 一定要有 refused_message），Pydantic 會自動保證
   「status 是什麼，對應欄位就一定要存在」，不需要額外寫檢查邏輯。

2. 合併版（TaskA_Merged / TaskB_Merged）
   專門用在「呼叫 Gemini API 時，當作 response_schema 傳進去」的地方。
   Gemini 的結構化輸出（response_schema）一次只能吃「單一固定形狀」的 schema，
   沒辦法直接描述「status=ok 用這個形狀、status=refused 用那個形狀」這種
   依條件變化的聯合型別，所以只能把所有可能欄位都攤平、設成 Optional，
   讓 Gemini 端知道「這個 JSON 大概長怎樣」。

   但合併版天生有一個弱點：所有欄位都是 Optional，代表
   {"status": "ok", "records": None} 這種矛盾資料在型別上是合法的，
   Pydantic 預設不會擋下來。所以這裡額外加上 model_validator(mode="after")，
   在合併版這一層就先做一次「status 跟欄位是否一致」的檢查，
   確保後續要轉換成嚴格版 model 時，資料一定是自洽的。

呼叫流程建議是：
    Gemini 回應 → 先用 Merged 版驗證（含一致性檢查）
                → 依 status 轉換成對應的嚴格版 model
                → 回傳嚴格版給呼叫端使用
"""

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

# ============ Task A：假資料生成 ============


class RecordField(BaseModel):
    """
    對應 system instruction 裡強調的格式：
    「須寫成 {"field": "姓名", "value": "林冠宇"}，不可直接以欄位名稱當 key」

    重要修正：value 欄位曾經固定寫死 str 型別，但 Gemini 遇到 number 型態的欄位
    （例如「年齡」）時，很自然地回傳 JSON 數字（28）而不是字串（"28"），
    導致 Pydantic 嚴格比對型別失敗。這裡用 field_validator 在驗證之前
    先把任何型別都強制轉成字串，避免這個問題。
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
    """
    專供 Gemini response_schema 使用的合併版，見檔案開頭說明。
    """

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

    @field_validator("suggested_param", mode="before")
    @classmethod
    def coerce_suggested_param_to_string(cls, v):
        if v is None:
            return ""
        return str(v)


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
    """
    專供 Gemini response_schema 使用的合併版，見檔案開頭說明。
    """

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
