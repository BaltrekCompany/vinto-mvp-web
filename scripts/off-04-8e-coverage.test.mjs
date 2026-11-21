import assert from "node:assert/strict";
import { test } from "node:test";
import { CAPTURE_SCOPE_TTL_HOURS, MAX_OFFLINE_HOURS, RENEW_WITHIN_HOURS,
  evaluateCaptureScopeCoverage, coverageDisplay } from "../lib/vinto/offline-capture-coverage.ts";
const H = 3_600_000;
const T = Date.UTC(2026, 10, 20, 17);
test("8h shift and 24h credential with proactive renewal at 12h", () => {
  assert.equal(MAX_OFFLINE_HOURS, 8);
  assert.equal(CAPTURE_SCOPE_TTL_HOURS, 24);
  assert.equal(RENEW_WITHIN_HOURS, 12);
  const first = evaluateCaptureScopeCoverage(T + 24 * H, T);
  assert.deepEqual(first, { status: "ready", coversFullShift: true, shouldRenewOnline: false, maySaveDraft: true });
  const approaching = evaluateCaptureScopeCoverage(T + 12 * H, T);
  assert.deepEqual(approaching, { status: "refresh_soon", coversFullShift: true, shouldRenewOnline: true, maySaveDraft: true });
  const insufficient = evaluateCaptureScopeCoverage(T + 8 * H, T);
  assert.equal(insufficient.status, "insufficient");
  assert.equal(insufficient.coversFullShift, false);
  assert.equal(insufficient.shouldRenewOnline, true);
});
test("missing or expired auth never erases local draft and cannot claim eight-hour readiness", () => {
  for (const expiry of [null, T - 1000, T, NaN]) {
    const state = evaluateCaptureScopeCoverage(expiry, T);
    assert.equal(state.maySaveDraft, true);
    assert.equal(state.coversFullShift, false);
    assert.equal(state.shouldRenewOnline, true);
    assert.notEqual(coverageDisplay(state, false, false), "ready");
  }
  assert.equal(coverageDisplay(evaluateCaptureScopeCoverage(null, T), true, true), "renewing");
  assert.equal(coverageDisplay(evaluateCaptureScopeCoverage(null, T), false, false), "online_needed");
});
test("valid but 9h remaining covers the full shift; no required operator button", () => {
  const state = evaluateCaptureScopeCoverage(T + 9 * H, T);
  assert.equal(state.coversFullShift, true);
  assert.equal(state.shouldRenewOnline, true);
  assert.equal(coverageDisplay(state, false, false), "ready");
});
test("clock validation is fail closed", () => {
  assert.throws(() => evaluateCaptureScopeCoverage(T + 24 * H, NaN), TypeError);
});
