// node --test scripts/p1-04-capture.test.mjs
// DEV-B2 · captura CENTRAL CANDIDATA de VINTO-P1-04 (Registro de consumo de fibra), construida desde la DEFINICIÓN original (9 manuales, 6 automáticos, 2 calculados) y no desde la pantalla legacy Fiber:
// contrato frente a form-definitions.ts, decimales, campos automáticos y calculados ausentes, flujo de envío, oferta según el backend, aislamiento por usuario y límites de alcance. Lógica PURA.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { offeredForms, parseAvailability, screenFor } from "../lib/vinto/availability.ts";
import { BOBINAS_CANDIDATE_SCREENS, candidateScreensFor, publishedCandidateScreens } from "../lib/vinto/bobinas-offers.ts";
import { P104, P104_AUTOMATIC, P104_CALCULATED, P104_FIELDS, P104_PENDING, P104_UNRESOLVED_AUTOMATIC, P1_04_CODE } from "../lib/vinto/p1-04.ts";
import { availabilityKey, candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", ASSIGNMENT = "7a1d9c0e-2b3f-4a5c-9d6e-8f7a6b5c4d3e", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const DRAFT = { fibra_corta_detalle: " corta ", fibra_larga_detalle: "larga", recorte_ph: " 12,5 ", recorte_servilleta: "3 bultos (texto)", recorte_toalla: "2", materia_prima_ph: "340", materia_prima_servilleta: "10", materia_prima_toalla: "7", observaciones: "" };
const legacy = FORM_DEFINITIONS.find((f) => f.id === "form_4_registro_de_consumo_de_fibra");
const isManual = (f) => f.source === "manual";

const envelope = (values) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: P1_04_CODE, version_number: 1, name: "x" }, machine: { code: "MP1", name: "MP1" },
  shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT }, work_order: { id: UUID, number: "OT-2026-0001" }, line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A", description: "d" } }, values });

test("el contrato son EXACTAMENTE los nueve campos manuales de la definición original: claves, orden, etiquetas, tipos y obligatoriedad", () => {
  assert.equal(legacy.fields.length, 17);
  const manual = legacy.fields.filter(isManual), automatic = legacy.fields.filter((f) => f.source === "automatic"), calculated = legacy.fields.filter((f) => f.source === "calculated");
  assert.deepEqual([manual.length, automatic.length, calculated.length], [9, 6, 2]);
  assert.deepEqual(P104_FIELDS.map((f) => f.key), manual.map((f) => f.key));
  assert.deepEqual(P104_FIELDS.map((f) => f.label), manual.map((f) => f.label));
  assert.deepEqual(P104_FIELDS.map((f) => f.required), manual.map((f) => f.required ?? f.requirement));
  assert.deepEqual(P104_FIELDS.map((f) => f.kind), manual.map((f) => f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : "text"));
  assert.deepEqual(P104_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key), ["recorte_ph", "materia_prima_ph"]); // exactamente dos decimales
  assert.equal(P104_FIELDS.find((f) => f.key === "observaciones").required, false);
  assert.deepEqual(automatic.map((f) => f.key), ["fecha", "turno", "maquina", "operador", "hora_inicio", "hora_fin"]);
  assert.deepEqual(calculated.map((f) => f.key), ["total_kg", "total_final"]);
  for (const f of [...automatic, ...calculated]) assert.equal(P104_FIELDS.some((x) => x.key === f.key), false, `${f.key} no se digita ni se envía`);
});

test("las brechas se documentan y se muestran: hora_inicio y hora_fin sin fuente confirmada, totales sin fórmula y la diferencia con el legacy", () => {
  assert.deepEqual([...P104_UNRESOLVED_AUTOMATIC], ["Hora inicio", "Hora fin"]);
  assert.deepEqual([...P104_CALCULATED], ["Total kg", "Total final"]);
  assert.equal(P104_AUTOMATIC.some((a) => /hora/i.test(a)), false, "las horas no figuran como resueltas por el contexto");
  const text = P104_PENDING.map((p) => `${p.label} ${p.pending}`).join(" ");
  assert.match(text, /Hora inicio y hora fin/);
  assert.match(text, /no se generan ni se sustituyen por la hora de envío/);
  assert.match(text, /no se calculan, no se guardan ni se muestran como oficiales/);
  assert.match(text, /Pantalla legacy/);
  const source = read("lib/vinto/p1-04.ts"), screen = read("components/vinto/candidate-form-capture.tsx"), candidates = read("lib/vinto/bobinas-candidates.ts");
  assert.match(source, /BRECHAS/);
  assert.match(screen, /candidate\.unresolved/);
  assert.match(screen, /candidate\.calculated/);
  assert.match(candidates, /unresolved: P104_UNRESOLVED_AUTOMATIC, calculated: P104_CALCULATED/);
});

test("el borrador valida los dos decimales estructuralmente y NO calcula totales ni genera horas", () => {
  const ok = P104.normalizeDraft(DRAFT);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.values, { fibra_corta_detalle: "corta", fibra_larga_detalle: "larga", recorte_ph: "12.5", recorte_servilleta: "3 bultos (texto)", recorte_toalla: "2", materia_prima_ph: "340", materia_prima_servilleta: "10", materia_prima_toalla: "7" });
  assert.equal(ok.values.recorte_servilleta, "3 bultos (texto)"); // el texto no se interpreta ni se convierte en número
  for (const key of ["total_kg", "total_final", "hora_inicio", "hora_fin", "fecha", "turno", "maquina", "operador"]) assert.equal(key in ok.values, false, key);
  for (const key of ["recorte_ph", "materia_prima_ph"]) {
    for (const bad of ["abc", "1e3", "12.5.1", "--1", "12 kg"]) assert.match(P104.normalizeDraft({ ...DRAFT, [key]: bad }).errors.join(" "), /debe ser un número decimal/, `${key} ${bad}`);
    assert.equal(P104.normalizeDraft({ ...DRAFT, [key]: "-3,50" }).values[key], "-3.50", "el signo y la escala se conservan: sin rangos inventados");
    assert.match(P104.normalizeDraft({ ...DRAFT, [key]: "  " }).errors.join(" "), /es obligatorio/);
  }
  // un campo de texto con número es texto: no se valida como decimal
  assert.equal(P104.normalizeDraft({ ...DRAFT, recorte_toalla: "texto libre" }).ok, true);
  const empty = P104.normalizeDraft(P104.emptyDraft());
  assert.equal(empty.errors.length, 8);
});

test("el payload es cerrado, sin campos automáticos ni calculados, y el parser estricto acepta solo lo contratado", () => {
  const { attempt } = P104.createAttempt(DRAFT, ASSIGNMENT, DEVICE, () => UUID);
  assert.deepEqual(Object.keys(attempt.payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(attempt.payload.form_code, P1_04_CODE);
  for (const key of ["total_kg", "total_final", "hora_inicio", "hora_fin", "fecha", "turno", "maquina", "operador"]) assert.equal(key in attempt.payload.values, false, key);
  assert.ok(Object.isFrozen(attempt.payload.values));
  const values = P104.normalizeDraft(DRAFT).values;
  assert.deepEqual(P104.parseCapture(envelope(values))?.values, values);
  assert.equal(P104.parseCapture(envelope({ ...values, recorte_ph: "12,5" })), null);
  for (const f of P104_FIELDS.filter((x) => x.required)) { const m = { ...values }; delete m[f.key]; assert.equal(P104.parseCapture(envelope(m)), null, f.key); }
  assert.equal(P104.parseCapture({ ...envelope(values), form: { code: "VINTO-P1-05", version_number: 1, name: "x" } }), null);
  assert.deepEqual(P104.parseCapture(envelope({ ...values, total_kg: "99" }))?.values, values, "un total que llegara en la respuesta se ignora: nunca se presenta");
});

const response = (status, data, code) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code });

test("flujo de envío: 201, 200 idempotente, rechazos, sesión y reconciliación con el MISMO capture_id", async () => {
  const values = P104.normalizeDraft(DRAFT).values, capture = P104.parseCapture(envelope(values));
  const created = P104.createAttempt(DRAFT, ASSIGNMENT, DEVICE, () => UUID).attempt;
  const ok = (c, a) => response(c ? 201 : 200, { created: c, already_submitted: a, capture });
  const first = await P104.submitAttempt(created, { post: async () => ok(true, false), get: async () => assert.fail() });
  assert.deepEqual([first.kind, first.created, first.reconciled], ["submitted", true, false]);
  const again = await P104.submitAttempt(created, { post: async () => ok(false, true), get: async () => assert.fail() });
  assert.deepEqual([again.created, again.alreadySubmitted], [false, true]);
  for (const [status, code, reason] of [[409, "ASSIGNMENT_STALE", "stale"], [409, "ASSIGNMENT_NOT_ACTIVE", "not_active"], [409, "FORM_NOT_AVAILABLE", "conflict"], [403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "CAPTURE_VALIDATION", "invalid"]]) {
    const out = await P104.submitAttempt(created, { post: async () => response(status, null, code), get: async () => assert.fail("un rechazo definitivo no reconcilia") });
    assert.deepEqual([out.kind, out.reason], ["rejected", reason], `${status} ${code}`);
  }
  assert.equal((await P104.submitAttempt(created, { post: async () => response(401), get: async () => assert.fail() })).kind, "session");
  const lost = { ok: false, kind: "network", status: 0 };
  const reconciled = await P104.submitAttempt(created, { post: async () => lost, get: async (id) => { assert.equal(id, UUID); return response(200, capture); } });
  assert.deepEqual([reconciled.kind, reconciled.reconciled], ["submitted", true]);
  assert.equal((await P104.submitAttempt(created, { post: async () => lost, get: async () => response(404, null) })).kind, "not_saved");
  assert.equal((await P104.submitAttempt(created, { post: async () => lost, get: async () => lost })).kind, "uncertain");
  const seen = [];
  for (let i = 0; i < 3; i++) await P104.submitAttempt(created, { post: async (p) => { seen.push(JSON.stringify(p)); return lost; }, get: async () => response(404, null) });
  assert.equal(new Set(seen).size, 1);
});

test("la ficha se ofrece solo si el backend la publica para la máquina, junto a P1-05 y P1-31, y el legacy no cambia el orden ni las demás pantallas", () => {
  const form = (code) => ({ code, name: code, version_number: 1 });
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  assert.deepEqual([...BOBINAS_CANDIDATE_SCREENS], ["p104", "p105", "p131"]);
  const real = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-06")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-06")] }]);
  assert.deepEqual([candidateScreensFor(real, "MP1"), publishedCandidateScreens(real)], [[], []], "configuración real: ninguna ficha candidata");
  const published = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-04"), form("VINTO-P1-05"), form("VINTO-P1-06"), form("VINTO-P1-31")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-04"), form("VINTO-P1-06")] }]);
  assert.deepEqual(candidateScreensFor(published, "MP1"), ["p104", "p105", "p131"]);
  assert.deepEqual(candidateScreensFor(published, "MP3"), ["p104"]);
  assert.deepEqual(publishedCandidateScreens(published), ["p104", "p105", "p131"]);
  assert.deepEqual(offeredForms("BOBINAS", published.sectors[0].machines[1]).map((o) => [o.form.code, o.screen]), [["VINTO-P1-04", "p104"], ["VINTO-P1-06", null]]);
  assert.equal(screenFor("BOBINAS", "VINTO-P1-04"), "p104");
  assert.equal(screenFor("REBOBINADO", "VINTO-P1-04"), null);
  assert.equal(screenFor("CONVERSION", "VINTO-P1-04"), null);
  assert.equal(screenFor("BOBINAS", "VINTO-P1-06"), null, "F6 conserva su pantalla propia");
});

test("aislamiento por usuario: el historial y la disponibilidad de P1-04 de la cuenta anterior nunca se presentan a otra", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  assert.notEqual(candidateHistoryKey("p104", sessionScope(A), 0), candidateHistoryKey("p104", sessionScope(B), 0));
  assert.notEqual(candidateHistoryKey("p104", sessionScope(A), 0), candidateHistoryKey("p105", sessionScope(A), 0));
  const stored = { key: candidateHistoryKey("p104", sessionScope(A), 0), attempt: 0, result: { ok: true, data: [{ id: "captura-de-A" }] } };
  assert.equal(deriveView(stored.key, true, 0, stored).status, "ready");
  const viewB = deriveView(candidateHistoryKey("p104", sessionScope(B), 0), true, 0, stored);
  assert.equal(viewB.status, "loading");
  assert.equal(JSON.stringify(viewB).includes("captura-de-A"), false);
  assert.equal(deriveView(availabilityKey(false, sessionScope(B)), true, 0, { ...stored, key: availabilityKey(false, sessionScope(A)) }).status, "loading");
  const page = read("app/page.tsx");
  assert.match(page, /candidateHistoryKey\("p104", scope, candRefresh\)/);
  assert.match(page, /p104: useResource<CandidateCapture\[\]>/);
});

test("alcance: la política real y seed_data no incluyen P1-04, el legacy no se toca y la pantalla central no usa almacenamiento local", () => {
  const capture = read("backend/app/capture_service.py"), sectors = read("backend/app/sectors.py"), manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  for (const file of ["lib/vinto/p1-04.ts", "lib/vinto/p1-04-api.ts", "lib/vinto/bobinas-candidates.ts"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records/.test(read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n")), false, file);
  const page = read("app/page.tsx");
  // con la ficha central publicada se oculta la tarjeta LOCAL equivalente (sin respaldo local de una captura central); sin publicación el comportamiento anterior no cambia
  assert.match(page, /const centralFibra = front === "Bobinas" && offeredCandidates\(bobAvailability\.view, machine\)\.includes\("p104"\)/);
  assert.match(page, /\.filter\(f => !\(centralFibra && f\.id === "form_4_registro_de_consumo_de_fibra"\)\)/);
  assert.match(page, /function Fiber\(/); // el componente legacy sigue existiendo: no se borra ni se migra
  assert.equal(/localStorage\.(removeItem|clear)/.test(page), false);
  assert.equal(/total_kg|total_final|hora_inicio|hora_fin/.test(read("components/vinto/candidate-form-capture.tsx")), false, "la pantalla genérica no conoce totales ni horas");
});
