import test from "node:test";
import assert from "node:assert/strict";
import {
    parseHandoffCapability, parseOpenHandoffs, parseReservedHandoff,
    parsePublishedHandoff, parseReassignedHandoff,
} from "../lib/vinto/handoff.ts";

const order = "426b24c7-8b81-47dc-afa1-557fe8b4a64f";
const h = "2cdc11ed-0476-4d00-a0fd-c666ac0b089e";
const oldA = "ccf806e4-4182-4b90-8490-58c470925f03";
const newA = "a350753a-ca92-4a3c-9940-6290c193974a";
const base = {
    handoff_id: h, work_order_id: order, work_order_number: "OT-2026-0032",
    line_code: "L1", machine_code: "MP1", status: "pending",
    expected_version: 2, published_version: null,
    prior_assignment_id: oldA, replacement_assignment_id: null,
    reason: "Motivo de prueba con al menos diez caracteres",
    created_at: "2026-11-08T21:20:00Z",
};

test("D2 capability only enables on a literal server boolean", () => {
    assert.equal(parseHandoffCapability({ enabled: true }), true);
    assert.equal(parseHandoffCapability({ enabled: false }), false);
    for (const bad of [{ enabled: "true" }, {}, [], null, { enabled: 1 }])
        assert.equal(parseHandoffCapability(bad), null);
});

test("D2 active pending reservation validates exact identifiers and state", () => {
    assert.deepEqual(parseOpenHandoffs([base]), [base]);
    assert.deepEqual(parseOpenHandoffs([]), []);
    assert.equal(parseOpenHandoffs([base, base]), null, "reject duplicate rows");
    assert.equal(parseOpenHandoffs([{ ...base, handoff_id: "wrong" }]), null);
});

test("D2 lifecycle requires compatible version and assignment pointers", () => {
    const published = { ...base, status: "published", published_version: 3 };
    const reassigned = { ...published, status: "reassigned", replacement_assignment_id: newA };
    assert.ok(parseOpenHandoffs([published, reassigned]) === null, "same handoff cannot appear twice");
    assert.deepEqual(parseOpenHandoffs([published]), [published]);
    assert.deepEqual(parseOpenHandoffs([reassigned]), [reassigned]);
    assert.equal(parseOpenHandoffs([{ ...base, status: "published" }]), null);
    assert.equal(parseOpenHandoffs([{ ...base, status: "reassigned" }]), null);
    assert.equal(parseOpenHandoffs([{ ...base, status: "acknowledged" }]), null);
    assert.equal(parseOpenHandoffs([{ ...base, expected_version: 1 }]), null);
});

test("D2 mutation responses fail closed for wrong lifecycle and identity", () => {
    assert.ok(parseReservedHandoff({ handoff_id: h, work_order_id: order, line_code: "L1", status: "pending" }));
    assert.ok(parseReservedHandoff({ handoff_id: h, work_order_id: order, line_code: "L1", status: "cancelled" }));
    assert.equal(parseReservedHandoff({ handoff_id: h, work_order_id: order, line_code: "L1", status: "published" }), null);
    assert.ok(parsePublishedHandoff({ handoff_id: h, work_order_id: order, line_code: "L1", version_number: 3, status: "published" }));
    assert.equal(parsePublishedHandoff({ handoff_id: h, work_order_id: order, line_code: "L1", version_number: 2, status: "reassigned" }), null);
    assert.ok(parseReassignedHandoff({
        handoff_id: h, work_order_id: order, status: "reassigned", version_number: 3,
        previous_assignment_id: oldA, replacement_assignment_id: newA,
    }));
    assert.equal(parseReassignedHandoff({
        handoff_id: h, work_order_id: order, status: "reassigned", version_number: 3,
        previous_assignment_id: oldA, replacement_assignment_id: oldA,
    }), null);
});
