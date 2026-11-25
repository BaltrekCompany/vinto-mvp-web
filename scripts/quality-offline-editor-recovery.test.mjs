import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../components/vinto/candidate-form-capture.tsx", import.meta.url), "utf8");
test("existing candidate editor recovers prepared encrypted draft only when offline", () => {
  assert.match(source, /offlineQuality\.draft!\.recover\(\)/);
  assert.match(source, /setDraft\(\{ \.\.\.initialDraft\(\), \.\.\.savedDraft\.values \}/);
  assert.match(source, /online \|\| !offlineQuality\?\.draft \|\| attempt/);
});
test("unprepared, frozen, unreadable or unresolved offline drafts remain blocked", () => {
  assert.match(source, /setOfflineRecovery\("loading"\)/);
  assert.match(source, /setOfflineRecovery\("error"\)/);
  assert.match(source, /setOfflineFrozen\(true\)/);
  assert.match(source, /offlineFrozen \|\| \(!online/);
  assert.match(source, /!offlineHydrated \|\| offlineRecovery !== "ready"/);
  assert.match(source, /busy\.current \|\| saved \|\| offlineQueuedId \|\| recoveryBlocked/);
  assert.match(source, /cancelled \|\| !live\(\)/);
});
