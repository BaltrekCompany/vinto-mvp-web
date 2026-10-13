// node --test scripts/capture-core.test.mjs
// Núcleo común de las capturas centrales (M2-B1): envelope, parsers genéricos, ruta de lectura y flujo de envío con reconciliación para un formulario
// DISTINTO de F6. Verifica que la generalización no hace que el cliente acepte respuestas incorrectas y que F6 conserva sus validaciones propias.
import assert from "node:assert/strict";
import test from "node:test";

import {
  SUBMIT_MESSAGES, capturesListPath, isRec, parseCaptureListOf, parseCaptureOf, parseSubmissionOf, reconcileOf, rejectionFor, submitAttemptOf, submitMessage,
} from "../lib/vinto/capture-core.ts";
import { parseCapture, parseCaptureList, parseSubmission } from "../lib/vinto/captures.ts";

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444";
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
// Un formulario ficticio de prueba (NO es P1-10 ni ningún formulario real): un texto obligatorio y una nota opcional.
const parseDemo = (v) => (isRec(v) && typeof v.codigo === "string" && v.codigo !== "" && (v.nota === undefined || typeof v.nota === "string") ? { codigo: v.codigo, ...(v.nota === undefined ? {} : { nota: v.nota }) } : null);
const ID = "11111111-1111-4111-8111-111111111111";
const F6_VALUES = { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50" };

test("the generic envelope parser delegates `values` to the form's own strict parser", () => {
  const ok = parseCaptureOf(envelope(ID, "DEMO-1", { codigo: "A", nota: "x", extra: 1 }), parseDemo);
  assert.deepEqual(ok.values, { codigo: "A", nota: "x" }); // unknown value keys are dropped by the form parser
  assert.equal(ok.form.code, "DEMO-1");
  for (const bad of [{}, { codigo: "" }, { codigo: 5 }, { codigo: "A", nota: 3 }, null, "x", []]) assert.equal(parseCaptureOf(envelope(ID, "DEMO-1", bad), parseDemo), null, JSON.stringify(bad));
});

test("an expected form code rejects a capture of another form (a new parser should always pass it)", () => {
  assert.notEqual(parseCaptureOf(envelope(ID, "DEMO-1", { codigo: "A" }), parseDemo, "DEMO-1"), null);
  assert.equal(parseCaptureOf(envelope(ID, "VINTO-P1-06", { codigo: "A" }), parseDemo, "DEMO-1"), null);
  assert.equal(parseCaptureOf(envelope(ID, "demo-1", { codigo: "A" }), parseDemo, "DEMO-1"), null); // exact match
});

test("the envelope still requires every context field the backend guarantees", () => {
  const good = envelope(ID, "DEMO-1", { codigo: "A" });
  const broken = [
    (c) => { delete c.id; }, (c) => { c.status = ""; }, (c) => { c.revision = 1.5; }, (c) => { c.submitted_at = undefined; }, (c) => { c.operating_date = ""; },
    (c) => { c.machine = { code: "", name: "x" }; }, (c) => { c.shift = null; }, (c) => { delete c.assignment; }, (c) => { c.work_order = { id: "x" }; },
    (c) => { c.line.article = null; }, (c) => { c.form = { code: "DEMO-1" }; },
  ];
  for (const [index, mutate] of broken.entries()) {
    const copy = JSON.parse(JSON.stringify(good)); mutate(copy);
    assert.equal(parseCaptureOf(copy, parseDemo), null, `mutation ${index}`);
  }
});

test("submission and list parsers reject a single malformed element", () => {
  const one = (id) => envelope(id, "DEMO-1", { codigo: "A" });
  const parse = (v) => parseCaptureOf(v, parseDemo);
  assert.equal(parseSubmissionOf({ created: true, already_submitted: false, capture: one(ID) }, parse).capture.id, ID);
  assert.equal(parseSubmissionOf({ created: "yes", already_submitted: false, capture: one(ID) }, parse), null);
  assert.equal(parseSubmissionOf({ created: true, already_submitted: false, capture: { ...one(ID), values: { codigo: 5 } } }, parse), null);
  assert.equal(parseCaptureListOf([one(ID), one(ID)], parse).length, 2);
  assert.equal(parseCaptureListOf([one(ID), { nope: 1 }], parse), null);
  assert.equal(parseCaptureListOf({}, parse), null);
});

test("F6 keeps its own strict value validation after the extraction", () => {
  assert.notEqual(parseCapture(envelope(ID, "VINTO-P1-06", F6_VALUES)), null);
  for (const bad of [{ ...F6_VALUES, cantidad_fardos: "2" }, { ...F6_VALUES, cantidad_fardos: 1.5 }, { ...F6_VALUES, punto_merma: "" }, { ...F6_VALUES, peso_kg: "1e3" },
    { ...F6_VALUES, peso_kg: null }, { ...F6_VALUES, observaciones: 5 }, { codigo: "A" }]) assert.equal(parseCapture(envelope(ID, "VINTO-P1-06", bad)), null, JSON.stringify(bad));
  assert.equal(parseCapture(envelope(ID, "VINTO-P1-06", { ...F6_VALUES, peso_kg: 125.5 })).values.peso_kg, "125.5"); // a finite JSON number is normalized to text
  assert.equal(parseSubmission({ created: true, already_submitted: false, capture: envelope(ID, "VINTO-P1-06", { codigo: "A" }) }), null); // another form's values never pass as F6
  assert.equal(parseCaptureList([envelope(ID, "VINTO-P1-06", F6_VALUES), envelope(ID, "DEMO-1", { codigo: "A" })]), null);
});

test("the list path keeps the historic F6 URL unless a form code is given", () => {
  assert.equal(capturesListPath(), "/api/captures?limit=50");
  assert.equal(capturesListPath(10), "/api/captures?limit=10");
  assert.equal(capturesListPath(50, "VINTO-P1-06"), "/api/captures?limit=50&form_code=VINTO-P1-06");
  assert.equal(capturesListPath(5, "a&b=c d"), "/api/captures?limit=5&form_code=a%26b%3Dc%20d"); // the code is always encoded
});

// ---- flujo de envío genérico (otro formulario) ------------------------------------------------------------------------------

const attempt = { captureId: ID, payload: { capture_id: ID, form_code: "DEMO-1", values: { codigo: "A" } } };
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: { created, already_submitted: !created, capture: parseCaptureOf(envelope(ID, "DEMO-1", { codigo: "A" }), parseDemo) } });

test("generic submit: 201 and 200 are submitted, with the same messages as F6", async () => {
  const posted = [];
  const created = await submitAttemptOf(attempt, deps({ post: async (p) => (posted.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(posted[0], attempt.payload); // the exact immutable payload is sent
  assert.equal(submitMessage(created), SUBMIT_MESSAGES.created);
  const again = await submitAttemptOf(attempt, deps({ post: async () => okSubmission(false) }));
  assert.equal(submitMessage(again), SUBMIT_MESSAGES.already);
});

test("generic submit: 401 ends the session and definitive rejections never reconcile", async () => {
  assert.deepEqual(await submitAttemptOf(attempt, deps({ post: async () => ({ ok: false, kind: "unauthorized", status: 401 }) })), { kind: "session" });
  for (const [status, code, reason] of [[403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "UNSUPPORTED_FORM", "invalid"], [409, "ASSIGNMENT_STALE", "stale"],
    [409, "ASSIGNMENT_NOT_ACTIVE", "not_active"], [409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"], [409, "FORM_NOT_AVAILABLE", "conflict"]]) {
    const outcome = await submitAttemptOf(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
    assert.equal(outcome.kind, "rejected", `${status} ${code}`);
    assert.equal(outcome.reason, reason);
  }
});

test("generic submit: an uncertain POST reconciles with GET using the SAME capture id", async () => {
  const calls = [];
  const found = await submitAttemptOf(attempt, deps({
    post: async () => ({ ok: false, kind: "unavailable", status: 0 }),
    get: async (id) => (calls.push(id), { ok: true, status: 200, data: parseCaptureOf(envelope(ID, "DEMO-1", { codigo: "A" }), parseDemo) }),
  }));
  assert.deepEqual(calls, [ID]);
  assert.equal(found.kind, "submitted");
  assert.equal(found.reconciled, true);
  assert.equal((await reconcileOf(ID, deps({ post: async () => null, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await reconcileOf(ID, deps({ post: async () => null, get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  assert.deepEqual(await reconcileOf(ID, deps({ post: async () => null, get: async () => ({ ok: false, kind: "n", status: 401 }) })), { kind: "session" });
});

test("reconciliation never accepts a capture with a different id", async () => {
  const other = parseCaptureOf(envelope("33333333-3333-4333-8333-333333333333", "DEMO-1", { codigo: "A" }), parseDemo);
  const outcome = await reconcileOf(ID, deps({ post: async () => null, get: async () => ({ ok: true, status: 200, data: other }) }));
  assert.equal(outcome.kind, "uncertain");
});

test("rejectionFor stays unchanged: 5xx and network errors are not definitive", () => {
  for (const status of [0, 500, 502, 503, 504]) assert.equal(rejectionFor(status), null, String(status));
});
