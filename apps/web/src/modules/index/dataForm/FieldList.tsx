import type { ClarificationNeeded, FieldSpecInput } from "@/api/gen";
import { Button } from "@/components/atoms/button";
import { Checkbox } from "@/components/atoms/checkbox";
import { Field, FieldLabel } from "@/components/atoms/field";
import { Input } from "@/components/atoms/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import {
  Sortable,
  SortableItem,
  SortableItemHandle,
} from "@/components/atoms/sortable";
import { cn } from "cn";
import { GripVerticalIcon, XIcon } from "lucide-react";

import { findClarificationForField, typeList } from "./dataForm";

interface FieldListProps {
  items: FieldSpecInput[];
  clarifications: ClarificationNeeded[];
  onItemsChange: (items: FieldSpecInput[]) => void;
}

const FieldList = ({
  items,
  onItemsChange,
  clarifications,
}: FieldListProps) => {
  const removeItem = (id: string) => {
    onItemsChange(items.filter((item) => item.id !== id));
  };

  const updateItem = <K extends keyof FieldSpecInput>(
    id: string,
    key: K,
    value: FieldSpecInput[K],
  ) => {
    onItemsChange(
      items.map((item) => (item.id === id ? { ...item, [key]: value } : item)),
    );
  };

  return (
    <Sortable
      value={items}
      onValueChange={onItemsChange}
      getItemValue={(item) => item.id}
      strategy="vertical"
      className="space-y-3"
    >
      {items.map((item) => {
        const clarification = findClarificationForField(
          item.id,
          clarifications,
        );

        return (
          <SortableItem
            key={item.id}
            value={item.id}
            className={cn(
              "bg-card flex cursor-default items-center gap-2 rounded-md border p-3",
              clarification && "border-amber-400 dark:border-amber-700",
            )}
          >
            <SortableItemHandle className="text-muted-foreground hover:text-foreground">
              <GripVerticalIcon className="h-4 w-4" />
            </SortableItemHandle>

            <div className="flex w-full flex-col gap-3.5">
              <div className="flex w-full gap-2">
                <Input
                  className="max-w-80"
                  value={item.name}
                  placeholder="欄位名稱，如「年齡」"
                  onChange={(e) => updateItem(item.id, "name", e.target.value)}
                />

                <Select
                  value={item.data_type}
                  onValueChange={(value) =>
                    updateItem(item.id, "data_type", value)
                  }
                >
                  <SelectTrigger className="min-w-[120px]">
                    <SelectValue />
                  </SelectTrigger>

                  <SelectContent>
                    <SelectGroup>
                      {typeList.map((type) => (
                        <SelectItem key={type.value} value={type.value}>
                          {type.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>

                <Input
                  className="max-w-96"
                  value={item.format_hint ?? ""}
                  placeholder="格式規則（選填）"
                  onChange={(e) =>
                    updateItem(item.id, "format_hint", e.target.value)
                  }
                />

                <Field
                  orientation="horizontal"
                  className="mr-auto w-fit shrink-0 gap-2"
                >
                  <Checkbox
                    id={`isImportant-${item.id}`}
                    checked={item.is_key_field}
                    onCheckedChange={(checked) =>
                      updateItem(item.id, "is_key_field", checked === true)
                    }
                  />

                  <FieldLabel htmlFor={`isImportant-${item.id}`}>
                    關鍵欄位
                  </FieldLabel>
                </Field>

                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeItem(item.id)}
                >
                  <XIcon />
                </Button>
              </div>

              {clarification && (
                <span className="px-2 text-sm text-amber-500 dark:text-amber-600">
                  {clarification}
                </span>
              )}
            </div>
          </SortableItem>
        );
      })}
    </Sortable>
  );
};

export default FieldList;
