import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";
import { DetailedCellError, HyperFormula } from "hyperformula";

const DpPreviewTable = ({
  formula,
  sample_before,
}: {
  formula: string;
  sample_before: string[];
}) => {
  const totalAvg = Math.round(
    sample_before.reduce((sum, str) => sum + (Number(str) || 0), 0) /
      sample_before.length,
  );

  const calcDpByFormula = (formula: string) => {
    const hf = HyperFormula.buildFromArray([["before"], [totalAvg]], {
      licenseKey: "gpl-v3",
    });

    const result = hf.calculateFormula(formula, 0);

    if (result instanceof DetailedCellError) {
      return result.value;
    }

    if (Array.isArray(result)) {
      return null;
    }

    return typeof result === "number" ? Math.round(result) : result;
  };

  return (
    <Table>
      <TableHeader className="bg-muted">
        <TableRow>
          {["原始平均", "差分隱私後"].map((val) => (
            <TableHead key={val} className="text-muted-foreground px-6">
              {val}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>

      <TableBody>
        <TableRow>
          {[totalAvg, calcDpByFormula(formula)].map((val, idx) => (
            <TableCell key={idx} className="px-6">
              {val}
            </TableCell>
          ))}
        </TableRow>
      </TableBody>
    </Table>
  );
};

export default DpPreviewTable;
