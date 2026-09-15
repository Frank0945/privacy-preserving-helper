import { useState, type Dispatch, type SetStateAction } from "react";
import {
  analyzeRequestSampleCountEnum,
  purposeEnum,
  useAnalyzeApiAnalyzePost,
  type AnalyzeRequestSampleCountEnumKey,
  type FieldSpecInput,
  type ProcessedField,
  type Purpose,
} from "@/api/gen";
import { Alert, AlertDescription, AlertTitle } from "@/components/atoms/alert";
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
import { FieldSet } from "@/components/atoms/field";
import { Spinner } from "@/components/atoms/spinner";
import {
  AlertTriangleIcon,
  ArrowUpLeftIcon,
  CircleXIcon,
  PlusIcon,
} from "lucide-react";

import DataActions from "./DataActions";
import { createDataField, parseAnalyzeError } from "./dataForm";
import FieldList from "./FieldList";

export interface DataActionsValue {
  purpose: Purpose;
  otherPurpose: string;
  dataAmount: AnalyzeRequestSampleCountEnumKey;
}

interface DataFormProps {
  setFields: Dispatch<SetStateAction<ProcessedField[]>>;
}

const DataForm = ({ setFields }: DataFormProps) => {
  const [items, setItems] = useState<FieldSpecInput[]>(() => [
    createDataField(),
  ]);

  const [actions, setActions] = useState<DataActionsValue>({
    purpose: purposeEnum.內部使用,
    otherPurpose: "",
    dataAmount: analyzeRequestSampleCountEnum[5],
  });

  const { mutate, data, isPending, isError, error } =
    useAnalyzeApiAnalyzePost();

  const addItem = () => {
    setItems((prev) => [...prev, createDataField()]);
  };

  const submitData = () => {
    mutate(
      {
        data: {
          purpose: actions.purpose,
          purpose_detail:
            actions.purpose === purposeEnum.其他 ? actions.otherPurpose : null,
          sample_count: actions.dataAmount,
          fields: items,
        },
      },
      {
        onSuccess: (data) => {
          setFields(data.fields ?? []);
        },
      },
    );
  };

  return (
    <FieldSet disabled={isPending} inert={isPending}>
      <Card>
        <CardHeader>
          <CardTitle>告訴我們您的資料長什麼樣子</CardTitle>

          <CardDescription>
            設定欄位型別、格式，以及是否為分析必要欄位。
          </CardDescription>

          <CardAction className="flex gap-5">
            <DataActions value={actions} onChange={setActions} />
          </CardAction>
        </CardHeader>

        <CardContent>
          {isError && (
            <Alert className="border-destructive" variant="destructive">
              <CircleXIcon />
              <AlertTitle>Something went wrong</AlertTitle>
              <AlertDescription className="whitespace-pre-line">
                {parseAnalyzeError(error)}
              </AlertDescription>
            </Alert>
          )}

          {data?.status === "need_clarification" && (
            <Alert className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-50">
              <AlertTriangleIcon />
              <AlertTitle>需要更多資訊</AlertTitle>
            </Alert>
          )}

          <FieldList
            items={items}
            onItemsChange={setItems}
            clarifications={data?.clarifications_needed ?? []}
          />
        </CardContent>

        <CardFooter className="flex justify-between">
          <Button onClick={addItem} variant="outline">
            <PlusIcon />
            新增欄位
          </Button>

          <Button onClick={submitData}>
            {isPending ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <ArrowUpLeftIcon />
            )}
            產生建議
          </Button>
        </CardFooter>
      </Card>
    </FieldSet>
  );
};

export default DataForm;
