/// <reference types="vite/client" />
/// <reference types="vite-plugin-pages/client-react" />
///declare module "matter-wrap";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import Pages from "vite-plugin-pages";

export default defineConfig({
  plugins: [
    react(),
    Pages({
      // 告訴套件去 src/modules 資料夾搜尋路由
      dirs: "src/modules",
      // 指定只有 .page.tsx 結尾的檔案才當作頁面
      extensions: ["page.tsx"],
    }),
  ],
});
