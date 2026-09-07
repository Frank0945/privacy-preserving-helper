"""
把每種技術轉成使用者可以直接複製到 Excel 儲存格的公式字串。

這裡老實承認兩個技術的限制，用 ⚠ 開頭的字串明確告訴使用者
「這不是完美對應後端演算法的公式」，而不是硬掰一個看起來能動、
實際上邏輯不同的公式去騙使用者：

- k_anonymity_group 需要跨列統計分組筆數，Excel 單一儲存格公式做不到，
  只能建議改用樞紐分析表
- differential_privacy 的雜訊應該是拉普拉斯分布，但 Excel 原生的 RAND()
  只能做均勻分布，只能給一個「近似」公式
"""


def generate_excel_formula(
    technique: str, cell_ref: str = "A2", params: dict | None = None
) -> str:
    params = params or {}

    if technique == "mask":
        position = params.get("position", "right")
        length = params.get("length", 4)

        if position == "right":
            return f'=LEFT({cell_ref},LEN({cell_ref})-{length})&REPT("*",{length})'
        elif position == "left":
            return f'=REPT("*",{length})&RIGHT({cell_ref},LEN({cell_ref})-{length})'
        else:  # middle
            return (
                f'=LEFT({cell_ref},(LEN({cell_ref})-{length})/2)&REPT("*",{length})&'
                f"RIGHT({cell_ref},(LEN({cell_ref})-{length})/2)  "
                f"⚠ 中間遮罩公式假設頭尾對稱，實際位置請依欄位長度手動微調"
            )

    elif technique == "generalize":
        if "level" in params:
            # 有 level 參數代表這是日期欄位的泛化（見 routers/analyze.py
            # 的 _default_params_for_technique：只有 date 型態才會給 level）
            level = params.get("level", "month")
            if level == "year":
                return f"=YEAR({cell_ref})  ⚠ 只取年份，例如 2000-02-03 → 2000"
            else:
                return (
                    f'=TEXT({cell_ref},"YYYY-MM")  '
                    f'⚠ 取年-月，例如 2000-02-03 → "2000-02"（結果為文字格式，非日期格式）'
                )
        else:
            bucket = params.get("bucket_size", 5)
            return f'=FLOOR({cell_ref},{bucket})&"-"&(FLOOR({cell_ref},{bucket})+{bucket - 1})'

    elif technique == "k_anonymity_group":
        k = params.get("k", 5)
        return (
            f"⚠ k-匿名分組需要跨列統計分組筆數，無法用單一儲存格公式完成。"
            f"建議做法：用「樞紐分析表」依準識別欄位分組，"
            f"篩選出筆數少於 {k} 的分組，手動將該組欄位值改為「其他」"
        )

    elif technique == "suppress":
        return '="" 　（建議直接刪除整欄，或用此公式將內容清空）'

    elif technique == "differential_privacy":
        epsilon = params.get("epsilon", 1.0)
        noise_range = round(1 / epsilon, 2)
        return (
            f"={cell_ref}+(RAND()-0.5)*2*{noise_range}  "
            f"⚠ 此為均勻分布近似，非精確的拉普拉斯雜訊，"
            f"正式場合建議用程式（如 Python numpy.random.laplace）產生後再貼回 Excel"
        )

    return "⚠ 尚無對應公式範本"
