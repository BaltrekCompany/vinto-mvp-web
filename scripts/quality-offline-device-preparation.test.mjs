import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = readFileSync(new URL("../lib/vinto/quality-offline-device-preparation.ts", import.meta.url), "utf8");
test("only a separately verified signed CAPTURE scope can prepare an operational draft", () => {
  assert.match(source, /await verifyCaptureBeforeEditor\(captureAuthority\)/);
  assert.match(source, /assertCaptureScope: verified\.assertCaptureScope/);
  assert.match(source, /assertPreparedCaptureScope: verified\.assertCaptureScope/);
  assert.match(source, /offline_quality_preparation_mismatch/);
  assert.match(source, /target\.formVersion !== context\.formVersion/);
  assert.match(source, /target\.scopeSnapshotId !== context\.scopeSnapshotId/);
});
test("preparation does not silently create an author, unlock an unknown vault or perform network writes", () => {
  assert.match(source, /key: CryptoKey/);
  assert.match(source, /identity: OfflineVaultIdentity/);
  assert.match(source, /createOperationalCaptureBindings/);
  assert.match(source, /createQualityOfflineDraftLifecycle/);
  assert.doesNotMatch(source, /\b(fetch|localStorage|indexedDB)\s*\(/);
});
