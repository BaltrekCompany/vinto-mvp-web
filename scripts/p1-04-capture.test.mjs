// node --test scripts/p1-04-capture.test.mjs
// DEV-B2 · captura CENTRAL CANDIDATA de VINTO-P1-04 (Registro de consumo de fibra). MF-12B (versión 2): un registro por consumo (hora, material, origen, presentación, cantidad de UM y peso unitario real) con el subtotal solo en
// pantalla: contrato (versión 2 y campos de la versión 1 como solo lectura), catálogos del MVP anterior, validación estructural y de listas dependientes, subtotal exacto, flujo de envío, oferta según el backend, aislamiento
// por usuario y límites de alcance. Lógica PURA.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { offeredForms, parseAvailability, screenFor } from "../lib/vinto/availability.ts";
import { BOBINAS_CANDIDATE_SCREENS, candidateScreensFor, publishedCandidateScreens } from "../lib/vinto/bobinas-offers.ts";
import { P104, P104_DERIVED, P104_FIELDS, P104_LEGACY_FIELDS, P104_MATERIALS, P104_ORIGINS, P104_ORIGINS_BY_MATERIAL, P104_PENDING, P104_PRESENTATIONS, P104_PRESENTATIONS_BY_MATERIAL, P1_04_CODE } from "../lib/vinto/p1-04.ts";
import { productTwoDecimals } from "../lib/vinto/exact-decimal.ts";
import { availabilityKey, candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", ASSIGNMENT = "7a1d9c0e-2b3f-4a5c-9d6e-8f7a6b5c4d3e", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const DRAFT = { hora_consumo: "07:30", material: "Fibra larga", origen: "Laja", presentacion: "Caja", cantidad_um: "12", peso_unitario_real: " 25,5 ", observaciones: "" };
const legacy = FORM_DEFINITIONS.find((f) => f.id === "form_4_registro_de_consumo_de_fibra");
const isManual = (f) => f.source === "manual";

const envelope = (values, version = 2) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: P1_04_CODE, version_number: version, name: "x" }, machine: { code: "MP1", name: "MP1" },
  shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT }, work_order: { id: UUID, number: "OT-2026-0001" }, line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A", description: "d" } }, values });

test("MF-12B: el contrato de la versión 2 son siete campos (hora, material, origen, presentación, cantidad, peso unitario y observaciones) y los ocho de la versión 1 pasan a solo lectura", () => {
  assert.deepEqual(P104_FIELDS.map((f) => f.key), ["hora_consumo", "material", "origen", "presentacion", "cantidad_um", "peso_unitario_real", "observaciones"]);
  assert.deepEqual(P104_FIELDS.map((f) => f.kind), ["time", "select", "select", "select", "integer", "decimal", "textarea"]);
  assert.deepEqual(P104_FIELDS.map((f) => f.required), [true, true, true, true, true, true, false], "todo obligatorio salvo las observaciones");
  assert.deepEqual(P104_FIELDS.map((f) => f.label), ["Hora de consumo", "Material", "Origen", "Presentación", "Cantidad de UM", "Peso unitario real", "Observaciones"]);
  assert.equal(P104_FIELDS.find((f) => f.key === "peso_unitario_real").suffix, "kg");
  for (const f of P104_FIELDS.filter((x) => x.required)) assert.equal(f.sinceVersion, 2, `${f.key}: la versión 1 no lo exige`);
  assert.equal(P104_FIELDS.some((f) => /subtotal|total/i.test(f.key + f.label)), false, "el subtotal NO es un campo");
  // los ocho campos manuales de la versión 1 (definición original) son solo lectura y opcionales
  const v1 = legacy.fields.filter(isManual).map((f) => f.key).filter((k) => k !== "observaciones");
  assert.deepEqual(P104_LEGACY_FIELDS.map((f) => f.key), v1);
  assert.equal(P104_LEGACY_FIELDS.every((f) => f.required === false), true);
  assert.deepEqual(P104_LEGACY_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key), ["recorte_ph", "materia_prima_ph"]);
  for (const f of P104_LEGACY_FIELDS) assert.equal(P104.emptyDraft()[f.key], undefined, `${f.key} no se digita`);
});

test("MF-12B: los catálogos son los del MVP anterior, con textos literales, y las listas dependientes coinciden con la unión de las opciones", () => {
  assert.deepEqual([...P104_MATERIALS], ["Fibra larga", "Fibra corta", "Recorte"]);
  assert.deepEqual(P104_ORIGINS_BY_MATERIAL, { "Fibra larga": ["Laja", "Susano", "Dorado"], "Fibra corta": ["Laja", "Cóndor"], Recorte: ["Sauce Rancho", "Máquina"] });
  assert.deepEqual(P104_PRESENTATIONS_BY_MATERIAL, { "Fibra larga": ["Caja", "Fardo"], "Fibra corta": ["Caja", "Fardo"], Recorte: ["Fardo"] }, "Recorte solo se presenta en Fardo");
  assert.deepEqual([...P104_ORIGINS], ["Laja", "Susano", "Dorado", "Cóndor", "Sauce Rancho", "Máquina"]);
  assert.deepEqual([...P104_PRESENTATIONS], ["Caja", "Fardo"]);
  assert.deepEqual([...new Set(Object.values(P104_ORIGINS_BY_MATERIAL).flat())].sort(), [...P104_ORIGINS].sort());
  assert.deepEqual([...new Set(Object.values(P104_PRESENTATIONS_BY_MATERIAL).flat())].sort(), [...P104_PRESENTATIONS].sort());
  const by = Object.fromEntries(P104_FIELDS.map((f) => [f.key, f]));
  assert.deepEqual([by.origen.dependsOn.field, by.presentacion.dependsOn.field], ["material", "material"]);
  assert.equal(by.origen.dependsOn.allowed, P104_ORIGINS_BY_MATERIAL);
});

test("el borrador valida hora, listas (con su dependencia), entero y decimal; guarda los textos literales; no genera subtotal ni horas automáticas", () => {
  const ok = P104.normalizeDraft(DRAFT);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.values, { hora_consumo: "07:30", material: "Fibra larga", origen: "Laja", presentacion: "Caja", cantidad_um: "12", peso_unitario_real: "25.5" }, "coma decimal → punto; observaciones vacías no viajan; textos literales");
  for (const key of ["subtotal", "subtotal_kg", "total_kg", "hora_inicio", "hora_fin", "fecha", "turno", "maquina", "operador"]) assert.equal(key in ok.values, false, key);
  for (const key of ["hora_consumo", "material", "origen", "presentacion", "cantidad_um", "peso_unitario_real"]) assert.match(P104.normalizeDraft({ ...DRAFT, [key]: "" }).errors.join(" "), /es obligatorio/, key);
  assert.equal(P104.normalizeDraft({ ...DRAFT, observaciones: "" }).ok, true, "las observaciones son opcionales");
  for (const bad of ["24:00", "12:60", "7:30", "abc"]) assert.equal(P104.normalizeDraft({ ...DRAFT, hora_consumo: bad }).ok, false, bad);
  assert.equal(P104.normalizeDraft({ ...DRAFT, hora_consumo: "23:59" }).ok, true);
  for (const bad of ["1.5", "abc", "-1", "1e3", "12 UM"]) assert.match(P104.normalizeDraft({ ...DRAFT, cantidad_um: bad }).errors.join(" "), /número entero/, `cantidad ${bad}`);
  for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(P104.normalizeDraft({ ...DRAFT, peso_unitario_real: bad }).errors.join(" "), /número decimal/, `peso ${bad}`);
  assert.match(P104.normalizeDraft({ ...DRAFT, material: "Papel" }).errors.join(" "), /Material: elige una de las opciones/);
  for (const [material, origen] of [["Fibra larga", "Cóndor"], ["Fibra larga", "Máquina"], ["Fibra corta", "Susano"], ["Fibra corta", "Dorado"], ["Recorte", "Laja"], ["Recorte", "Cóndor"]]) {
    assert.match(P104.normalizeDraft({ ...DRAFT, material, origen, presentacion: "Fardo" }).errors.join(" "), /Origen: no corresponde a lo elegido en Material/, `${material}/${origen}`);
  }
  assert.match(P104.normalizeDraft({ ...DRAFT, material: "Recorte", origen: "Máquina", presentacion: "Caja" }).errors.join(" "), /Presentación: no corresponde a lo elegido en Material/);
  for (const [material, origen, presentacion] of [["Fibra larga", "Dorado", "Fardo"], ["Fibra corta", "Cóndor", "Caja"], ["Recorte", "Sauce Rancho", "Fardo"], ["Recorte", "Máquina", "Fardo"], ["Fibra corta", "Laja", "Fardo"]]) {
    assert.equal(P104.normalizeDraft({ ...DRAFT, material, origen, presentacion }).ok, true, `${material}/${origen}/${presentacion}`);
  }
  assert.equal(P104.normalizeDraft(P104.emptyDraft()).errors.length, 6);
});

test("el subtotal (cantidad × peso unitario, kg) es solo visual: exacto, con dos decimales, vacío si falta un valor, y nunca viaja ni se guarda", () => {
  const [subtotal] = P104_DERIVED;
  assert.deepEqual([subtotal.key, subtotal.label, subtotal.suffix], ["subtotal_kg", "Subtotal", "kg"]);
  assert.equal(subtotal.compute({ cantidad_um: "12", peso_unitario_real: "25.5" }), "306.00");
  assert.equal(subtotal.compute({ cantidad_um: "3", peso_unitario_real: "0.1" }), "0.30", "sin error de coma flotante (3 × 0.1)");
  assert.equal(subtotal.compute({ cantidad_um: "7", peso_unitario_real: "1.115" }), "7.81", "mitad hacia arriba: 7.805 → 7.81");
  assert.equal(subtotal.compute({ cantidad_um: "2", peso_unitario_real: "25,5" }), "51.00", "acepta la coma del borrador");
  assert.equal(subtotal.compute({ cantidad_um: "0", peso_unitario_real: "25.5" }), "0.00");
  assert.equal(subtotal.compute({ cantidad_um: "", peso_unitario_real: "25.5" }), null);
  assert.equal(subtotal.compute({ cantidad_um: "12" }), null);
  assert.equal(subtotal.compute({ cantidad_um: "abc", peso_unitario_real: "25.5" }), null);
  assert.equal(productTwoDecimals("99999999999", "99999999999.99"), "9999999999899000000000.01", "números grandes: sin pérdida de precisión");
  assert.equal(Object.keys(P104.emptyDraft()).some((k) => /subtotal/.test(k)), false);
  const { attempt } = P104.createAttempt({ ...DRAFT }, ASSIGNMENT, DEVICE, () => UUID);
  assert.equal(Object.keys(attempt.payload.values).some((k) => /subtotal|total/.test(k)), false);
  const values = P104.normalizeDraft(DRAFT).values;
  assert.deepEqual(P104.parseCapture(envelope({ ...values, subtotal_kg: "306.00" }))?.values, values, "un subtotal que llegara en la respuesta se ignora");
});

test("el payload es cerrado, sin subtotal ni automáticos, el parser exige los campos de la versión 2 y la versión 1 se lee con sus campos como solo lectura", () => {
  const { attempt } = P104.createAttempt(DRAFT, ASSIGNMENT, DEVICE, () => UUID);
  assert.deepEqual(Object.keys(attempt.payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(attempt.payload.form_code, P1_04_CODE);
  assert.ok(Object.isFrozen(attempt.payload.values));
  const values = P104.normalizeDraft(DRAFT).values;
  assert.equal(P104.parseCapture(envelope({ ...values, cantidad_um: 12 }))?.values.cantidad_um, "12", "el backend devuelve el entero como número JSON");
  for (const f of P104_FIELDS.filter((x) => x.required)) { const m = { ...values }; delete m[f.key]; assert.equal(P104.parseCapture(envelope(m)), null, f.key); }
  assert.equal(P104.parseCapture(envelope({ ...values, origen: "Otro" })), null, "un valor fuera de la lista no se interpreta");
  assert.equal(P104.parseCapture({ ...envelope(values), form: { code: "VINTO-P1-05", version_number: 2, name: "x" } }), null);
  const old = { fibra_corta_detalle: "corta", fibra_larga_detalle: "larga", recorte_ph: "12.5", recorte_servilleta: "3 bultos", recorte_toalla: "2", materia_prima_ph: "340", materia_prima_servilleta: "10", materia_prima_toalla: "7", observaciones: "ok" };
  const parsed = P104.parseCapture(envelope(old, 1));
  assert.ok(parsed, "la captura v1 se lee");
  assert.deepEqual(parsed.values, old, "todos los valores históricos intactos");
  assert.equal(P104.parseCapture(envelope(old, 2)), null, "una captura v2 sí exige los campos nuevos");
  assert.match(P104_PENDING.map((p) => p.pending).join(" "), /NO se guarda como campo/);
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
  assert.deepEqual([...BOBINAS_CANDIDATE_SCREENS], ["p104", "p105", "p131", "p102", "p101"]); // p102 / p101 se añadieron en DEV-B3 (no cambian el orden de las anteriores)
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
  // INT-02A (cambio de contrato): ya no existe la tarjeta LOCAL de fibra ni su ocultamiento condicional; las tarjetas de Bobinas son solo F3 y P1-06 y P1-04 solo aparece si el backend la publica
  assert.equal(/centralFibra|function Fiber\(/.test(page), false);
  assert.match(page, /const CENTRAL_BOBINAS_FORMS = FORM_DEFINITIONS\.filter\(f => f\.id === F3_FORM_ID \|\| f\.id === F6_FORM_ID\)/);
  assert.equal(/localStorage\.(removeItem|clear)/.test(page), false);
  assert.equal(/total_kg|total_final|hora_inicio|hora_fin/.test(read("components/vinto/candidate-form-capture.tsx")), false, "la pantalla genérica no conoce totales ni horas");
});
