import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
const source=readFileSync(new URL("../components/vinto/candidate-form-capture.tsx",import.meta.url),"utf8");
const hook=readFileSync(new URL("../lib/vinto/use-quality-offline-draft-editor.ts",import.meta.url),"utf8");
test("current Quality editor uses encrypted recovery and autosave for original fields",()=>{
  assert.match(source,/useQualityOfflineDraftEditor\(/);
  assert.match(source,/Object\.keys\(form\.emptyDraft\(\)\)/);
  assert.match(hook,/port\.recover\(\)/);
  assert.match(hook,/setDraft\(restored\)/);
  assert.match(hook,/port\.save\(snapshot,expected\)/);
});
test("unknown, frozen, absent, conflicted or failed stored drafts block writes",()=>{
  assert.match(hook,/setStatus\("missing"\)/);
  assert.match(hook,/setStatus\("frozen"\)/);
  assert.match(hook,/setStatus\("error"\)/);
  assert.match(source,/offlineQuality\?\.draft \|\| persistence\.blocked/);
  assert.match(source,/busy\.current \|\| saved \|\| offlineQueuedId \|\| recoveryBlocked/);
  assert.match(source,/await persistence\.flush\(\)/);
});
