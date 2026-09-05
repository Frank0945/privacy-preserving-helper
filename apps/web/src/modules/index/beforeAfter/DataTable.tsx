import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/atoms/table";

const DataTable = () => {
  return (
    <div className="w-full overflow-hidden">
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead className="px-6">Invoice</TableHead>
            <TableHead className="px-6">Status</TableHead>
            <TableHead className="px-6">Method</TableHead>
            <TableHead className="px-6">Amount</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell className="px-6">INV001</TableCell>
            <TableCell className="px-6">Paid</TableCell>
            <TableCell className="px-6">Credit Card</TableCell>
            <TableCell className="px-6">$250.00</TableCell>
          </TableRow>
          <TableRow>
            <TableCell className="px-6">INV001</TableCell>
            <TableCell className="px-6">Paid</TableCell>
            <TableCell className="px-6">Credit Card</TableCell>
            <TableCell className="px-6">$250.00</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  );
};

export default DataTable;
