import { defineConfig } from "@kubb/core";
import { pluginClient } from "@kubb/plugin-client";
import { pluginOas } from "@kubb/plugin-oas";
import { pluginReactQuery } from "@kubb/plugin-react-query";
import { pluginTs } from "@kubb/plugin-ts";

import "dotenv/config";

export default defineConfig(() => {
  return {
    root: ".",
    input: {
      path: "./src/api/openapi.json",
    },
    output: {
      path: "./src/api/gen",
      clean: true,
    },
    plugins: [
      pluginOas(),
      pluginTs(),
      pluginClient({
        baseURL: process.env.VITE_API_BASE_URL,
      }),
      pluginReactQuery(),
    ],
  };
});