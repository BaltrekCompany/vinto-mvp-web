import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read=(path)=>readFileSync(new URL("../"+path,import.meta.url),"utf8");
const hook=read("lib/vinto/use-quality-offline-draft-editor.ts");
for(const path of [
  "components/vinto/candidate-form-capture.tsx",
  "components/vinto/quality-humidity-capture.tsx",
  "components/vinto/quality-physical-capture.tsx",
]){
  test(path+" retains its original form while using encrypted draft recovery",()=>{
    const src=read(path);
    assert.match(src,/useQualityOfflineDraftEditor\(/);
    assert.match(src,/offlineQuality\?\.draft/);
    assert.match(src,/await persistence\.flush\(draft\)/);
    assert.match(src,/await offlineQuality\.queue\(prepared\.value\)/);
    assert.match(src,/recoveryBlocked/);
  });
}
test("encrypted edits use serialized CAS revisions and flush before capture",()=>{
  assert.match(hook,/chain\.current=chain\.current\.then/);
  assert.match(hook,/port\.save\(snapshot,expected\)/);
  assert.match(hook,/next\.revision!==expected\+1/);
  assert.match(hook,/failed\.current=true/);
  assert.match(hook,/await chain\.current/);
  assert.match(hook,/equal\(lastSaved\.current,current\.current as QualityDraftValues\)/);
});
test("no automatic UI mount or plaintext draft storage",()=>{
  const main=read("app/page.tsx");
  assert.doesNotMatch(main,/offlineQuality=/);
  assert.doesNotMatch(hook,/localStorage|indexedDB/);
});
