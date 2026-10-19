import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
export default defineConfig({
  plugins: [tailwindcss()],
  resolve: {
    alias: [
      { find: /^@\//, replacement: fileURLToPath(new URL("./src/", import.meta.url)) },
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
  test: {
    setupFiles: ["./src/test-setup.ts"],
    server: { deps: { inline: [/@sarchauhan\//] } },
  },
  build: {
    outDir: "../src/coding_agent/web/static",
    emptyOutDir: true,
    rollupOptions: {
      // RSC "use client" directives (and the sourcemap notes they cause) do
      // not apply to this single-page bundle.
      onwarn(warning, warn) {
        if (warning.code === "MODULE_LEVEL_DIRECTIVE") return;
        if (warning.code === "SOURCEMAP_ERROR") return;
        warn(warning);
      },
    },
  },
});
