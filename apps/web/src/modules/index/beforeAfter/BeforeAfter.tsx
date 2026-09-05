import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/atoms/item";
import { ChartNoAxesGanttIcon, StarsIcon } from "lucide-react";

import DataTable from "./DataTable";

const BeforeAfter = () => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>隱私保護對照 - 示範資料</CardTitle>
      </CardHeader>

      <CardContent>
        <ItemGroup className="grid grid-cols-2">
          <Item className="min-w-0 gap-2" variant="outline">
            <ItemMedia variant="icon">
              <ChartNoAxesGanttIcon className="text-muted-foreground" />
            </ItemMedia>

            <ItemContent className="min-w-0">
              <ItemTitle className="text-muted-foreground mb-2 whitespace-nowrap">
                Before
              </ItemTitle>

              <ItemDescription className="text-foreground min-w-0 overflow-x-auto">
                <DataTable />
              </ItemDescription>
            </ItemContent>
          </Item>

          <Item className="min-w-0 gap-2" variant="outline">
            <ItemMedia variant="icon">
              <StarsIcon className="text-yellow-500" />
            </ItemMedia>

            <ItemContent className="min-w-0">
              <ItemTitle className="mb-2 whitespace-nowrap">After</ItemTitle>

              <ItemDescription className="text-foreground min-w-0 overflow-x-auto">
                <DataTable />
              </ItemDescription>
            </ItemContent>
          </Item>
        </ItemGroup>
      </CardContent>
    </Card>
  );
};

export default BeforeAfter;
