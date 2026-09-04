import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import { ArrowRightCircle } from "lucide-react";

import DataTable from "./DataTable";

const BeforeAfter = () => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>處理前後對照 - 示範資料</CardTitle>
      </CardHeader>

      <CardContent className="flex-row items-center gap-x-2">
        <div className="w-full">
          <div className="text-muted-foreground mb-2 ml-2 flex items-center gap-1">
            處理前
          </div>
          <DataTable />
        </div>

        <ArrowRightCircle className="text-muted-foreground w-16" />

        <div className="w-full">
          <div className="mb-2 ml-2 flex items-center gap-1">處理後</div>
          <DataTable />
        </div>
      </CardContent>
    </Card>
  );
};

export default BeforeAfter;
