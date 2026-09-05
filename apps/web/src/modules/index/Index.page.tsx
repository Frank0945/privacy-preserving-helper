import { Layout } from "@/layouts";

import BeforeAfter from "./beforeAfter/BeforeAfter";
import ColumnDetails from "./columnDetails/ColumnDetails";
import DataForm from "./dataForm/DataForm";

const IndexPage = () => {
  return (
    <Layout>
      <DataForm />
      <BeforeAfter />
      <ColumnDetails />
    </Layout>
  );
};

export default IndexPage;
