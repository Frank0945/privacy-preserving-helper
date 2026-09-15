import type { ProcessedField } from "@/api/gen";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
import {
  Item,
  ItemContent,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/atoms/item";
import { ScrollArea, ScrollBar } from "@/components/atoms/scroll-area";
import { ChartNoAxesGanttIcon, StarsIcon } from "lucide-react";

import DataTable from "./DataTable";

interface ComparisonProps {
  fields: ProcessedField[];
}

const Comparison = ({ fields }: ComparisonProps) => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>隱私保護對照 - 示範資料</CardTitle>
      </CardHeader>

      <CardContent>
        <ItemGroup className="grid grid-cols-2">
          <Item className="items-start gap-2" variant="outline">
            <ItemMedia variant="icon">
              <ChartNoAxesGanttIcon className="text-muted-foreground" />
            </ItemMedia>

            <ItemContent className="min-w-0">
              <ItemTitle className="text-muted-foreground mb-2 whitespace-nowrap">
                Before
              </ItemTitle>

              <ScrollArea className="w-full">
                <DataTable />
                <ScrollBar orientation="horizontal" />
              </ScrollArea>
            </ItemContent>
          </Item>

          <Item className="items-start gap-2" variant="outline">
            <ItemMedia variant="icon">
              <StarsIcon className="text-yellow-500" />
            </ItemMedia>

            <ItemContent className="min-w-0">
              <ItemTitle className="mb-2 whitespace-nowrap">After</ItemTitle>

              <ScrollArea className="w-full">
                <DataTable />
                <ScrollBar orientation="horizontal" />
              </ScrollArea>
            </ItemContent>
          </Item>
        </ItemGroup>
      </CardContent>
    </Card>
  );
};

export default Comparison;
