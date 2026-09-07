"""
呼叫 Task A（假資料生成），邏輯跟 services/technique_selector.py 完全對稱，
只是換成 Task A 的 system instruction 跟對應的 model。維持兩支檔案結構一致，
之後如果要加 Task C，可以直接照抄這個模板。
"""

import json
import logging

from core.llm_client import call_gemini
from core.prompts import TASK_A_SYSTEM_INSTRUCTION, build_task_a_prompt
from schemas.llm_outputs import (
    TaskA_Merged,
    TaskA_NeedClarification,
    TaskA_Ok,
    TaskA_Refused,
)
from schemas.requests import FieldSpec

logger = logging.getLogger(__name__)

TaskAResult = TaskA_Ok | TaskA_NeedClarification | TaskA_Refused


async def generate_synthetic_data(fields: list[FieldSpec]) -> TaskAResult:
    prompt = build_task_a_prompt(fields)

    raw_text = await call_gemini(
        TASK_A_SYSTEM_INSTRUCTION,
        prompt,
        response_schema=TaskA_Merged,
    )

    data = _parse_json_defensively(raw_text)

    try:
        merged = TaskA_Merged.model_validate(data)
    except Exception as e:
        logger.error(f"Task A 回傳資料驗證失敗：{e}")
        raise ValueError("LLM 回傳格式異常，請稍後再試") from e

    return _convert_to_strict_result(merged)


def _parse_json_defensively(raw_text: str) -> dict:
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
            logger.error(f"Task A 回傳內容無法解析為 JSON，原始內容：{raw_text!r}")
            raise ValueError("LLM 回傳格式異常，請稍後再試") from e

    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict) and "status" in data[0]:
            logger.warning(f"Task A 回傳被多包了一層陣列，已自動解開：{data!r}")
            data = data[0]
        else:
            logger.warning(
                f"Task A 回傳缺少外層 status 物件，直接是陣列，已自動包裝成 ok 格式：{data!r}"
            )
            data = {"status": "ok", "records": data}

    if not isinstance(data, dict):
        logger.error(f"Task A 回傳非預期型別 {type(data)}：{data!r}")
        raise ValueError("LLM 回傳格式異常，請稍後再試")

    return data


def _convert_to_strict_result(merged: TaskA_Merged) -> TaskAResult:

    if merged.status == "ok":
        if merged.records is None:
            raise ValueError("Task A 回傳格式異常：status=ok 但 records 缺失")

        return TaskA_Ok(
            status="ok",
            records=merged.records,
        )

    elif merged.status == "need_clarification":
        if merged.clarification_field is None or merged.clarification_question is None:
            raise ValueError(
                "Task A 回傳格式異常：status=need_clarification "
                "但 clarification 欄位缺失"
            )

        return TaskA_NeedClarification(
            status="need_clarification",
            clarification_field=merged.clarification_field,
            clarification_question=merged.clarification_question,
        )

    elif merged.status == "refused":
        if merged.refused_message is None:
            raise ValueError(
                "Task A 回傳格式異常：status=refused 但 refused_message 缺失"
            )

        return TaskA_Refused(
            status="refused",
            refused_message=merged.refused_message,
        )

    else:
        raise ValueError(f"Task A 回傳未知的 status: {merged.status}")
