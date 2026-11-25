import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { test } from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const modules = [
  "offline-operational-capture-bindings", "offline-operational-local-store", "offline-operational-model",
  "offline-operational-id", "offline-vault", "offline-sync-engine", "offline-sync-types",
  "offline-sync-rules", "offline-queue-record", "offline-scope-verify", "offline-auto-sync",
  "offline-operational-sync-runtime", "offline-operational-http",
  "offline-operational-capture-scope-verify", "offline-operational-capture-gate"
];
test("offline operational runtime imports resolve within isolated production-safe modules", () => {
  for (const name of modules) {
    const path = resolve(root, "lib/vinto", name + ".ts");
    assert.ok(existsSync(path), name);
    const source = readFileSync(path, "utf8");
    for (const [, relative] of source.matchAll(/from\s+["'](\.[^"']+)["']/g)) {
      const destination = resolve(dirname(path), relative);
      assert.ok(existsSync(destination) || existsSync(destination + ".ts"), name + " missing " + relative);
      assert.ok(!/offline-(?:draft-schema|store|synthetic|qa|lab)/.test(relative), name + " imports lab " + relative);
    }
  }
});
test("operational sync requires real registration acknowledgement and signed capture authority", () => {
  const sync = readFileSync(resolve(root, "lib/vinto/offline-operational-sync-runtime.ts"), "utf8");
  const gate = readFileSync(resolve(root, "lib/vinto/offline-operational-capture-gate.ts"), "utf8");
  assert.match(sync, /requireOperationalAck: true/);
  assert.match(gate, /verifyOperationalCaptureScope/);
});
