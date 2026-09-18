"""
全域設定。所有可調參數集中於此，並可透過 .env 覆寫。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Google AI Studio ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # --- Rate limit（對應 Google AI Studio 的 RPM / TPM / RPD 限制）---
    # 這裡實作的是簡單的 RPM 限流器；TPM / RPD 建議在正式環境另外用
    # Google Cloud 的配額監控或自行累計 token 數來把關。
    gemini_rpm_limit: int = 15
    gemini_timeout_seconds: int = 60
    # 注意：重試會一併計入 RPM
    gemini_max_retries: int = 3
    # Task A 的輸出量 = 欄位數 × 筆數，20 筆 × 15 欄位會產生很長的 JSON。
    # 設得太小會讓 JSON 被截斷（表現為 502），太大則沒有壞處。
    gemini_max_output_tokens: int = 16384

    # --- Excel 公式 ---
    # 公式一律由 LLM（Task C）產生。若公式沒通過 core.formula_guard 的安全檢查，
    # 把原因回饋給 LLM 讓它重寫的次數。設為 0 表示不修正，直接回報 formula_error。
    # 每次修正都會多花一次請求額度。
    # 實測 1 次不夠：巢狀 IF 很深時 LLM 第一次常數錯括號，差分隱私也常忘記保護 LN。
    # 2 次的成功率明顯較好，代價是失敗時多花一次請求額度。
    formula_repair_attempts: int = 2

    # --- CORS ---
    cors_allow_origins: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
