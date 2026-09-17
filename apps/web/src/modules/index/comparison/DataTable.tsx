import type { ProcessedField } from "@/api/gen";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";

import type { ChangedFieldMap } from "./comparison";
import useProcessedSamples, { getSampleSize } from "./useProcessedSamples";

interface DataTableProps {
  fields: ProcessedField[];
  changedFieldMap: ChangedFieldMap;
  isApplyFormula?: boolean;
}

const DataTable = ({
  fields,
  changedFieldMap,
  isApplyFormula = false,
}: DataTableProps) => {
  const sampleSize = getSampleSize(fields);

  const processedSamples = useProcessedSamples(
    fields,
    changedFieldMap,
    isApplyFormula,
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
              {fields.map((field) => {
                const value = isApplyFormula
                  ? processedSamples[field.field_id]?.[rowIndex]
                  : field.sample_before[rowIndex];

                return (
                  <TableCell key={field.field_id} className="px-6">
                    {value ?? "—"}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

export default DataTable;
