import type { FunctionComponent, ReactNode } from "react";

import { SiteHeader } from "./siteHeader";

type LayoutProps = {
  children: ReactNode;
};

const Layout: FunctionComponent<LayoutProps> = ({ children }) => {
  return (
    <>
      <SiteHeader />
      <main className="@container/main mx-auto flex max-w-[1440px] flex-1 flex-col gap-4 p-4 md:p-6 lg:p-8">
        {children}
      </main>
    </>
  );
};
export default Layout;
