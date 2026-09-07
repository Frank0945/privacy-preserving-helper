"""
你的安全要求寫「log 不留欄位內容」，這裡用「白名單」而不是「黑名單」的方式做：
只允許明確列出的幾個 key（時間、session_id、技術種類、狀態）被記錄，
其他一律不寫進 log。

為什麼不用「字串截斷」或「關鍵字過濾」這種黑名單做法：
黑名單永遠會漏掉你沒想到的情況（例如某個欄位剛好叫「備註」，
裡面卻被使用者填了半個真實地址），白名單則是「預設不信任、明確允許才放行」，
安全性高很多，也比較符合競賽的稽核要求。
"""

import logging
import sys

# 允許出現在 log 裡的欄位（僅限中繼資訊，不含任何實際資料內容）
ALLOWED_LOG_KEYS = {
    "timestamp",
    "session_id",
    "technique",
    "status",
    "field_count",
    "endpoint",
}


def safe_log_context(**kwargs) -> dict:
    """
    呼叫端要記錄任何東西前，都先過這個函式篩選一次。
    用法：logger.info("analyze called", extra=safe_log_context(session_id=sid, field_count=3))
    """
    return {k: v for k, v in kwargs.items() if k in ALLOWED_LOG_KEYS}


class _DefaultSessionIdFilter(logging.Filter):
    """
    如果呼叫 logger.info(...) 時沒有透過 extra 帶 session_id，
    幫它補一個預設值，避免 formatter 因為缺少欄位而丟例外、讓整個服務炸掉。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "session_id"):
            record.session_id = "-"
        return True


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s | session_id=%(session_id)s"
    )
    handler.setFormatter(formatter)
    handler.addFilter(_DefaultSessionIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    # Google GenAI SDK 底層的 request/response log 可能會把 prompt 內容整段印出來，
    # 這裡把它調高門檻，避免不小心洩漏欄位內容到 console 或伺服器 log 檔。
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
