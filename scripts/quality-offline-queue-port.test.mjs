import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../components/vinto/candidate-form-capture.tsx", import.meta.url), "utf8");

test("existing Quality candidate screen has an opt-in offline queue port", () => {
  assert.match(source, /offlineQuality\?:/);
  assert.match(source, /prepareCurrentQualityOfflineInput/);
  assert.match(source, /form\.context === "assignment"/);
  assert.match(source, /await offlineQuality\.queue\(prepared\.value\)/);
});
test("local success locks the form and disables a second submit", () => {
  assert.match(source, /setOfflineQueuedId\(queued\.captureId\)/);
  assert.match(source, /offlineQueuedId !== null/);
  assert.match(source, /if \(busy\.current \|\| saved \|\| offlineQueuedId\) return/);
  assert.match(source, /!saved && !offlineQueuedId && <SubmitBar/);
});
test("offline queue is not connected by default", () => {
  assert.match(source, /if \(!offlineQuality/);
  assert.match(source, /if \(!online\)/);
});
