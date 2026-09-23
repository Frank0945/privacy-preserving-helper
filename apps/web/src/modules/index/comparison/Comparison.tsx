import { useEffect, useRef } from "react";
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
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/atoms/item";
import { ScrollArea, ScrollBar } from "@/components/atoms/scroll-area";
import { cn } from "cn";
import { ChartNoAxesGanttIcon, StarsIcon } from "lucide-react";

import type { ChangedFieldMap } from "./comparison";
import DataTable from "./DataTable";

interface ComparisonProps {
  fields: ProcessedField[];
  changedFieldMap: ChangedFieldMap;
}

const Comparison = ({ fields, changedFieldMap }: ComparisonProps) => {
  const titles = ["原始資料", "隱私保護後"];
  const isBefore = (title: string) => title === titles[0];

  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const left = leftScrollRef.current;
    const right = rightScrollRef.current;

    if (!left || !right) return;

    const sync = (source: HTMLDivElement, target: HTMLDivElement) => {
      target.scrollLeft = source.scrollLeft;
    };

    const onLeftScroll = () => sync(left, right);
    const onRightScroll = () => sync(right, left);

    left.addEventListener("scroll", onLeftScroll);
    right.addEventListener("scroll", onRightScroll);

    return () => {
      left.removeEventListener("scroll", onLeftScroll);
      right.removeEventListener("scroll", onRightScroll);
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>隱私保護對照 - 示範資料</CardTitle>
      </CardHeader>

      <CardContent>
        <ItemGroup className="grid grid-cols-2">
          {titles.map((title) => (
            <Item className="gap-2" variant="outline" key={title}>
              <ItemMedia variant="icon">
                {isBefore(title) ? (
                  <ChartNoAxesGanttIcon className="text-muted-foreground" />
                ) : (
                  <StarsIcon className="text-yellow-600" />
                )}
              </ItemMedia>

              <ItemContent className="min-w-0">
                <ItemTitle
                  className={cn(
                    "mb-2 whitespace-nowrap text-yellow-600",
                    isBefore(title) && "text-muted-foreground",
                  )}
                >
                  {title}
                </ItemTitle>
                <ItemDescription></ItemDescription>
                <ScrollArea
                  viewportRef={isBefore(title) ? leftScrollRef : rightScrollRef}
                  className="w-full"
                >
                  <DataTable
                    fields={fields}
                    isApplyFormula={!isBefore(title)}
                    changedFieldMap={changedFieldMap}
                  />
                  <ScrollBar orientation="horizontal" />
                </ScrollArea>
              </ItemContent>
            </Item>
          ))}
        </ItemGroup>
      </CardContent>
    </Card>
  );
};

export default Comparison;
