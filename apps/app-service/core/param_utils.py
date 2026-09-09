"""
參數轉型的小工具，routers/analyze.py 與 routers/recalculate.py 共用。

為什麼獨立成一個檔案：
這兩支路由都需要把「字串型態的參數」轉成演算法要的 int / float —
/analyze 轉的是 LLM 給的 default_param_value，/recalculate 轉的是前端
滑桿送來的值。原本這段邏輯散在兩支路由裡各寫一次，
如果讓 recalculate.py 直接 import analyze.py 的私有函式（_safe_int），
等於在兩支路由之間建立了不必要的相依，日後只要 analyze.py 改名就會壞。
放在 core/ 是「兩邊都依賴同一個底層工具」，方向乾淨得多。

轉型失敗一律回退到呼叫端指定的預設值並寫 log，而不是丟例外：
使用者拖個滑桿不該收到 500，畫面上看到「參數沒生效」比整頁報錯好處理。
"""

import logging

logger = logging.getLogger(__name__)


def coerce_int(value, fallback: int) -> int:
    """
    把可能是 "4"、"4.0"、4、None 的值轉成 int。
    轉不動就回退，例如 LLM 不小心回了 "k=5" 這種帶文字的值。
    """
    if value is None:
        return fallback
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        logger.warning(f"無法把參數 {value!r} 轉成整數，改用預設值 {fallback}")
        return fallback


def coerce_float(value, fallback: float) -> float:
    """同 coerce_int，但轉成 float（給 epsilon 用）。"""
    if value is None:
        return fallback
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        logger.warning(f"無法把參數 {value!r} 轉成浮點數，改用預設值 {fallback}")
        return fallback
