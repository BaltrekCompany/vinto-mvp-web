/**
 * OFF-03B.1: one source of truth. Bundle browser-only TS vault implementation to
 * a public offline runtime before dev/build. Never cache API or private HTML.
 */
import { build } from "vite";

export async function buildOfflineBoot() {
  await build({
    configFile: false,
    publicDir: false,
    logLevel: "error",
    build: {
      outDir: "public",
      emptyOutDir: false,
      copyPublicDir: false,
      minify: true,
      lib: {
        entry: "lib/vinto/offline-boot.ts",
        name: "VINTOOfflineBoot",
        formats: ["iife"],
        fileName: () => "offline-boot.js",
      },
    },
  });
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  await buildOfflineBoot();
}
