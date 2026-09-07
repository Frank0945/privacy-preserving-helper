"""
k-匿名分組跟其他四種技術本質上不同：mask/generalize/suppress 都是
「拿一個值，回傳處理後的值」，可以逐筆獨立處理；
但 k-匿名要看「整批記錄裡，某個準識別欄位組合總共出現幾次」，
必須先掌握全部資料才能判斷，所以獨立寫成一個檔案、一個函式簽名也不一樣
（吃一整個 list of dict，而不是單一 value）。

這也對應 system instruction 裡寫的：
「若依建議的分組層級可能導致某些組合筆數低於k值，
建議...將稀疏組合歸併至『其他』類別，以確保k值保證的完整性」
"""

from collections import defaultdict


def apply_k_anonymity_group(
    records: list[dict[str, str]],
    quasi_identifiers: list[str],
    k: int,
) -> list[dict[str, str]]:
    """
    records：每筆是一個 dict，key 是欄位名稱、value 是該欄位的值
             （這裡的 records 應該是同一批合成假資料，依 row_index 組好的完整記錄，
             不是單一欄位的值列表）
    quasi_identifiers：被判斷為 k_anonymity_group 技術的欄位名稱清單
                        （例如 ["年齡", "地區", "性別"]）
    k：LLM 建議的最小分組筆數

    回傳：每筆記錄的 quasi_identifiers 欄位，如果所屬分組筆數 < k，
          就把該筆記錄的這些欄位值全部改成 "其他"，確保剩下的每個分組
          筆數都 >= k（達到 k-匿名保證）。
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)

    for record in records:
        # 用「這幾個準識別欄位的值組合」當作分組的 key
        key = tuple(record.get(qi, "") for qi in quasi_identifiers)
        groups[key].append(record)

    result: list[dict] = []
    for group_records in groups.values():
        if len(group_records) >= k:
            # 這組筆數夠多，符合 k-匿名，原樣保留
            result.extend(group_records)
        else:
            # 筆數不夠，把這幾個準識別欄位歸併成「其他」，
            # 讓這些筆數併入其他同樣被歸併的記錄裡，避免單獨曝光
            for record in group_records:
                merged = record.copy()
                for qi in quasi_identifiers:
                    merged[qi] = "其他"
                result.append(merged)

    return result


def check_k_anonymity_feasibility(
    records: list[dict[str, str]],
    quasi_identifiers: list[str],
    k: int,
) -> dict:
    """
    輔助函式：在套用分組之前，先檢查資料的實際分組狀況，
    回傳有多少組合達標、多少組合不足，方便前端顯示「有 3 組資料因為筆數不足
    被歸併為其他」這類提示，讓使用者了解為什麼看到的資料變粗了。
    """
    groups: dict[tuple, int] = defaultdict(int)
    for record in records:
        key = tuple(record.get(qi, "") for qi in quasi_identifiers)
        groups[key] += 1

    sufficient = sum(1 for count in groups.values() if count >= k)
    insufficient = sum(1 for count in groups.values() if count < k)

    return {
        "total_groups": len(groups),
        "groups_meeting_k": sufficient,
        "groups_merged_to_other": insufficient,
    }
