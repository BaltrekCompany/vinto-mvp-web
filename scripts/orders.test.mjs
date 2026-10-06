// node --test scripts/orders.test.mjs
// Pruebas puras de lib/vinto/orders.ts: validación de las respuestas centrales, contexto de captura y payloads.
import assert from "node:assert/strict";
import test from "node:test";

import {
  ASSIGNMENT_LABELS, CONTEXT_MESSAGES, FAILURE_MESSAGES, WORK_ORDER_LABELS, activatePayload, addLinePayload, captureContextOf, contextFromActive,
  createWorkOrderPayload, failureKindFromStatus, failureMessage, parseActivation, parseActive, parseAssignment, parseAssignmentList, parseLineDraft,
  parseWorkOrder, parseWorkOrderList, toDisplayAssignment, toDisplayOt, usesCentralAssignment,
} from "../lib/vinto/orders.ts";

const line = (overrides = {}) => ({
  id: "11111111-1111-4111-8111-111111111111", line_code: "L1", pv_reference: "PV-001",
  article: { code: "M1-1024", description: "M1-BOBINA PH G-22 CR-25% R-540640" }, quantity: 100, unit: "KG", due_date: "2026-10-30", ...overrides,
});
const order = (overrides = {}) => ({
  id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001", status: "draft", machine: { code: "MP1", name: "MP1" },
  baseline: { id: "33333333-3333-4333-8333-333333333333", version_number: 1, published_at: null, lines: [line()] }, ...overrides,
});
const assignment = (overrides = {}) => ({
  id: "44444444-4444-4444-8444-444444444444", status: "active", operating_date: "2026-10-06", created_at: "2026-10-06T16:00:00Z", finished_at: null,
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, work_order: { id: order().id, number: "OT-2026-0001" },
  operational: { version_number: 2 }, line: line({ id: "55555555-5555-4555-8555-555555555555" }), assigned_by: { id: "66666666-6666-4666-8666-666666666666", display_name: "Supervisión DEV" }, ...overrides,
});
const active = (stale, a = assignment()) => ({ assignment: a, current_shift: { code: "DIA", name: "Día", operating_date: "2026-10-06" }, stale });

test("parseWorkOrder accepts the backend shape", () => {
  const parsed = parseWorkOrder(order());
  assert.equal(parsed.number, "OT-2026-0001");
  assert.equal(parsed.baseline.lines[0].article.code, "M1-1024");
  assert.deepEqual(parseWorkOrder(order({ status: "published", baseline: { ...order().baseline, published_at: "2026-10-06T16:00:00Z" } })).baseline.published_at, "2026-10-06T16:00:00Z");
  for (const status of ["draft", "published", "in_progress", "closed"]) assert.ok(parseWorkOrder(order({ status })), status);
});

test("parseWorkOrder / parseWorkOrderList reject malformed responses instead of trusting a cast", () => {
  const bad = [
    null, undefined, "x", 3, [], {}, order({ id: "" }), order({ number: 5 }), order({ status: "Publicada" }), order({ status: "weird" }),
    order({ machine: null }), order({ machine: { code: "MP1" } }), order({ baseline: null }), order({ baseline: { ...order().baseline, lines: "nope" } }),
    order({ baseline: { ...order().baseline, version_number: "1" } }), order({ baseline: { ...order().baseline, published_at: 12 } }),
    order({ baseline: { ...order().baseline, lines: [line({ quantity: "100" })] } }), order({ baseline: { ...order().baseline, lines: [line({ quantity: 0 })] } }),
    order({ baseline: { ...order().baseline, lines: [line({ article: null })] } }), order({ baseline: { ...order().baseline, lines: [line({ line_code: "" })] } }),
  ];
  for (const payload of bad) assert.equal(parseWorkOrder(payload), null, JSON.stringify(payload));
  assert.equal(parseWorkOrderList({ not: "a list" }), null);
  assert.equal(parseWorkOrderList([order(), { broken: true }]), null);
  assert.deepEqual(parseWorkOrderList([]), []);
  assert.equal(parseWorkOrderList([order(), order({ id: "x2", number: "OT-2026-0002" })]).length, 2);
});

test("parseWorkOrder never exposes unknown fields", () => {
  const parsed = parseWorkOrder({ ...order(), created_by: "x", token: "y" });
  assert.equal("created_by" in parsed, false);
  assert.equal("token" in parsed, false);
});

test("backend status maps to the visual labels (presentation only)", () => {
  assert.deepEqual(WORK_ORDER_LABELS, { draft: "Borrador", published: "Publicada", in_progress: "En ejecución", closed: "Cerrada" });
  assert.deepEqual(ASSIGNMENT_LABELS, { active: "Activa", finished: "Finalizada" });
});

test("parseAssignment accepts the backend shape and rejects malformed ones", () => {
  const parsed = parseAssignment(assignment());
  assert.equal(parsed.work_order.number, "OT-2026-0001");
  assert.equal(parsed.shift.name, "Día");
  assert.equal(parsed.assigned_by.display_name, "Supervisión DEV");
  assert.ok(parseAssignment(assignment({ status: "finished", finished_at: "2026-10-06T20:00:00Z" })));
  const bad = [null, {}, assignment({ status: "Activa" }), assignment({ shift: null }), assignment({ operational: {} }), assignment({ line: { id: "x" } }),
    assignment({ assigned_by: { id: "x" } }), assignment({ operating_date: 20261006 }), assignment({ finished_at: 5 }), assignment({ work_order: { id: "x" } })];
  for (const payload of bad) assert.equal(parseAssignment(payload), null, JSON.stringify(payload));
  assert.equal(parseAssignmentList([assignment(), {}]), null);
  assert.equal(parseAssignmentList(assignment()), null);
  assert.deepEqual(parseAssignmentList([]), []);
});

test("parseActive accepts assignment|null, current_shift and stale true/false/null", () => {
  for (const stale of [true, false, null]) assert.equal(parseActive(active(stale)).stale, stale);
  assert.deepEqual(parseActive({ assignment: null, current_shift: null, stale: null }), { assignment: null, current_shift: null, stale: null });
  assert.equal(parseActive({ assignment: null, current_shift: { code: "DIA", name: "Día", operating_date: "2026-10-06" }, stale: null }).current_shift.code, "DIA");
  for (const bad of [null, {}, { assignment: {}, current_shift: null, stale: false }, { assignment: null, current_shift: null }, { assignment: null, current_shift: null, stale: "no" },
    { assignment: null, current_shift: { code: "DIA" }, stale: null }]) assert.equal(parseActive(bad), null, JSON.stringify(bad));
});

test("parseActivation", () => {
  const ok = { created: true, already_active: false, finished_assignment_id: null, assignment: assignment() };
  assert.equal(parseActivation(ok).created, true);
  assert.equal(parseActivation({ ...ok, finished_assignment_id: "abc" }).finished_assignment_id, "abc");
  for (const bad of [null, {}, { ...ok, created: "yes" }, { ...ok, assignment: {} }, { ...ok, finished_assignment_id: 3 }]) assert.equal(parseActivation(bad), null);
});

test("stale === false is the only state that gives a production capture context", () => {
  const check = contextFromActive(active(false));
  assert.equal(check.ok, true);
  assert.deepEqual(check.context, {
    assignmentId: assignment().id, workOrderId: order().id, otId: "OT-2026-0001", lineId: "L1", pv: "PV-001", productCode: "M1-1024",
    productName: "M1-BOBINA PH G-22 CR-25% R-540640", machine: "MP1", shift: "Día", date: "2026-10-06",
  });
});

test("stale true blocks the context and keeps the assignment for display", () => {
  const check = contextFromActive(active(true));
  assert.equal(check.ok, false);
  assert.equal(check.reason, "stale");
  assert.equal(check.assignment.id, assignment().id);
  assert.match(CONTEXT_MESSAGES.stale, /otro turno o fecha operativa.*Supervisión debe reactivarla/);
});

test("stale null (shift not resolvable) blocks the context", () => {
  const check = contextFromActive(active(null));
  assert.equal(check.ok, false);
  assert.equal(check.reason, "unresolvable");
  assert.ok(check.assignment);
});

test("no assignment blocks the context", () => {
  for (const value of [null, undefined, { assignment: null, current_shift: null, stale: null }, { assignment: null, current_shift: null, stale: false }]) {
    const check = contextFromActive(value);
    assert.deepEqual([check.ok, check.reason, check.assignment], [false, "none", null]);
  }
  assert.equal(CONTEXT_MESSAGES.none, "Se requiere una asignación activa y vigente.");
});

test("only Bobinas production execution uses the central assignment", () => {
  assert.equal(usesCentralAssignment("Bobinas", "ejecucion"), true);
  for (const view of ["programacion", "seguimiento", "ejecucion"]) assert.equal(usesCentralAssignment("Calidad", view), false, `Calidad/${view}`);
  for (const view of ["programacion", "seguimiento"]) assert.equal(usesCentralAssignment("Bobinas", view), false, `Bobinas/${view}`);
  for (const front of ["Rebobinado", "Conversión", "", "bobinas"]) assert.equal(usesCentralAssignment(front, "ejecucion"), false, front);
});

test("Bobinas production: a current assignment gives context, a stale one does not", () => {
  assert.equal(contextFromActive(active(false)).ok, true);
  assert.equal(contextFromActive(active(true)).ok, false);
  assert.equal(contextFromActive(active(null)).ok, false);
});

test("the assignment states never decide anything for Calidad (the central flow is not consulted)", () => {
  const states = [null, { assignment: null, current_shift: null, stale: null }, active(false), active(true), active(null)];
  // Changing MP1's assignment changes the production context only; Calidad's availability is not a function of it.
  const production = states.map((state) => contextFromActive(state).ok);
  assert.deepEqual(production, [false, false, true, false, false]);
  assert.deepEqual(states.map(() => usesCentralAssignment("Calidad", "ejecucion")), [false, false, false, false, false]);
});

test("capture context comes from the central assignment, never from a local clock", () => {
  const context = captureContextOf(assignment({ shift: { code: "NOCHE", name: "Noche" }, operating_date: "2026-10-05" }));
  assert.equal(context.shift, "Noche");
  assert.equal(context.date, "2026-10-05");
  assert.match(context.otId, /^OT-\d{4}-\d{4}$/);
});

test("create OT payload carries only the contract fields (no number, line_code, unit, description or ids)", () => {
  const payload = createWorkOrderPayload("MP1", { pvReference: "  PV-001 ", articleCode: "M1-1024", quantity: 100, dueDate: "2026-10-30" });
  assert.deepEqual(payload, { machine_code: "MP1", lines: [{ pv_reference: "PV-001", article_code: "M1-1024", quantity: 100, due_date: "2026-10-30" }] });
  assert.deepEqual(Object.keys(payload).sort(), ["lines", "machine_code"]);
  assert.deepEqual(Object.keys(payload.lines[0]).sort(), ["article_code", "due_date", "pv_reference", "quantity"]);
  const text = JSON.stringify(payload);
  for (const forbidden of ["number", "line_code", "unit", "description", "id", "status", "Borrador", "Publicada"]) assert.equal(text.includes(`"${forbidden}"`), false, forbidden);
});

test("add-line payload has only the four line fields", () => {
  assert.deepEqual(addLinePayload({ pvReference: "PV-2", articleCode: "M1-1031", quantity: 7.5, dueDate: "2026-11-01" }),
    { pv_reference: "PV-2", article_code: "M1-1031", quantity: 7.5, due_date: "2026-11-01" });
});

test("activate payload only has work_order_id and baseline_line_id", () => {
  const payload = activatePayload("wo-id", "line-id");
  assert.deepEqual(payload, { work_order_id: "wo-id", baseline_line_id: "line-id" });
  assert.deepEqual(Object.keys(payload).sort(), ["baseline_line_id", "work_order_id"]);
  for (const forbidden of ["machine", "machine_code", "shift", "shift_schedule_id", "operating_date", "operational_line_id", "assigned_by"]) assert.equal(forbidden in payload, false);
});

test("the form draft is validated before calling the backend", () => {
  assert.deepEqual(parseLineDraft({ pv: "PV-1", code: "M1-1024", qty: "12.5", date: "2026-10-30" }), { pvReference: "PV-1", articleCode: "M1-1024", quantity: 12.5, dueDate: "2026-10-30" });
  for (const bad of [{ pv: "", code: "A", qty: "1", date: "2026-10-30" }, { pv: "  ", code: "A", qty: "1", date: "2026-10-30" }, { pv: "P", code: "", qty: "1", date: "2026-10-30" },
    { pv: "P", code: "A", qty: "", date: "2026-10-30" }, { pv: "P", code: "A", qty: "0", date: "2026-10-30" }, { pv: "P", code: "A", qty: "-3", date: "2026-10-30" },
    { pv: "P", code: "A", qty: "abc", date: "2026-10-30" }, { pv: "P", code: "A", qty: "1", date: "" }]) assert.equal(parseLineDraft(bad), null, JSON.stringify(bad));
});

test("HTTP statuses map to failure kinds and safe messages", () => {
  assert.deepEqual([401, 403, 404, 409, 422, 503, 500, 502, 0, 400].map(failureKindFromStatus),
    ["session", "forbidden", "not_found", "conflict", "invalid", "unavailable", "unavailable", "unavailable", "unavailable", "unavailable"]);
  assert.equal(failureMessage("forbidden"), "No tienes permisos para esta acción.");
  assert.equal(failureMessage("not_found"), "El registro ya no existe.");
  assert.equal(failureMessage("conflict"), "El estado cambió. Actualiza y vuelve a intentar.");
  assert.equal(failureMessage("invalid"), "Los datos enviados no son válidos.");
  assert.equal(failureMessage("unavailable"), "El servidor no está disponible.");
  for (const message of Object.values(FAILURE_MESSAGES)) assert.doesNotMatch(message, /SQL|Traceback|\{|\}|psycopg/i);
});

test("central data adapts to the existing visual shapes without inventing fields", () => {
  const display = toDisplayOt(parseWorkOrder(order({ status: "in_progress" })));
  assert.deepEqual(display, { id: "OT-2026-0001", sector: "Bobinas", machine: "MP1", status: "En ejecución", baseline: 1,
    lines: [{ id: "L1", pv: "PV-001", productCode: "M1-1024", productName: "M1-BOBINA PH G-22 CR-25% R-540640", quantity: 100, unit: "KG", dueDate: "2026-10-30" }] });
  const shown = toDisplayAssignment(parseAssignment(assignment({ status: "finished", finished_at: "2026-10-06T20:00:00Z" })));
  assert.deepEqual(shown, { id: assignment().id, ot: "OT-2026-0001", line: "L1", machine: "MP1", shift: "Día", date: "2026-10-06", status: "Finalizada", by: "Supervisión DEV" });
  assert.equal(toDisplayOt(parseWorkOrder(order())).id.startsWith("OT-PRUEBA"), false);
});
