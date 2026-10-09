// node --test scripts/quality-humidity-capture.test.mjs
// Captura central de Calidad VINTO-P1-19 (Control de humedad) de una Bobina: borrador, cálculo de presentación (fórmula existente de
// app/page.tsx), payload, intento pendiente, reconciliación y comprobaciones estructurales. La red se simula con funciones inyectadas.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { DEVICE_KEY_STORAGE, getDeviceKey, resetDeviceKeyMemory } from "../lib/vinto/device.ts";
import {
  EMPTY_HUMIDITY_DRAFT, HUMIDITY_MESSAGES, Q19_FORM_CODE, Q19_FORM_ID, WEIGHT_KEYS, bobbinToShow, buildHumidityPayload, captureMatchesHumidityAttempt, computeHumidity, createHumidityAttempt, decimalText, deepFreeze,
  formatHumidity, humidityRejectionFor, humiditySuccessMessage, isUuidV4, newQualityCaptureId, normalizeHumidityDraft, parseQualityCapture, parseQualityCaptureSubmission,
  pendingNotice, submitHumidityAttempt,
} from "../lib/vinto/quality-captures.ts";

const BOBBIN_ID = "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b";
const OTHER_BOBBIN_ID = "12121212-1212-4212-8212-121212121212";
const CAPTURE_ID = "0b0f8b6a-5b1e-4b8e-9a43-7d2f1a6c9e10";
const DEVICE = "99999999-9999-4999-8999-999999999999";
const draft = (o = {}) => ({ ...EMPTY_HUMIDITY_DRAFT, peso_humedo_comando: "100.50", peso_seco_comando: "94.10", peso_humedo_medio: "101.000", peso_seco_medio: "95.25",
  peso_humedo_transversal: "99.9", peso_seco_transversal: "93.80", observaciones: "ensayo", ...o });
const inboxItem = (id = BOBBIN_ID, code = "1", machine = "MP1") => ({
  bobbin: { id, code, machine: { code: machine, name: machine }, management_start_year: 2026, sequence_number: Number(code), start_time: "12:00:00", end_time: "13:00:00", diameter_mm: "1200",
    weight_kg: "845.25", grammage_g_m2: "15.5", number_of_cuts: "3", notes: null },
  production: { capture_id: "40b936c3-387f-4399-a394-33642813ffbd", captured_at: "2026-10-07T16:00:00Z", operating_date: "2026-10-07", shift: { code: "DIA", name: "Día" },
    work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
    line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-DEV-001", article: { code: "M1-1031", description: "M1-BOBINA PH G-15.5" } } },
  quality: { status: "pending" },
});
const attempt = (o = {}, item = inboxItem()) => { const made = createHumidityAttempt(draft(o), item, DEVICE, () => CAPTURE_ID); assert.ok(made.ok); return made.attempt; };
const values = (o = {}) => { const c = normalizeHumidityDraft(draft(o)); assert.ok(c.ok, JSON.stringify(c)); return c.values; };
const errors = (o = {}) => { const c = normalizeHumidityDraft(draft(o)); assert.equal(c.ok, false); return c.errors.join(" | "); };
const capture = (o = {}) => ({
  id: CAPTURE_ID, status: "submitted", revision: 1, captured_at: "2026-10-08T10:00:00Z", submitted_at: "2026-10-08T10:00:01Z", form: { code: "VINTO-P1-19", version_number: 1, name: "Control de humedad" },
  bobbin: { id: BOBBIN_ID, code: "1" }, machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-07",
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-DEV-001", article: { code: "M1-1031", description: "x" } },
  values: { peso_humedo_comando: "100.50", peso_seco_comando: "94.10", peso_humedo_medio: "101.000", peso_seco_medio: "95.25", peso_humedo_transversal: "99.9", peso_seco_transversal: "93.80", observaciones: "ensayo" }, ...o,
});
const submission = (o = {}, c = {}) => ({ created: true, already_submitted: false, capture: capture(c), ...o });

// ---- borrador ----------------------------------------------------------------------------------------------------------------

test("a valid draft normalises the six weights and the optional notes", () => {
  const v = values();
  assert.deepEqual(Object.keys(v).sort(), [...WEIGHT_KEYS, "observaciones"].sort());
  assert.equal(v.observaciones, "ensayo");
});

test("the six weights are required decimals", () => {
  for (const key of WEIGHT_KEYS) {
    assert.match(errors({ [key]: "" }), /ingresa un número decimal/, key);
    assert.match(errors({ [key]: "abc" }), /ingresa un número decimal/, key);
    for (const bad of ["1e3", "1.2.3", ".5", "12 kg", "1,2,3"]) assert.equal(normalizeHumidityDraft(draft({ [key]: bad })).ok, false, `${key} ${bad}`);
  }
  assert.equal(normalizeHumidityDraft(EMPTY_HUMIDITY_DRAFT).errors.length, 6);
});

test("observations are optional: empty ones are omitted, filled ones trimmed", () => {
  for (const empty of ["", "   ", "\n\t "]) assert.equal("observaciones" in values({ observaciones: empty }), false);
  assert.equal(values({ observaciones: "  ok  " }).observaciones, "ok");
});

test("decimal comma becomes a point and the text stays EXACT (no Number)", () => {
  assert.equal(values({ peso_humedo_comando: "100,50" }).peso_humedo_comando, "100.50");
  assert.equal(values({ peso_seco_medio: "0.10" }).peso_seco_medio, "0.10");
  assert.equal(values({ peso_humedo_medio: "101.000" }).peso_humedo_medio, "101.000");
  const long = "12345678901234567890.123456789";
  assert.equal(values({ peso_humedo_transversal: long }).peso_humedo_transversal, long);
  for (const key of WEIGHT_KEYS) assert.equal(typeof values()[key], "string");
  assert.equal(decimalText(" 5,5 "), "5.5");
});

test("no functional range was invented for the weights: zero, large and technical probes pass", () => {
  assert.equal(values({ peso_seco_comando: "0" }).peso_seco_comando, "0");
  assert.equal(values({ peso_humedo_comando: "9".repeat(30) }).peso_humedo_comando, "9".repeat(30));
  // SONDA TÉCNICA: un negativo solo demuestra que el frontend no impone rango; NO significa que el negocio lo considere un peso válido.
  assert.equal(values({ peso_seco_comando: "-1" }).peso_seco_comando, "-1");
  assert.equal(normalizeHumidityDraft(draft({ peso_seco_comando: "1".repeat(41) })).ok, false); // solo el límite técnico de longitud
});

// ---- fórmula ------------------------------------------------------------------------------------------------------------------

test("the existing humidity formula and average are preserved", () => {
  const r = computeHumidity(draft({ peso_humedo_comando: "100", peso_seco_comando: "94", peso_humedo_medio: "50", peso_seco_medio: "47", peso_humedo_transversal: "80", peso_seco_transversal: "75" }));
  assert.equal(r.comando, 6);
  assert.equal(r.medio, 6);
  assert.equal(r.transversal, 6.25);
  assert.equal(r.promedio, Number(((6 + 6 + 6.25) / 3).toFixed(2)));
  assert.equal(r.promedio, 6.08);
});

test("the humidity is rounded to 2 decimals per position and the average uses the ROUNDED values", () => {
  const r = computeHumidity(draft({ peso_humedo_comando: "3", peso_seco_comando: "2", peso_humedo_medio: "7", peso_seco_medio: "6", peso_humedo_transversal: "9", peso_seco_transversal: "8" }));
  assert.deepEqual([r.comando, r.medio, r.transversal], [33.33, 14.29, 11.11]);
  assert.equal(r.promedio, Number(((33.33 + 14.29 + 11.11) / 3).toFixed(2)));
  assert.equal(r.promedio, 19.58);
  assert.equal(formatHumidity(6), "6.00");
});

test("empty, zero or invalid wet weights give 0 like the original and a decimal comma is understood", () => {
  assert.deepEqual(computeHumidity(EMPTY_HUMIDITY_DRAFT), { comando: 0, medio: 0, transversal: 0, promedio: 0 });
  const r = computeHumidity(draft({ peso_humedo_comando: "0", peso_humedo_medio: "abc", peso_humedo_transversal: "100,0", peso_seco_transversal: "90,0" }));
  assert.deepEqual([r.comando, r.medio, r.transversal], [0, 0, 10]);
});

test("the formula matches the original code in app/page.tsx", () => {
  const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /w > 0 \? Number\(\(\(\(w - d\) \/ w\) \* 100\)\.toFixed\(2\)\) : 0/);
  assert.match(page, /\/ 3\)\.toFixed\(2\)\)/);
});

// ---- payload ------------------------------------------------------------------------------------------------------------------

test("the payload is exactly capture_id, form_code, device_key and values", () => {
  assert.deepEqual(attempt().payload, {
    capture_id: CAPTURE_ID, form_code: "VINTO-P1-19", device_key: DEVICE,
    values: { peso_humedo_comando: "100.50", peso_seco_comando: "94.10", peso_humedo_medio: "101.000", peso_seco_medio: "95.25", peso_humedo_transversal: "99.9", peso_seco_transversal: "93.80", observaciones: "ensayo" },
  });
  assert.equal(Q19_FORM_CODE, "VINTO-P1-19");
  assert.equal(Q19_FORM_ID, "form_19_control_de_humedad");
});

test("the payload carries no calculated humidity and no production context", () => {
  const { payload } = attempt();
  assert.deepEqual(Object.keys(payload).sort(), ["capture_id", "device_key", "form_code", "values"]);
  assert.deepEqual(Object.keys(payload.values).sort(), ["observaciones", ...WEIGHT_KEYS].sort());
  const text = JSON.stringify(payload);
  for (const forbidden of ["humedad_comando", "humedad_medio", "humedad_transversal", "promedio", "machine", "maquina", "shift", "turno", "operating_date", "work_order", "pv", "article",
    "assignment", "bobbin", "numero_de_bobina", "responsable", "fecha", "hora", "revision", "status", "muestra"]) assert.equal(text.includes(forbidden), false, forbidden);
});

test("a draft without observations omits the field from the payload", () => {
  assert.equal("observaciones" in attempt({ observaciones: "  " }).payload.values, false);
});

test("buildHumidityPayload copies the values (no aliasing)", () => {
  const v = values();
  const payload = buildHumidityPayload(CAPTURE_ID, DEVICE, v);
  assert.notEqual(payload.values, v);
  assert.deepEqual(payload.values, v);
});

test("ids: UUIDv4 per logical attempt", () => {
  const ids = new Set(Array.from({ length: 30 }, newQualityCaptureId));
  assert.equal(ids.size, 30);
  for (const id of ids) assert.ok(isUuidV4(id));
  const made = createHumidityAttempt(draft(), inboxItem(), DEVICE);
  assert.ok(made.ok && isUuidV4(made.attempt.captureId));
  assert.equal(createHumidityAttempt(EMPTY_HUMIDITY_DRAFT, inboxItem(), DEVICE, () => assert.fail("must not generate an id")).ok, false);
});

// ---- dispositivo ---------------------------------------------------------------------------------------------------------------

test("the technical device key is reused, not generated per attempt", () => {
  resetDeviceKeyMemory();
  const store = new Map([[DEVICE_KEY_STORAGE, DEVICE]]);
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => void store.set(k, v) };
  const first = getDeviceKey(storage, () => assert.fail("must not generate"));
  assert.equal(first, DEVICE);
  const a = createHumidityAttempt(draft(), inboxItem(), first);
  const b = createHumidityAttempt(draft(), inboxItem(), getDeviceKey(storage));
  assert.equal(a.attempt.payload.device_key, b.attempt.payload.device_key);
  resetDeviceKeyMemory();
});

// ---- intento pendiente ---------------------------------------------------------------------------------------------------------

test("a pending attempt is deeply immutable and keeps its own bobbin snapshot", () => {
  const item = inboxItem();
  const a = attempt({}, item);
  for (const level of [a, a.payload, a.payload.values, a.draft, a.bobbin]) assert.ok(Object.isFrozen(level));
  assert.throws(() => { "use strict"; a.bobbinId = "x"; });
  assert.throws(() => { "use strict"; a.payload.values.peso_seco_medio = "1"; });
  assert.equal(a.bobbinId, BOBBIN_ID);
  assert.notEqual(a.bobbin, item);
  item.bobbin.code = "99"; item.production.work_order.number = "OT-OTRA"; // el inbox cambia después
  assert.equal(a.bobbin.bobbin.code, "1");
  assert.equal(a.bobbin.production.work_order.number, "OT-2026-0001");
});

test("reopening shows the pending attempt's bobbin even if another one is selected", () => {
  const a = attempt({}, inboxItem(BOBBIN_ID, "1", "MP1"));
  const other = inboxItem(OTHER_BOBBIN_ID, "7", "MP3");
  assert.equal(bobbinToShow(a, other).bobbin.id, BOBBIN_ID);
  assert.equal(bobbinToShow(a, null).bobbin.code, "1");
  assert.equal(bobbinToShow(null, other).bobbin.id, OTHER_BOBBIN_ID);
  assert.equal(bobbinToShow(null, null), null);
  const notice = pendingNotice(a);
  for (const part of ["1", "MP1", "OT-2026-0001"]) assert.ok(notice.includes(part), part);
  assert.equal(notice.includes("MP3"), false);
});

// ---- envío --------------------------------------------------------------------------------------------------------------------

const never = () => assert.fail("must not be called");
const fail = (status, code) => ({ ok: false, kind: "x", status, code });

test("the POST goes to the bobbin of the attempt with exactly the attempt payload", async () => {
  const a = attempt();
  const calls = [];
  const out = await submitHumidityAttempt(a, { post: async (id, payload) => { calls.push([id, payload]); return { ok: true, status: 201, data: parseQualityCaptureSubmission(submission()) }; }, get: never });
  assert.equal(out.kind, "submitted");
  assert.deepEqual(calls, [[BOBBIN_ID, a.payload]]);
  assert.match(out.message, /Control de humedad registrado para la bobina 1 · Calidad sigue pendiente/);
});

test("200 already_submitted is a success", async () => {
  const out = await submitHumidityAttempt(attempt(), { post: async () => ({ ok: true, status: 200, data: parseQualityCaptureSubmission(submission({ created: false, already_submitted: true })) }), get: never });
  assert.deepEqual([out.kind, out.created, out.alreadySubmitted], ["submitted", false, true]);
  assert.match(out.message, /ya registrado/);
});

test("an uncertain response keeps the SAME capture_id and bobbin and reconciles with GET", async () => {
  const a = attempt();
  for (const status of [0, 500, 502, 503, 504, 200]) {
    const ids = [];
    const out = await submitHumidityAttempt(a, {
      post: async (id, payload) => { ids.push([id, payload.capture_id]); return fail(status); },
      get: async (captureId) => { ids.push(["get", captureId]); return { ok: true, status: 200, data: parseQualityCapture(capture()) }; },
    });
    assert.deepEqual([out.kind, out.reconciled], ["submitted", true], String(status));
    assert.deepEqual(ids, [[BOBBIN_ID, CAPTURE_ID], ["get", CAPTURE_ID]]);
  }
});

test("GET reconciliation: 404 -> not saved (retry the same POST), 401 -> session, other -> uncertain, other bobbin -> uncertain", async () => {
  const a = attempt();
  const run = (get) => submitHumidityAttempt(a, { post: async () => fail(0), get });
  assert.equal((await run(async () => fail(404))).kind, "not_saved");
  assert.deepEqual(await run(async () => fail(401)), { kind: "session" });
  assert.equal((await run(async () => fail(503))).kind, "uncertain");
  assert.equal((await run(async () => fail(500))).message, HUMIDITY_MESSAGES.uncertain);
  const otherBobbin = parseQualityCapture(capture({ bobbin: { id: OTHER_BOBBIN_ID, code: "7" } }));
  assert.equal((await run(async () => ({ ok: true, status: 200, data: otherBobbin }))).kind, "uncertain");
  const otherCapture = parseQualityCapture(capture({ id: "33333333-3333-4333-8333-333333333333" }));
  assert.equal((await run(async () => ({ ok: true, status: 200, data: otherCapture }))).kind, "uncertain");
});

test("an uncertain attempt never creates another capture_id across retries", async () => {
  const a = attempt();
  const sent = [];
  const responses = [fail(0), fail(503), { ok: true, status: 200, data: parseQualityCaptureSubmission(submission({ created: false, already_submitted: true })) }];
  const deps = { post: async (id, payload) => { sent.push([id, payload.capture_id, JSON.stringify(payload)]); return responses.shift(); }, get: async () => fail(404) };
  const kinds = [];
  for (let i = 0; i < 3; i++) kinds.push((await submitHumidityAttempt(a, deps)).kind);
  assert.deepEqual(kinds, ["not_saved", "not_saved", "submitted"]); // GET 404 tras un POST incierto: se reintenta el MISMO POST
  assert.equal(new Set(sent.map((s) => s.join("|"))).size, 1);
  assert.equal(sent[0][1], a.captureId);
});

test("401 means session lost", async () => {
  assert.deepEqual(await submitHumidityAttempt(attempt(), { post: async () => fail(401), get: never }), { kind: "session" });
});

test("422, 409, 403 and 404 are definitive and never reconcile", async () => {
  const cases = [[403, undefined, "forbidden"], [404, "BOBBIN_NOT_FOUND", "not_found"], [422, "CAPTURE_VALIDATION", "invalid"], [409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"],
    [409, "FORM_NOT_AVAILABLE", "form_unavailable"], [409, "UNSUPPORTED_FORM_DEFINITION", "conflict"], [409, undefined, "conflict"]];
  for (const [status, code, reason] of cases) {
    const out = await submitHumidityAttempt(attempt(), { post: async () => fail(status, code), get: never });
    assert.deepEqual([out.kind, out.reason], ["rejected", reason], `${status} ${code}`);
    assert.ok(out.message.length > 0);
  }
  assert.equal(humidityRejectionFor(500), null);
});

test("there is no stale-assignment concept for Calidad", () => {
  assert.equal(humidityRejectionFor(409, "ASSIGNMENT_STALE").reason, "conflict");
  assert.equal(humidityRejectionFor(409, "ASSIGNMENT_NOT_ACTIVE").reason, "conflict");
});

test("success message text", () => {
  assert.equal(humiditySuccessMessage(parseQualityCapture(capture())), "Control de humedad registrado para la bobina 1 · Calidad sigue pendiente");
});

// ---- parser de la respuesta -----------------------------------------------------------------------------------------------------

test("the response parser is defensive and returns a clean object", () => {
  const ok = parseQualityCaptureSubmission(submission({ extra: 1 }, { created_by: "u", values: { ...capture().values, interno: "x" } }));
  assert.ok(ok);
  assert.equal("created_by" in ok.capture, false);
  assert.equal("interno" in ok.capture.values, false);
  assert.equal(ok.capture.values.peso_humedo_medio, "101.000");
  assert.equal(parseQualityCapture(capture({ status: "closed" })).status, "closed");
  const noNotes = capture(); delete noNotes.values.observaciones;
  assert.equal("observaciones" in parseQualityCapture(noNotes).values, false);
  for (const bad of [null, "x", {}, capture({ status: "draft" }), capture({ revision: 0 }), capture({ form: { code: "VINTO-P1-03", version_number: 1, name: "x" } }), capture({ bobbin: null }),
    capture({ values: {} }), capture({ values: { ...capture().values, peso_seco_medio: "abc" } }), capture({ values: { ...capture().values, peso_seco_medio: undefined } }),
    capture({ values: { ...capture().values, observaciones: 5 } }), capture({ line: null }), capture({ work_order: null })]) assert.equal(parseQualityCapture(bad), null);
  assert.equal(parseQualityCaptureSubmission({ created: "yes", already_submitted: false, capture: capture() }), null);
  assert.equal(parseQualityCaptureSubmission(null), null);
});

// ---- identidad del intento (auditoría Q2) ----------------------------------------------------------------------------------------

const reconcileWith = (data) => submitHumidityAttempt(attempt(), { post: async () => fail(0), get: async () => ({ ok: true, status: 200, data }) });

test("captureMatchesHumidityAttempt compares id, bobbin, form and the exact source values", () => {
  const a = attempt();
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(capture()), a), true);
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(capture({ id: "33333333-3333-4333-8333-333333333333" })), a), false);
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(capture({ bobbin: { id: OTHER_BOBBIN_ID, code: "7" } })), a), false);
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(capture({ values: { ...capture().values, peso_humedo_medio: "101" } })), a), false); // "101" != "101.000": texto, no float
  const noNotes = capture(); delete noNotes.values.observaciones;
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(noNotes), a), false); // distinta presencia
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(noNotes), attempt({ observaciones: "" })), true);
  assert.equal(captureMatchesHumidityAttempt(parseQualityCapture(capture()), attempt({ observaciones: "" })), false);
});

test("GET with the same capture_id and bobbin but one different weight is uncertain", async () => {
  const out = await reconcileWith(parseQualityCapture(capture({ values: { ...capture().values, peso_seco_transversal: "93.81" } })));
  assert.equal(out.kind, "uncertain");
});

test("GET with the same capture_id and bobbin but different observations is uncertain", async () => {
  assert.equal((await reconcileWith(parseQualityCapture(capture({ values: { ...capture().values, observaciones: "otra" } })))).kind, "uncertain");
  const noNotes = capture(); delete noNotes.values.observaciones;
  assert.equal((await reconcileWith(parseQualityCapture(noNotes))).kind, "uncertain");
});

test("GET with exactly the attempt is submitted and reconciled", async () => {
  const out = await reconcileWith(parseQualityCapture(capture()));
  assert.deepEqual([out.kind, out.reconciled, out.created], ["submitted", true, false]);
});

test("a 2xx POST whose capture id differs is NOT a direct success", async () => {
  const gets = [];
  const other = parseQualityCaptureSubmission(submission({}, { id: "33333333-3333-4333-8333-333333333333" }));
  const out = await submitHumidityAttempt(attempt(), { post: async () => ({ ok: true, status: 201, data: other }), get: async (id) => { gets.push(id); return fail(503); } });
  assert.equal(out.kind, "uncertain");
  assert.deepEqual(gets, [CAPTURE_ID]); // se reconcilia por el capture_id DEL INTENTO
});

test("a 2xx POST with different values is NOT a direct success (it reconciles, and only the exact capture counts)", async () => {
  const changed = parseQualityCaptureSubmission(submission({}, { values: { ...capture().values, peso_humedo_comando: "100.5" } }));
  const uncertain = await submitHumidityAttempt(attempt(), { post: async () => ({ ok: true, status: 201, data: changed }), get: async () => ({ ok: true, status: 200, data: changed.capture }) });
  assert.equal(uncertain.kind, "uncertain");
  const proven = await submitHumidityAttempt(attempt(), { post: async () => ({ ok: true, status: 201, data: changed }), get: async () => ({ ok: true, status: 200, data: parseQualityCapture(capture()) }) });
  assert.deepEqual([proven.kind, proven.reconciled], ["submitted", true]);
  const contradictory404 = await submitHumidityAttempt(attempt(), { post: async () => ({ ok: true, status: 201, data: changed }), get: async () => fail(404) });
  assert.deepEqual(contradictory404, { kind: "uncertain", message: HUMIDITY_MESSAGES.uncertain }); // un 2xx contradictorio + GET 404 NO prueba "no guardado"
});

test("a 2xx POST with a different capture id followed by GET 404 stays uncertain (same attempt, same id)", async () => {
  const a = attempt();
  const sent = [];
  const other = parseQualityCaptureSubmission(submission({}, { id: "33333333-3333-4333-8333-333333333333" }));
  const out = await submitHumidityAttempt(a, { post: async (id, payload) => { sent.push(payload.capture_id); return { ok: true, status: 201, data: other }; }, get: async () => fail(404) });
  assert.deepEqual(out, { kind: "uncertain", message: HUMIDITY_MESSAGES.uncertain });
  assert.deepEqual(sent, [a.captureId]);
});

test("a contradictory 2xx: GET 401 is session, GET error or incompatible capture is uncertain", async () => {
  const changed = parseQualityCaptureSubmission(submission({}, { values: { ...capture().values, peso_seco_medio: "1" } }));
  const run = (get) => submitHumidityAttempt(attempt(), { post: async () => ({ ok: true, status: 200, data: changed }), get });
  assert.deepEqual(await run(async () => fail(401)), { kind: "session" });
  assert.equal((await run(async () => fail(503))).kind, "uncertain");
  assert.equal((await run(async () => fail(0))).kind, "uncertain");
  assert.equal((await run(async () => ({ ok: true, status: 200, data: changed.capture }))).kind, "uncertain");
});

test("an uncertain POST (network/5xx) followed by GET 404 is still not_saved", async () => {
  for (const status of [0, 500, 503]) {
    const out = await submitHumidityAttempt(attempt(), { post: async () => fail(status), get: async () => fail(404) });
    assert.deepEqual(out, { kind: "not_saved", message: HUMIDITY_MESSAGES.notSaved }, String(status));
  }
});

test("a decimal sent as a JSON number is rejected by the parser; text keeps its exact scale", () => {
  for (const number of [101, 101.0, 94.1]) {
    assert.equal(parseQualityCapture(capture({ values: { ...capture().values, peso_humedo_medio: number } })), null, String(number));
  }
  assert.equal(parseQualityCaptureSubmission(submission({}, { values: { ...capture().values, peso_seco_comando: 94.1 } })), null);
  assert.equal(parseQualityCapture(capture()).values.peso_humedo_medio, "101.000");
});

test("the bobbin snapshot of an attempt is deep-frozen", () => {
  const a = attempt();
  assert.throws(() => { "use strict"; a.bobbin.bobbin.code = "99"; });
  assert.throws(() => { "use strict"; a.bobbin.production.work_order.number = "OT-OTRA"; });
  assert.equal(a.bobbin.bobbin.code, "1");
  assert.equal(a.bobbin.production.work_order.number, "OT-2026-0001");
  const levels = [a, a.payload, a.payload.values, a.draft, a.bobbin, a.bobbin.bobbin, a.bobbin.bobbin.machine, a.bobbin.production, a.bobbin.production.shift,
    a.bobbin.production.work_order, a.bobbin.production.line, a.bobbin.production.line.article, a.bobbin.quality];
  for (const level of levels) assert.ok(Object.isFrozen(level));
});

test("deepFreeze freezes nested objects and arrays and returns the same object", () => {
  const dto = { a: { b: { c: 1 } }, list: [{ d: 2 }] };
  assert.equal(deepFreeze(dto), dto);
  for (const level of [dto, dto.a, dto.a.b, dto.list, dto.list[0]]) assert.ok(Object.isFrozen(level));
  assert.equal(deepFreeze(null), null);
  assert.equal(deepFreeze(5), 5);
});

// ---- estructura -----------------------------------------------------------------------------------------------------------------

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const page = read("../app/page.tsx");
const api = strip(read("../lib/vinto/quality-captures-api.ts"));
const lib = strip(read("../lib/vinto/quality-captures.ts"));
const component = strip(read("../components/vinto/quality-humidity-capture.tsx"));
const inbox = strip(read("../components/vinto/quality-bobbin-inbox.tsx"));

test("the API path uses the bobbin id, POST for the capture and GET for the reconciliation", () => {
  assert.match(api, /`\/api\/quality\/bobbins\/\$\{encodeURIComponent\(bobbinId\)\}\/captures`/);
  assert.match(api, /method: "POST"/);
  assert.match(api, /`\/api\/quality\/captures\/\$\{encodeURIComponent\(captureId\)\}`/);
  assert.equal(/PATCH|PUT|DELETE|release|reject|Authorization|document\.cookie|localStorage|sessionStorage/.test(api), false);
  assert.match(api, /requestJson/);
});

test("the humidity code never touches browser storage nor releases/rejects", () => {
  for (const [name, text] of [["lib", lib], ["api", api], ["component", component]]) {
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|vinto-ot|vinto-asg|setRecords|setReleases/.test(text), false, name);
  }
  assert.equal(/Liberar|Rechazar|liberar|rechazar|quality\.release/.test(component + lib), false);
  assert.match(component, /getDeviceKey\(\)/);
  assert.equal(/activeAssignment|useActiveAssignment|assignmentId/.test(component + lib), false);
});

test("the humidity values shown are derived and never sent", () => {
  assert.match(component, /computeHumidity\(draft\)/);
  assert.match(component, /createHumidityAttempt\(draft, shown, getDeviceKey\(\)\)/);
  assert.equal(/humedad_comando|promedio_humedad/.test(component + lib), false);
});

test("the Inbox has the 'Registrar humedad' action per bobbin", () => {
  assert.match(inbox, /Registrar humedad/);
  assert.match(inbox, /onRegisterHumidity\(i\)/);
  assert.match(page, /onRegisterHumidity=\{item => setSelectedQualityBobbin\(humidityAttempt \? humidityAttempt\.bobbin : item\)\}/);
});

test("Home opens the central humidity form from the selected bobbin, not from an assignment", () => {
  const branch = page.slice(page.indexOf("if (selectedQualityBobbin)"), page.indexOf("// F3 tampoco usa Capture/save()"));
  assert.match(branch, /<QualityHumidityCapture item=\{selectedQualityBobbin\}/);
  assert.match(branch, /attempt=\{humidityAttempt\} setAttempt=\{setHumidityAttempt\}/);
  assert.match(branch, /onSessionLost=\{sessionLost\}/);
  assert.equal(/save\(|setRecords|vinto-p1-records|activeAssignment|captureContext/.test(branch), false);
  assert.ok((page.match(/setSelectedQualityBobbin\(null\); setHumidityAttempt\(null\);/g) ?? []).length >= 2, "sessionLost clears the selection and the attempt");
});

test("after a success the form closes and the INBOX is refreshed so the bobbin stays pending", () => {
  const branch = page.slice(page.indexOf("if (selectedQualityBobbin)"), page.indexOf("// F3 tampoco usa Capture/save()"));
  assert.match(branch, /onSubmitted=\{\(\) => \{ setSelectedQualityBobbin\(null\); qualityInbox\.refresh\(\); \}\}/);
  assert.match(component, /setAttempt\(null\); toast\.success/);
  assert.equal(/filter|splice|slice\(/.test(branch), false, "the bobbin is not removed locally");
});

test("the legacy P1-19 and P1-20 cards are excluded from the Calidad cards and nothing else changes", () => {
  assert.match(page, /f\.area === "quality" && f\.id !== Q19_FORM_ID && f\.id !== Q20_FORM_ID && norm\(/); // P1-20 central (Q3.2-B)
  assert.equal((page.match(/Q19_FORM_ID/g) ?? []).length, 2); // import + filtro
  assert.equal((page.match(/Q20_FORM_ID/g) ?? []).length, 2); // import + filtro: ningún otro formulario se excluye
  assert.match(page, /f\.id === "form_19_control_de_humedad"/); // la definición legacy sigue existiendo
  assert.equal(/f\.id !== "form_18|f\.id !== "form_20|f\.id !== "form_21/.test(page), false);
});

test("the pending attempt survives Volver: the form is mounted with the attempt's bobbin", () => {
  assert.match(component, /bobbinToShow\(attempt, item\)/);
  assert.match(component, /useState<HumidityDraft>\(attempt \? \{ \.\.\.attempt\.draft \} : EMPTY_HUMIDITY_DRAFT\)/);
  assert.match(component, /pendingNotice\(attempt\)/);
  assert.match(component, /disabled=\{locked\}/);
});
