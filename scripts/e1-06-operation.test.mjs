// E1-06 deterministic contract tests: Node --test, no browser or network.
import assert from "node:assert/strict";
import test from "node:test";

import { parseMachineExecution, isStartedAssignment, selectedContextAllowed,
         executionStatus, operationBlockedMessage } from "../lib/vinto/machine-execution.ts";
import { bobbinRejectionFor } from "../lib/vinto/bobbins.ts";
import { rejectionFor } from "../lib/vinto/capture-core.ts";

const item = (assignment_id, status) => ({ assignment_id, status });
const snapshot = (...assignments) => ({ line_execution: true, assignments });
const legacy = { line_execution: false, assignments: [] };
const active = (id, stale = false) => ({ kind: "single", active: { stale, assignment: id ? { id } : null } });
const multiple = (entries) => ({ kind: "multiple", lines: { items: entries.map(([id, stale]) => ({ assignment: { id }, stale })) } });

test("parse machine projection, reject unknown statuses, mismatched flags and ambiguity", () => {
  const valid = snapshot(item("a", "enabled"), item("b", "in_production"));
  assert.deepEqual(parseMachineExecution(valid), valid);
  assert.deepEqual(parseMachineExecution(legacy), legacy);
  for (const bad of [
    null, {}, [], { line_execution: "true", assignments: [] },
    { line_execution: false, assignments: [item("x", "enabled")] },
    { line_execution: true, assignments: "x" },
    snapshot(item("a", "active")), snapshot(item("a", "enabled"), item("a", "in_production")),
    snapshot({ assignment_id: "", status: "enabled" }),
    snapshot({ assignment_id: 77, status: "enabled" }),
  ]) assert.equal(parseMachineExecution(bad), null);
});

test("enabled assignment is not producing, even if shift is active", () => {
  const state = snapshot(item("one", "enabled"), item("two", "in_production"));
  assert.equal(isStartedAssignment(state, "one"), false);
  assert.equal(isStartedAssignment(state, "two"), true);
  assert.equal(isStartedAssignment(state, "missing"), false);
  assert.equal(executionStatus(state, "one"), "enabled");
  assert.equal(executionStatus(state, "missing"), null);
  assert.match(operationBlockedMessage(state, "one"), /Supervisión/);
  assert.equal(operationBlockedMessage(state, "two"), "");
});

test("only assigned, unexpired, in_production line is capturable", () => {
  const state = snapshot(item("one", "in_production"), item("two", "enabled"));
  assert.equal(selectedContextAllowed(state, active("one"), "one"), true);
  assert.equal(selectedContextAllowed(state, active("one", true), "one"), false);
  assert.equal(selectedContextAllowed(state, active("two"), "two"), false);
  assert.equal(selectedContextAllowed(state, active("one"), "two"), false);
  assert.equal(selectedContextAllowed(state, multiple([["one", false], ["two", false]]), "one"), true);
  assert.equal(selectedContextAllowed(state, multiple([["one", true], ["two", false]]), "one"), false);
  assert.equal(selectedContextAllowed(state, multiple([["one", false], ["two", false]]), "two"), false);
  assert.equal(selectedContextAllowed(state, multiple([["one", false]]), null), false);
});

test("legacy flag OFF deliberately preserves original current-shift behavior", () => {
  assert.equal(isStartedAssignment(legacy, "any"), true);
  assert.equal(selectedContextAllowed(legacy, active("one", false), "one"), true);
  assert.equal(operationBlockedMessage(legacy, "one"), "");
});

test("missing state and finished state fail closed with clear operator messages", () => {
  const state = snapshot(item("one", "finished"), item("two", "requires_review"));
  assert.match(operationBlockedMessage(state, "one"), /terminó/);
  assert.match(operationBlockedMessage(state, "two"), /revisión/);
  assert.match(operationBlockedMessage(state, "missing"), /verificar/);
  assert.match(operationBlockedMessage(state, null), /Selecciona/);
});

test("LINE_NOT_IN_PRODUCTION refreshes F3/F6 screen like stale assignment", () => {
  assert.equal(bobbinRejectionFor(409, "LINE_NOT_IN_PRODUCTION")?.reason, "line_not_producing");
  assert.equal(rejectionFor(409, "LINE_NOT_IN_PRODUCTION")?.reason, "line_not_producing");
  assert.equal(bobbinRejectionFor(409, "ASSIGNMENT_STALE")?.reason, "stale");
  assert.equal(rejectionFor(409, "ASSIGNMENT_NOT_ACTIVE")?.reason, "not_active");
});
