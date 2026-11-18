/** OFF-03C.4: bundle the CI-only browser harness with Vite (already a dev dependency). */
import { build } from "vite";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const out = process.env.OFF03C4_HARNESS_JS;
if (!out) throw new Error("OFF03C4_HARNESS_JS (absolute output path) is required");
mkdirSync(dirname(resolve(out)), { recursive: true });
await build({
  configFile: false, publicDir: false, logLevel: "error",
  build: {
    outDir: dirname(resolve(out)), emptyOutDir: false, copyPublicDir: false, minify: false,
    lib: { entry: "scripts/off-03c4-harness-entry.ts", name: "OFF03C4Harness", formats: ["iife"], fileName: () => out.split("/").pop() },
  },
});
console.log("OFF03C4_HARNESS_BUNDLE=PASS");
