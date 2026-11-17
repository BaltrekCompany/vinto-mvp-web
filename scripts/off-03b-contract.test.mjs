import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";

const root = resolve(import.meta.dirname, "..");
const file = (path) => readFileSync(resolve(root, path), "utf8");

test("offline boot has no network or production capture", () => {
  const boot = file("lib/vinto/offline-boot.ts");
  assert.match(boot, /unlockLocalVault\(/);
  assert.match(boot, /readLocalProfile\(/);
  assert.match(boot, /localStorage\.getItem\(DEVICE_KEY_STORAGE\)/);
  assert.doesNotMatch(boot, /fetch\s*\(|document\.cookie|api\/captures|api\/auth/);
  assert.match(boot, /Las capturas y los permisos industriales siguen deshabilitados/);
});

test("online enrollment revalidates identity and requires local persistence", () => {
  const page = file("app/offline-preparacion/page.tsx");
  assert.ok((page.match(/await getCurrentUser\(\)/g) ?? []).length >= 2);
  assert.match(page, /auth\.user\.id !== user\.id/);
  assert.match(page, /auth\.user\.must_change|!u\.must_change/);
  assert.match(page, /user\.permissions|u\.permissions/);
  assert.match(page, /getDeviceKey\(/);
  assert.match(page, /storeLocalProfile\(/);
  assert.doesNotMatch(page, /qualityApi|createCapture|postCapture|sendCapture|syncCaptures/);
});

test("same TypeScript crypto is compiled into a public JS runtime", () => {
  const script = file("scripts/build-offline-boot.mjs");
  const runner = file("scripts/run-framework.mjs");
  assert.match(script, /entry: "lib\/vinto\/offline-boot\.ts"/);
  assert.match(script, /formats: \["iife"\]/);
  assert.match(script, /fileName: \(\) => "offline-boot\.js"/);
  assert.match(runner, /await buildOfflineBoot\(\)/);
  const sw = file("public/sw.js");
  assert.match(sw, /"\/offline-boot\.js"/);
  assert.match(sw, /vinto-off03c3-static-v1/);
});

test("offline shell exposes only local verification and not industrial forms", () => {
  const html = file("public/offline.html");
  assert.match(html, /offline-unlock-form/);
  assert.match(html, /offline-unlock-secret/);
  assert.match(html, /offline-boot\.js/);
  assert.match(html, /la captura de datos reales/);
  assert.doesNotMatch(html, /<form[^>]+action=["']\/api\//);
});
