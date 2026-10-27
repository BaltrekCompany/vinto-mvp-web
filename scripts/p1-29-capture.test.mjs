// node --test scripts/p1-29-capture.test.mjs
// VINTO-P1-29 «Producción Tubetera» (M3-B), ficha CANDIDATA: la especificación coincide con la definición legacy (claves y tipos), validación ESTRUCTURAL, payload sin contexto ni ids,
// intento pendiente inmutable con filas, separación de parsers entre formularios, flujo 201/200/409/422/401/403/404 con reconciliación, cliente HTTP con `fetch` simulado y el componente
// renderizado. Nada de lo que se prueba decide reglas industriales (catálogo de tubetes, unidad en metros, visto bueno, alcance de los grupos): siguen pendientes.
// MF-10: la versión 2 retira «Peso fardo» y «Peso» por formato, renombra «Formato de tubete», muestra el espesor en mm, guarda los diámetros como texto y añade las horas; la versión 1 se lee con su definición (último bloque).
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { addRow, removeRow, setCell } from "../lib/vinto/capture-groups.ts";
import { parseCapture as parseF6 } from "../lib/vinto/captures.ts";
import { parseP110Capture } from "../lib/vinto/p1-10.ts";
import {
  CONTEXT_NOTES, MAX_TEXT_LENGTH, P129_GROUPS, P129_GROUPS_V1, P129_PENDING, P129_SIMPLE_FIELDS, P1_29_CODE, buildP129Payload, createP129Attempt, emptyP129Draft, isIsoDate, normalizeP129Draft,
  parseP129Capture, parseP129List, parseP129Submission, reconcileP129, submitP129Attempt,
} from "../lib/vinto/p1-29.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-p129-test-${process.pid}`);
const aliasPlugin = {
  name: "at-alias", enforce: "pre",
  resolveId(source) {
    if (!source.startsWith("@/")) return null;
    const base = `${root}/${source.slice(2)}`;
    for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) if (existsSync(candidate)) return candidate;
    return null;
  },
};
async function bundle(entry, name) {
  const output = await build({
    configFile: false, root, logLevel: "error", mode: "production", plugins: [aliasPlugin], oxc: { jsx: { runtime: "automatic" } },
    build: { write: false, ssr: join(root, entry), minify: false, target: "node22", rollupOptions: { output: { format: "es" } } },
  });
  const chunk = (Array.isArray(output) ? output[0] : output).output.find((item) => item.type === "chunk");
  const file = join(workDir, `${name}.mjs`);
  writeFileSync(file, chunk.code);
  return import(pathToFileURL(file).href);
}
let api, f6api, component, React, server;
before(async () => {
  process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8190";
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [api, f6api, component] = await Promise.all([bundle("lib/vinto/p1-29-api.ts", "p129api"), bundle("lib/vinto/captures-api.ts", "f6api"), bundle("components/vinto/p1-29-capture.tsx", "comp")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444", DEVICE = "99999999-9999-4999-8999-999999999999", ID = "11111111-1111-4111-8111-111111111111";
let n = 0;
const key = () => `k${++n}`;
const rodela = (id, weight) => ({ rodela_papel_kraft_identificacion: id, rodela_papel_kraft_peso_kg: weight });
const formato = (o = {}) => ({ formato_tipo_de_tubete: "FORMATO-FICTICIO-1", cantidad_tubetes_producidos_por_formato: "120 (texto)", merma_kg_por_formato: "0.500", diametro_interno_mm_por_formato: "77-78",
  diametro_externo_mm_por_formato: "80-81", cantidad_de_hojas_por_formato: "4", espesor_mm_por_formato: "1.800", ...o });
const formatoV1 = (o = {}) => ({ ...formato(), diametro_interno_mm_por_formato: "38.10", diametro_externo_mm_por_formato: "42.00", peso_kg_por_formato: "6.750", ...o }); // versión 1: diámetros decimales y peso por formato
const VALUES = { fecha_de_produccion: "2026-01-15", lote_de_produccion: "LOTE-FICTICIO-001", hora_inicio: "06:30:00", hora_fin: "14:45:00", pegamento_total_kg: "12,5 (texto)", numero_mrp_del_sistema: "MRP-FICTICIO", _groups: { rodelas: [rodela("R-A", "10.250"), rodela("R-B", "8.100")], formatos: [formato(), formato({ formato_tipo_de_tubete: "FORMATO-FICTICIO-2", cantidad_tubetes_producidos_por_formato: "80" })] } };
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "TUBETERA", name: "Tubetera (prueba)" }, shift: { code: "FICT_DIA", name: "Día (ficticio)" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" }, line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "A", description: "B" } }, values,
});
const p129 = (id = ID, values = VALUES, version = 2) => ({ ...envelope(id, P1_29_CODE, values), form: { code: P1_29_CODE, version_number: version, name: "Formulario" } });
const draftOf = (o = {}) => {
  const draft = emptyP129Draft(key);
  const rows = (spec, list) => list.map((cells) => ({ rowKey: key(), cells: Object.fromEntries(spec.fields.map((f) => [f.key, cells[f.key] ?? ""])) }));
  return { simple: { ...draft.simple, fecha_de_produccion: "2026-01-15", lote_de_produccion: "LOTE-FICTICIO-001", hora_inicio: "06:30", hora_fin: "14:45", pegamento_total_kg: " 12,5 (texto) ", numero_mrp_del_sistema: "MRP-FICTICIO", observaciones: "", ...o.simple },
    groups: { rodelas: rows(P129_GROUPS[0], o.rodelas ?? [rodela("R-A", "10,250"), rodela("R-B", "8.100")]), formatos: rows(P129_GROUPS[1], o.formatos ?? [formato({ merma_kg_por_formato: "0,500" }), formato({ formato_tipo_de_tubete: "FORMATO-FICTICIO-2" })]) } };
};

// ---- la especificación coincide con la definición legacy -------------------------------------------------------------------------------------------

test("the candidate specification (v2) is the 17 manual legacy fields minus the two retired weights plus the two hours, with the approved type changes, and none of the 3 automatic ones", () => {
  const legacy = FORM_DEFINITIONS.find((form) => form.code === P1_29_CODE);
  assert.equal(legacy.fields.length, 20);
  const manual = legacy.fields.filter((f) => f.source === "manual"), automatic = legacy.fields.filter((f) => f.source === "automatic");
  assert.equal(manual.length, 17);
  assert.deepEqual(automatic.map((f) => f.key).sort(), ["operador", "turno", "visto_bueno_responsable"]);
  const spec = [...P129_SIMPLE_FIELDS.map((f) => ({ key: f.key, kind: f.kind, required: f.required })), ...P129_GROUPS.flatMap((g) => g.fields.map((f) => ({ key: f.key, kind: f.kind, required: f.required })))];
  assert.equal(spec.length, 17);
  const RETIRED = ["peso_fardo", "peso_kg_por_formato"], NEW = ["hora_inicio", "hora_fin"], TEXT_NOW = ["diametro_interno_mm_por_formato", "diametro_externo_mm_por_formato"];
  assert.deepEqual(spec.map((f) => f.key).sort(), [...manual.map((f) => f.key).filter((k) => !RETIRED.includes(k)), ...NEW].sort());
  for (const field of manual.filter((f) => !RETIRED.includes(f.key))) {
    const s = spec.find((x) => x.key === field.key);
    assert.equal(s.kind, TEXT_NOW.includes(field.key) ? "text" : field.type, field.key); // text stays text (quantities), decimal stays decimal (MF-10: los diámetros pasan a texto), date stays date, textarea stays textarea
    assert.equal(s.required, field.required, field.key);
  }
  for (const key of NEW) assert.deepEqual(spec.find((x) => x.key === key), { key, kind: "time", required: true });
  for (const key of RETIRED) assert.equal(spec.some((f) => f.key === key), false, `${key} ya no se solicita`);
  for (const key of ["operador", "turno", "visto_bueno_responsable"]) assert.equal(spec.some((f) => f.key === key), false, key); // no simulated manual fields
  assert.equal(new Set(spec.map((f) => f.key)).size, 17);
});

test("the legacy definition is untouched and the known discrepancies are documented, not corrected (MF-10: espesor en mm; sin metros)", () => {
  const legacy = FORM_DEFINITIONS.find((form) => form.code === P1_29_CODE);
  assert.deepEqual(legacy.allowedMachineIds, ["tubertera"]); // the legacy name is NOT silently changed to TUBETERA
  assert.equal(legacy.machineLabel, "Tubertera");
  assert.equal(legacy.fields.find((f) => f.key === "espesor_mm_por_formato").unit, "kg"); // legacy metadata: mm-named field, kg unit
  assert.equal(P129_GROUPS[1].fields.find((f) => f.key === "espesor_mm_por_formato").unit, "mm"); // MF-10: la unidad aprobada del espesor es mm
  assert.equal(P129_GROUPS[1].fields.find((f) => f.key === "formato_tipo_de_tubete").kind, "text"); // no approved catalog: free text
  assert.equal(P129_GROUPS[1].fields.find((f) => f.key === "formato_tipo_de_tubete").label, "Formato de tubete");
  assert.deepEqual(P129_GROUPS.flatMap((g) => g.fields).filter((f) => f.unit === "m" || f.unit === "M").map((f) => f.key), [], "la unidad en metros NO está confirmada: no se añade «m» a ningún campo");
  assert.deepEqual(P129_PENDING.map((p) => p.id), ["maquina", "espesor", "diametros", "horas", "catalogo", "visto-bueno", "alcance"]);
  assert.deepEqual(Object.keys(CONTEXT_NOTES), ["operador", "turno", "visto_bueno_responsable"]);
  assert.ok(P129_PENDING[0].detail.includes("tubertera") && P129_PENDING[0].detail.includes("TUBETERA"));
  assert.ok(P129_PENDING[1].detail.includes("mm") && P129_PENDING[1].detail.includes("METROS"));
});

// ---- parsers: solo P1-29 ------------------------------------------------------------------------------------------------------------------------

test("P1-29 parsers accept only P1-29 captures and every other form's parser rejects them", () => {
  const parsed = parseP129Capture(p129());
  assert.deepEqual(parsed.values._groups.rodelas.map((r) => r.rodela_papel_kraft_peso_kg), ["10.250", "8.100"]); // decimals stay text
  assert.equal(parseP129Capture(envelope(ID, "VINTO-P1-06", VALUES)), null);
  assert.equal(parseP129Capture(envelope(ID, "VINTO-P1-10", VALUES)), null);
  assert.equal(parseP129Capture(envelope(ID, "VINTO-TEST-GRP-1", VALUES)), null);
  assert.equal(parseP129Capture(envelope(ID, "vinto-p1-29", VALUES)), null);
  assert.equal(parseF6(p129()), null);
  assert.equal(parseP110Capture(p129()), null);
  assert.equal(parseP129List([p129(), envelope(ID, "VINTO-P1-06", { cantidad_fardos: 1, punto_merma: "a", tipo_producto: "b", peso_kg: "1" })]), null);
  assert.equal(parseP129List([p129(), p129("33333333-3333-4333-8333-333333333333")]).length, 2);
  assert.equal(parseP129Submission({ created: true, already_submitted: false, capture: envelope(ID, "VINTO-P1-06", VALUES) }), null);
});

test("P1-29 parsing is strict about the values, the groups and their declared cardinality", () => {
  const without = (patch) => ({ ...VALUES, ...patch });
  for (const bad of [without({ fecha_de_produccion: "15/01/2026" }), without({ lote_de_produccion: "" }), without({ pegamento_total_kg: 12.5 }), without({ observaciones: 3 }),
    without({ _groups: { rodelas: VALUES._groups.rodelas } }), without({ _groups: { ...VALUES._groups, rodelas: [] } }), // min_rows = 1 (test hypothesis)
    without({ _groups: { ...VALUES._groups, formatos: [formato({ cantidad_de_hojas_por_formato: 4 })] } }), without({ _groups: { ...VALUES._groups, extra: [] } }),
    without({ _groups: { ...VALUES._groups, rodelas: [{ ...rodela("R", "1"), id: "x" }] } }), without({ _groups: { ...VALUES._groups, rodelas: [rodela("R", "abc")] } })]) {
    assert.equal(parseP129Capture(p129(ID, bad)), null, JSON.stringify(bad).slice(0, 120));
  }
  const simpleOnly = { ...VALUES };
  delete simpleOnly._groups;
  assert.equal(parseP129Capture(p129(ID, simpleOnly)), null);
  assert.notEqual(parseP129Capture(p129(ID, { ...VALUES, observaciones: "x" })), null);
});

// ---- validación estructural y payload ------------------------------------------------------------------------------------------------------------

test("validation: trims, keeps quantities as text and decimals as dotted text, and invents no format, range, catalog or conversion", () => {
  const check = normalizeP129Draft(draftOf());
  assert.equal(check.ok, true);
  assert.equal(check.values.pegamento_total_kg, "12,5 (texto)"); // trimmed, otherwise untouched (text)
  assert.equal(check.values.fecha_de_produccion, "2026-01-15");
  assert.equal("observaciones" in check.values, false); // optional and blank
  assert.deepEqual(check.values._groups.rodelas, [rodela("R-A", "10.250"), rodela("R-B", "8.100")]); // comma -> dot, TEXT (never a float: the trailing zero survives)
  assert.equal(check.values._groups.formatos[0].merma_kg_por_formato, "0.500");
  assert.equal(check.values._groups.formatos[0].cantidad_tubetes_producidos_por_formato, "120 (texto)"); // a text quantity is NOT turned into an integer
  assert.equal(check.values._groups.formatos[0].cantidad_de_hojas_por_formato, "4");
  assert.equal(typeof check.values._groups.formatos[0].cantidad_de_hojas_por_formato, "string");
  assert.equal(normalizeP129Draft(draftOf({ simple: { pegamento_total_kg: "cualquier texto" } })).ok, true); // no range/format rule for the text quantities
  assert.equal(check.values.hora_inicio, "06:30");
  assert.equal(check.values.hora_fin, "14:45");
  assert.equal("peso_fardo" in check.values || "peso_kg_por_formato" in check.values._groups.formatos[0], false, "MF-10: ya no se solicitan");
  assert.equal(normalizeP129Draft(draftOf({ formatos: [formato({ formato_tipo_de_tubete: "tipo inventado" })] })).ok, true); // free text: there is no approved catalog
  assert.equal(normalizeP129Draft(draftOf({ rodelas: [rodela("R", "123456789.123456789")] })).values._groups.rodelas[0].rodela_papel_kraft_peso_kg, "123456789.123456789");
});

test("validation errors name the field or the row and block the attempt", () => {
  const empty = normalizeP129Draft(emptyP129Draft(key));
  assert.equal(empty.ok, false);
  const simpleErrors = empty.errors.filter((e) => e.group === "").map((e) => e.message);
  assert.deepEqual(simpleErrors.sort(), ["Fecha de producción: es obligatorio.", "Lote de producción: es obligatorio.", "Número MRP del sistema: es obligatorio.", "Hora inicio: es obligatorio.", "Hora fin: es obligatorio.", "Pegamento total: es obligatorio."].sort());
  assert.ok(empty.errors.some((e) => e.group === "rodelas" && e.row === 1 && e.field === "rodela_papel_kraft_identificacion"));
  assert.ok(empty.errors.some((e) => e.group === "formatos" && e.row === 1 && e.field === "espesor_mm_por_formato"));
  const bad = normalizeP129Draft(draftOf({ simple: { fecha_de_produccion: "2026-02-30" }, rodelas: [rodela("R-A", "10,250"), rodela("R-B", "ocho")], formatos: [formato({ espesor_mm_por_formato: "1e3" })] }));
  assert.equal(bad.ok, false);
  assert.ok(bad.errors.some((e) => e.field === "fecha_de_produccion" && /fecha válida/.test(e.message)));
  assert.ok(bad.errors.some((e) => e.group === "rodelas" && e.row === 2 && e.field === "rodela_papel_kraft_peso_kg" && /decimal/.test(e.message)));
  assert.ok(bad.errors.some((e) => e.group === "formatos" && e.row === 1 && e.field === "espesor_mm_por_formato"));
  assert.equal(normalizeP129Draft(draftOf({ rodelas: [] })).ok, false); // minimum rows (test hypothesis)
  assert.equal(normalizeP129Draft(draftOf({ simple: { lote_de_produccion: "x".repeat(MAX_TEXT_LENGTH + 1) } })).ok, false);
  for (const badHour of ["24:00", "12:60", "7:30", "abc", "1230"]) assert.ok(normalizeP129Draft(draftOf({ simple: { hora_fin: badHour } })).errors.some((e) => e.field === "hora_fin" && /hora válida HH:MM/.test(e.message)), badHour);
  for (const [start, end] of [["00:00", "23:59"], ["23:30", "00:15"], ["10:00", "09:00"]]) assert.equal(normalizeP129Draft(draftOf({ simple: { hora_inicio: start, hora_fin: end } })).ok, true, `${start}-${end}: sin validación de orden ni de cruce de día`);
  assert.equal(isIsoDate("2026-02-29"), false);
  assert.equal(isIsoDate("2028-02-29"), true);
});

test("the payload keeps values._groups and carries no internal row ids, no context and none of the pending automatic fields", () => {
  const made = createP129Attempt(draftOf(), ASSIGNMENT, DEVICE, () => ID);
  assert.equal(made.ok, true);
  const { payload } = made.attempt;
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(payload.form_code, "VINTO-P1-29");
  assert.deepEqual(Object.keys(payload.values._groups), ["rodelas", "formatos"]);
  const text = JSON.stringify(payload);
  assert.equal(/rowKey|row_number|group_row|field_group|"id"/.test(text), false);
  for (const key of ["operador", "turno", "visto_bueno_responsable", "maquina", "responsable", "firma"]) assert.equal(text.includes(`"${key}"`), false, key);
  assert.deepEqual(buildP129Payload(ID, ASSIGNMENT, DEVICE, {}).values, {});
});

test("an attempt is immutable: adding, removing or editing rows afterwards never changes it", () => {
  const draft = draftOf();
  const { attempt } = createP129Attempt(draft, ASSIGNMENT, DEVICE, () => ID);
  const snapshot = JSON.stringify(attempt);
  const [rodelas, formatos] = [P129_GROUPS[0], P129_GROUPS[1]];
  const moved = setCell(addRow(rodelas, removeRow(rodelas, draft.groups.rodelas, draft.groups.rodelas[0].rowKey), key), draft.groups.rodelas[1].rowKey, "rodela_papel_kraft_identificacion", "CAMBIADA");
  assert.equal(moved.length, 2);
  addRow(formatos, draft.groups.formatos, key);
  draft.groups.rodelas[0].cells.rodela_papel_kraft_identificacion = "MUTADA";
  draft.simple.lote_de_produccion = "MUTADO";
  assert.equal(JSON.stringify(attempt), snapshot);
  assert.ok(Object.isFrozen(attempt.payload.values._groups.rodelas[0]) && Object.isFrozen(attempt.draft.groups.rodelas[0].cells));
  assert.throws(() => { "use strict"; attempt.payload.values._groups.formatos.push({}); }, TypeError);
  assert.notEqual(createP129Attempt(draftOf(), ASSIGNMENT, DEVICE).attempt.captureId, createP129Attempt(draftOf(), ASSIGNMENT, DEVICE).attempt.captureId);
  assert.equal(createP129Attempt(emptyP129Draft(key), ASSIGNMENT, DEVICE).ok, false);
});

// ---- flujo ------------------------------------------------------------------------------------------------------------------------------------------

const attempt = createP129Attempt(draftOf(), ASSIGNMENT, DEVICE, () => ID).attempt;
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: parseP129Submission({ created, already_submitted: !created, capture: p129(ID, attempt.payload.values) }) });
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });

test("submit: 201 created, 200 already received, both with the exact immutable payload", async () => {
  const sent = [];
  const created = await submitP129Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  const again = await submitP129Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(false)) }));
  assert.equal(again.alreadySubmitted, true);
  assert.equal(sent[0], attempt.payload);
  assert.equal(sent[1], sent[0]); // the retry sends the very same payload: same capture_id, same rows, same order
});

test("submit: 401/403/404/409/422 map to the agreed outcomes and never reconcile", async () => {
  const reject = (status, code) => submitP129Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
  assert.deepEqual(await reject(401), { kind: "session" });
  assert.equal((await reject(403)).reason, "forbidden");
  assert.equal((await reject(404)).reason, "not_found");
  assert.equal((await reject(422, "CAPTURE_VALIDATION")).reason, "invalid");
  assert.equal((await reject(409, "CAPTURE_IDEMPOTENCY_CONFLICT")).reason, "idempotency");
  assert.equal((await reject(409, "ASSIGNMENT_STALE")).reason, "stale");
  assert.equal((await reject(409, "FORM_NOT_AVAILABLE")).reason, "conflict");
});

test("reconciliation after a lost response or request: GET by the SAME id decides saved / not saved / uncertain", async () => {
  const lost = async () => ({ ok: false, kind: "unavailable", status: 0 });
  const asked = [];
  const saved = await submitP129Attempt(attempt, deps({ post: lost, get: async (id) => (asked.push(id), { ok: true, status: 200, data: parseP129Capture(p129(ID, attempt.payload.values)) }) }));
  assert.deepEqual(asked, [ID]);
  assert.equal(saved.kind, "submitted");
  assert.equal(saved.reconciled, true);
  assert.deepEqual(saved.capture.values._groups.formatos.map((r) => r.formato_tipo_de_tubete), ["FORMATO-FICTICIO-1", "FORMATO-FICTICIO-2"]); // all rows, in order
  assert.equal((await submitP129Attempt(attempt, deps({ post: lost, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await submitP129Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "s", status: 503 }), get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  const other = parseP129Capture(p129("33333333-3333-4333-8333-333333333333"));
  assert.equal((await reconcileP129(ID, deps({ post: lost, get: async () => ({ ok: true, status: 200, data: other }) }))).kind, "uncertain");
});

// ---- cliente HTTP --------------------------------------------------------------------------------------------------------------------------------------

function fakeFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, credentials: init.credentials }); return handler(String(url), init); };
  return { calls, restore: () => { globalThis.fetch = original; } };
}
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("HTTP: P1-29 uses the shared central routes with its own strict parser; F6 keeps its historic URL", async () => {
  const stub = fakeFetch((url, init) => (init.method === "POST" ? json(201, { created: true, already_submitted: false, capture: p129() }) : url.includes("form_code") || /captures\/[0-9a-f-]{36}$/.test(url) ? (url.includes("form_code") ? json(200, [p129()]) : json(200, p129())) : json(200, [])));
  try {
    assert.equal((await api.submitP129(attempt.payload)).status, 201);
    assert.equal((await api.getP129(ID)).ok, true);
    assert.equal((await api.listP129(undefined, 10)).data[0].form.code, P1_29_CODE);
    assert.equal((await f6api.listCaptures()).ok, true);
  } finally { stub.restore(); }
  assert.deepEqual(stub.calls.map((c) => `${c.method} ${c.url}`), ["POST http://127.0.0.1:8190/api/captures", `GET http://127.0.0.1:8190/api/captures/${ID}`, "GET http://127.0.0.1:8190/api/captures?limit=10&form_code=VINTO-P1-29", "GET http://127.0.0.1:8190/api/captures?limit=50"]);
  assert.deepEqual(JSON.parse(stub.calls[0].body), JSON.parse(JSON.stringify(attempt.payload)));
  assert.ok(stub.calls.every((c) => c.credentials === "include"));
});

test("HTTP: a response of another form is never accepted as P1-29, and a P1-29 response is never accepted as F6", async () => {
  const f6capture = envelope(ID, "VINTO-P1-06", { cantidad_fardos: 1, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "1" });
  for (const [run, body] of [[() => api.listP129(), [f6capture]], [() => api.getP129(ID), f6capture], [() => api.submitP129(attempt.payload), { created: true, already_submitted: false, capture: f6capture }]]) {
    const stub = fakeFetch(() => json(200, body));
    try { assert.equal((await run()).ok, false); } finally { stub.restore(); }
  }
  const stub = fakeFetch(() => json(200, [p129()]));
  try { assert.equal((await f6api.listCaptures()).ok, false); } finally { stub.restore(); }
});

// ---- componente ---------------------------------------------------------------------------------------------------------------------------------------------

const CONTEXT = { assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "A", productName: "BOBINA 1024", machine: "TUBETERA", shift: "Día (ficticio)", date: "2026-10-06" };
const html = (props) => server.renderToStaticMarkup(React.createElement(component.P129CaptureForm, { context: CONTEXT, online: true, attempt: null, setAttempt() {}, back() {}, onAssignmentChanged() {}, onSessionLost() {}, ...props }));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const disabledCount = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length;

test("component: candidate notice, server context, pending context fields, lote fields and both groups with their first row", () => {
  const markup = html({ user: { display_name: "Operación DEV" } }), plain = text(markup);
  for (const piece of ["Producción Tubetera", "Ficha candidata — No homologada", "OT-2026-0001", "L1 / PV-1", "TUBETERA", "Día (ficticio) · 2026-10-06", "Turno · automático", "Operador", "Visto bueno del responsable",
    "— pendiente de definición —", "Por definir: responsable, mecanismo y efecto sobre la aprobación", "Fecha de producción *", "Lote de producción *", "Hora inicio *", "Hora fin *", "Pegamento total *", "Número MRP del sistema *", "Observaciones",
    "Rodelas de papel kraft", "Formatos de tubete", "Fila 1", "Agregar fila", "Identificación de la rodela / lote *", "Peso de la rodela *", "Formato de tubete *", "Cantidad de tubetes observados", "Espesor *",
    "1 fila · mínimo 1", "Decisiones pendientes de VINTO", "tubertera", "TUBETERA", "Enviar registro trazable", "no es el operador ni el visto bueno del responsable"]) assert.ok(plain.includes(piece), piece);
  assert.match(markup, /type="date"/);
  assert.equal((markup.match(/type="time"/g) ?? []).length, 2, "MF-10: Hora inicio y Hora fin");
  for (const gone of ["Peso fardo", "Tipo de tubete", "Peso *"]) assert.equal(plain.includes(gone), false, `${gone}: ya no se muestra`);
  assert.match(plain, /Espesor \* mm/, "el espesor muestra mm");
  assert.match(plain, /Diámetro interno \* mm/);
  assert.equal((markup.match(/data-row="1"/g) ?? []).length, 2);
  assert.equal((markup.match(/data-row="2"/g) ?? []).length, 0);
  assert.equal(disabledCount(markup, "input") + disabledCount(markup, "textarea"), 0);
  const contextual = markup.slice(markup.indexOf('data-section="contextual"'), markup.indexOf("Lote de producción"));
  assert.equal(/<(input|select|textarea)/.test(contextual), false); // the pending context fields are not editable
  assert.equal(/Operador\s*Operación DEV|Visto bueno del responsable\s*Operación DEV/.test(plain), false); // the session identity is never shown as operator or approval
});

test("component: the remove buttons of the first rows are disabled at the minimum and no business storage or network is used", () => {
  const markup = html({});
  assert.ok(/aria-label="Eliminar fila 1 de Rodelas de papel kraft"/.test(markup));
  const remove = markup.match(/<button[^>]*aria-label="Eliminar fila 1 de [^"]*"[^>]*>/g);
  assert.equal(remove.length, 2);
  assert.ok(remove.every((t) => DISABLED.test(t)));
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["components/vinto/p1-29-capture.tsx", "lib/vinto/p1-29.ts", "lib/vinto/p1-29-api.ts"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie|Authorization/.test(code(file)), false, file);
  assert.equal(/form-definitions/.test(code("components/vinto/p1-29-capture.tsx")) || /form-definitions/.test(code("lib/vinto/p1-29.ts")), false); // the capture does not bundle the 8,900-line definitions
});

test("component: a pending attempt locks fields and rows, keeps the typed draft and offers the retry", () => {
  const made = createP129Attempt(draftOf({ simple: { lote_de_produccion: "LOTE-PENDIENTE" } }), ASSIGNMENT, DEVICE, () => ID).attempt;
  const markup = html({ attempt: made }), plain = text(markup);
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío."));
  assert.ok(disabledCount(markup, "input") >= 3 + 2 * 2 + 8);
  const buttons = markup.match(/<button[^>]*>/g) ?? [];
  assert.ok(buttons.filter((t) => !DISABLED.test(t)).length === 2); // «Volver» and «Reintentar envío» only
  assert.match(markup, /value="LOTE-PENDIENTE"/);
  assert.match(markup, /value="10,250"/); // the exact typed draft is restored (no float round trip)
  assert.equal((markup.match(/data-row="2"/g) ?? []).length, 2); // both groups restored with their two rows
});

test("P1-29 is wired only behind the backend-verified Rebobinado navigation (M4-A): no route, not in the central policy, not in the seed bundle", () => {
  const page = readFileSync(join(root, "app/page.tsx"), "utf8");
  assert.match(page, /P129CaptureForm/); // M4-A: reachable only from the Rebobinado front, whose visibility the backend decides
  for (const dir of ["app/p1-29", "app/tubetera", "app/preview", "app/qa-harness", "app/__qa", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir);
  const service = readFileSync(join(root, "backend/app/capture_service.py"), "utf8");
  assert.match(service, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  assert.equal(/CENTRAL_FORM_CODES[^\n]*P1-29/.test(service), false);
  for (const name of ["forms.json", "form_versions.json", "field_definitions.json", "field_groups.json", "form_version_machines.json"]) {
    const file = join(root, "backend/seed_data", name);
    if (existsSync(file)) assert.equal(readFileSync(file, "utf8").includes("VINTO-P1-29"), false, name);
  }
  assert.match(readFileSync(join(root, "backend/app/sectors.py"), "utf8"), /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
});

// ---- MF-10: lectura por versión ---------------------------------------------------------------------------------------------------------------------------------
test("MF-10: la versión 1 conserva «Peso fardo», «Peso» por formato y los diámetros decimales; la versión 2 exige horas y acepta diámetros de texto", () => {
  const v1Values = { fecha_de_produccion: "2026-01-15", lote_de_produccion: "L1", pegamento_total_kg: "12,5", peso_fardo: "100,0 (texto)", numero_mrp_del_sistema: "MRP", _groups: { rodelas: [rodela("R-A", "10.250")], formatos: [formatoV1()] } };
  const v1 = parseP129Capture(p129(ID, v1Values, 1));
  assert.equal(v1.values.peso_fardo, "100,0 (texto)", "los datos históricos conservan su formato");
  assert.equal(v1.values._groups.formatos[0].peso_kg_por_formato, "6.750");
  assert.equal(v1.values._groups.formatos[0].diametro_interno_mm_por_formato, "38.10");
  assert.equal("hora_inicio" in v1.values, false, "no se fabrican horas para registros anteriores");
  assert.equal(parseP129Capture(p129(ID, { ...v1Values, peso_fardo: "" }, 1)), null, "una v1 sigue exigiendo su peso");
  assert.equal(parseP129Capture(p129(ID, { ...v1Values, _groups: { ...v1Values._groups, formatos: [formatoV1({ diametro_interno_mm_por_formato: "77-78" })] } }, 1)), null, "en la v1 los diámetros eran decimales");
  assert.equal(parseP129Capture(p129(ID, v1Values, 2)), null, "una captura v2 sin horas no es válida");
  const v2 = parseP129Capture(p129());
  assert.equal(v2.values._groups.formatos[0].diametro_interno_mm_por_formato, "77-78", "los diámetros de texto se conservan sin interpretar");
  assert.equal(parseP129Capture(p129(ID, { ...VALUES, hora_inicio: "25:00:00" })), null);
  assert.equal(parseP129Capture(p129(ID, { ...VALUES, hora_fin: undefined })), null);
  assert.deepEqual(P129_GROUPS_V1[1].fields.map((f) => f.key).filter((k) => k === "peso_kg_por_formato"), ["peso_kg_por_formato"]);
  const list = parseP129List([p129(ID, v1Values, 1), p129("33333333-3333-4333-8333-333333333333")]);
  assert.deepEqual(list.map((c) => c.form.version_number), [1, 2]);
  for (const text of ["77-78", "80-81", "76,5 - 77", "entre 77 y 78"]) assert.equal(normalizeP129Draft(draftOf({ formatos: [formato({ diametro_interno_mm_por_formato: text })] })).values._groups.formatos[0].diametro_interno_mm_por_formato, text, "sin normalizar");
});
