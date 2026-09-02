import { useState } from "react";
import { Button } from "@/components/atoms/button";
import {
  Card,
  CardAction,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
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
import {
  ArrowUpLeftIcon,
  GripVerticalIcon,
  PlusIcon,
  XIcon,
} from "lucide-react";

const typeList = [
  { label: "文字", value: "文字" },
  { label: "數字", value: "數字" },
  { label: "日期", value: "日期" },
];

const purposeList = [
  { label: "內部使用", value: "內部使用" },
  { label: "跨部門使用", value: "跨部門使用" },
  { label: "對外公開研究", value: "對外公開研究" },
  { label: "其他", value: "其他" },
];

const fakeDataAmountList = [
  { label: "5", value: "5" },
  { label: "10", value: "10" },
  { label: "20", value: "20" },
];

interface SortableItem {
  id: string;
  name: string;
  type: "文字" | "數字" | "日期";
  rule: string;
  isImportant: boolean;
}

const createItem = (): SortableItem => ({
  id: crypto.randomUUID(),
  name: "",
  type: "文字",
  rule: "",
  isImportant: false,
});

const DataForm = () => {
  const [items, setItems] = useState<SortableItem[]>(() => [createItem()]);
  const [purposeOptions, setPurposeOptions] = useState(purposeList[0].value);
  const [purpose, setPurpose] = useState("");
  const [fakeDataAmount, setFakeDataAmount] = useState(
    fakeDataAmountList[0].value,
  );

  const getItemValue = (item: SortableItem) => item.id;

  const addItem = () => {
    setItems((prev) => [...prev, createItem()]);
  };

  const removeItem = (id: string) => {
    setItems(items.filter((item) => item.id !== id));
  };

  const handleValueChange = (newItems: SortableItem[]) => {
    setItems(newItems);
  };

  const updateItem = <K extends keyof SortableItem>(
    id: string,
    key: K,
    value: SortableItem[K],
  ) => {
    setItems((prevItems) =>
      prevItems.map((item) =>
        item.id === id ? { ...item, [key]: value } : item,
      ),
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>告訴我們您的資料長什麼樣子</CardTitle>
        <CardAction className="flex gap-5">
          <Field orientation="horizontal" className="w-fit gap-2 text-nowrap">
            <FieldLabel>使用目的：</FieldLabel>
            <Select
              value={purposeOptions}
              onValueChange={(value) => setPurposeOptions(value)}
            >
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {purposeList.map((purpose) => (
                    <SelectItem key={purpose.value} value={purpose.value}>
                      {purpose.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            {purposeOptions === "其他" && (
              <Input
                onChange={(e) => setPurpose(e.target.value)}
                value={purpose}
                placeholder="請輸入使用目的"
              />
            )}
          </Field>
          <Field orientation="horizontal" className="w-fit gap-2 text-nowrap">
            <FieldLabel>筆數：</FieldLabel>
            <Select
              value={fakeDataAmount}
              onValueChange={(value) => setFakeDataAmount(value)}
            >
              <SelectTrigger className="w-16">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {fakeDataAmountList.map((amount) => (
                    <SelectItem key={amount.value} value={amount.value}>
                      {amount.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        </CardAction>
      </CardHeader>
      <CardContent>
        <Sortable
          value={items}
          onValueChange={handleValueChange}
          getItemValue={getItemValue}
          strategy="vertical"
          className="space-y-3"
        >
          {items.map((item) => (
            <SortableItem
              className="bg-card flex items-center gap-2 rounded-md border p-3"
              key={item.id}
              value={item.id}
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
                  updateItem(item.id, "type", value as SortableItem["type"])
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
                    updateItem(item.id, "isImportant", checked as boolean)
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
            </SortableItem>
          ))}
        </Sortable>
      </CardContent>
      <CardFooter className="flex justify-between">
        <Button onClick={addItem} variant="outline">
          <PlusIcon />
          新增欄位
        </Button>
        <Button onClick={() => console.log(items)}>
          <ArrowUpLeftIcon />
          產生建議
        </Button>
      </CardFooter>
    </Card>
  );
};

export default DataForm;
