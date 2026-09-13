"""
封裝與 Google AI Studio（Gemini）之間的呼叫。

包含：
1. RPM（每分鐘請求數）滑動視窗限流器 —— 對應 Gemini 模型頁面上
   「RPM / TPM / RPD 三個限制同時存在，任一先達上限即被擋」的說明。
   TPM / RPD 沒有實作，建議另外用 Google AI Studio 的用量頁面監控。
2. 對暫時性錯誤（逾時、連線失敗）的重試（tenacity）。
   注意：重試會一併計入 RPM，最壞情況一次分析會消耗
   gemini_max_retries × 3 次請求額度。
3. 統一的「呼叫並解析 JSON」流程。

因為 config 裡設了 response_mime_type="application/json"，Gemini 會走 JSON 模式，
不會夾帶 ```json 圍欄或前後文字，所以這裡不再做圍欄剝除。
但 json.loads 的錯誤處理必須保留，因為還有兩種與「LLM 不聽話」無關的失敗：
輸出撞到 token 上限被截斷（JSON 少半邊括號）、以及安全過濾導致 response.text 為 None。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any

from core.config import get_settings
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class LLMRefusedError(Exception):
    """LLM 依其 system prompt 拒絕了這次請求。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LLMOutputError(Exception):
    """LLM 回傳內容不符合預期（非合法 JSON，或欄位對應不上）。"""


class LLMUpstreamError(Exception):
    """Gemini 端回報錯誤（金鑰無效、配額用盡、服務暫時不可用等）。

    status_code 為 Google 回的 HTTP 狀態碼（逾時時填 504 代表「本地判定逾時」）。
    router 一律回 502，只用它決定 error_code 是 quota_exceeded / llm_timeout / llm_unavailable。
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _SlidingWindowRateLimiter:
    """每分鐘請求數（RPM）限流器。超過上限時等待，不回錯誤。"""

    def __init__(self, max_requests_per_minute: int):
        self._max_requests = max_requests_per_minute
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            window_start = now - 60
            while self._timestamps and self._timestamps[0] < window_start:
                self._timestamps.popleft()

            if len(self._timestamps) >= self._max_requests:
                sleep_for = 60 - (now - self._timestamps[0]) + 0.05
                await asyncio.sleep(max(sleep_for, 0))

            self._timestamps.append(time.monotonic())


_settings = get_settings()
_rate_limiter = _SlidingWindowRateLimiter(_settings.gemini_rpm_limit)
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=_settings.gemini_api_key)
    return _client


class _TransientError(Exception):
    """只有這一類錯誤才重試（逾時、連線失敗、Google 5xx / 429）。"""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


@retry(
    reraise=True,
    retry=retry_if_exception_type(_TransientError),
    stop=stop_after_attempt(_settings.gemini_max_retries),
    wait=wait_exponential(multiplier=1, min=1, max=8),
)
async def _call_gemini_once(system_prompt: str, user_content: str) -> str:
    client = _get_client()
    await _rate_limiter.acquire()

    try:
        return await _send(client, system_prompt, user_content)
    except asyncio.TimeoutError as exc:
        raise _TransientError(exc) from exc
    except genai_errors.APIError as exc:
        # 4xx（金鑰無效、請求格式錯誤）重試也不會好，直接往外丟；
        # 429 與 5xx 屬於暫時性，交給 tenacity 重試。
        if exc.code == 429 or (exc.code or 0) >= 500:
            raise _TransientError(exc) from exc
        raise LLMUpstreamError(
            f"Gemini 回報錯誤（{exc.code}）：{exc}", exc.code
        ) from exc


async def _send(client: genai.Client, system_prompt: str, user_content: str) -> str:
    response = await asyncio.wait_for(
        client.aio.models.generate_content(
            model=_settings.gemini_model,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                max_output_tokens=_settings.gemini_max_output_tokens,
                # 沒有使用工具，關閉自動函式呼叫（否則 SDK 會印出建議改用 Chat 的警告）
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        ),
        timeout=_settings.gemini_timeout_seconds,
    )
    return response.text or ""


async def _call_gemini(system_prompt: str, user_content: str) -> str:
    try:
        return await _call_gemini_once(system_prompt, user_content)
    except _TransientError as exc:
        # 重試次數用完
        original = exc.original
        status = getattr(original, "code", None)
        if isinstance(original, asyncio.TimeoutError):
            raise LLMUpstreamError(
                f"LLM 超過 {_settings.gemini_timeout_seconds} 秒未回應（已重試"
                f" {_settings.gemini_max_retries} 次）",
                504,
            ) from original
        raise LLMUpstreamError(
            f"Gemini 暫時無法使用（已重試 {_settings.gemini_max_retries} 次）：{original}",
            status,
        ) from original


async def generate_json(system_prompt: str, user_content: str) -> dict[str, Any]:
    """呼叫 LLM 並回傳解析後的 dict。若 LLM 回傳 status=refused，會拋出 LLMRefusedError。"""
    raw_text = await _call_gemini(system_prompt, user_content)
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        # 最常見的原因是輸出撞到 max_output_tokens 被截斷，或安全過濾導致回傳空字串
        raise LLMOutputError(
            f"LLM 回傳內容非合法 JSON（長度 {len(raw_text)}）：{raw_text[:500]}"
        ) from exc

    if not isinstance(data, dict):
        raise LLMOutputError(f"LLM 回傳 JSON 最外層不是物件：{raw_text[:200]}")

    if data.get("status") == "refused":
        raise LLMRefusedError(data.get("refused_message", "此功能無法協助這個請求。"))

    return data
