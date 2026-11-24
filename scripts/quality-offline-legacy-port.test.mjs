import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = path => readFileSync(new URL("../" + path, import.meta.url), "utf8");
const bridge = read("lib/vinto/quality-offline-legacy-bridge.ts");

test("P1-19 and P1-20 keep their existing validators", () => {
  assert.match(bridge, /normalizeHumidityDraft\(form\.draft\)/);
  assert.match(bridge, /normalizePhysicalDraft\(form\.draft\)/);
  assert.match(bridge, /authority_context_missing/);
  assert.match(bridge, /bobbin_context/);
});
for (const [code, path] of [
  ["Q19_FORM_CODE", "components/vinto/quality-humidity-capture.tsx"],
  ["Q20_FORM_CODE", "components/vinto/quality-physical-capture.tsx"],
]) {
  test(path + " does not queue without an explicit secure provider", () => {
    const source = read(path);
    assert.match(source, new RegExp("prepareLegacyQualityOfflineCapture\\(\\{formCode: " + code));
    assert.match(source, /if \(!offlineQuality \|\| attempt\)/);
    assert.match(source, /setOfflineQueuedId\(queued\.captureId\)/);
    assert.match(source, /offlineQueuedId !== null/);
  });
}
