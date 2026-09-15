import { useState } from "react";
import type { ProcessedField } from "@/api/gen";
import { Layout } from "@/layouts";

import Comparison from "./comparison/Comparison";
import DataForm from "./dataForm/DataForm";
import Suggestion from "./suggestion/Suggestion";

const IndexPage = () => {
  const [fields, setFields] = useState<ProcessedField[]>([]);

  return (
    <Layout>
      <DataForm setFields={setFields} />
      {fields.length != 0 && (
        <>
          <Comparison fields={fields} />
          <Suggestion fields={fields} />
        </>
      )}
    </Layout>
  );
};

export default IndexPage;
