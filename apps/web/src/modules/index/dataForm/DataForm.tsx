import { useState } from "react";
import { Button } from "@/components/atoms/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";
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
import { ArrowUpLeftIcon, PlusIcon } from "lucide-react";

import type { DataField } from "./dataForm";
import { createDataField, fakeDataAmountList, purposeList } from "./dataForm";
import FieldList from "./FieldList";

const DataForm = () => {
  const [items, setItems] = useState<DataField[]>(() => [createDataField()]);

  const [purposeOption, setPurposeOption] = useState(purposeList[0].value);

  const [customPurpose, setCustomPurpose] = useState("");

  const [fakeDataAmount, setFakeDataAmount] = useState(
    fakeDataAmountList[0].value,
  );

  const addItem = () => {
    setItems((prev) => [...prev, createDataField()]);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>告訴我們您的資料長什麼樣子</CardTitle>

        <CardDescription>
          設定欄位型別、格式，以及是否為分析必要欄位。
        </CardDescription>

        <CardAction className="flex gap-5">
          <Field orientation="horizontal" className="w-fit gap-2 text-nowrap">
            <FieldLabel>使用目的：</FieldLabel>

            <Select value={purposeOption} onValueChange={setPurposeOption}>
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

            {purposeOption === "其他" && (
              <Input
                value={customPurpose}
                onChange={(e) => setCustomPurpose(e.target.value)}
                placeholder="請輸入使用目的"
              />
            )}
          </Field>

          <Field orientation="horizontal" className="w-fit gap-2 text-nowrap">
            <FieldLabel>示範資料筆數：</FieldLabel>

            <Select value={fakeDataAmount} onValueChange={setFakeDataAmount}>
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
        <FieldList items={items} onItemsChange={setItems} />
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
