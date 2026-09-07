"""
這個檔案負責「實際打 Gemini API」這件事，並且把限流邏輯包在裡面，
讓 services/ 裡的商業邏輯完全不用管「現在能不能發請求」，
只要呼叫 call_gemini() 就好，該不該等待、等多久，都由這裡處理。

為什麼要自己寫限流器，而不是抓到 429 錯誤才重試：
Gemini 3.1 Flash Lite 的免費額度是 RPM=15 / TPM=250K / RPD=500，
三個限制「同時存在」，任何一個先到上限就會被擋。
如果都不管，等打到 429 才重試，使用者體驗會是「卡住報錯」；
自己在發送前先檢查配額夠不夠，不夠就先 sleep 等待，
使用者感受到的是「稍微變慢」而不是「失敗」，體驗差很多。
"""

import asyncio
import time
from collections import deque
from typing import Any

from core.config import settings
from google import genai
from google.genai.types import GenerateContentConfig

client = genai.Client(api_key=settings.GEMINI_API_KEY)

MODEL_NAME = "gemini-3.1-flash-lite"


class RateLimiter:
    """
    用三個 deque（雙向佇列）分別記錄：
    - 最近一分鐘內的請求時間
    - 最近一分鐘內的 token 使用量
    - 最近一天內的請求時間

    每次要發請求前呼叫 acquire()：
    1. 先把過期的紀錄從 deque 前端丟掉
    2. 檢查目前累積量是否會超過上限
    3. 如果會超過 RPM 或 TPM，就 sleep 到有空間為止
    4. 如果 RPD 已經滿了，直接丟例外
    """

    def __init__(self, rpm: int, tpm: int, rpd: int):
        self.rpm = rpm
        self.tpm = tpm
        self.rpd = rpd

        self._minute_requests: deque[float] = deque()
        self._minute_tokens: deque[tuple[float, int]] = deque()
        self._day_requests: deque[float] = deque()

        self._lock = asyncio.Lock()

    def _evict_expired(self, now: float) -> None:
        while self._minute_requests and now - self._minute_requests[0] > 60:
            self._minute_requests.popleft()

        while self._minute_tokens and now - self._minute_tokens[0][0] > 60:
            self._minute_tokens.popleft()

        while self._day_requests and now - self._day_requests[0] > 86400:
            self._day_requests.popleft()

    async def acquire(self, estimated_tokens: int = 2000) -> None:
        # FastAPI 可能同時處理多個請求，因此使用 lock
        # 避免多個 coroutine 同時修改 deque。
        async with self._lock:
            now = time.time()
            self._evict_expired(now)

            if len(self._day_requests) >= self.rpd:
                raise RuntimeError(
                    "今日 LLM 請求額度已用盡（RPD 已達上限），請明天再試"
                )

            current_tpm = sum(tokens for _, tokens in self._minute_tokens)

            wait_seconds = 0.0

            if len(self._minute_requests) >= self.rpm:
                wait_seconds = max(
                    wait_seconds,
                    60 - (now - self._minute_requests[0]),
                )

            if current_tpm + estimated_tokens > self.tpm and self._minute_tokens:
                wait_seconds = max(
                    wait_seconds,
                    60 - (now - self._minute_tokens[0][0]),
                )

            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

                now = time.time()
                self._evict_expired(now)

            self._minute_requests.append(now)
            self._minute_tokens.append((now, estimated_tokens))
            self._day_requests.append(now)


# 依照競賽公告的額度建立單一共用的限流器實例
# 15 RPM / 250K TPM / 500 RPD
rate_limiter = RateLimiter(
    rpm=15,
    tpm=250_000,
    rpd=500,
)


async def call_gemini(
    system_instruction: str,
    user_prompt: str,
    estimated_tokens: int = 3000,
    response_schema: type | None = None,
) -> str:
    """
    真正呼叫 Gemini 的地方。

    幾個細節：
    - response_mime_type 設成 application/json，強迫模型只回 JSON，
      減少「模型多講了幾句客套話」導致 json.loads 失敗的機率。
    - response_schema 傳入 Pydantic model class，讓 Gemini 依照指定 schema
      產生 JSON。
    - genai.Client.models.generate_content 是同步呼叫，
      使用 asyncio.to_thread 避免阻塞 FastAPI event loop。
    """
    await rate_limiter.acquire(estimated_tokens)

    config = GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_schema,
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL_NAME,
        contents=user_prompt,
        config=config,
    )

    if response.text is None:
        raise RuntimeError("Gemini API 回應沒有文字內容")

    return response.text
