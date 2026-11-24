import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../lib/vinto/quality-offline-queue-port.ts", import.meta.url), "utf8");

test("existing Quality UI queue port requires a verified initialized draft", () => {
  assert.match(source, /deps\.bindingsFor\(prepared\)/);
  assert.match(source, /await bindings\.resume\(\)/);
  assert.match(source, /offline_draft_not_initialized/);
  assert.match(source, /offline_draft_conflict/);
  assert.match(source, /sameValues\(prior\.values, values\)/);
});
test("the only queue operation is atomic freeze with signed authority inside bindings", () => {
  assert.match(source, /await bindings\.freeze\(revision\)/);
  assert.match(source, /offline_capture_unconfirmed/);
  assert.doesNotMatch(source, /\b(fetch|localStorage|indexedDB)\s*\(/);
  assert.doesNotMatch(source, /createOperationalLocalStore\(/);
});
