// node --test scripts/bobbins.test.mjs
// Pruebas puras de la producción central de bobinas F3: payload, normalización del borrador, intento pendiente, parser de la
// respuesta (Bobbin + Capture), clasificación de errores y reintento incierto con el MISMO capture_id. La red se inyecta.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  BOBBIN_MESSAGES, EMPTY_BOBBIN_DRAFT, F3_FORM_ID, bobbinRejectionFor, bobbinSuccessMessage, buildBobbinPayload, contextToShow, createBobbinAttempt, isF3, isUuidV4, pendingNotice,
  newBobbinCaptureId, normalizeBobbinDraft, parseBobbin, parseBobbinSubmission, submitBobbinAttempt,
} from "../lib/vinto/bobbins.ts";

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444";
const DEVICE = "99999999-9999-4999-8999-999999999999";
const FIXED_ID = "0b0f8b6a-5b1e-4b8e-9a43-7d2f1a6c9e10";
const draft = (o = {}) => ({ ...EMPTY_BOBBIN_DRAFT, hora_inicio: "07:15", hora_fin: "08:40", diametro: "1200.5", peso_kg: "845.25", numero_de_cortes: "3", observaciones: "sin novedades", ...o });
const values = (o = {}) => { const c = normalizeBobbinDraft(draft(o)); assert.ok(c.ok, JSON.stringify(c)); return c.values; };
const errors = (o = {}) => { const c = normalizeBobbinDraft(draft(o)); assert.equal(c.ok, false); return c.errors.join(" | "); };

const bobbin = (o = {}) => ({
  id: "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b", code: "2", capture_id: FIXED_ID, machine: { code: "MP1", name: "MP1" }, management_start_year: 2026, sequence_number: 2,
  start_time: "07:15:00", end_time: "08:40:00", diameter_mm: "1200.5", weight_kg: "845.25", grammage_g_m2: "15.5", number_of_cuts: "3", notes: "x",
  article: { code: "M1-1031", description: "M1-BOBINA PH G-15.5 CR-22% R-540640" }, quality_status: "pending", created_at: "2026-10-06T16:00:00Z", ...o,
});
const capture = (o = {}) => ({
  id: FIXED_ID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: "VINTO-P1-03", version_number: 1, name: "Registro de producción de bobinas" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1031", description: "BOBINA" } },
  values: { hora_inicio: "07:15:00", hora_fin: "08:40:00", diametro: "1200.5", peso_kg: "845.25", numero_de_cortes: "3", observaciones: "x" }, ...o,
});
const submission = (o = {}, b = {}, c = {}) => ({ created: true, already_submitted: false, bobbin: bobbin(b), capture: capture(c), ...o });
const ctx = (o = {}) => ({ assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1031", productName: "M1-BOBINA PH G-15.5 CR-22% R-540640", machine: "MP1", shift: "Día", date: "2026-10-06", ...o });
const MP3_CTX = ctx({ assignmentId: "77777777-7777-4777-8777-777777777777", workOrderId: "88888888-8888-4888-8888-888888888888", otId: "OT-2026-0009", lineId: "L3", pv: "PV-9", machine: "MP3" });
const attempt = (o = {}, context = ctx()) => { const made = createBobbinAttempt(draft(o), context, DEVICE, () => FIXED_ID); assert.ok(made.ok); return made.attempt; };

// ---- payload ----------------------------------------------------------------------------------------------------------------

test("the F3 payload is exactly the agreed shape (no form_code)", () => {
  assert.deepEqual(attempt().payload, {
    capture_id: FIXED_ID, assignment_id: ASSIGNMENT, device_key: DEVICE,
    values: { hora_inicio: "07:15", hora_fin: "08:40", diametro: "1200.5", peso_kg: "845.25", numero_de_cortes: "3", observaciones: "sin novedades" },
  });
});

test("the payload carries only capture_id, assignment_id, device_key and values", () => {
  const { payload } = attempt();
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "values"]);
  assert.deepEqual(Object.keys(payload.values).sort(), ["diametro", "hora_fin", "hora_inicio", "numero_de_cortes", "observaciones", "peso_kg"]);
  const text = JSON.stringify(payload);
  for (const forbidden of ["form_code", "machine", "shift", "turno", "operating_date", "work_order", "line", "article", "grammage", "gramaje", "bobbin", "code", "user", "revision", "status", "descripcion", "codigo_tubete"]) {
    assert.equal(text.includes(forbidden), false, forbidden);
  }
});

test("F3 form id and ids", () => {
  assert.equal(F3_FORM_ID, "form_3_registro_de_produccion_de_bobinas");
  assert.ok(isF3(F3_FORM_ID));
  assert.equal(isF3("form_6_registro_de_control_de_fardos"), false);
  const ids = new Set(Array.from({ length: 30 }, newBobbinCaptureId));
  assert.equal(ids.size, 30);
  for (const id of ids) assert.ok(isUuidV4(id));
});

// ---- horas ------------------------------------------------------------------------------------------------------------------

test("hours are both required and valid times", () => {
  assert.match(errors({ hora_inicio: "" }), /Hora inicio/);
  assert.match(errors({ hora_fin: "" }), /Hora fin/);
  for (const bad of ["25:00", "7:15", "07:60", "abc", "07-15", "24:00"]) assert.match(errors({ hora_inicio: bad }), /Hora inicio/, bad);
  assert.equal(values({ hora_inicio: "07:15:30" }).hora_inicio, "07:15:30");
});

test("hora_inicio after hora_fin is valid (the bobbin can cross midnight)", () => {
  const v = values({ hora_inicio: "23:50", hora_fin: "00:15" });
  assert.deepEqual([v.hora_inicio, v.hora_fin], ["23:50", "00:15"]);
});

test("equal hours are valid and there is no relation between them", () => {
  const v = values({ hora_inicio: "12:00", hora_fin: "12:00" });
  assert.equal(v.hora_inicio, v.hora_fin);
});

// ---- diámetro ---------------------------------------------------------------------------------------------------------------

test("diameter: decimal comma becomes a point and stays a string", () => {
  assert.equal(values({ diametro: "1200,5" }).diametro, "1200.5");
  assert.equal(values({ diametro: " 1200.50 " }).diametro, "1200.50");
  assert.equal(typeof values().diametro, "string");
});

test("diameter is required and must be decimal", () => {
  assert.match(errors({ diametro: "" }), /Diámetro/);
  for (const bad of ["abc", "1.2.3", "1,2,3", "1e3", "12 mm", ".5"]) assert.match(errors({ diametro: bad }), /Diámetro/, bad);
});

test("diameter has NO functional range: zero and very large values pass", () => {
  assert.equal(values({ diametro: "0" }).diametro, "0");
  assert.equal(values({ diametro: "0.0" }).diametro, "0.0");
  const big = "9".repeat(30);
  assert.equal(values({ diametro: big }).diametro, big);
  // SONDA TÉCNICA: un valor negativo solo demuestra que el frontend no inventó una regla de rango para el diámetro. NO significa que
  // el negocio considere válido u operativo un diámetro negativo: VINTO no confirmó ningún rango y el backend decide.
  assert.equal(values({ diametro: "-1" }).diametro, "-1");
});

test("diameter keeps only the technical length limit", () => {
  assert.match(errors({ diametro: "1".repeat(41) }), /Diámetro/);
  assert.equal(values({ diametro: "1".repeat(40) }).diametro.length, 40);
});

// ---- peso -------------------------------------------------------------------------------------------------------------------

test("weight: decimal comma, zero and large values are valid", () => {
  assert.equal(values({ peso_kg: "845,25" }).peso_kg, "845.25");
  assert.equal(values({ peso_kg: "0" }).peso_kg, "0");
  assert.equal(values({ peso_kg: "-0" }).peso_kg, "-0"); // el backend acepta -0 (no es negativo)
  assert.equal(values({ peso_kg: "99999999.999" }).peso_kg, "99999999.999");
});

test("a negative weight is rejected (weight_kg >= 0 already exists in the base schema)", () => {
  assert.match(errors({ peso_kg: "-0.01" }), /Peso: no puede ser negativo/);
  assert.match(errors({ peso_kg: "-1" }), /Peso: no puede ser negativo/);
  assert.match(errors({ peso_kg: "-1,5" }), /Peso: no puede ser negativo/);
  assert.match(errors({ peso_kg: "" }), /Peso/);
  assert.match(errors({ peso_kg: "abc" }), /Peso/);
});

// ---- cortes y observaciones -------------------------------------------------------------------------------------------------

test("numero_de_cortes stays TEXT: no numeric coercion", () => {
  for (const raw of ["3", "03", "2 + 1", "1.0", "tres", "007", "1e2"]) {
    const v = values({ numero_de_cortes: raw });
    assert.equal(typeof v.numero_de_cortes, "string");
    assert.equal(v.numero_de_cortes, raw);
  }
  assert.equal(values({ numero_de_cortes: "  4  " }).numero_de_cortes, "4");
  assert.match(errors({ numero_de_cortes: "   " }), /Número de cortes/);
  assert.match(errors({ numero_de_cortes: "" }), /Número de cortes/);
});

test("empty observations are omitted from the payload; filled ones are trimmed", () => {
  for (const empty of ["", "   ", "\n\t "]) {
    const v = values({ observaciones: empty });
    assert.equal("observaciones" in v, false);
    assert.equal("observaciones" in attempt({ observaciones: empty }).payload.values, false);
  }
  assert.equal(values({ observaciones: "  ok  " }).observaciones, "ok");
});

test("an invalid draft reports every problem and creates no attempt", () => {
  const made = createBobbinAttempt(draft({ hora_inicio: "", diametro: "x", peso_kg: "-1", numero_de_cortes: "" }), ctx(), DEVICE, () => assert.fail("must not generate an id"));
  assert.equal(made.ok, false);
  assert.equal(made.errors.length, 4);
});

// ---- intento pendiente ------------------------------------------------------------------------------------------------------

test("a pending attempt is immutable and keeps capture_id and payload across retries", async () => {
  const a = attempt();
  assert.throws(() => { "use strict"; a.captureId = "x"; });
  assert.throws(() => { "use strict"; a.payload.capture_id = "x"; });
  assert.throws(() => { "use strict"; a.payload.values.peso_kg = "1"; });
  assert.throws(() => { "use strict"; a.draft.peso_kg = "1"; });
  for (const level of [a, a.payload, a.payload.values, a.draft]) assert.ok(Object.isFrozen(level));
  const seen = [];
  const deps = { post: async (payload) => { seen.push(structuredClone(payload)); return { ok: false, kind: "unavailable", status: 0 }; } };
  for (let i = 0; i < 4; i++) await submitBobbinAttempt(a, deps);
  assert.equal(seen.length, 4);
  for (const payload of seen) assert.deepEqual(payload, seen[0]);
  assert.equal(seen[0].capture_id, a.captureId);
  assert.equal(a.draft.peso_kg, "845.25"); // el borrador congelado permite rehidratar el formulario bloqueado
});

test("each logical attempt gets its own UUIDv4", () => {
  const ids = new Set();
  for (let i = 0; i < 20; i++) { const made = createBobbinAttempt(draft(), ctx(), DEVICE); assert.ok(made.ok); assert.ok(isUuidV4(made.attempt.captureId)); ids.add(made.attempt.captureId); }
  assert.equal(ids.size, 20);
});

// ---- parser -----------------------------------------------------------------------------------------------------------------

test("parses a 201 created response", () => {
  const parsed = parseBobbinSubmission(submission());
  assert.ok(parsed);
  assert.deepEqual([parsed.created, parsed.already_submitted, parsed.bobbin.code, parsed.bobbin.grammage_g_m2, parsed.bobbin.quality_status], [true, false, "2", "15.5", "pending"]);
  assert.equal(parsed.capture.revision, 1);
  assert.equal(parsed.capture.values.numero_de_cortes, "3");
});

test("parses a 200 already_submitted response", () => {
  const parsed = parseBobbinSubmission(submission({ created: false, already_submitted: true }));
  assert.deepEqual([parsed.created, parsed.already_submitted], [false, true]);
});

test("parses a bobbin with grammage and with grammage null", () => {
  assert.equal(parseBobbin(bobbin({ grammage_g_m2: "14.5" })).grammage_g_m2, "14.5");
  assert.equal(parseBobbin(bobbin({ grammage_g_m2: 17 })).grammage_g_m2, "17"); // número JSON -> texto
  assert.equal(parseBobbin(bobbin({ grammage_g_m2: null })).grammage_g_m2, null);
  assert.equal(parseBobbin(bobbin({ notes: null })).notes, null);
});

test("the parser is defensive and returns a clean object", () => {
  for (const bad of [null, undefined, "x", 1, [], {}, submission({ created: "yes" }), submission({ already_submitted: undefined }), submission({ bobbin: null }), submission({ capture: null }),
    submission({}, { id: "" }), submission({}, { code: 3 }), submission({}, { machine: null }), submission({}, { diameter_mm: "abc" }), submission({}, { weight_kg: null }),
    submission({}, { grammage_g_m2: "abc" }), submission({}, { grammage_g_m2: undefined }), submission({}, { sequence_number: 1.5 }), submission({}, { quality_status: "" }),
    submission({}, { article: { code: "A" } }), submission({}, { notes: 5 }), submission({}, { capture_id: "otra-captura" }),
    submission({}, {}, { values: null }), submission({}, {}, { values: { peso_kg: true } }), submission({}, {}, { revision: "1" }), submission({}, {}, { line: null })]) {
    assert.equal(parseBobbinSubmission(bad), null, JSON.stringify(bad)?.slice(0, 80));
  }
  const extra = parseBobbinSubmission(submission({ secret: "x" }, { internal: 1, created_by: "u" }, { created_by: "u" }));
  assert.equal("secret" in extra, false);
  assert.equal("internal" in extra.bobbin, false);
  assert.equal("created_by" in extra.capture, false);
});

// ---- mensajes ---------------------------------------------------------------------------------------------------------------

test("success messages use the backend result and treat null grammage neutrally", () => {
  assert.equal(bobbinSuccessMessage(bobbin()), "Bobina 2 registrada · gramaje 15.5 · Calidad pendiente");
  const none = bobbinSuccessMessage(bobbin({ grammage_g_m2: null }));
  assert.equal(none, "Bobina 2 registrada · sin gramaje en el maestro · Calidad pendiente");
  assert.doesNotMatch(none, /error|falta|no se pudo/i);
  assert.match(bobbinSuccessMessage(bobbin(), true), /ya había sido registrada/);
});

// ---- clasificación de errores y flujo ---------------------------------------------------------------------------------------

const failing = (status, code) => ({ post: async () => ({ ok: false, kind: "x", status, code }) });
const succeeding = (data, status = 201) => ({ post: async () => ({ ok: true, status, data }) });

test("201 created and 200 already_submitted are both success", async () => {
  const created = await submitBobbinAttempt(attempt(), succeeding(parseBobbinSubmission(submission())));
  assert.equal(created.kind, "submitted");
  assert.deepEqual([created.created, created.alreadySubmitted], [true, false]);
  assert.match(created.message, /Bobina 2 registrada/);
  const again = await submitBobbinAttempt(attempt(), succeeding(parseBobbinSubmission(submission({ created: false, already_submitted: true })), 200));
  assert.equal(again.kind, "submitted");
  assert.deepEqual([again.created, again.alreadySubmitted], [false, true]);
  assert.match(again.message, /ya había sido registrada/);
});

test("definitive responses end the attempt", async () => {
  assert.deepEqual(await submitBobbinAttempt(attempt(), failing(401)), { kind: "session" });
  const cases = [[403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "CAPTURE_VALIDATION", "invalid"], [409, "ASSIGNMENT_STALE", "stale"],
    [409, "ASSIGNMENT_NOT_ACTIVE", "not_active"], [409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"], [409, "OTRO", "conflict"], [409, undefined, "conflict"]];
  for (const [status, code, reason] of cases) {
    const out = await submitBobbinAttempt(attempt(), failing(status, code));
    assert.equal(out.kind, "rejected", `${status} ${code}`);
    assert.equal(out.reason, reason, `${status} ${code}`);
    assert.ok(out.message.length > 0);
  }
  assert.equal(bobbinRejectionFor(500), null);
  assert.equal(bobbinRejectionFor(0), null);
});

test("network, 5xx and unreadable bodies are uncertain and use no other endpoint", async () => {
  let calls = 0;
  for (const status of [0, 500, 502, 503, 504, 200 /* cuerpo ilegible: requestJson lo marca unavailable con el status de la respuesta */]) {
    const out = await submitBobbinAttempt(attempt(), { post: async () => { calls++; return { ok: false, kind: "unavailable", status }; }, get: () => assert.fail("F3 never reconciles with GET") });
    assert.equal(out.kind, "uncertain", String(status));
    assert.equal(out.message, BOBBIN_MESSAGES.uncertain);
  }
  assert.equal(calls, 6);
});

test("an uncertain response never creates another capture_id; the retry is the same POST and can succeed", async () => {
  const a = attempt();
  const ids = [];
  const sequence = [{ ok: false, kind: "unavailable", status: 0 }, { ok: false, kind: "server", status: 503 }, { ok: true, status: 200, data: parseBobbinSubmission(submission({ created: false, already_submitted: true })) }];
  const deps = { post: async (payload) => { ids.push(payload.capture_id); return sequence.shift(); } };
  const outcomes = [];
  for (let i = 0; i < 3; i++) outcomes.push((await submitBobbinAttempt(a, deps)).kind);
  assert.deepEqual(outcomes, ["uncertain", "uncertain", "submitted"]);
  assert.deepEqual(new Set(ids), new Set([a.captureId]));
});

test("a retry that ends in 422 or idempotency conflict is definitive and does not mint a new id", async () => {
  const a = attempt();
  const ids = [];
  const responses = [{ ok: false, kind: "unavailable", status: 0 }, { ok: false, kind: "x", status: 409, code: "CAPTURE_IDEMPOTENCY_CONFLICT" }];
  const deps = { post: async (payload) => { ids.push(payload.capture_id); return responses.shift(); } };
  assert.equal((await submitBobbinAttempt(a, deps)).kind, "uncertain");
  const out = await submitBobbinAttempt(a, deps);
  assert.deepEqual([out.kind, out.reason], ["rejected", "idempotency"]);
  assert.deepEqual(new Set(ids), new Set([a.captureId]));
});

test("buildBobbinPayload copies the values (no aliasing)", () => {
  const v = values();
  const payload = buildBobbinPayload(FIXED_ID, ASSIGNMENT, DEVICE, v);
  assert.notEqual(payload.values, v);
  assert.deepEqual(payload.values, v);
});

// ---- F3 fuera del camino local ----------------------------------------------------------------------------------------------

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
const component = readFileSync(new URL("../components/vinto/f3-bobbin-capture.tsx", import.meta.url), "utf8");
const lib = readFileSync(new URL("../lib/vinto/bobbins.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../lib/vinto/bobbins-api.ts", import.meta.url), "utf8");

test("F3 is rendered by its own component before the generic Capture and never calls save()", () => {
  const f3 = page.indexOf("selected.id === F3_FORM_ID && (f3Attempt || captureContext)");
  const generic = page.indexOf("return <Capture form={selected}");
  assert.ok(f3 > 0 && generic > f3, "F3BobbinCapture must be returned before the generic Capture");
  const branch = page.slice(f3, generic);
  assert.match(branch, /<F3BobbinCapture/);
  for (const forbidden of ["save(", "setRecords", "vinto-p1-records"]) assert.equal(branch.includes(forbidden), false, forbidden);
  assert.match(page, /selected\.id === F6_FORM_ID && captureContext[\s\S]*<F6Capture/); // F6 sigue igual
});

test("session loss clears the F3 attempt and old local F3 records are not shown as central tracking", () => {
  assert.ok((page.match(/setF3Attempt\(null\)/g) ?? []).length >= 2);
  assert.ok((page.match(/r\.formId !== F6_FORM_ID && r\.formId !== F3_FORM_ID/g) ?? []).length >= 2);
});

test("the old F3 override (codigo_tubete, manual grammage/description) is gone from effectiveForms", () => {
  const start = page.indexOf('f.id === "form_3_registro_de_produccion_de_bobinas"');
  assert.ok(start > 0);
  // Solo el CÓDIGO de la rama F3 de effectiveForms (los comentarios explicativos pueden nombrar lo eliminado; otras partes de
  // page.tsx, como el helper grammage() o el historial de tubetes, son lógica legítima ajena a F3 y no se inspeccionan).
  const block = page.slice(start, page.indexOf('f.id === "form_6_registro_de_control_de_fardos"')).replace(/^\s*\/\/.*$/gm, "");
  assert.equal(block.includes("codigo_tubete"), false);
  assert.equal(block.includes('"gramaje"'), false);
  assert.equal(block.includes("descripcion_producto"), false);
  for (const key of ["hora_inicio", "hora_fin", "diametro", "peso_kg", "numero_de_cortes", "observaciones"]) assert.ok(block.includes(`"${key}"`), key);
});

test("F3 code never touches localStorage records and the component asks only for the six manual fields", () => {
  for (const [name, text] of [["component", component], ["lib", lib], ["api", api]]) {
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|setRecords/.test(text.replace(/^\s*\/\/.*$/gm, "")), false, name);
  }
  assert.equal(component.includes("codigo_tubete"), false);
  assert.match(component, /se asignará al guardar/);
  assert.match(component, /se tomará del maestro central/);
  assert.equal(/G-\d|productName\.(match|replace|split)|\.match\(\/G-/.test(component + lib), false); // no parsea gramaje del nombre
  assert.match(api, /"\/api\/bobbins"/);
});

// ---- intento ligado a su contexto original ------------------------------------------------------------------------------------

test("an attempt keeps an immutable snapshot of its ORIGINAL context", () => {
  const current = ctx();
  const a = attempt({}, current);
  assert.deepEqual(a.context, current);
  assert.notEqual(a.context, current); // copia, sin alias
  assert.ok(Object.isFrozen(a.context));
  assert.throws(() => { "use strict"; a.context.machine = "MP3"; });
  assert.equal(a.context.assignmentId, a.payload.assignment_id); // el contexto mostrado y el assignment_id enviado salen de la misma fuente
});

test("changing the current context afterwards does not change the attempt's context", () => {
  const current = ctx();
  const a = attempt({}, current);
  current.machine = "MP3"; current.otId = "OT-OTRA"; current.assignmentId = MP3_CTX.assignmentId; // el selector cambia
  assert.equal(a.context.machine, "MP1");
  assert.equal(a.context.otId, "OT-2026-0001");
  assert.equal(a.context.assignmentId, ASSIGNMENT);
  assert.equal(a.payload.assignment_id, ASSIGNMENT);
});

test("MP1 uncertain attempt, then the selector moves to MP3: the screen and the retry stay on MP1", async () => {
  const a = attempt({}, ctx());
  const shown = contextToShow(a, MP3_CTX); // el selector ahora apunta a MP3
  assert.equal(shown.machine, "MP1");
  assert.notEqual(shown.machine, "MP3");
  assert.equal(shown.assignmentId, ASSIGNMENT);
  assert.equal(contextToShow(a, null).machine, "MP1"); // aunque el selector no tenga contexto
  assert.equal(contextToShow(null, MP3_CTX).machine, "MP3"); // sin intento pendiente manda el contexto actual
  assert.equal(contextToShow(null, null), null);
  const sent = [];
  const deps = { post: async (payload) => { sent.push(payload); return { ok: false, kind: "unavailable", status: 0 }; } };
  await submitBobbinAttempt(a, deps);
  await submitBobbinAttempt(a, deps);
  assert.equal(sent.length, 2);
  for (const payload of sent) {
    assert.equal(payload.assignment_id, ASSIGNMENT); // retry conserva el assignment_id original
    assert.equal(payload.capture_id, FIXED_ID); // y el capture_id original
    assert.equal(payload.device_key, DEVICE);
    assert.notEqual(payload.assignment_id, MP3_CTX.assignmentId);
  }
});

test("a retry of a stale or inactive assignment is definitive without losing the original context", async () => {
  const a = attempt({}, ctx());
  for (const code of ["ASSIGNMENT_STALE", "ASSIGNMENT_NOT_ACTIVE"]) {
    const out = await submitBobbinAttempt(a, failing(409, code));
    assert.equal(out.kind, "rejected");
    assert.equal(a.context.machine, "MP1");
  }
});

test("the pending notice names the original machine, work order and line", () => {
  const notice = pendingNotice(attempt({}, ctx()));
  for (const part of ["MP1", "OT-2026-0001", "L1", "PV-1", "Día", "2026-10-06"]) assert.ok(notice.includes(part), part);
  assert.equal(notice.includes("MP3"), false);
});

test("structure: the component and the page reopen the pending attempt with its own context", () => {
  const body = component.replace(/^\s*\/\/.*$/gm, "");
  assert.match(body, /contextToShow\(attempt, context\)/);
  assert.match(body, /createBobbinAttempt\(draft, shown,/);
  assert.equal(/\bcontext\.(otId|lineId|pv|productName|machine|shift|date|assignmentId)/.test(body), false, "the screen must read the context only through `shown`");
  assert.match(body, /pendingNotice\(attempt\)/);
  assert.match(page, /selected\.id === F3_FORM_ID && \(f3Attempt \|\| captureContext\)/);
  assert.match(page, /f\.id === F3_FORM_ID && f3Attempt/);
});

// ---- parser endurecido --------------------------------------------------------------------------------------------------------

test("quality_status accepts exactly pending, released and rejected", () => {
  for (const status of ["pending", "released", "rejected"]) assert.equal(parseBobbin(bobbin({ quality_status: status })).quality_status, status);
  for (const bad of ["foo", "PENDING", "Pending", "", null, 1, undefined]) assert.equal(parseBobbin(bobbin({ quality_status: bad })), null, String(bad));
  assert.equal(parseBobbinSubmission(submission({}, { quality_status: "foo" })), null);
});

test("sequence_number and management_start_year must be positive integers", () => {
  for (const bad of [0, -1, 1.5, "2", null]) {
    assert.equal(parseBobbin(bobbin({ sequence_number: bad, code: String(bad) })), null, `sequence ${bad}`);
    assert.equal(parseBobbin(bobbin({ management_start_year: bad })), null, `year ${bad}`);
  }
  assert.ok(parseBobbin(bobbin({ sequence_number: 1, code: "1" })));
});

test("code must be exactly String(sequence_number)", () => {
  assert.equal(parseBobbin(bobbin({ code: "3" })), null); // sequence_number es 2
  assert.equal(parseBobbin(bobbin({ code: "02" })), null);
  assert.equal(parseBobbin(bobbin({ code: "2 " })), null);
  assert.ok(parseBobbin(bobbin({ sequence_number: 11, code: "11" })));
});

test("bobbin decimals: diameter without range, weight not negative, grammage null or decimal", () => {
  assert.ok(parseBobbin(bobbin({ diameter_mm: "0" })));
  assert.ok(parseBobbin(bobbin({ diameter_mm: "-1" }))); // sin rango funcional para el diámetro (sonda técnica del parser)
  assert.equal(parseBobbin(bobbin({ diameter_mm: "x" })), null);
  assert.ok(parseBobbin(bobbin({ weight_kg: "0" })));
  assert.ok(parseBobbin(bobbin({ weight_kg: "-0" })));
  assert.equal(parseBobbin(bobbin({ weight_kg: "-0.5" })), null);
  assert.equal(parseBobbin(bobbin({ grammage_g_m2: "x" })), null);
  assert.equal(parseBobbin(bobbin({ grammage_g_m2: null })).grammage_g_m2, null);
});

test("the capture must be an F3 capture: form code VINTO-P1-03 and a real status", () => {
  assert.equal(parseBobbinSubmission(submission({}, {}, { form: { code: "VINTO-P1-06", version_number: 1, name: "x" } })), null);
  assert.equal(parseBobbinSubmission(submission({}, {}, { form: { code: "vinto-p1-03", version_number: 1, name: "x" } })), null);
  assert.ok(parseBobbinSubmission(submission({}, {}, { status: "submitted" })));
  assert.ok(parseBobbinSubmission(submission({}, {}, { status: "closed" })));
  for (const bad of ["draft", "blocked", "", null, "foo"]) assert.equal(parseBobbinSubmission(submission({}, {}, { status: bad })), null, String(bad));
  for (const bad of [0, -1, 1.5, "1", null]) assert.equal(parseBobbinSubmission(submission({}, {}, { revision: bad })), null, `revision ${bad}`);
});

test("the capture values must carry every mandatory F3 value", () => {
  const full = capture().values;
  assert.equal(parseBobbinSubmission(submission({}, {}, { values: {} })), null);
  for (const key of ["hora_inicio", "hora_fin", "diametro", "peso_kg", "numero_de_cortes"]) {
    const rest = { ...full };
    delete rest[key];
    assert.equal(parseBobbinSubmission(submission({}, {}, { values: rest })), null, `missing ${key}`);
  }
  assert.equal(parseBobbinSubmission(submission({}, {}, { values: { ...full, numero_de_cortes: "" } })), null);
  assert.equal(parseBobbinSubmission(submission({}, {}, { values: { ...full, diametro: "abc" } })), null);
  assert.equal(parseBobbinSubmission(submission({}, {}, { values: { ...full, peso_kg: true } })), null);
  assert.equal(parseBobbinSubmission(submission({}, {}, { values: { ...full, observaciones: 5 } })), null);
});

test("capture values: observaciones optional, JSON numbers normalised, unknown keys dropped", () => {
  const withoutNotes = { ...capture().values };
  delete withoutNotes.observaciones;
  const noNotes = parseBobbinSubmission(submission({}, {}, { values: withoutNotes }));
  assert.ok(noNotes);
  assert.equal("observaciones" in noNotes.capture.values, false);
  const numeric = parseBobbinSubmission(submission({}, {}, { values: { ...withoutNotes, diametro: 1200.5, peso_kg: 845 } }));
  assert.deepEqual([numeric.capture.values.diametro, numeric.capture.values.peso_kg], ["1200.5", "845"]);
  const extra = parseBobbinSubmission(submission({}, {}, { values: { ...withoutNotes, interno: "x" } }));
  assert.equal("interno" in extra.capture.values, false);
  assert.equal(parseBobbinSubmission(submission()).capture.values.observaciones, "x");
});
