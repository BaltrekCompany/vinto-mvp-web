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
  const files = ["public/offline-lab.html", "public/offline-draft-lab.js", "public/offline-sync-lab.html", "public/offline-sync-lab.js", "public/offline-e2e-lab.html", "public/offline-e2e-lab.js", "public/off048i-indexeddb.html", "public/off048i-indexeddb.js"];
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
  // OFF-04.3: the synchronisation engine laboratory (fake server) ships ONLY with the same opt-in flag.
  await build({
    configFile: false,
    publicDir: false,
    logLevel: "error",
    build: {
      outDir: "public",
      emptyOutDir: false,
      copyPublicDir: false,
      minify: true,
      lib: { entry: "lib/vinto/offline-sync-lab.ts", name: "VINTOOfflineSyncLab", formats: ["iife"], fileName: () => "offline-sync-lab.js" },
    },
  });
  copyFileSync("lab/offline-sync-lab.html", "public/offline-sync-lab.html");
  // OFF-04.5A: the end-to-end Quality laboratory (loopback receiver only) ships ONLY with the same opt-in flag.
  await build({
    configFile: false,
    publicDir: false,
    logLevel: "error",
    build: {
      outDir: "public",
      emptyOutDir: false,
      copyPublicDir: false,
      minify: true,
      lib: { entry: "lib/vinto/offline-quality-e2e-lab.ts", name: "VINTOOfflineQualityE2ELab", formats: ["iife"], fileName: () => "offline-e2e-lab.js" },
    },
  });
  copyFileSync("lab/offline-e2e-lab.html", "public/offline-e2e-lab.html");
  // OFF-04.8I isolated Chrome IndexedDB QA (no API or operational routes).
  await build({
    configFile: false,
    publicDir: false,
    logLevel: "error",
    build: {
      outDir: "public",
      emptyOutDir: false,
      copyPublicDir: false,
      minify: true,
      lib: { entry: "lib/vinto/off048i-indexeddb-browser.ts", name: "VINTO_OFF048I_TEST", formats: ["iife"], fileName: () => "off048i-indexeddb.js" },
    },
  });
  copyFileSync("lab/off048i-indexeddb.html", "public/off048i-indexeddb.html");
  return true;
}

/** Operational Quality mobile entrypoint: only when explicitly enabled for
 * a QA/production build. Never ship automatically from an unreviewed PR. */
export async function buildOperationalQualityMobile() {
  const files=["public/offline-calidad.html","public/offline-calidad.js"];
  if(process.env.OFFLINE_OPERATIONAL_CAPTURE!=="1"){
    for(const file of files)rmSync(file,{force:true});
    return false;
  }
  await build({
    configFile:false,publicDir:false,logLevel:"error",
    build:{outDir:"public",emptyOutDir:false,copyPublicDir:false,minify:true,
      lib:{entry:"lib/vinto/offline-operational-mobile-page.ts",
        name:"VINTOOfflineQualityMobile",formats:["iife"],
        fileName:()=>"offline-calidad.js"}},
  });
  copyFileSync("lab/offline-calidad.html","public/offline-calidad.html");
  return true;
}

export async function buildOfflineBoot() {
  await buildOfflineDraftLab();
  await buildOperationalQualityMobile();
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
