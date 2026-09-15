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
      <Comparison fields={fields} />
      <Suggestion />
    </Layout>
  );
};

export default IndexPage;
