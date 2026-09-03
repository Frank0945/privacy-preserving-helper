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
import { GripVerticalIcon, XIcon } from "lucide-react";

import type { DataField } from "./dataForm";
import { typeList } from "./dataForm";

interface FieldListProps {
  items: DataField[];
  onItemsChange: (items: DataField[]) => void;
}

const FieldList = ({ items, onItemsChange }: FieldListProps) => {
  const removeItem = (id: string) => {
    onItemsChange(items.filter((item) => item.id !== id));
  };

  const updateItem = <K extends keyof DataField>(
    id: string,
    key: K,
    value: DataField[K],
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
      {items.map((item) => (
        <SortableItem
          key={item.id}
          value={item.id}
          className="bg-card flex items-center gap-2 rounded-md border p-3"
        >
          <SortableItemHandle className="text-muted-foreground hover:text-foreground">
            <GripVerticalIcon className="h-4 w-4" />
          </SortableItemHandle>

          <Input
            className="max-w-80"
            value={item.name}
            placeholder="欄位名稱，如「年齡」"
            onChange={(e) => updateItem(item.id, "name", e.target.value)}
          />

          <Select
            value={item.type}
            onValueChange={(value) =>
              updateItem(item.id, "type", value as DataField["type"])
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
            value={item.rule}
            placeholder="格式規則（選填）"
            onChange={(e) => updateItem(item.id, "rule", e.target.value)}
          />

          <Field
            orientation="horizontal"
            className="mr-auto w-fit shrink-0 gap-2"
          >
            <Checkbox
              id={`isImportant-${item.id}`}
              checked={item.isImportant}
              onCheckedChange={(checked) =>
                updateItem(item.id, "isImportant", checked === true)
              }
            />

            <FieldLabel htmlFor={`isImportant-${item.id}`}>關鍵欄位</FieldLabel>
          </Field>

          <Button
            variant="ghost"
            size="icon"
            onClick={() => removeItem(item.id)}
          >
            <XIcon />
          </Button>
        </SortableItem>
      ))}
    </Sortable>
  );
};

export default FieldList;
