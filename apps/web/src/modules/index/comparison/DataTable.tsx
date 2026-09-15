import type { ProcessedField } from "@/api/gen";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";

interface DataTableProps {
  fields: ProcessedField[];
  isApplyFormula?: boolean;
}

const DataTable = ({ fields }: DataTableProps) => {
  const sampleSize = fields[0]?.sample_before.length || 0;

  return (
    <div className="w-full overflow-hidden">
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            {fields.map((f) => (
              <TableHead key={f.field_id} className="px-6">
                {f.field_name}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...Array(sampleSize)].map((_, i) => (
            <TableRow key={i}>
              {fields.map((field) => (
                <TableCell key={field.field_id} className="px-6">
                  {field.sample_before[i]}
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
