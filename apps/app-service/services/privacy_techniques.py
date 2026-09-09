"""
這個檔案是整個系統裡「唯一負責真正改資料」的地方，而且刻意設計成
跟 LLM 完全無關的確定性（deterministic）函式：同樣的輸入永遠得到同樣的輸出。

為什麼一定要這樣：
1. LLM 判斷「該用哪種技術」是主觀、可能不穩定的，
   但「套用某個技術之後資料長怎樣」必須是精確、可驗證的規則，
   不能讓 LLM 自己生成處理後的資料，否則遮罩位數、泛化區間都有可能算錯。
2. /api/recalculate 需求明確寫「純程式運算，不重新呼叫LLM」，
   代表滑桿調整時要能立刻重跑這裡的函式，如果邏輯藏在 LLM 呼叫裡就做不到。

本次修改（與你上傳的版本相比）：
- apply_differential_privacy：原本用 random.gauss 近似，且沒有種子，
  導致「同一個 epsilon 連按兩次滑桿，數字每次都不一樣」，使用者會誤以為
  滑桿壞掉。改成真正的拉普拉斯分布（用反函數法，不需要 numpy），
  並加上 seed 參數讓示範資料可重現：只有 epsilon 變動時數字才會變。
- 各函式補上邊界防呆（length<=0、bucket_size<=0、epsilon<=0、非字串輸入）。
- apply_generalize_date 額外支援 "YYYY/MM/DD" 這種分隔符。

每個函式都對應 Task B system instruction 裡定義的技術代碼：
mask, generalize, k_anonymity_group, suppress, differential_privacy
"""

import hashlib
import math
import random

MASK_CHAR = "*"
SUPPRESS_PLACEHOLDER = "[已移除]"


def apply_mask(value: str, position: str = "right", length: int = 4) -> str:
    """
    遮罩。position 可以是 left / right / middle，對應 system instruction
    裡「判斷建議遮蔽位置（左/中/右）」。

    範例：apply_mask("A123456789", position="right", length=4)
    → "A12345****"（右側 4 碼變星號，其餘保留）
    """
    text = value if isinstance(value, str) else str(value)
    n = len(text)
    if n == 0:
        return text

    # 防呆：遮罩長度不能是負數，也不能超過原字串長度
    length = max(0, min(int(length), n))
    if length == 0:
        return text

    if position == "left":
        return MASK_CHAR * length + text[length:]
    if position == "middle":
        edge = max((n - length) // 2, 0)
        return text[:edge] + MASK_CHAR * length + text[edge + length :]
    # 其餘（含未知值）一律當成 right，避免因為 LLM 給了意外字串就整個壞掉
    return text[: n - length] + MASK_CHAR * length


def apply_generalize_numeric(value: float, bucket_size: int = 5) -> str:
    """
    數值泛化，例如年齡欄位「5歲一階」：34 → "30-34"

    bucket_size 就是 LLM 在 default_param_value 裡給的預設區間粗細，
    使用者可以透過滑桿把 5 歲一階改成 10 歲一階，直接重算，不用重問 LLM。
    """
    bucket_size = int(bucket_size)
    if bucket_size <= 0:
        # 區間為 0 或負數在數學上沒有意義，退回不分組，避免除以零
        return str(value)

    lower = int(math.floor(float(value) / bucket_size)) * bucket_size
    upper = lower + bucket_size - 1
    return f"{lower}-{upper}"


def apply_generalize_date(date_str: str, level: str = "month") -> str:
    """
    日期泛化。level 可以是 "year" 或 "month"。
    預期輸入格式為 YYYY-MM-DD（Task A 的 system instruction 已要求
    日期型態一律用這個格式輸出），另外容忍 YYYY/MM/DD。
    格式不符則原樣回傳，由前端提示。
    """
    text = date_str if isinstance(date_str, str) else str(date_str)
    normalized = text.replace("/", "-").strip()
    parts = normalized.split("-")

    if len(parts) < 2 or not parts[0]:
        return text
    if level == "year":
        return parts[0]
    return f"{parts[0]}-{parts[1]}"


def apply_suppress(value: str) -> str:
    """整欄移除。直接回傳固定的遮蔽標記，不保留任何原始資訊。"""
    return SUPPRESS_PLACEHOLDER


def apply_differential_privacy(
    value: float,
    epsilon: float = 1.0,
    sensitivity: float = 1.0,
    seed: int | None = None,
) -> float:
    """
    差分隱私：對聚合統計數字加入拉普拉斯（Laplace）雜訊。

    epsilon 越小，加入的雜訊越大、隱私保護越強，但資料失真也越大；
    這個 trade-off 就是為什麼系統要讓使用者可以用滑桿調整 epsilon，
    即時看到雜訊大小如何影響「處理後」的數字。

    sensitivity（敏感度）代表單一筆記錄變動對聚合結果的最大影響量，
    這裡先簡化為 1.0，正式使用時應該依實際聚合方式計算真實的敏感度。

    seed：只影響「示範畫面」的可重現性。傳入固定 seed 時，同一筆資料在
    同一個 epsilon 下每次都會得到同樣的雜訊，使用者拖滑桿才看得出
    「數字的變化是 epsilon 造成的」。正式對外發布資料時不應該固定 seed。

    實作說明：用反函數法（inverse transform sampling）從均勻分布產生
    拉普拉斯雜訊，避免為了一行雜訊而多裝 numpy。
    u ~ U(-0.5, 0.5)，noise = -b * sgn(u) * ln(1 - 2|u|)，b = sensitivity/epsilon。
    """
    epsilon = float(epsilon)
    if epsilon <= 0:
        # epsilon <= 0 在定義上不成立（會變成無限大的雜訊），直接擋掉
        raise ValueError("epsilon 必須大於 0")

    scale = float(sensitivity) / epsilon
    rng = random.Random(seed) if seed is not None else random

    u = rng.random() - 0.5
    # 1 - 2|u| 在 u 極接近 ±0.5 時會趨近 0，取 log 會爆掉，這裡夾一個下界
    magnitude = max(1e-12, 1.0 - 2.0 * abs(u))
    noise = -scale * math.copysign(1.0, u) * math.log(magnitude)

    return round(float(value) + noise, 2)


def apply_pseudonymization(value: str, mapping_table: dict[str, str]) -> str:
    """
    假名化：同一個原始值永遠對應同一個代號（在同一個 session 內），
    但代號本身無法反推回原始值。mapping_table 由呼叫端在單次請求範圍內建立，
    不落地儲存，請求結束後就消失，符合「不儲存使用者真實個資」的要求。
    """
    if value not in mapping_table:
        mapping_table[value] = f"USER_{len(mapping_table) + 1:04d}"
    return mapping_table[value]


def apply_hash(value: str, salt: str = "") -> str:
    """
    單向雜湊（雖然 Task B 的技術清單沒有明列這個代碼，但保留作為
    mask/pseudonymization 之外的第三種選擇，方便未來擴充）。
    """
    return hashlib.sha256((value + salt).encode()).hexdigest()[:16]


# 技術代碼 → 對應函式的對照表，router 會用這個表快速找到該呼叫哪個函式
TECHNIQUE_HANDLERS = {
    "mask": apply_mask,
    "generalize": apply_generalize_numeric,
    "suppress": apply_suppress,
    "differential_privacy": apply_differential_privacy,
    # k_anonymity_group 不在這裡，因為它需要「一整批記錄」而不是單一值，
    # 邏輯獨立寫在 services/k_anonymity.py
}
