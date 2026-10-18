import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
export default defineConfig({
  resolve: {
    alias: [
      {
        find: /^@sarchauhan\/protocol$/,
        replacement: fileURLToPath(
          new URL("./src/protocol-compat.ts", import.meta.url),
        ),
      },
      {
        find: "@sarchauhan/protocol-original",
        replacement: fileURLToPath(
          new URL(
            "./node_modules/@sarchauhan/protocol/dist/index.mjs",
            import.meta.url,
          ),
        ),
      },
    ],
  },
  test: { server: { deps: { inline: [/@sarchauhan\//] } } },
  build: { outDir: "../src/coding_agent/web/static", emptyOutDir: true },
});
