import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type { ProcessedField } from "@/api/gen";
import { Alert, AlertTitle } from "@/components/atoms/alert";
import { Badge } from "@/components/atoms/badge";
import { Button } from "@/components/atoms/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/atoms/input-group";
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
import { Slider } from "@/components/atoms/slider";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/atoms/tooltip";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { mapParamToFormula } from "@/lib/utils";
import { cn } from "cn";
import {
  BadgeCheckIcon,
  CheckIcon,
  CircleXIcon,
  CopyIcon,
  Undo2Icon,
} from "lucide-react";

import type {
  ChangedFieldConfig,
  ChangedFieldMap,
} from "../comparison/comparison";

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
  const { copyToClipboard, isCopied } = useCopyToClipboard();

  const [param, setParam] = useState([0]);
  const [variant, setVariant] = useState("");

  useEffect(() => {
    setParam([field.param.default ?? 0]);
    setVariant(field.default_variant ?? "");
  }, [field]);

  const isSuppressed = (field: ProcessedField) =>
    field.technique === "suppress";

  const isSlider = (field: ProcessedField) =>
    field.param.control_type === "slider";

  const isSelect = (field: ProcessedField) =>
    field.param.control_type === "select";

  const getFormula = (field: ProcessedField) => {
    if (field.default_variant) {
      return mapParamToFormula(
        field.excel_formulas,
        variant,
        param[0] ?? 0,
        indexToLetter(index) + "2",
      );
    }
    return "";
  };

  const updateChangedFieldMap = (updates: Partial<ChangedFieldConfig>) => {
    setChangedFieldMap((prev) => ({
      ...prev,
      [field.field_id]: {
        variant: updates.variant ?? variant,
        param: updates.param ?? param[0] ?? 0,
      },
    }));
  };

  const handleParamChange = (value: number[]) => {
    setParam(value);
    updateChangedFieldMap({ param: value[0] });
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
            variant={isSuppressed(field) ? "destructive" : "secondary"}
          >
            {processedFieldTechniqueEnum[field.technique]}
          </Badge>
        </ItemTitle>
        <ItemDescription className="line-clamp-none">
          {field.reason}
        </ItemDescription>

        {field.excel_formulas.length > 1 ||
          (isSelect(field) && (
            <Select value={variant} onValueChange={handleVariantChange}>
              <SelectTrigger
                className={cn("min-w-[180px]", isSlider(field) && "-mb-3")}
              >
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
          ))}

        {isSlider(field) && (
          <div>
            <div className="flex h-8.5 w-full items-end">
              {field.param.default != param[0] && (
                <Button
                  variant="outline"
                  className="rounded-full"
                  onClick={() => handleParamChange([field.param.default ?? 0])}
                >
                  <Undo2Icon />
                  <span>還原為預設值</span>
                </Button>
              )}
              <div className="ml-auto text-base">
                {param + " " + field.param.unit}
              </div>
            </div>
            <Slider
              className="my-2"
              value={param}
              min={field.param.min ?? 0}
              max={field.param.max ?? 0}
              step={field.param.step ?? 0}
              onValueChange={handleParamChange}
            />
            <div className="text-muted-foreground flex justify-between text-xs">
              <span>{field.param.min} (MIN)</span>
              <span>{field.param.max} (MAX)</span>
            </div>
          </div>
        )}

        {field.excel_formulas.length != 0 && (
          <>
            <InputGroup>
              <InputGroupTextarea
                className="text-muted-foreground [&::-webkit-scrollbar-thumb]:bg-border [&::-webkit-scrollbar-thumb:hover]:bg-muted-foreground/30 field-sizing-content h-19 overflow-y-auto font-mono [scrollbar-color:var(--border)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-track]:bg-transparent"
                value={getFormula(field)}
                readOnly
              />
              <InputGroupAddon align="inline-end">
                <InputGroupButton
                  aria-label="Copy"
                  title="Copy"
                  size="icon-xs"
                  onClick={() => {
                    copyToClipboard(getFormula(field));
                  }}
                >
                  {isCopied ? <CheckIcon /> : <CopyIcon />}
                </InputGroupButton>
              </InputGroupAddon>
            </InputGroup>
            {field.formula_error && (
              <Alert className="border-destructive" variant="destructive">
                <CircleXIcon />
                <AlertTitle>{field.formula_error}</AlertTitle>
              </Alert>
            )}
          </>
        )}
      </ItemContent>
    </Item>
  );
};

export default FieldSuggestion;
