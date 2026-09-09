"""
這裡定義的是「前端畫面實際要拿到什麼」，跟 llm_outputs.py（LLM 原始輸出格式）分開，
是因為 LLM 回傳的資料還沒套用實際的遮罩/泛化演算法算出「處理前後對照」，
中間會經過後端組合加工，所以需要一個獨立的「最終回應格式」。

AnalyzeResponse 是「判別聯合型別」（discriminated union），掛在路由的
response_model 上，FastAPI 會依此在 /docs 自動產生完整、精確的回應格式文件。

本次修改（與你上傳的版本相比），四處：

(1) 欄位說明從「欄位下方的裸字串」改成 Field(description=...)。
    這是一個實際會影響你需求的問題：你要求「後端給前端的值要顯示在 FastAPI
    可以看到，方便前端工程師撰寫使用」。原本寫在欄位下面的
    \"\"\"這是說明\"\"\" 對 Pydantic v2 而言只是沒有作用的字面值，
    不會進到 JSON Schema，所以 /docs 上那些欄位其實是「有型別、沒說明」的。
    改成 description 之後前端工程師才真的看得到每個欄位是什麼意思。
    （另一個做法是設 model_config = ConfigDict(use_attribute_docstrings=True)，
     但那要求 Pydantic >= 2.7，且對 IDE 較不友善，這裡選用明確寫法。）

(2) 新增 param_key：告訴前端「呼叫 /recalculate 時，params 這個 dict 該用哪個 key」。
    原本前端必須自己記住「mask 要送 length、k匿名要送 k、DP 要送 epsilon…」，
    這種隱含約定寫在後端程式碼裡、沒有出現在任何 API 文件上，前端只能用猜的。
    這個值由後端依技術種類推導，不是問 LLM 來的（規則固定，不該交給 LLM 判斷）。

(3) 新增 mask_position：LLM 判斷的遮蔽位置，讓前端可以顯示「遮蔽位置：中間」，
    也讓畫面上的示範資料與 Excel 公式一致。

(4) 新增 notice：後端給前端的補充提醒（目前用於 k-匿名筆數不足的情況）。
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field
from schemas.llm_outputs import ParamOption


class FieldResult(BaseModel):
    field_name: str = Field(description="欄位名稱，與使用者送出的 name 相同")

    original_samples: list[str] = Field(
        description="處理前的合成假資料（由 Task A 生成，非真實個資）"
    )

    processed_samples: list[str] = Field(
        description=(
            "套用隱私保護技術後的資料，供前端畫「處理前 vs 處理後」對照表。"
            "與 original_samples 長度相同、順序一一對應（第 i 筆對第 i 筆）。"
            "首次回傳時採用的參數就是 default_param_value"
        )
    )

    technique: Literal[
        "mask", "generalize", "k_anonymity_group", "suppress", "differential_privacy"
    ] = Field(description="LLM 判斷採用的隱私保護技術代碼")

    suggested_param: str = Field(
        description='LLM 建議的參數，給使用者看的原始文字說明（例如 "k=5"）'
    )

    reason: str = Field(description="LLM 給的判斷理由，口語化說明")

    param_type: Literal["numeric_slider", "categorical", "none"] = Field(
        description=(
            "決定前端要畫什麼控制項："
            "numeric_slider → 畫滑桿；categorical → 畫下拉選單或按鈕組；"
            "none → 不畫任何控制項。suppress 一定是 none"
        )
    )

    param_key: str | None = Field(
        description=(
            "呼叫 POST /recalculate 時，params 物件要使用的 key 名稱。"
            'mask→"length"、數值泛化→"bucket_size"、日期泛化→"level"、'
            'k匿名→"k"、差分隱私→"epsilon"。param_type="none" 時為 null。'
            '例如：{"session_id": "...", "field_name": "年齡", "params": {"bucket_size": 10}}'
        )
    )

    default_param_value: str | None = Field(
        description=(
            "滑桿或選項的預設值（字串型態，數值請前端自行轉型）。"
            "後端第一次計算 processed_samples 時就是用這個值。"
            'param_type="none" 時為 null'
        )
    )

    param_min: float | None = Field(
        description='滑桿最小值，非 "numeric_slider" 時為 null'
    )
    param_max: float | None = Field(
        description='滑桿最大值，非 "numeric_slider" 時為 null'
    )
    param_step: float | None = Field(
        description='滑桿刻度，非 "numeric_slider" 時為 null'
    )

    param_group: list[str] | None = Field(
        default=None,
        description=(
            "共用同一個參數的欄位名稱清單，只有 technique=k_anonymity_group 時有值。"
            "k-匿名保護的是「這幾個欄位的組合」不可辨識，所以整組欄位必然共用同一個 k，"
            "後端也是整組一起計算的。前端建議把這組欄位的滑桿合併成一個，"
            "或在調整其中一個欄位的 k 之後，一併重新請求同組其他欄位的 processed_samples，"
            "否則畫面上會出現「同一組欄位卻套用不同 k」的矛盾顯示"
        ),
    )

    mask_position: Literal["left", "middle", "right"] | None = Field(
        description=(
            "遮蔽位置，只有 technique=mask 時有值。"
            "這是固定值、不是可調參數，前端可直接顯示成文字說明（左／中／右）"
        )
    )

    excel_formula_template: str | None = Field(
        description=(
            'param_type="numeric_slider"：公式字串裡的 "{value}" 是佔位符，'
            '前端拖動滑桿時用 template.replaceAll("{value}", 新數字) 換算出新公式，'
            "不需要呼叫 /recalculate。"
            'param_type="none"：完整、不含佔位符的固定公式或操作說明。'
            'param_type="categorical" 時為 null，公式請改看 param_options'
        )
    )

    param_options: list[ParamOption] | None = Field(
        description='只有 param_type="categorical" 時才有值，每個選項各自附完整公式'
    )

    notice: str | None = Field(
        default=None,
        description=(
            "後端給使用者的補充提醒，沒有提醒時為 null。"
            "目前用於 k-匿名：當示範資料筆數太少、導致大量記錄被歸併為「其他」時，"
            "前端可以把這段文字顯示在該欄位卡片下方，避免使用者誤以為系統壞掉"
        ),
    )


class AnalyzeOkResponse(BaseModel):
    status: Literal["ok"]
    session_id: str = Field(
        description="本次分析的工作階段代號，呼叫 /recalculate 時要帶回來"
    )
    results: list[FieldResult]


class AnalyzeClarificationResponse(BaseModel):
    status: Literal["need_clarification"]
    source: Literal["synthetic_data", "technique_selection"] = Field(
        description="是哪一個階段需要澄清：假資料生成（Task A）或技術判斷（Task B）"
    )
    field: str = Field(description="需要澄清的欄位名稱")
    question: str = Field(description="要顯示給使用者的追問內容")


# 判別聯合型別：FastAPI 會依 "status" 欄位的值，自動判斷這次回應
# 到底該長得像 AnalyzeOkResponse 還是 AnalyzeClarificationResponse，
# 並且在 /docs 裡把兩種可能的形狀都完整列出來。
# 注意：status="refused" 不在這個聯合型別裡，因為拒絕是以 HTTP 400
# （main.py 的 domain_exception_handler，格式為 {"status":"error","message":...}）
# 回傳的，不是 200 的正常回應。
AnalyzeResponse = Annotated[
    Union[AnalyzeOkResponse, AnalyzeClarificationResponse],
    Field(discriminator="status"),
]


class RecalculateResponse(BaseModel):
    field_name: str = Field(
        description=(
            "本次重算對應的欄位名稱。前端若同時拖動多個欄位的滑桿，"
            "可以用這個值確認回應屬於哪一欄，避免非同步回應順序顛倒時套錯資料"
        )
    )

    applied_param: str | None = Field(
        description="後端這次實際採用的參數值（字串）。若前端送的值無法解析，這裡會是回退後的值"
    )

    processed_samples: list[str] = Field(
        description=(
            "重新計算後的處理結果，順序與 /analyze 回傳的 original_samples 一一對應。"
            "這裡不包含 excel_formula，因為 Excel 公式在 /analyze 階段就已由 LLM 產生"
            "模板（excel_formula_template）或選項列表（param_options）交給前端，"
            "前端自行做字串取代或選項查找即可，不需要每次調整滑桿都重新問後端"
        )
    )
