"""
k-匿名分組跟其他四種技術本質上不同：mask/generalize/suppress 都是
「拿一個值，回傳處理後的值」，可以逐筆獨立處理；
但 k-匿名要看「整批記錄裡，某個準識別欄位組合總共出現幾次」，
必須先掌握全部資料才能判斷，所以獨立寫成一個檔案、函式簽名也不一樣
（吃一整個 list of dict，而不是單一 value）。

本次修改（與你上傳的版本相比）── 這是一個會直接顯示在畫面上的 bug：
原本的實作是先用 defaultdict 把記錄分組，再依「分組」的順序 extend 回結果，
所以回傳的列順序跟輸入的列順序不一樣。
routers/analyze.py 拿到結果之後是用「第 i 列對第 i 列」的方式跟
original_samples 對照顯示的，順序一被打亂，前端的
「處理前 vs 處理後」表格就會左右對不上（第 1 列的原始值配到第 3 列的處理後值）。
現在改成「先統計每個組合的筆數，再依原順序逐筆決定要不要歸併」，
只掃兩趟、O(n)，且保證輸出順序與輸入完全一致。
"""

from collections import Counter

MERGED_LABEL = "其他"


def apply_k_anonymity_group(
    records: list[dict[str, str]],
    quasi_identifiers: list[str],
    k: int,
) -> list[dict[str, str]]:
    """
    records：每筆是一個 dict，key 是欄位名稱、value 是該欄位的值
             （應該是同一批合成假資料依 row_index 組好的完整記錄，
             不是單一欄位的值列表）
    quasi_identifiers：被判斷為 k_anonymity_group 技術的「所有」欄位名稱清單
                        （例如 ["年齡", "地區", "性別"]）。
                        注意這裡必須一次帶入整組準識別欄位，
                        因為 k-匿名保證的是「這些欄位的組合」不可被辨識，
                        逐欄分開算是沒有意義的。
    k：最小分組筆數（來自 LLM 的建議值或使用者滑桿）

    回傳：與輸入「同樣長度、同樣順序」的新 list。
          若某筆記錄所屬分組的筆數 < k，就把該筆記錄的準識別欄位值
          全部改成 "其他"，讓它併入其他同樣被歸併的記錄裡。
    """
    if not quasi_identifiers or k <= 1:
        return [record.copy() for record in records]

    def group_key(record: dict[str, str]) -> tuple:
        return tuple(record.get(qi, "") for qi in quasi_identifiers)

    counts = Counter(group_key(record) for record in records)

    result: list[dict[str, str]] = []
    for record in records:
        merged = record.copy()
        if counts[group_key(record)] < k:
            for qi in quasi_identifiers:
                merged[qi] = MERGED_LABEL
        result.append(merged)

    return result


def check_k_anonymity_feasibility(
    records: list[dict[str, str]],
    quasi_identifiers: list[str],
    k: int,
) -> dict:
    """
    輔助函式：在套用分組之前，先檢查資料的實際分組狀況，
    方便前端顯示「有 3 組資料因為筆數不足被歸併為其他」這類提示，
    讓使用者了解為什麼看到的資料變粗了。

    merged_bucket_size 是「被歸併到『其他』的總筆數」。
    這個數字如果大於 0 但小於 k，代表連歸併後的『其他』本身都還不到 k 筆，
    嚴格來說仍未達成 k-匿名保證 —— 在只有 5~20 筆示範資料的情境下這很常見，
    前端應該把它當成「示範資料筆數太少」的提示，而不是演算法出錯。
    """
    if not quasi_identifiers:
        return {
            "total_groups": 0,
            "groups_meeting_k": 0,
            "groups_merged_to_other": 0,
            "merged_bucket_size": 0,
        }

    groups: Counter = Counter(
        tuple(record.get(qi, "") for qi in quasi_identifiers) for record in records
    )

    sufficient = sum(1 for count in groups.values() if count >= k)
    insufficient_groups = [count for count in groups.values() if count < k]

    return {
        "total_groups": len(groups),
        "groups_meeting_k": sufficient,
        "groups_merged_to_other": len(insufficient_groups),
        "merged_bucket_size": sum(insufficient_groups),
    }
