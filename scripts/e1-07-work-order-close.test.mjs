import test from "node:test";
import assert from "node:assert/strict";
import { closeReadiness, safeExecutionMessage } from "../lib/vinto/line-execution.ts";

const order = (state = "in_progress") => ({
    id: "ot-1", status: state, baseline: { lines: [
        { id: "id-1", line_code: "L1", machine: { code: "MP1" } },
        { id: "id-2", line_code: "L2", machine: { code: "MP3" } },
    ] },
});
const item = (n, status, machine) => ({
    baseline_line_id: "id-" + n, line_code: "L" + n, machine_code: machine, status,
    current_assignment_id: null, started_at: null, started_by: null,
    finished_at: null, finished_by: null,
});
const projection = (lines, id = "ot-1") => ({ work_order_id: id, lines });

test("only all finished original baseline lines can offer Close OT", () => {
    const complete = closeReadiness(order(), projection([
        item(1, "finished", "MP1"), item(2, "finished", "MP3"),
    ]));
    assert.deepEqual(complete, { total: 2, finished: 2, canClose: true, pending: [] });
    assert.equal(closeReadiness(order("published"), projection([
        item(1, "finished", "MP1"), item(2, "finished", "MP3"),
    ])).canClose, false);
    assert.equal(closeReadiness(order("closed"), projection([
        item(1, "finished", "MP1"), item(2, "finished", "MP3"),
    ])).canClose, false);
});

test("partial/active/planned/no execution data never enables Close OT", () => {
    for (const state of ["planned", "enabled", "in_production", "requires_review"]) {
        const check = closeReadiness(order(), projection([
            item(1, "finished", "MP1"), item(2, state, "MP3"),
        ]));
        assert.equal(check.canClose, false, state);
        assert.deepEqual(check.pending, ["L2"]);
    }
    assert.equal(closeReadiness(order(), null).canClose, false);
    assert.equal(closeReadiness(order(), projection([item(1, "finished", "MP1")])).canClose, false);
    assert.equal(closeReadiness(order(), projection([
        item(1, "finished", "MP1"), item(2, "finished", "MP3"),
    ], "other-ot")).canClose, false);
});

test("mismatched machine, duplicate or extra data never enables close", () => {
    const mismatched = closeReadiness(order(), projection([
        item(1, "finished", "MP3"), item(2, "finished", "MP3"),
    ]));
    assert.equal(mismatched.canClose, false);
    assert.deepEqual(mismatched.pending, ["L1"]);
    const duplicated = closeReadiness(order(), projection([
        item(1, "finished", "MP1"), item(1, "finished", "MP1"),
    ]));
    assert.equal(duplicated.canClose, false);
    const extra = closeReadiness(order(), projection([
        item(1, "finished", "MP1"), item(2, "finished", "MP3"), item(3, "finished", "MP3"),
    ]));
    assert.equal(extra.canClose, false);
});

test("quantity deficit has no effect on completion readiness", () => {
    const completed = order();
    completed.baseline.lines[0].quantity = 120;
    completed.baseline.lines[1].quantity = 550;
    assert.equal(closeReadiness(completed, projection([
        item(1, "finished", "MP1"), item(2, "finished", "MP3"),
    ])).canClose, true);
});

test("server close conflict has a user-facing message", () => {
    assert.match(safeExecutionMessage("WORK_ORDER_CLOSE_PENDING_LINES", "fallback"), /líneas/);
    assert.match(safeExecutionMessage("WORK_ORDER_CLOSE_INVALID_STATE", "fallback"), /OT/);
    assert.equal(safeExecutionMessage("UNRELATED", "fallback"), "fallback");
});
