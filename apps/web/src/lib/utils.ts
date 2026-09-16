import type { ExcelFormulaTemplate } from "@/api/gen";

export const mapParamToFormula = (
  formulas: ExcelFormulaTemplate[],
  variant: string,
  param: number,
  cell: string,
) => {
  let returnFormula = "";

  formulas.find((formula) => {
    if (variant === formula.variant) {
      returnFormula = formula.formula_template
        .replaceAll(formula.param_placeholder ?? "{param}", param.toString())
        .replaceAll(formula.cell_placeholder ?? "{cell}", cell);
    }
  });

  return returnFormula;
};
