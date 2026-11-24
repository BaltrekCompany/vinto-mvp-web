import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const src=readFileSync(new URL("../lib/vinto/quality-offline-draft-lifecycle.ts",import.meta.url),"utf8");
test("recover saved draft instead of replacing it",()=>{
  assert.match(src,/const existing = await deps\.bindings\.resume\(\)/);
  assert.match(src,/if \(existing\) return existing/);
  assert.match(src,/const concurrent = await deps\.bindings\.resume\(\)/);
  assert.match(src,/if \(concurrent\) return concurrent/);
});
test("new draft requires verified authority and prepared owner+draft identity",()=>{
  assert.match(src,/await deps\.assertPreparedCaptureScope\(\)/);
  assert.match(src,/draftId: deps\.draftId/);
  assert.match(src,/ownerId: deps\.identity\.ownerId/);
  assert.match(src,/revision: null/);
  assert.doesNotMatch(src,/\b(fetch|localStorage|indexedDB)\s*\(/);
});
