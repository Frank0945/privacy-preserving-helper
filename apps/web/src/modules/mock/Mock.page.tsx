import { useState } from "react";
import type { ProcessedField } from "@/api/gen";
import { Alert, AlertDescription, AlertTitle } from "@/components/atoms/alert";
import { Layout } from "@/layouts";
import { AlertOctagonIcon } from "lucide-react";

import Comparison from "../index/comparison/Comparison";
import type { ChangedFieldMap } from "../index/comparison/comparison";
import DataForm from "../index/dataForm/DataForm";
import Suggestion from "../index/suggestion/Suggestion";
import mockResponse from "./mockResponse.json";

const IndexPage = () => {
  const [fields, setFields] = useState<ProcessedField[]>(
    mockResponse.fields as ProcessedField[],
  );
  const [changedFieldMap, setChangedFieldMap] = useState<ChangedFieldMap>({});

  const handleUpdateFields = (fields: ProcessedField[]) => {
    setFields(fields);
    setChangedFieldMap({});
  };

  return (
    <Layout>
      <Alert className="border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-50">
        <AlertOctagonIcon />
        <AlertTitle>Mock Page</AlertTitle>
        <AlertDescription className="whitespace-pre-line">
          為確保網路穩定性，本頁為預生成的結果。
        </AlertDescription>
      </Alert>
      <DataForm updateFields={handleUpdateFields} isMock={true} />

      {fields.length > 0 && (
        <>
          <Comparison fields={fields} changedFieldMap={changedFieldMap} />
          <Suggestion fields={fields} setChangedFieldMap={setChangedFieldMap} />
        </>
      )}
    </Layout>
  );
};

export default IndexPage;
