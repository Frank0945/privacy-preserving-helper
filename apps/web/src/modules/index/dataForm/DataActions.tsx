import type { Dispatch, SetStateAction } from "react";
import {
  analyzeRequestSampleCountEnum,
  purposeEnum,
  type AnalyzeRequestSampleCountEnumKey,
  type PurposeEnumKey,
} from "@/api/gen";
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

import type { DataActionsValue } from "./DataForm";

interface DataActionsProps {
  value: DataActionsValue;
  onChange: Dispatch<SetStateAction<DataActionsValue>>;
}

const DataActions = ({ value, onChange }: DataActionsProps) => {
  const update = (patch: Partial<DataActionsValue>) => {
    onChange({
      ...value,
      ...patch,
    });
  };

  return (
    <>
      <Field orientation="horizontal" className="w-fit gap-2 text-nowrap">
        <FieldLabel>使用目的：</FieldLabel>

        <Select
          value={value.purpose}
          onValueChange={(v) => update({ purpose: v as PurposeEnumKey })}
        >
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>

          <SelectContent>
            <SelectGroup>
              {Object.keys(purposeEnum).map((purpose) => (
                <SelectItem key={purpose} value={purpose}>
                  {purpose}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>

        {value.purpose === "其他" && (
          <Input
            value={value.otherPurpose}
            onChange={(e) => update({ otherPurpose: e.target.value })}
            placeholder="請輸入使用目的"
          />
        )}
      </Field>

      <Field orientation="horizontal" className="w-fit gap-2 text-nowrap">
        <FieldLabel>示範資料筆數：</FieldLabel>

        <Select
          value={value.dataAmount.toString()}
          onValueChange={(value) =>
            update({
              dataAmount: Number(value) as AnalyzeRequestSampleCountEnumKey,
            })
          }
        >
          <SelectTrigger className="w-16">
            <SelectValue />
          </SelectTrigger>

          <SelectContent>
            <SelectGroup>
              {Object.keys(analyzeRequestSampleCountEnum).map((amount) => (
                <SelectItem key={amount} value={amount}>
                  {amount}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
    </>
  );
};

export default DataActions;
