import { useMemo } from "react";
import type { ProcessedField } from "@/api/gen";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { mapParamToFormula } from "@/lib/utils";
import {
  DetailedCellError,
  HyperFormula,
  NotAFormulaError,
} from "hyperformula";

import type { ChangedFieldMap } from "./comparison";

interface DataTableProps {
  fields: ProcessedField[];
  changedFieldMap: ChangedFieldMap;
  isApplyFormula?: boolean;
}

const calculateProcessedSamples = (
  fields: ProcessedField[],
  changedFieldMap: ChangedFieldMap,
) => {
  if (fields.length === 0) return [];

  const sampleSize = fields[0]?.sample_before.length ?? 0;

  const sheetData = [
    fields.map((field) => field.field_name),
    ...Array.from({ length: sampleSize }, (_, rowIndex) =>
      fields.map((field) => field.sample_before[rowIndex] ?? null),
    ),
  ];

  const hf = HyperFormula.buildFromArray(sheetData, {
    licenseKey: "gpl-v3",
  });

  try {
    return Array.from({ length: sampleSize }, (_, rowIndex) =>
      fields.map((field, columnIndex) => {
        if (!field.default_variant || field.param.default == null) {
          return null;
        }

        const cellAddress = hf.simpleCellAddressToString(
          {
            sheet: 0,
            row: rowIndex + 1,
            col: columnIndex,
          },
          {
            includeSheetName: false,
          },
        );

        if (!cellAddress) {
          return null;
        }

        const changed = changedFieldMap[field.field_id];

        const formula = mapParamToFormula(
          field.excel_formulas,
          changed?.variant ?? field.default_variant,
          changed?.param ?? field.param.default,
          cellAddress,
        );

        if (!formula) {
          return null;
        }

        const result = hf.calculateFormula(formula, 0);

        if (result instanceof DetailedCellError) {
          return result.value;
        }

        if (Array.isArray(result)) {
          return null;
        }

        return result;
      }),
    );
  } catch (error) {
    if (error instanceof NotAFormulaError) {
      alert("公式錯誤");
    }
  } finally {
    hf.destroy();
  }
};

const DataTable = ({
  fields,
  isApplyFormula,
  changedFieldMap,
}: DataTableProps) => {
  const sampleSize = fields[0]?.sample_before.length ?? 0;

  const processedSamples = useMemo(
    () =>
      isApplyFormula
        ? calculateProcessedSamples(fields, changedFieldMap)
        : null,
    [fields, isApplyFormula, changedFieldMap],
  );

  return (
    <div className="w-full overflow-hidden">
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            {fields.map((field) => (
              <TableHead key={field.field_id} className="px-6">
                {field.field_name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>

        <TableBody>
          {Array.from({ length: sampleSize }, (_, rowIndex) => (
            <TableRow key={rowIndex}>
              {fields.map((field, columnIndex) => (
                <TableCell key={field.field_id} className="px-6">
                  {isApplyFormula
                    ? (processedSamples?.[rowIndex]?.[columnIndex] ?? "—")
                    : field.sample_before[rowIndex]}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

export default DataTable;
