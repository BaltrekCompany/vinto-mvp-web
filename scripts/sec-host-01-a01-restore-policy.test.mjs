import test from "node:test";
import assert from "node:assert/strict";
import { selectRestorePlan, startGatesSatisfied } from "./sec-host-01-a01-restore-policy.mjs";

const safe = {
 serverVersionNum: 170012,
 setting: "off",
 context: "superuser-backend",
 vartype: "bool",
 source: "default",
 sourcefileKind: "none",
 pendingRestart: false,
};
test("missing or unsafe baseline always denies rollback plan", () => {
 for (const override of [
  { serverVersionNum: 180000 },
  { serverVersionNum: 130020 },
  { setting: "on" },
  { context: "postmaster" },
  { vartype: "string" },
  { pendingRestart: true },
  { source: "command line" },
  { source: "override" },
  { source: "configuration file", sourcefileKind: "unknown" },
  { source: "default", sourcefileKind: "auto" },
  { sourcefileKind: undefined },
 ]) {
  const output = selectRestorePlan({ ...safe, ...override });
  assert.equal(output.eligible, false, JSON.stringify(override));
 }
});

test("a new override must be RESET to recover the file/default baseline", () => {
 const def = selectRestorePlan(safe);
 assert.deepEqual(def, {
  eligible: true, restoreAction: "RESET_NEW_OVERRIDE", baseline: "off",
 });
 const file = selectRestorePlan({
  ...safe, source: "configuration file", sourcefileKind: "regular",
 });
 assert.equal(file.eligible, true);
 assert.equal(file.restoreAction, "RESET_NEW_OVERRIDE");
});

test("a pre-existing auto configuration requires restoration of its original value", () => {
 const oldAuto = selectRestorePlan({
  ...safe, source: "configuration file", sourcefileKind: "auto",
 });
 assert.equal(oldAuto.eligible, true);
 assert.equal(oldAuto.restoreAction, "RESTORE_PRIOR_AUTO_VALUE");
 assert.notEqual(oldAuto.restoreAction, "RESET_NEW_OVERRIDE");
});

test("no observation starts until independent new approval and every gate is met", () => {
 const gates = {
  specificWriteApproval: true,
  preflightPass: true,
  sourceFileKindVerified: true,
  logRouteVerified: true,
  sourceFidelityPlan: true,
  retentionAndAccessPlan: true,
  stopTimerInstalledAndTested: true,
  restoreModeRecorded: true,
  serviceContinuityBaseline: true,
 };
 assert.equal(startGatesSatisfied(gates), true);
 for (const key of Object.keys(gates)) {
  assert.equal(startGatesSatisfied({ ...gates, [key]: false }), false, key);
 }
 assert.equal(startGatesSatisfied({}), false);
});
