import path from "path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react-swc";
import { defineConfig } from "vite";
import Pages from "vite-plugin-pages";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    Pages({
      dirs: [
        {
          dir: "src/modules",
          baseRoute: "",
          filePattern: "**/*.page.*",
        },
      ],
      extendRoute(route: { path: string }) {
        return {
          ...route,
          // Remove the filename since we only consider the directory structure for routing
          path: route.path.endsWith(".page") ? "" : route.path,
        };
      },
      onRoutesGenerated(routes) {
        routes.push({
          path: "/",
          element: path.resolve(__dirname, "src/modules/index/Index.page.tsx"),
        });
        routes.push({
          path: "*",
          element: path.resolve(
            __dirname,
            "src/modules/notFound/NotFound.page.tsx",
          ),
        });
      },
    }),
  ],
  server: {
    watch: {
      usePolling: true,
    },
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
