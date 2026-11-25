import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../lib/vinto/quality-offline-target.ts", import.meta.url), "utf8");

test("mapping is restricted to existing Quality form groups", () => {
  assert.match(source, /QUALITY_SCREEN_BY_FORM/);
  assert.match(source, /BOBBIN_SCREEN_BY_FORM/);
  assert.match(source, /VINTO-P1-19/);
  assert.match(source, /VINTO-P1-20/);
  assert.match(source, /return null/);
});

test("no side effects or offline authorization bypass", () => {
  assert.doesNotMatch(source, /\b(fetch|localStorage|indexedDB)\s*\(/);
  assert.match(source, /if \(!machineCode\) return null/);
  assert.match(source, /if \(!bobbinId\) return null/);
  assert.match(source, /if \(context\.bobbinId\) return null/);
});
