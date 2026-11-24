import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const file = readFileSync(new URL("../lib/vinto/quality-offline-current-form-bridge.ts", import.meta.url), "utf8");

test("Quality offline adapter reuses existing form validation", () => {
  assert.match(file, /input\.form\.normalizeDraft\(input\.draft\)/);
  assert.match(file, /resolveQualityOfflineTarget/);
  assert.match(file, /target\.kind !== input\.form\.context/);
});

test("incomplete authorization and bobbin context fail closed", () => {
  assert.match(file, /authority_context_missing/);
  assert.match(file, /bobbin_context_missing/);
  assert.match(file, /unexpected_bobbin_context/);
  assert.doesNotMatch(file, /\b(fetch|indexedDB|localStorage)\s*\(/);
});
