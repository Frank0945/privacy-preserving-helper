import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";

import DataItem from "./DataItem";

const ColumnDetails = () => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>欄位建議</CardTitle>
      </CardHeader>

      <CardContent>
        <DataItem />
        <DataItem />
        <DataItem />
      </CardContent>
    </Card>
  );
};

export default ColumnDetails;
