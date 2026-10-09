// node --test scripts/quality-physical-capture.test.mjs
// Q3.2-B · Captura central VINTO-P1-20 (Propiedades físicas de bobina): borrador, decimales exactos, promedios SOLO visuales, payload, intento
// pendiente inmutable, parser estricto, reconciliación POST/GET con red simulada (funciones inyectadas) y comprobaciones estructurales de la
// integración (Inbox, app/page.tsx, exclusión de la tarjeta legacy, P1-19 y Q3.1 intactos). No hay entorno de renderizado React en Node.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  AVERAGE_EXTRA_DIGITS, EMPTY_PHYSICAL_DRAFT, MAX_DECIMAL_CHARS, PHYSICAL_GROUPS, PHYSICAL_KEYS, PHYSICAL_LABELS, PHYSICAL_MESSAGES, PHYSICAL_UNITS, Q20_FORM_CODE, Q20_FORM_ID,
  averageLabel, averageOf, buildPhysicalPayload, captureMatchesPhysicalAttempt, createPhysicalAttempt, isUuidV4, newPhysicalCaptureId, normalizePhysicalDraft, parsePhysicalCapture,
  parsePhysicalCaptureSubmission, physicalAverages, physicalBobbinToShow, physicalDecimalText, physicalPendingNotice, physicalRejectionFor, submitPhysicalAttempt,
} from "../lib/vinto/quality-physical.ts";
import { Q19_FORM_CODE, decimalText, parseQualityCapture, parseQualityCaptureSubmission } from "../lib/vinto/quality-captures.ts";
import { humidityViewer, parseQualityBobbinHistory, physicalViewer } from "../lib/vinto/quality-history.ts";

const BOBBIN_ID = "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b";
const OTHER_BOBBIN_ID = "12121212-1212-4212-8212-121212121212";
const CAPTURE_ID = "0b0f8b6a-5b1e-4b8e-9a43-7d2f1a6c9e10";
const DEVICE = "99999999-9999-4999-8999-999999999999";
// Ejemplo técnico del contrato Q3.2-B (no son estándares de VINTO).
const SPEC_VALUES = {
  crepado: "15.500", gramaje: "18.250", resistencia_longitudinal_centro: "0.1180", resistencia_longitudinal_medio: "0.1200", resistencia_longitudinal_extremo: "0.1190",
  resistencia_transversal_centro: "0.0700", resistencia_transversal_medio: "0.0710", resistencia_transversal_extremo: "0.0690",
  espesor_centro: "0.100", espesor_medio: "0.101", espesor_extremo: "0.099",
};
const draft = (o = {}) => ({ ...EMPTY_PHYSICAL_DRAFT, ...SPEC_VALUES, ...o });
const inboxItem = (id = BOBBIN_ID, code = "1", machine = "MP1", order = "OT-2026-0001") => ({
  bobbin: { id, code, machine: { code: machine, name: machine }, management_start_year: 2026, sequence_number: Number(code), start_time: "12:00:00", end_time: "13:00:00", diameter_mm: "1200",
    weight_kg: "845.25", grammage_g_m2: "15.5", number_of_cuts: "3", notes: null },
  production: { capture_id: "40b936c3-387f-4399-a394-33642813ffbd", captured_at: "2026-10-07T16:00:00Z", operating_date: "2026-10-07", shift: { code: "DIA", name: "Día" },
    work_order: { id: "22222222-2222-4222-8222-222222222222", number: order },
    line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-DEV-001", article: { code: "M1-1031", description: "M1-BOBINA PH G-15.5" } } },
  quality: { status: "pending" },
});
const attempt = (o = {}, item = inboxItem(), id = CAPTURE_ID) => { const made = createPhysicalAttempt(draft(o), item, DEVICE, () => id); assert.ok(made.ok, JSON.stringify(made)); return made.attempt; };
const capture = (o = {}) => ({
  id: CAPTURE_ID, status: "submitted", revision: 1, captured_at: "2026-10-08T10:00:00Z", submitted_at: "2026-10-08T10:00:01Z",
  form: { code: "VINTO-P1-20", version_number: 1, name: "Propiedades físicas de bobina" }, bobbin: { id: BOBBIN_ID, code: "1" }, machine: { code: "MP1", name: "MP1" },
  shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-07", work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-DEV-001", article: { code: "M1-1031", description: "x" } },
  values: { ...SPEC_VALUES }, ...o,
});
const submission = (o = {}, c = {}) => ({ created: true, already_submitted: false, capture: capture(c), ...o });
const ok = (data, status = 200) => ({ ok: true, data, status });
const fail = (status, code, kind = "unavailable") => ({ ok: false, kind, status, ...(code ? { code } : {}) });
// Red simulada: registra cada llamada y devuelve las respuestas en orden.
function network(posts, gets = []) {
  const calls = { post: [], get: [] };
  return {
    calls,
    deps: {
      post: async (bobbinId, payload) => { calls.post.push({ bobbinId, payload }); const next = posts.shift(); assert.ok(next, "unexpected POST"); return next; },
      get: async (captureId) => { calls.get.push(captureId); const next = gets.shift(); assert.ok(next, "unexpected GET"); return next; },
    },
  };
}

// ---- contrato y borrador ---------------------------------------------------------------------------------------------------

test("the contract keys are exactly the eleven published decimals, in the bundle order", () => {
  assert.equal(Q20_FORM_CODE, "VINTO-P1-20");
  assert.equal(Q20_FORM_ID, "form_20_propiedades_fisicas_de_bobina");
  const bundle = JSON.parse(readFileSync(new URL("../backend/seed_data/forms/VINTO-P1-20.json", import.meta.url), "utf8"));
  assert.deepEqual([...PHYSICAL_KEYS, "observaciones"], bundle.fields.map((f) => f.key));
  assert.deepEqual(bundle.fields.filter((f) => f.value_type === "decimal" && f.required).map((f) => f.key), [...PHYSICAL_KEYS]);
  assert.equal(bundle.fields.find((f) => f.key === "observaciones").required, false);
  assert.deepEqual(PHYSICAL_GROUPS.map((g) => [g.title, [...g.keys]]), [
    ["Crepado y gramaje medido", ["crepado", "gramaje"]],
    ["Resistencia longitudinal", ["resistencia_longitudinal_centro", "resistencia_longitudinal_medio", "resistencia_longitudinal_extremo"]],
    ["Resistencia transversal", ["resistencia_transversal_centro", "resistencia_transversal_medio", "resistencia_transversal_extremo"]],
    ["Espesor", ["espesor_centro", "espesor_medio", "espesor_extremo"]],
  ]);
  // *_centro se ve como «Comando» (como el bundle) sin renombrar la clave; gramaje medido distinto del nominal
  for (const key of PHYSICAL_KEYS.filter((k) => k.endsWith("_centro"))) assert.match(PHYSICAL_LABELS[key], /Comando$/);
  assert.equal(PHYSICAL_LABELS.gramaje, "Gramaje medido por Calidad");
  assert.deepEqual(PHYSICAL_UNITS, { gramaje: "g/m²", espesor_centro: "mm", espesor_medio: "mm", espesor_extremo: "mm" }); // sin unidades de crepado ni resistencias
});

test("the eleven decimals are required and observaciones is optional (empty is omitted, text is trimmed)", () => {
  const values = normalizePhysicalDraft(draft()).values;
  assert.deepEqual(values, SPEC_VALUES);
  assert.equal(Object.prototype.hasOwnProperty.call(values, "observaciones"), false);
  assert.equal(normalizePhysicalDraft(draft({ observaciones: "   " })).values.observaciones, undefined);
  assert.equal(normalizePhysicalDraft(draft({ observaciones: "  borde húmedo " })).values.observaciones, "borde húmedo");
  for (const key of PHYSICAL_KEYS) {
    const check = normalizePhysicalDraft(draft({ [key]: "" }));
    assert.equal(check.ok, false, key);
    assert.match(check.errors.join(" "), new RegExp(PHYSICAL_LABELS[key].replace(/[·()]/g, ".")), key);
  }
  const all = normalizePhysicalDraft(EMPTY_PHYSICAL_DRAFT);
  assert.equal(all.ok, false);
  assert.equal(all.errors.length, 11);
  assert.equal(normalizePhysicalDraft(draft({ observaciones: "x".repeat(10_001) })).ok, false);
});

test("decimals are kept exactly as text; a decimal comma becomes a point; there are no functional ranges", () => {
  assert.equal(normalizePhysicalDraft(draft({ espesor_medio: "0,1180" })).values.espesor_medio, "0.1180");
  assert.equal(normalizePhysicalDraft(draft({ gramaje: " 18.250 " })).values.gramaje, "18.250");
  assert.equal(normalizePhysicalDraft(draft({ crepado: "0" })).values.crepado, "0");
  assert.equal(normalizePhysicalDraft(draft({ crepado: "-1.5" })).values.crepado, "-1.5"); // sin mínimos inventados
  const long = "1".repeat(MAX_DECIMAL_CHARS - 4) + ".123";
  assert.equal(normalizePhysicalDraft(draft({ crepado: long })).values.crepado, long);
  for (const bad of ["abc", "1.", ".5", "1e5", "NaN", "Infinity", "1,2,3", "1.2.3", "+1", "1 000", "1".repeat(MAX_DECIMAL_CHARS + 1)]) {
    assert.equal(normalizePhysicalDraft(draft({ espesor_extremo: bad })).ok, false, bad);
  }
  // misma regla de entrada que P1-19 (decimalText) en una tabla de casos
  for (const raw of ["1", "0,5", "1,25", "-3,0", " 7 ", "1.", "1e3", "", "x", "12,", "1,2,3", "0.100"]) assert.equal(physicalDecimalText(raw), decimalText(raw), raw);
});

test("the payload is exactly capture_id, form_code, device_key and the source values: no context, no averages", () => {
  const payload = buildPhysicalPayload(CAPTURE_ID, DEVICE, normalizePhysicalDraft(draft()).values);
  assert.deepEqual(payload, { capture_id: CAPTURE_ID, form_code: "VINTO-P1-20", device_key: DEVICE, values: SPEC_VALUES });
  assert.deepEqual(Object.keys(payload).sort(), ["capture_id", "device_key", "form_code", "values"]);
  const text = JSON.stringify(payload);
  for (const forbidden of ["promedio", "machine", "maquina", "turno", "shift", "fecha", "operating_date", "work_order", "pv", "article", "grammage", "nominal", "number_of_cuts", "cortes", "bobbin"]) {
    assert.equal(text.includes(`"${forbidden}`), false, forbidden);
  }
  for (const value of Object.values(payload.values)) assert.equal(typeof value, "string");
});

// ---- promedios visuales ---------------------------------------------------------------------------------------------------

test("averages: exact means keep the input scale, inexact ones are marked ≈ with two extra digits (provisional representation)", () => {
  assert.equal(AVERAGE_EXTRA_DIGITS, 2);
  assert.deepEqual(averageOf(["0.100", "0.101", "0.099"]), { kind: "exact", text: "0.100" });
  assert.deepEqual(averageOf(["0.1180", "0.1200", "0.1190"]), { kind: "exact", text: "0.1190" });
  assert.deepEqual(averageOf(["410.0", "398", "402.25"]), { kind: "approx", text: "403.4167" }); // 403.41666… -> 403.4167
  assert.deepEqual(averageOf(["0.0700", "0.0710", "0.0690"]), { kind: "exact", text: "0.0700" });
  assert.deepEqual(averageOf(["1", "1", "2"]), { kind: "approx", text: "1.33" });
  assert.deepEqual(averageOf(["1", "2", "2"]), { kind: "approx", text: "1.67" }); // 1.666… redondea la mitad lejos de cero
  assert.deepEqual(averageOf(["-1", "-2", "-2"]), { kind: "approx", text: "-1.67" });
  assert.deepEqual(averageOf(["-1", "1", "0"]), { kind: "exact", text: "0" });
  assert.deepEqual(averageOf(["0,5", "0,5", "0,5"]), { kind: "exact", text: "0.5" });
  assert.equal(averageLabel({ kind: "exact", text: "0.100" }), "0.100");
  assert.equal(averageLabel({ kind: "approx", text: "1.33" }), "≈ 1.33");
});

test("averages never show a fictitious zero, NaN or Infinity for incomplete, invalid or huge inputs", () => {
  for (const raws of [["", "1", "2"], ["1", "", ""], ["", "", ""], ["abc", "1", "2"], ["1e400", "1", "1"], ["Infinity", "1", "1"], ["NaN", "1", "1"], [], ["1".repeat(41), "1", "1"]]) {
    assert.deepEqual(averageOf(raws), { kind: "incomplete" }, JSON.stringify(raws));
    assert.equal(averageLabel(averageOf(raws)), "—");
  }
  const huge = "9".repeat(36) + ".99"; // 39 caracteres: más allá de la precisión de Number, exacto con BigInt
  const view = averageOf([huge, huge, huge]);
  assert.deepEqual(view, { kind: "exact", text: huge });
  const mixed = averageOf(["9".repeat(39), "0", "1"]);
  assert.equal(mixed.kind, "approx");
  assert.match(mixed.text, /^3{39}\.33$/);
  for (const text of [view.text, mixed.text]) assert.doesNotMatch(text, /NaN|Infinity|e\+/);
});

test("averages are display-only: computed from the draft, never part of the attempt or the payload", () => {
  const d = draft({ resistencia_longitudinal_medio: "" });
  const before = JSON.stringify(d);
  const averages = physicalAverages(d);
  assert.deepEqual(averages.resistencia_longitudinal, { kind: "incomplete" });
  assert.deepEqual(averages.resistencia_transversal, { kind: "exact", text: "0.0700" });
  assert.deepEqual(averages.espesor, { kind: "exact", text: "0.100" });
  assert.equal(JSON.stringify(d), before, "the draft is not modified");
  assert.equal(JSON.stringify(attempt().payload).includes("promedio"), false);
});

// ---- intento pendiente ----------------------------------------------------------------------------------------------------

test("every new logical attempt gets its own UUIDv4", () => {
  const ids = new Set(Array.from({ length: 50 }, () => newPhysicalCaptureId()));
  assert.equal(ids.size, 50);
  for (const id of ids) assert.ok(isUuidV4(id), id);
  const a = createPhysicalAttempt(draft(), inboxItem(), DEVICE).attempt, b = createPhysicalAttempt(draft(), inboxItem(), DEVICE).attempt;
  assert.notEqual(a.captureId, b.captureId);
  assert.equal(a.payload.capture_id, a.captureId);
  assert.equal(createPhysicalAttempt(EMPTY_PHYSICAL_DRAFT, inboxItem(), DEVICE, () => assert.fail("no id for an invalid draft")).ok, false);
});

test("the attempt freezes capture_id, bobbin_id, device_key, form_code, values and the bobbin snapshot, deeply", () => {
  const item = inboxItem();
  const a = attempt({}, item);
  assert.deepEqual([a.captureId, a.bobbinId, a.payload.device_key, a.payload.form_code], [CAPTURE_ID, BOBBIN_ID, DEVICE, "VINTO-P1-20"]);
  for (const node of [a, a.payload, a.payload.values, a.draft, a.bobbin, a.bobbin.bobbin, a.bobbin.bobbin.machine, a.bobbin.production, a.bobbin.production.line, a.bobbin.production.line.article]) {
    assert.ok(Object.isFrozen(node));
  }
  assert.throws(() => { "use strict"; a.payload.values.gramaje = "1"; }, TypeError);
  assert.throws(() => { "use strict"; a.bobbin.bobbin.code = "99"; }, TypeError);
  item.bobbin.code = "77"; item.production.work_order.number = "OT-OTRA"; // el inbox cambia después
  assert.equal(a.bobbin.bobbin.code, "1");
  assert.equal(a.bobbin.production.work_order.number, "OT-2026-0001");
});

test("two different bobbins never mix: a pending attempt always shows ITS bobbin", () => {
  const a = attempt({}, inboxItem(BOBBIN_ID, "1", "MP1", "OT-A"));
  const b = inboxItem(OTHER_BOBBIN_ID, "2", "MP3", "OT-B");
  assert.equal(physicalBobbinToShow(a, b).bobbin.id, BOBBIN_ID);
  assert.equal(physicalBobbinToShow(null, b).bobbin.id, OTHER_BOBBIN_ID);
  assert.equal(physicalBobbinToShow(null, null), null);
  assert.match(physicalPendingNotice(a), /bobina 1 \(MP1 · OT-A\)/);
  const other = attempt({ gramaje: "20" }, b, "11111111-1111-4111-8111-111111111111");
  assert.notEqual(other.captureId, a.captureId);
  assert.deepEqual([other.bobbinId, a.bobbinId], [OTHER_BOBBIN_ID, BOBBIN_ID]);
  assert.equal(a.payload.values.gramaje, "18.250");
});

// ---- parsers estrictos ----------------------------------------------------------------------------------------------------

test("parsePhysicalCapture accepts only a coherent P1-20 capture with the eleven decimals as text", () => {
  assert.deepEqual(parsePhysicalCapture(capture()).values, SPEC_VALUES);
  assert.equal(parsePhysicalCapture(capture({ values: { ...SPEC_VALUES, observaciones: "ok" } })).values.observaciones, "ok");
  assert.equal(parsePhysicalCapture(capture({ status: "closed", submitted_at: null })).status, "closed");
  const rejected = [
    capture({ form: { code: "VINTO-P1-19", version_number: 1, name: "Control de humedad" } }), capture({ form: { code: "VINTO-P1-20", version_number: 0, name: "x" } }),
    capture({ status: "draft" }), capture({ revision: 0 }), capture({ bobbin: { id: BOBBIN_ID } }), capture({ work_order: { id: "x" } }), capture({ machine: null }),
    capture({ values: { ...SPEC_VALUES, gramaje: 18.25 } }), capture({ values: { ...SPEC_VALUES, espesor_medio: "abc" } }), capture({ values: { ...SPEC_VALUES, observaciones: 5 } }),
    capture({ values: { ...SPEC_VALUES, promedio_espesor: "0.100" } }), capture({ values: { ...SPEC_VALUES, peso_humedo_comando: "1" } }), capture({ values: [] }), null, "x",
  ];
  for (const [i, raw] of rejected.entries()) assert.equal(parsePhysicalCapture(raw), null, String(i));
  for (const key of PHYSICAL_KEYS) { const v = { ...SPEC_VALUES }; delete v[key]; assert.equal(parsePhysicalCapture(capture({ values: v })), null, key); }
  assert.ok(parsePhysicalCaptureSubmission(submission()));
  assert.equal(parsePhysicalCaptureSubmission({ created: "yes", already_submitted: false, capture: capture() }), null);
  assert.equal(parsePhysicalCaptureSubmission(submission({}, { form: { code: "VINTO-P1-19", version_number: 1, name: "x" } })), null);
});

test("the P1-19 parsers are not relaxed: they still reject a P1-20 capture", () => {
  assert.equal(Q19_FORM_CODE, "VINTO-P1-19");
  assert.equal(parseQualityCapture(capture()), null);
  assert.equal(parseQualityCaptureSubmission(submission()), null);
});

test("captureMatchesPhysicalAttempt requires the same id, bobbin, form and every source value with its exact representation", () => {
  const a = attempt({ observaciones: "nota" });
  const same = parsePhysicalCapture(capture({ values: { ...SPEC_VALUES, observaciones: "nota" } }));
  assert.equal(captureMatchesPhysicalAttempt(same, a), true);
  assert.equal(captureMatchesPhysicalAttempt({ ...same, id: "33333333-3333-4333-8333-333333333333" }, a), false);
  assert.equal(captureMatchesPhysicalAttempt({ ...same, bobbin: { id: OTHER_BOBBIN_ID, code: "1" } }, a), false);
  assert.equal(captureMatchesPhysicalAttempt({ ...same, form: { ...same.form, code: "VINTO-P1-19" } }, a), false);
  for (const key of PHYSICAL_KEYS) assert.equal(captureMatchesPhysicalAttempt({ ...same, values: { ...same.values, [key]: `${same.values[key]}0` } }, a), false, key); // "0.100" ≠ "0.1000"
  const withoutNotes = { ...same.values };
  delete withoutNotes.observaciones;
  assert.equal(captureMatchesPhysicalAttempt({ ...same, values: withoutNotes }, a), false);
  assert.equal(captureMatchesPhysicalAttempt({ ...same, values: { ...same.values, observaciones: "otra" } }, a), false);
  assert.equal(captureMatchesPhysicalAttempt(parsePhysicalCapture(capture()), attempt()), true); // ambos sin observaciones
});

// ---- envío y reconciliación -------------------------------------------------------------------------------------------------

test("201 with the same capture is a success without reconciliation; the frozen payload is sent as is", async () => {
  const a = attempt();
  const net = network([ok(parsePhysicalCaptureSubmission(submission()), 201)]);
  const outcome = await submitPhysicalAttempt(a, net.deps);
  assert.deepEqual([outcome.kind, outcome.created, outcome.alreadySubmitted, outcome.reconciled], ["submitted", true, false, false]);
  assert.equal(net.calls.post.length, 1);
  assert.equal(net.calls.get.length, 0);
  assert.equal(net.calls.post[0].bobbinId, BOBBIN_ID);
  assert.equal(net.calls.post[0].payload, a.payload); // el mismo objeto congelado
  assert.match(outcome.message, /Calidad sigue pendiente/);
});

test("an identical retry is 200 already_submitted and reported as already registered", async () => {
  const net = network([ok(parsePhysicalCaptureSubmission(submission({ created: false, already_submitted: true })), 200)]);
  const outcome = await submitPhysicalAttempt(attempt(), net.deps);
  assert.deepEqual([outcome.kind, outcome.created, outcome.alreadySubmitted], ["submitted", false, true]);
  assert.match(outcome.message, /ya registradas/);
});

test("timeout, network loss, 5xx and an unreadable 2xx body are uncertain: they are reconciled by GET capture_id", async () => {
  for (const uncertain of [fail(0), fail(500), fail(502), fail(503), fail(504), fail(201)]) {
    const a = attempt();
    const net = network([uncertain], [ok(parsePhysicalCapture(capture()))]);
    const outcome = await submitPhysicalAttempt(a, net.deps);
    assert.deepEqual([outcome.kind, outcome.reconciled], ["submitted", true], JSON.stringify(uncertain));
    assert.deepEqual(net.calls.get, [CAPTURE_ID]);
  }
  for (const getResult of [fail(0), fail(503), fail(200), ok(parsePhysicalCapture(capture({ values: { ...SPEC_VALUES, gramaje: "1" } })))]) {
    const net = network([fail(0)], [getResult]);
    const outcome = await submitPhysicalAttempt(attempt(), net.deps);
    assert.equal(outcome.kind, "uncertain", JSON.stringify(getResult));
    assert.equal(outcome.message, PHYSICAL_MESSAGES.uncertain);
  }
});

test("GET 404 after an uncertain POST is 'not saved' and the retry keeps the SAME UUID and payload", async () => {
  const a = attempt();
  const first = network([fail(0)], [fail(404, "CAPTURE_NOT_FOUND", "not_found")]);
  assert.equal((await submitPhysicalAttempt(a, first.deps)).kind, "not_saved");
  const second = network([ok(parsePhysicalCaptureSubmission(submission()), 201)]);
  assert.equal((await submitPhysicalAttempt(a, second.deps)).kind, "submitted");
  assert.equal(second.calls.post[0].payload.capture_id, first.calls.post[0].payload.capture_id);
  assert.deepEqual(second.calls.post[0].payload, first.calls.post[0].payload);
  assert.equal(second.calls.post[0].payload, first.calls.post[0].payload);
});

test("a 2xx that does not prove identity is reconciled; a GET 404 then stays uncertain (never 'not saved')", async () => {
  const foreign = ok(parsePhysicalCaptureSubmission(submission({}, { bobbin: { id: OTHER_BOBBIN_ID, code: "2" } })), 201);
  const net = network([foreign], [fail(404, "CAPTURE_NOT_FOUND", "not_found")]);
  assert.equal((await submitPhysicalAttempt(attempt(), net.deps)).kind, "uncertain");
  const matched = network([ok(parsePhysicalCaptureSubmission(submission({}, { values: { ...SPEC_VALUES, crepado: "15.5" } })), 201)], [ok(parsePhysicalCapture(capture()))]);
  const reconciled = await submitPhysicalAttempt(attempt(), matched.deps); // "15.5" ≠ "15.500": el POST no prueba identidad, el GET sí
  assert.deepEqual([reconciled.kind, reconciled.reconciled], ["submitted", true]);
});

test("definitive answers: 401 session, 403, 404, 422, 409 FORM_NOT_AVAILABLE / CAPTURE_IDEMPOTENCY_CONFLICT; no GET and no new UUID", async () => {
  const cases = [
    [fail(401, undefined, "session"), { kind: "session" }],
    [fail(403, undefined, "forbidden"), { kind: "rejected", reason: "forbidden" }],
    [fail(404, "BOBBIN_NOT_FOUND", "not_found"), { kind: "rejected", reason: "not_found" }],
    [fail(422, "CAPTURE_VALIDATION", "invalid"), { kind: "rejected", reason: "invalid" }],
    [fail(409, "FORM_NOT_AVAILABLE", "conflict"), { kind: "rejected", reason: "form_unavailable" }],
    [fail(409, "CAPTURE_IDEMPOTENCY_CONFLICT", "conflict"), { kind: "rejected", reason: "idempotency" }],
    [fail(409, "OTRO", "conflict"), { kind: "rejected", reason: "conflict" }],
  ];
  for (const [response, expected] of cases) {
    let ids = 0;
    const a = createPhysicalAttempt(draft(), inboxItem(), DEVICE, () => { ids += 1; return CAPTURE_ID; }).attempt;
    const net = network([response]);
    const outcome = await submitPhysicalAttempt(a, net.deps);
    for (const [k, v] of Object.entries(expected)) assert.equal(outcome[k], v, `${response.status} ${response.code}`);
    assert.equal(net.calls.get.length, 0);
    assert.equal(ids, 1, "submitting never generates another capture_id");
  }
  assert.match(physicalRejectionFor(409, "FORM_NOT_AVAILABLE").message, /todavía no está publicado en esta base de datos o para esta máquina/);
  assert.match(physicalRejectionFor(409, "CAPTURE_IDEMPOTENCY_CONFLICT").message, /No se reenvió/);
  assert.equal(physicalRejectionFor(500), null);
  assert.equal(physicalRejectionFor(0), null);
  // 401 durante la reconciliación también es sesión perdida
  const net = network([fail(0)], [fail(401, undefined, "session")]);
  assert.equal((await submitPhysicalAttempt(attempt(), net.deps)).kind, "session");
});

// ---- Q3.2-C: el historial muestra P1-20 con su visor, siempre a través del parser estricto de esta captura -------------------

test("the history shows a P1-20 capture with its specific viewer, parsed by the strict P1-20 parser", () => {
  const viewers = { [Q19_FORM_CODE]: humidityViewer(parseQualityCapture), [Q20_FORM_CODE]: physicalViewer(parsePhysicalCapture) };
  const history = parseQualityBobbinHistory([capture({ captured_at: "2026-10-08T10:00:00Z" })], { id: BOBBIN_ID, code: "1" }, viewers);
  assert.equal(history.entries[0].kind, "physical");
  assert.deepEqual(history.entries[0].capture, parsePhysicalCapture(capture()));
  const invalid = parseQualityBobbinHistory([capture({ values: { ...SPEC_VALUES, gramaje: 18.25 } })], { id: BOBBIN_ID, code: "1" }, viewers);
  assert.equal(invalid.entries[0].kind, "invalid");
  // sin visor registrado P1-20 vuelve a ser solo metadatos (el registro es la única puerta)
  assert.equal(parseQualityBobbinHistory([capture()], { id: BOBBIN_ID, code: "1" }, { [Q19_FORM_CODE]: humidityViewer(parseQualityCapture) }).entries[0].kind, "unsupported");
});

// ---- estructura ----------------------------------------------------------------------------------------------------------------

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/ .*$/gm, "");
const page = read("../app/page.tsx");
const lib = strip(read("../lib/vinto/quality-physical.ts"));
const api = strip(read("../lib/vinto/quality-physical-api.ts"));
const component = strip(read("../components/vinto/quality-physical-capture.tsx"));
const inbox = strip(read("../components/vinto/quality-bobbin-inbox.tsx"));
const historyApi = strip(read("../lib/vinto/quality-history-api.ts"));

test("the API uses only the existing quality endpoints, with the strict P1-20 parsers and no storage", () => {
  assert.match(api, /`\/api\/quality\/bobbins\/\$\{encodeURIComponent\(bobbinId\)\}\/captures`, \{ method: "POST", body: payload, signal: AbortSignal\.timeout\(POST_TIMEOUT_MS\) \}, parsePhysicalCaptureSubmission\)/);
  assert.match(api, /`\/api\/quality\/captures\/\$\{encodeURIComponent\(captureId\)\}`, \{ signal: signal \?\? AbortSignal\.timeout\(GET_TIMEOUT_MS\) \}, parsePhysicalCapture\)/);
  assert.equal(/PATCH|PUT|DELETE|release|reject|Authorization|document\.cookie|localStorage|sessionStorage|fetch\(|parseQualityCapture/.test(api), false);
});

test("the pure module has type-only imports and no network, storage or Number coercion of source values", () => {
  const imports = lib.match(/^import .*$/gm) ?? [];
  assert.ok(imports.length > 0 && imports.every((line) => line.startsWith("import type ")), imports.join("\n"));
  assert.equal(/fetch\(|localStorage|sessionStorage|indexedDB|parseFloat|Number\((?!\.)|toFixed/.test(lib), false);
});

test("the form: decimal text inputs, locked while pending, double-click guard, device key, snapshot bobbin, averages only displayed", () => {
  assert.match(component, /type="text" inputMode="decimal"/);
  assert.match(component, /disabled=\{locked\}/);
  assert.match(component, /const locked = sending \|\| attempt !== null;/);
  assert.match(component, /if \(busy\.current \|\| !shown\) return;/);
  assert.match(component, /createPhysicalAttempt\(draft, shown, getDeviceKey\(\)\)/);
  assert.match(component, /setAttempt\(current\);/);
  assert.match(component, /physicalBobbinToShow\(attempt, item\)/);
  assert.match(component, /useState<PhysicalDraft>\(attempt \? \{ \.\.\.attempt\.draft \} : EMPTY_PHYSICAL_DRAFT\)/);
  assert.match(component, /physicalPendingNotice\(attempt\)/);
  assert.match(component, /submitPhysicalAttempt\(current, \{ post: submitPhysicalCapture, get: id => getPhysicalCapture\(id\) \}\)/);
  assert.match(component, /if \(outcome\.kind === "session"\) \{ setAttempt\(null\); return void onSessionLost\(\); \}/);
  assert.match(component, /physicalAverages\(draft\)/);
  assert.match(component, /averageLabel\(averages\[series\]\)/);
  assert.equal(/localStorage|sessionStorage|vinto-p1-records|setRecords|Number\(|parseFloat|toFixed|activeAssignment|assignmentId|Liberar|Rechazar|liberar|rechazar/.test(component), false);
  assert.equal(/QualityHumidityCapture|submitHumidityAttempt|createHumidityAttempt/.test(component), false);
});

test("the header is inherited (read-only) and separates nominal grammage from the measured one", () => {
  for (const label of ["Bobina", "Máquina", "OT", "Línea / PV", "Artículo", "Fecha operativa", "Turno", "Número de cortes (Producción)", "Gramaje nominal de Producción"]) {
    assert.ok(component.includes(`<Auto label="${label}"`), label);
  }
  assert.match(component, /grammageLabel\(bobbin\.grammage_g_m2\)/);
  assert.match(component, /value=\{bobbin\.number_of_cuts\}/);
  assert.equal((component.match(/<Input /g) ?? []).length, 1, "one Input template, rendered per measurement key");
  assert.match(component, /PHYSICAL_GROUPS\.map/);
});

test("the Inbox offers 'Registrar propiedades' per bobbin with that row's item", () => {
  assert.match(inbox, /onClick=\{\(\) => onRegisterProperties\(i\)\}>Registrar propiedades<\/Button>/);
  for (const kept of ["onRegisterHumidity(i)", "onViewHistory(i)", "Registrar humedad", "Ver controles", "Actualizar"]) assert.ok(inbox.includes(kept), kept);
});

test("Home: own selection and attempt for P1-20, opened from the inbox, gated by quality.capture, cleared on logout/session loss", () => {
  assert.match(page, /const \[selectedPhysicalBobbin, setSelectedPhysicalBobbin\] = useState<QualityBobbinInboxItem \| null>\(null\), \[physicalAttempt, setPhysicalAttempt\] = useState<PendingPhysicalAttempt \| null>\(null\);/);
  assert.match(page, /onRegisterProperties=\{item => setSelectedPhysicalBobbin\(physicalAttempt \? physicalAttempt\.bobbin : item\)\}/);
  assert.equal((page.match(/setSelectedQualityBobbin\(null\); setHumidityAttempt\(null\); setQualityHistory\(null\); setSelectedPhysicalBobbin\(null\); setPhysicalAttempt\(null\);/g) ?? []).length, 2);
  const branch = page.slice(page.indexOf("if (selectedPhysicalBobbin && canReadQualityInbox)"), page.indexOf("// Calidad · historial de controles"));
  assert.match(branch, /<QualityPhysicalCapture item=\{selectedPhysicalBobbin\} online=\{online\} attempt=\{physicalAttempt\} setAttempt=\{setPhysicalAttempt\}/);
  assert.match(branch, /back=\{\(\) => setSelectedPhysicalBobbin\(null\)\}/); // Volver NO borra el intento pendiente
  assert.match(branch, /onSubmitted=\{\(\) => \{ setSelectedPhysicalBobbin\(null\); qualityInbox\.refresh\(\); \}\}/);
  assert.match(branch, /onSessionLost=\{sessionLost\}/);
  assert.equal(/setHumidityAttempt|setSelectedQualityBobbin|save\(|setRecords|activeAssignment|captureContext/.test(branch), false);
  assert.ok(page.indexOf("if (selectedQualityBobbin)") < page.indexOf("if (selectedPhysicalBobbin && canReadQualityInbox)"));
  // el inbox (y por tanto la acción) solo existe con quality.capture
  assert.match(page, /qualityInbox=\{canReadQualityInbox \? <QualityBobbinInbox /);
});

test("the legacy local P1-20 card is excluded from the Calidad cards; other fronts are untouched", () => {
  assert.match(page, /front === "Calidad" \? f\.area === "quality" && f\.id !== Q19_FORM_ID && f\.id !== Q20_FORM_ID && norm\(/);
  assert.match(page, /: f\.area === "production" && norm\(f\.sector\)\.includes\(norm\(front\)\)/); // Rebobinado / Conversión / Bobinas sin cambios
  assert.match(page, /f\.id === "form_20_propiedades_fisicas_de_bobina"/); // la definición legacy sigue existiendo (no se borra)
});

test("the history API stays a read-only GET; its viewer registry maps P1-19 and P1-20 to their own strict parsers", () => {
  assert.match(historyApi, /const VIEWERS: HistoryViewers = \{ \[Q19_FORM_CODE\]: humidityViewer\(parseQualityCapture\), \[Q20_FORM_CODE\]: physicalViewer\(parsePhysicalCapture\) \};/);
  assert.equal(/method:|POST|PATCH|PUT|DELETE|localStorage|sessionStorage|submitPhysical|createPhysicalAttempt/.test(historyApi), false);
});
