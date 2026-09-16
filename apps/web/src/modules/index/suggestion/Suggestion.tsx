import type { Dispatch, SetStateAction } from "react";
import type { ProcessedField } from "@/api/gen";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/atoms/card";

import type { ChangedFieldMap } from "../comparison/comparison";
import FieldSuggestion from "./FieldSuggestion";

interface SuggestionProps {
  fields: ProcessedField[];
  setChangedFieldMap: Dispatch<SetStateAction<ChangedFieldMap>>;
}

const Suggestion = ({ fields, setChangedFieldMap }: SuggestionProps) => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>欄位建議</CardTitle>
      </CardHeader>

      <CardContent className="grid grid-cols-[repeat(auto-fit,minmax(350px,1fr))] gap-3">
        {fields.map((field, i) => (
          <FieldSuggestion
            key={field.field_id}
            index={i}
            field={field}
            setChangedFieldMap={setChangedFieldMap}
          />
        ))}
      </CardContent>
    </Card>
  );
};

export default Suggestion;
