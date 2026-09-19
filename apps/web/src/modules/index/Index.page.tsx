import { useState } from "react";
import type { ProcessedField } from "@/api/gen";
import { Layout } from "@/layouts";

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
