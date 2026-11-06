// E1-05 pure contract tests. Run with Node 22.18+.
import test from "node:test";
import assert from "node:assert/strict";

import { actionForLine, EXECUTION_LABELS, parseExecutionMutation, parseWorkOrderExecution, parseExecutionCapability, safeExecutionMessage } from "../lib/vinto/line-execution.ts";
import { NO_CAPABILITIES, capabilitiesOf, parseCapabilities, parseCapabilitiesResponse } from "../lib/vinto/work-order-capabilities.ts";

const line = (n, status = "enabled", machine = "MP3", assignment = "current-1") => ({
  baseline_line_id: "baseline-" + n, line_code: "L" + n, machine_code: machine,
  status, current_assignment_id: assignment,
  started_at: null, started_by: null, finished_at: null, finished_by: null,
});
const response = (lines) => ({ work_order_id: "order-1", lines });

test("new server capability is independent, historical multi-machine contract remains unchanged", () => {
  assert.equal(parseExecutionCapability({ line_execution: true }), true);
  assert.equal(parseExecutionCapability({ line_execution: false }), false);
  for (const value of [null, {}, { line_execution: "true" }, { line_execution: 1 }]) {
    assert.equal(parseExecutionCapability(value), null);
  }
  assert.deepEqual(parseCapabilitiesResponse({ multi_machine: true }), { multiMachine: true });
  assert.deepEqual(parseCapabilities({ multi_machine: true }), { multiMachine: true });
  assert.deepEqual(parseCapabilitiesResponse({ multi_machine: false }), NO_CAPABILITIES);
  assert.deepEqual(capabilitiesOf({ status: "ready", data: NO_CAPABILITIES }).capabilities, NO_CAPABILITIES);
  assert.deepEqual(capabilitiesOf({ status: "error" }).capabilities, NO_CAPABILITIES);
});

test("parse exactly the API line execution projection, no state invention", () => {
  const original = response([line(1), line(2, "in_production")]);
  assert.deepEqual(parseWorkOrderExecution(original), original);
  for (const broken of [
    null, [], {}, { lines: [] }, { work_order_id: "x", lines: null },
    response([{ ...line(1), status: "active" }]),
    response([{ ...line(1), current_assignment_id: 17 }]),
    response([{ ...line(1), finished_at: undefined }]),
    response([line(1), line(1)]),
    response([{ ...line(1), machine_code: "" }]),
  ]) assert.equal(parseWorkOrderExecution(broken), null);
  assert.equal(EXECUTION_LABELS.in_production, "En producción");
});

test("only enabled with current assignment, in_progress OT and no producing competitor can start", () => {
  const l1 = line(1), l2 = line(2);
  assert.deepEqual(actionForLine(l1, "in_progress", [l1, l2]), { canStart: true, canFinish: false, reason: null });
  assert.equal(actionForLine(l1, "published", [l1, l2]).canStart, false);
  assert.equal(actionForLine(l1, "closed", [l1, l2]).canStart, false);
  assert.equal(actionForLine({ ...l1, current_assignment_id: null }, "in_progress", [l1]).canStart, false);
  const busy = line(2, "in_production");
  assert.equal(actionForLine(l1, "in_progress", [l1, busy]).canStart, false);
  assert.match(actionForLine(l1, "in_progress", [l1, busy]).reason, /L2/);
  assert.equal(actionForLine(l1, "in_progress", [l1, line(2, "in_production", "MP1")]).canStart, true);
  assert.equal(actionForLine(line(1, "planned"), "in_progress", [l1]).canStart, false);
  assert.equal(actionForLine(line(1, "requires_review"), "in_progress", [l1]).canStart, false);
});

test("finish is available only to an in_production line, no text reason required", () => {
  const active = line(1, "in_production", "MP3", null);
  assert.equal(actionForLine(active, "in_progress", [active]).canFinish, true);
  assert.equal(actionForLine(line(1, "enabled"), "in_progress", []).canFinish, false);
  assert.equal(actionForLine(line(1, "finished"), "in_progress", []).canFinish, false);
});

test("mutation parser validates backend response separately from read projection", () => {
  const raw = {
    ...line(1, "in_production"),
    work_order_id: "order-1",
  };
  const { current_assignment_id: assignment, ...expected } = raw;
  assert.equal(assignment, "current-1");
  assert.deepEqual(parseExecutionMutation(expected), expected);
  assert.equal(parseExecutionMutation({ ...expected, status: "active" }), null);
  assert.equal(parseExecutionMutation({ ...expected, work_order_id: undefined }), null);
});

test("backend error codes produce safe and actionable messages", () => {
  assert.match(safeExecutionMessage("LINE_MACHINE_IN_PRODUCTION", "bad"), /máquina/);
  assert.match(safeExecutionMessage("LINE_EXECUTION_DISABLED", "bad"), /servidor/);
  assert.equal(safeExecutionMessage("UNKNOWN", "Error general"), "Error general");
});
