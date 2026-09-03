import { Layout } from "@/layouts";

import BeforeAfter from "./beforeAfter/BeforeAfter";
import DataForm from "./dataForm/DataForm";

const IndexPage = () => {
  return (
    <Layout>
      <DataForm />
      <BeforeAfter />
    </Layout>
  );
};

export default IndexPage;
