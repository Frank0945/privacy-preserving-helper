import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type { ProcessedField } from "@/api/gen";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/atoms/accordion";
import { Badge } from "@/components/atoms/badge";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/atoms/item";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/atoms/tooltip";
import { mapParamToFormula } from "@/lib/utils";
import { cn } from "cn";
import { BadgeCheckIcon } from "lucide-react";

import type {
  ChangedFieldConfig,
  ChangedFieldMap,
} from "../comparison/comparison";
import DpPreviewTable from "./DpPreviewTable";
import Formula from "./Formula";
import ParamSlider from "./ParamSlider";

interface DataItemProps {
  field: ProcessedField;
  index: number;
  setChangedFieldMap: Dispatch<SetStateAction<ChangedFieldMap>>;
}

const processedFieldTechniqueEnum = {
  mask: "遮罩",
  generalize: "泛化",
  suppress: "抑制",
  differential_privacy: "差分隱私",
} as const;

const indexToLetter = (index: number) => String.fromCharCode(65 + index);

const FieldSuggestion = ({
  field,
  index,
  setChangedFieldMap,
}: DataItemProps) => {
  const [param, setParam] = useState([0]);
  const [dpParam, setDpParam] = useState([0]);
  const [variant, setVariant] = useState("");

  useEffect(() => {
    setParam([field.param.default ?? 0]);
    setDpParam([field.dp_param?.default ?? 0]);
    setVariant(field.default_variant ?? "");
  }, [field]);

  const isSuppressed = field.technique === "suppress";

  const isSlider = field.param.control_type === "slider";

  const isSelect = field.param.control_type === "select";

  const isMultipleFormula = field.excel_formulas.length > 1;

  const resolvedFormula = mapParamToFormula(
    field.excel_formulas,
    variant,
    param[0] ?? 0,
    indexToLetter(index) + "2",
  );

  const resolvedDpFormula = mapParamToFormula(
    field.dp_excel_formulas ?? [],
    field.dp_default_variant ?? "",
    dpParam[0] ?? 0,
    "A2",
  );

  const updateChangedFieldMap = (updates: Partial<ChangedFieldConfig>) => {
    setChangedFieldMap((prev) => ({
      ...prev,
      [field.field_id]: {
        variant: updates.variant ?? variant,
        param: updates.param ?? param[0] ?? 0,
      },
    }));
  };

  const handleParamValueChange = (value: number[]) => {
    setParam(value);
    updateChangedFieldMap({ param: value[0] });
  };

  const handleDpParamValueChange = (value: number[]) => {
    setDpParam(value);
  };

  const handleVariantChange = (value: string) => {
    setVariant(value);
    updateChangedFieldMap({ variant: value });
  };

  return (
    <Item variant="outline" className="py-5">
      <ItemContent className="h-full w-full gap-y-3">
        <ItemTitle className="flex w-full items-center justify-between text-xl">
          <div className="flex">
            <span>{field.field_name}</span>
            {field.is_key_field && (
              <Tooltip>
                <TooltipTrigger>
                  <BadgeCheckIcon className="ml-2 w-4 text-blue-500" />
                </TooltipTrigger>
                <TooltipContent>
                  <p>關鍵分析欄位</p>
                </TooltipContent>
              </Tooltip>
            )}
          </div>
          <Badge
            className="h-8 items-center px-3"
            variant={isSuppressed ? "destructive" : "secondary"}
          >
            {processedFieldTechniqueEnum[field.technique]}
          </Badge>
        </ItemTitle>
        <ItemDescription className="line-clamp-none">
          {field.reason}
        </ItemDescription>

        {(isMultipleFormula || isSelect) && (
          <Select value={variant} onValueChange={handleVariantChange}>
            <SelectTrigger className={cn("min-w-[180px]", isSlider && "-mb-3")}>
              <SelectValue placeholder="Theme" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {field.excel_formulas.map((item) => (
                  <SelectItem key={item.variant} value={item.variant}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        )}

        {isSlider && (
          <ParamSlider
            value={param}
            sliderParam={field.param}
            moveRestButtonOnTop={isMultipleFormula}
            onValueChange={handleParamValueChange}
          />
        )}

        {field.excel_formulas.length != 0 && (
          <Formula
            formula={resolvedFormula}
            errorMessage={field.formula_error}
          />
        )}

        {field.dp_excel_formulas && field.dp_param && (
          <Item variant="outline" className="border-dashed">
            <ItemContent className="w-full">
              <Accordion type="single" collapsible>
                <AccordionItem value="dp">
                  <AccordionTrigger className="py-0 font-normal data-[state=open]:font-bold">
                    使用「差分隱私」保護統計資料
                  </AccordionTrigger>
                  <AccordionContent className="h-full space-y-3 pt-3 pb-0">
                    <div className="text-muted-foreground">
                      {field.dp_explanation}
                      <br />
                      <br />
                      {field.dp_sensitivity_basis}
                    </div>
                    <ParamSlider
                      value={dpParam}
                      sliderParam={field.dp_param}
                      moveRestButtonOnTop={false}
                      onValueChange={handleDpParamValueChange}
                    />

                    <Formula
                      formula={resolvedDpFormula}
                      errorMessage={field.dp_formula_error}
                    />

                    <div className="text-muted-foreground -mt-1 text-xs">
                      ＊ 請根據您的真實資料，調整「敏感度 (
                      {field.dp_sensitivity})」
                    </div>

                    <DpPreviewTable
                      formula={resolvedDpFormula}
                      sample_before={field.sample_before}
                    />
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </ItemContent>
          </Item>
        )}
      </ItemContent>
    </Item>
  );
};

export default FieldSuggestion;
