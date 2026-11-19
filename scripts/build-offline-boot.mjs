/**
 * OFF-03B.1: one source of truth. Bundle browser-only TS vault implementation to
 * a public offline runtime before dev/build. Never cache API or private HTML.
 */
import { build } from "vite";
import { copyFileSync, rmSync } from "node:fs";

/**
 * OFF-04.1: the draft LABORATORY is generated only when OFFLINE_DRAFT_LAB=1. A default build
 * (and any operational build) deletes stale lab files, so the lab cannot be served by accident.
 */
export async function buildOfflineDraftLab() {
  const files = ["public/offline-lab.html", "public/offline-draft-lab.js"];
  if (process.env.OFFLINE_DRAFT_LAB !== "1") {
    for (const file of files) rmSync(file, { force: true });
    return false;
  }
  await build({
    configFile: false,
    publicDir: false,
    logLevel: "error",
    build: {
      outDir: "public",
      emptyOutDir: false,
      copyPublicDir: false,
      minify: true,
      lib: { entry: "lib/vinto/offline-draft-lab.ts", name: "VINTOOfflineDraftLab", formats: ["iife"], fileName: () => "offline-draft-lab.js" },
    },
  });
  copyFileSync("lab/offline-lab.html", "public/offline-lab.html");
  return true;
}

export async function buildOfflineBoot() {
  await buildOfflineDraftLab();
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
