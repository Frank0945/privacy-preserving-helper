"""
呼叫 Task B（技術判斷），並把 Gemini 回應解析成嚴格型別的結果。

流程：
1. 用 TaskB_Merged 當 response_schema 呼叫 Gemini，讓 Google 端就先強制
   輸出符合這個形狀的 JSON，減少格式錯誤的機率。
2. 就算有 response_schema，仍不完全信任 LLM 一定守規矩，先做防禦性的
   JSON 解析（處理可能夾帶的 markdown 符號、外層多包一層陣列等狀況）。
3. 用 TaskB_Merged.model_validate(data) 驗證一次，這一步除了基本型別檢查，
   也會觸發 llm_outputs.py 裡定義的 model_validator，擋下
   「status=ok 但 fields=None」這種邏輯矛盾的資料。
4. 驗證通過後，依 status 轉換成對應的嚴格版 model（TaskB_Ok /
   TaskB_NeedClarification / TaskB_Refused）回傳給呼叫端（routers/analyze.py）。
   之所以要多轉換這一步，而不是直接把 TaskB_Merged 回傳出去，是因為
   呼叫端（analyze.py）原本就是依賴嚴格版 model 的欄位保證在寫邏輯
   （例如直接存取 task_b_result.fields，不需要再檢查是不是 None），
   維持這個介面不變，可以讓這次的修改完全侷限在這個檔案裡，
   不必連動修改 routers/analyze.py。
"""

import json
import logging

from core.llm_client import call_gemini
from core.prompts import TASK_B_SYSTEM_INSTRUCTION, build_task_b_prompt
from schemas.llm_outputs import (
    TaskB_Merged,
    TaskB_NeedClarification,
    TaskB_Ok,
    TaskB_Refused,
)
from schemas.requests import FieldSpec

logger = logging.getLogger(__name__)

TaskBResult = TaskB_Ok | TaskB_NeedClarification | TaskB_Refused


async def select_techniques(fields: list[FieldSpec]) -> TaskBResult:
    prompt = build_task_b_prompt(fields)

    raw_text = await call_gemini(
        TASK_B_SYSTEM_INSTRUCTION,
        prompt,
        response_schema=TaskB_Merged,
    )

    data = _parse_json_defensively(raw_text)

    # 用合併版驗證，這裡會順便觸發 model_validator 做一致性檢查，
    # 如果 Gemini 回傳了 status=ok 但漏掉 fields 這種矛盾資料，
    # 會在這裡直接丟出 ValidationError，而不是等到後面存取欄位時才出錯。
    try:
        merged = TaskB_Merged.model_validate(data)
    except Exception as e:
        logger.error(f"Task B 回傳資料驗證失敗：{e}")
        raise ValueError("LLM 回傳格式異常，請稍後再試") from e

    return _convert_to_strict_result(merged)


def _parse_json_defensively(raw_text: str) -> dict:
    """
    即使設定了 response_schema，仍做防禦性解析，處理三種常見的偏移狀況：
    1. 夾帶 markdown 代碼區塊符號（```json ... ```）
    2. 外層被多包了一層陣列，例如 [{"status": "ok", ...}]
    3. 直接漏了外層的 status 物件，只回傳 fields 陣列本身
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        cleaned = (
            raw_text.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
        )
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(f"Task B 回傳內容無法解析為 JSON，原始內容：{raw_text!r}")
            raise ValueError("LLM 回傳格式異常，請稍後再試") from e

    if isinstance(data, list):
        # 情況一：[{"status": "ok", "fields": [...]}] → 外面多包了一層 list
        if len(data) == 1 and isinstance(data[0], dict) and "status" in data[0]:
            logger.warning(f"Task B 回傳被多包了一層陣列，已自動解開：{data!r}")
            data = data[0]

        # 情況二：[{"field": ..., "technique": ...}, ...]
        # → 直接漏了外層 status 物件
        else:
            logger.warning(
                "Task B 回傳缺少外層 status 物件，直接是陣列，"
                f"已自動包裝成 ok 格式：{data!r}"
            )
            data = {"status": "ok", "fields": data}

    if not isinstance(data, dict):
        logger.error(f"Task B 回傳非預期型別 {type(data)}：{data!r}")
        raise ValueError("LLM 回傳格式異常，請稍後再試")

    return data


def _convert_to_strict_result(merged: TaskB_Merged) -> TaskBResult:
    """把驗證通過的合併版，依 status 轉換成對應的嚴格版 model。"""

    if merged.status == "ok":
        # Pylance 不會因為 model_validator 自動知道 fields 一定不是 None，
        # 因此這裡明確檢查，讓型別與 runtime 邏輯都安全。
        if merged.fields is None:
            raise ValueError("Task B 回傳格式異常：status=ok 但 fields 缺失")

        return TaskB_Ok(
            status="ok",
            fields=merged.fields,
        )

    elif merged.status == "need_clarification":
        # 這兩個欄位在 strict model 中都是 str，
        # 因此在從 Optional 欄位轉換前必須確認不是 None。
        if merged.clarification_field is None or merged.clarification_question is None:
            raise ValueError(
                "Task B 回傳格式異常：status=need_clarification "
                "但 clarification 欄位缺失"
            )

        return TaskB_NeedClarification(
            status="need_clarification",
            clarification_field=merged.clarification_field,
            clarification_question=merged.clarification_question,
        )

    elif merged.status == "refused":
        # strict model 要求 refused_message 為 str，
        # 所以先排除 None。
        if merged.refused_message is None:
            raise ValueError(
                "Task B 回傳格式異常：status=refused " "但 refused_message 缺失"
            )

        return TaskB_Refused(
            status="refused",
            refused_message=merged.refused_message,
        )

    else:
        # 理論上不會走到這裡，因為 Literal 型別已經限制了 status。
        raise ValueError(f"Task B 回傳未知的 status: {merged.status}")
