// node --test scripts/captures.test.mjs
// Pruebas puras de la captura central F6: device key, capture_id, payload, validación de respuestas, intento pendiente,
// reconciliación tras respuesta incierta y mensajes de error. La red se simula con funciones inyectadas.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  EMPTY_DRAFT, F6_FORM_CODE, F6_FORM_ID, PUNTO_MERMA_OPTIONS, SUBMIT_MESSAGES, TIPO_PRODUCTO_OPTIONS, buildPayload, createAttempt, isF6, isUuidV4, newCaptureId,
  normalizeDraft, parseCapture, parseCaptureList, parseSubmission, reconcile, rejectionFor, submitAttempt, submitMessage,
} from "../lib/vinto/captures.ts";
import { DEVICE_KEY_STORAGE, getDeviceKey, isUuid, resetDeviceKeyMemory } from "../lib/vinto/device.ts";

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444";
const DEVICE = "99999999-9999-4999-8999-999999999999";
const draft = (o = {}) => ({ ...EMPTY_DRAFT, cantidad_fardos: "2", punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50", observaciones: "Prueba F6 central", ...o });
const capture = (id, o = {}) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: "VINTO-P1-06", version_number: 1, name: "Registro de control de fardos" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } },
  values: { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50", observaciones: "x" }, ...o,
});
const store = (initial) => { const m = new Map(initial ? [[DEVICE_KEY_STORAGE, initial]] : []); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v), m }; };

test("a valid stored device key is kept", () => {
  resetDeviceKeyMemory();
  const s = store(DEVICE);
  assert.equal(getDeviceKey(s, () => assert.fail("must not generate")), DEVICE);
  assert.equal(getDeviceKey(s), DEVICE);
});

test("a missing or corrupt device key is replaced by a new UUID and then stays stable", () => {
  for (const bad of [null, "", "not-a-uuid", "1234", "99999999-9999-4999-8999-99999999999"]) {
    resetDeviceKeyMemory();
    const s = store(bad);
    const key = getDeviceKey(s);
    assert.ok(isUuid(key), String(bad));
    assert.equal(s.m.get(DEVICE_KEY_STORAGE), key);
    assert.equal(getDeviceKey(s), key);
  }
  resetDeviceKeyMemory();
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(getDeviceKey(blocked), getDeviceKey(blocked)); // en memoria: no genera una clave por envío
  resetDeviceKeyMemory();
});

test("the device key store holds only the UUID", () => {
  resetDeviceKeyMemory();
  const s = store(null);
  getDeviceKey(s);
  assert.deepEqual([...s.m.keys()], ["vinto-device-key"]);
  assert.match([...s.m.values()][0], /^[0-9a-f-]{36}$/);
  resetDeviceKeyMemory();
});

test("newCaptureId generates UUIDv4", () => {
  const ids = new Set(Array.from({ length: 50 }, newCaptureId));
  assert.equal(ids.size, 50);
  for (const id of ids) assert.ok(isUuidV4(id));
  assert.equal(isUuidV4("11111111-1111-1111-8111-111111111111"), false);
});

test("the F6 payload is exactly the agreed shape", () => {
  const made = createAttempt(draft(), ASSIGNMENT, DEVICE, () => "0b0f8b6a-5b1e-4b8e-9a43-7d2f1a6c9e10");
  assert.ok(made.ok);
  assert.deepEqual(made.attempt.payload, {
    capture_id: "0b0f8b6a-5b1e-4b8e-9a43-7d2f1a6c9e10", form_code: "VINTO-P1-06", assignment_id: ASSIGNMENT, device_key: DEVICE,
    values: { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50", observaciones: "Prueba F6 central" },
  });
});

test("the payload carries no context fields", () => {
  const { attempt } = createAttempt(draft(), ASSIGNMENT, DEVICE);
  assert.deepEqual(Object.keys(attempt.payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.deepEqual(Object.keys(attempt.payload.values).sort(), ["cantidad_fardos", "observaciones", "peso_kg", "punto_merma", "tipo_producto"]);
  const text = JSON.stringify(attempt.payload);
  for (const forbidden of ["machine", "shift", "turno", "operating_date", "work_order", "pv", "article", "gramaje", "user", "revision", "status", "captured_at", "form_version"]) assert.equal(text.includes(forbidden), false, forbidden);
});

test("options are stored as option_key with a separate label", () => {
  assert.deepEqual(PUNTO_MERMA_OPTIONS.map((o) => [o.value, o.label]), [["bobina_rechazada", "Bobina rechazada"], ["recorte_maquina", "Recorte de máquina"]]);
  assert.deepEqual(TIPO_PRODUCTO_OPTIONS.map((o) => [o.value, o.label]), [["servilleta", "Servilleta"], ["hoja_doble", "Hoja doble"], ["hoja_simple", "Hoja simple"]]);
  for (const label of ["Recorte de máquina", "Hoja doble"]) assert.equal(normalizeDraft(draft({ punto_merma: label, tipo_producto: label })).ok, false); // una etiqueta no es un valor
});

test("cantidad_fardos must be a real integer; zero is allowed", () => {
  assert.equal(normalizeDraft(draft({ cantidad_fardos: " 7 " })).values.cantidad_fardos, 7);
  assert.equal(normalizeDraft(draft({ cantidad_fardos: "0" })).values.cantidad_fardos, 0);
  for (const bad of ["", "  ", "1.5", "1,5", "abc", "NaN", "1e3", "9".repeat(20), "Infinity"]) assert.equal(normalizeDraft(draft({ cantidad_fardos: bad })).ok, false, bad);
});

test("the decimal weight keeps its precision as clean text", () => {
  for (const [input, out] of [["125.50", "125.50"], ["0.001", "0.001"], ["123456789.123456789", "123456789.123456789"], [" 7 ", "7"], ["10,25", "10.25"], ["0", "0"]]) assert.equal(normalizeDraft(draft({ peso_kg: input })).values.peso_kg, out);
  for (const bad of ["", "abc", "NaN", "1e5", "1.2.3", ".5", "5.", "1".repeat(41)]) assert.equal(normalizeDraft(draft({ peso_kg: bad })).ok, false, bad);
  assert.equal(typeof normalizeDraft(draft()).values.peso_kg, "string");
});

test("an empty observation is omitted and a filled one is trimmed", () => {
  for (const blank of ["", "   ", "\n\t"]) assert.equal("observaciones" in normalizeDraft(draft({ observaciones: blank })).values, false);
  assert.equal(normalizeDraft(draft({ observaciones: "  hola  " })).values.observaciones, "hola");
});

test("parseSubmission accepts the backend shape and drops unknown fields", () => {
  const parsed = parseSubmission({ created: true, already_submitted: false, extra: 1, capture: { ...capture("a"), created_by: "x", internal: 1, values: { ...capture("a").values, otro: 1 } } });
  assert.equal(parsed.capture.id, "a");
  assert.equal("created_by" in parsed.capture, false);
  assert.equal("otro" in parsed.capture.values, false);
  assert.equal(parsed.capture.values.peso_kg, "125.50");
  assert.equal(parseSubmission({ created: true, already_submitted: false, capture: capture("a", { values: { ...capture("a").values, peso_kg: 125.5 } }) }).capture.values.peso_kg, "125.5");
  const bare = { cantidad_fardos: 1, punto_merma: "recorte_maquina", tipo_producto: "servilleta", peso_kg: "1" };
  assert.equal("observaciones" in parseSubmission({ created: true, already_submitted: false, capture: capture("a", { values: bare }) }).capture.values, false);
});

test("malformed responses are rejected instead of trusted", () => {
  const ok = { created: true, already_submitted: false, capture: capture("a") };
  const bad = [null, undefined, "x", 3, [], {}, { ...ok, created: "yes" }, { ...ok, already_submitted: null }, { ...ok, capture: null },
    { ...ok, capture: capture("") }, { ...ok, capture: capture("a", { revision: "1" }) }, { ...ok, capture: capture("a", { form: null }) },
    { ...ok, capture: capture("a", { machine: { code: "MP1" } }) }, { ...ok, capture: capture("a", { assignment: {} }) }, { ...ok, capture: capture("a", { work_order: { id: "x" } }) },
    { ...ok, capture: capture("a", { line: { id: "x" } }) }, { ...ok, capture: capture("a", { values: null }) },
    { ...ok, capture: capture("a", { values: { ...capture("a").values, cantidad_fardos: "2" } }) }, { ...ok, capture: capture("a", { values: { ...capture("a").values, peso_kg: "abc" } }) },
    { ...ok, capture: capture("a", { submitted_at: 5 }) }];
  bad.forEach((value, i) => assert.equal(parseSubmission(value), null, `case ${i}`));
  assert.equal(parseCapture({ ...capture("a"), operating_date: "" }), null);
  assert.equal(parseCaptureList({}), null);
  assert.equal(parseCaptureList([capture("a"), { nope: 1 }]), null);
  assert.deepEqual(parseCaptureList([]), []);
  assert.equal(parseCaptureList([capture("a"), capture("b")]).length, 2);
});

// red simulada
const attemptOf = () => createAttempt(draft(), ASSIGNMENT, DEVICE).attempt;
const fakeDeps = ({ posts = [], gets = [] }) => {
  const calls = { post: [], get: [] };
  return { calls, deps: { post: async (p) => { calls.post.push(p); return posts.shift(); }, get: async (id) => { calls.get.push(id); return gets.shift(); } } };
};
const okPost = (created, already, id, status) => ({ ok: true, status, data: { created, already_submitted: already, capture: capture(id) } });
const fail = (status, code, kind = "unavailable") => ({ ok: false, kind, status, code });

test("201 is a created capture; 200 is an idempotent retry already received", async () => {
  const a = attemptOf();
  const created = await submitAttempt(a, fakeDeps({ posts: [okPost(true, false, a.captureId, 201)] }).deps);
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  assert.equal(submitMessage(created), SUBMIT_MESSAGES.created);
  assert.equal(SUBMIT_MESSAGES.created, "Registro enviado correctamente.");
  const again = await submitAttempt(a, fakeDeps({ posts: [okPost(false, true, a.captureId, 200)] }).deps);
  assert.equal(again.alreadySubmitted, true);
  assert.equal(submitMessage(again), "El registro ya había sido recibido.");
});

test("a pending attempt keeps its capture_id and an identical payload across retries", async () => {
  const a = attemptOf();
  const snapshot = JSON.stringify(a.payload);
  const { calls, deps } = fakeDeps({ posts: [fail(0), fail(503), okPost(true, false, a.captureId, 201)], gets: [fail(0), fail(404, undefined, "not_found")] });
  assert.equal((await submitAttempt(a, deps)).kind, "uncertain");
  assert.equal((await submitAttempt(a, deps)).kind, "not_saved");
  assert.equal((await submitAttempt(a, deps)).kind, "submitted");
  assert.equal(new Set(calls.post.map((p) => p.capture_id)).size, 1);
  assert.equal(calls.post.every((p) => JSON.stringify(p) === snapshot), true);
  assert.equal(JSON.stringify(a.payload), snapshot);
  assert.throws(() => { "use strict"; a.payload.capture_id = "other"; }); // inmutable
});

test("an uncertain error never creates a new capture_id", async () => {
  let made = 0;
  const first = createAttempt(draft(), ASSIGNMENT, DEVICE, () => { made += 1; return newCaptureId(); });
  const { calls, deps } = fakeDeps({ posts: [fail(0), fail(0)], gets: [fail(0), fail(0)] });
  const o1 = await submitAttempt(first.attempt, deps), o2 = await submitAttempt(first.attempt, deps);
  assert.deepEqual([o1.kind, o2.kind, o1.message], ["uncertain", "uncertain", "No se pudo confirmar el envío."]);
  assert.equal(made, 1);
  assert.deepEqual(calls.get, [first.attempt.captureId, first.attempt.captureId]);
});

test("GET 200 after an uncertain POST is a success; GET 404 allows retrying the same id", async () => {
  const a = attemptOf();
  for (const failure of [fail(0), fail(503), fail(500), { ok: false, kind: "unavailable", status: 201 }]) {
    const found = await submitAttempt(a, fakeDeps({ posts: [failure], gets: [{ ok: true, status: 200, data: capture(a.captureId) }] }).deps);
    assert.equal(found.kind, "submitted");
    assert.equal(found.reconciled, true);
  }
  const missing = await submitAttempt(a, fakeDeps({ posts: [fail(0)], gets: [fail(404, undefined, "not_found")] }).deps);
  assert.deepEqual([missing.kind, missing.message], ["not_saved", SUBMIT_MESSAGES.notSaved]);
  assert.equal((await reconcile(a.captureId, fakeDeps({ gets: [{ ok: true, status: 200, data: capture("another-id") }] }).deps)).kind, "uncertain"); // otra captura: no cuenta
  assert.equal((await reconcile(a.captureId, fakeDeps({ gets: [fail(401, undefined, "session")] }).deps)).kind, "session");
});

test("backend rejections map to the agreed messages and never trigger reconciliation", async () => {
  const cases = [
    [403, undefined, "forbidden", "No tienes permisos para enviar este registro."],
    [404, "ASSIGNMENT_NOT_FOUND", "not_found", "La asignación o contexto ya no existe."],
    [409, "ASSIGNMENT_STALE", "stale", "La asignación ya no corresponde al turno o fecha actual. Solicita a Supervisión que la reactive."],
    [409, "ASSIGNMENT_NOT_ACTIVE", "not_active", "La asignación ya no está activa."],
    [409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency", "No se puede reutilizar este identificador para datos distintos."],
    [422, "CAPTURE_VALIDATION", "invalid", "Revisa los campos obligatorios y sus valores."],
  ];
  for (const [status, code, reason, message] of cases) {
    const { calls, deps } = fakeDeps({ posts: [fail(status, code)] });
    const outcome = await submitAttempt(attemptOf(), deps);
    assert.deepEqual([outcome.kind, outcome.reason, outcome.message], ["rejected", reason, message]);
    assert.equal(calls.get.length, 0);
  }
  assert.equal(rejectionFor(409, "SOMETHING_ELSE").reason, "conflict");
  assert.equal(rejectionFor(503), null);
  assert.equal((await submitAttempt(attemptOf(), fakeDeps({ posts: [fail(401, undefined, "session")] }).deps)).kind, "session");
  for (const text of Object.values(SUBMIT_MESSAGES)) assert.doesNotMatch(text, /SQL|traceback|\{|ASSIGNMENT_STALE/i);
});

test("only the F6 form id is centralized", () => {
  assert.equal(isF6(F6_FORM_ID), true);
  assert.equal(F6_FORM_CODE, "VINTO-P1-06");
  for (const other of ["form_10_registro_de_fardos", "form_3_registro_de_produccion_de_bobinas", "form_16_registro_de_control_de_merma", "form_31_consumo_de_quimicos", ""]) assert.equal(isF6(other), false);
  assert.equal(buildPayload("c", "a", "d", { cantidad_fardos: 1, punto_merma: "x", tipo_producto: "y", peso_kg: "1" }).form_code, "VINTO-P1-06");
});

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("the page routes F6 to the central component and keeps the other forms on local save()", () => {
  const f6 = page.slice(page.indexOf("if (selected && selected.id === F6_FORM_ID"), page.indexOf("    // F3 tampoco usa Capture/save()")); // la rama F3 tiene su propio test en bobbins.test.mjs
  assert.ok(f6.includes("<F6Capture"));
  assert.equal(/save\(|setRecords|vinto-p1-records/.test(f6), false);
  assert.match(page, /if \(selected\)\n\s+return <Capture form=\{selected\}[^\n]*save=\{r => \{ setRecords\(x => \[r, \.\.\.x\]\)/); // los demás formularios siguen locales
  assert.equal((page.match(/records=\{records\.filter\(r => r\.formId !== F6_FORM_ID && r\.formId !== F3_FORM_ID\)\}/g) ?? []).length, 2); // F6 y F3 locales históricos fuera de Seguimiento
});

test("the F6 component and API client never touch local storage for records", () => {
  for (const file of ["../components/vinto/f6-capture.tsx", "../lib/vinto/captures-api.ts", "../lib/vinto/captures.ts"]) {
    const text = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|Authorization|document\.cookie/.test(text.replace(/\/\/[^\n]*/g, "")), false, file);
  }
  const api = readFileSync(new URL("../lib/vinto/captures-api.ts", import.meta.url), "utf8");
  assert.match(api, /requestJson\("\/api\/captures", \{ method: "POST"/);
});
