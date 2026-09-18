import type { ProcessedField } from "@/api/gen";
import { Alert, AlertDescription, AlertTitle } from "@/components/atoms/alert";
import { Layout } from "@/layouts";
import { InfoIcon } from "lucide-react";
import { useState } from "react";

import Comparison from "./comparison/Comparison";
import type { ChangedFieldMap } from "./comparison/comparison";
import DataForm from "./dataForm/DataForm";
import Suggestion from "./suggestion/Suggestion";

const IndexPage = () => {
  const [fields, setFields] = useState<ProcessedField[]>([]);
  const [changedFieldMap, setChangedFieldMap] = useState<ChangedFieldMap>({});

  const handleUpdateFields = (fields: ProcessedField[]) => {
    setFields(fields);
    setChangedFieldMap({});
  };

  return (
    <Layout>
      <Alert>
        <InfoIcon />
        <AlertTitle>How to Use</AlertTitle>
        <AlertDescription>
          This website is currently available in Chinese. To try the main
          feature, click the cyan "產生建議" (Generate Suggestions) button. The
          system will generate privacy-preserving recommendations and
          corresponding Excel formulas based on the provided field information
          (A few example fields have been pre-filled).
          <br />
          <br />
          Note: The feature is still being improved. If an error occurs, please
          try again.
        </AlertDescription>
      </Alert>
      <DataForm updateFields={handleUpdateFields} />
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
