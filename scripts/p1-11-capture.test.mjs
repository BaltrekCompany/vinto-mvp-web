// node --test scripts/p1-11-capture.test.mjs
// VINTO-P1-11 CANDIDATO central (M6-D, Conversión): contrato de UN grupo repetible `bobinas` de bobinas DECLARADAS (número, posición superior/inferior y tres saldos) más observaciones opcionales; validación
// ESTRUCTURAL, payload inmutable, intento pendiente, reconciliación, separación de los demás formularios, componente (filas dinámicas) e historial. La red se simula con funciones inyectadas o con un `fetch` de prueba.
// Nada de lo que se prueba aquí decide reglas industriales de P1-11 (consumo, balance, inventario, genealogía, receta, rodelas, insumos): siguen pendientes de VINTO y NO se calculan.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { addRow, canAddRow, canRemoveRow, removeRow, setCell } from "../lib/vinto/capture-groups.ts";
import { parseCapture, parseCaptureList } from "../lib/vinto/captures.ts";
import { parseP110Capture } from "../lib/vinto/p1-10.ts";
import {
  ADVISORY, P111_GROUPS, P1_11_CODE, PENDING_NOTES, POSICION_OPTIONS, buildP111Payload, createP111Attempt, emptyP111Draft, normalizeP111Draft, parseP111Capture, parseP111List, parseP111Submission,
  reconcileP111, submitP111Attempt,
} from "../lib/vinto/p1-11.ts";
import { parseP112Capture } from "../lib/vinto/p1-12.ts";
import { parseP113Capture } from "../lib/vinto/p1-13.ts";
import { parseP116Capture } from "../lib/vinto/p1-16.ts";
import { parseP129Capture } from "../lib/vinto/p1-29.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-p111-test-${process.pid}`);
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

let api, component, history, React, server;
before(async () => {
  process.env.NEXT_PUBLIC_API_URL = "http://127.0.0.1:8190";
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [api, component, history] = await Promise.all([bundle("lib/vinto/p1-11-api.ts", "p111api"), bundle("components/vinto/p1-11-capture.tsx", "comp"), bundle("components/vinto/central-form-history.tsx", "history")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444", DEVICE = "99999999-9999-4999-8999-999999999999", ID = "11111111-1111-4111-8111-111111111111";
const ROWS = [
  { numero_bobina: "BOBINA-FICTICIA-001", posicion: "superior", saldo_inicial_kg: "100.5", ingreso_kg: "20", saldo_final_kg: "60.25" },
  { numero_bobina: "BOBINA-FICTICIA-002", posicion: "superior", saldo_inicial_kg: "10", ingreso_kg: "0", saldo_final_kg: "150.125" },
  { numero_bobina: "BOBINA-FICTICIA-003", posicion: "inferior", saldo_inicial_kg: "0", ingreso_kg: "5.5", saldo_final_kg: "3" },
];
const P111_VALUES = { observaciones: "Dato de prueba", _groups: { bobinas: ROWS } };
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "GAMBINI", name: "Gambini" }, shift: { code: "FICT_CONV_MANANA", name: "Mañana (ficticio)" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
const p111 = (id = ID, values = P111_VALUES) => envelope(id, P1_11_CODE, values);
const p112 = () => envelope(ID, "VINTO-P1-12", { cantidad_jabas: 40, hora_inicio: "08:15:00", hora_fin: "09:05:00" });
const p113 = () => envelope(ID, "VINTO-P1-13", { numero_bobina: "B", saldo_inicial_kg: "1", ingreso_kg: "0", saldo_final_kg: "1", cantidad_jabas: 1, hora_inicio: "01:00:00", hora_fin: "02:00:00" });
const p116 = () => envelope(ID, "VINTO-P1-16", { tipo_merma: "toalla", origen_merma: "logs", peso_merma_kg: "1.500" });
const f6 = () => envelope(ID, "VINTO-P1-06", { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50" });
const rowCells = (row) => ({ numero_bobina: row.numero_bobina, posicion: row.posicion, saldo_inicial_kg: row.saldo_inicial_kg.replace(".", ","), ingreso_kg: row.ingreso_kg, saldo_final_kg: row.saldo_final_kg });
// a draft with the given rows typed the way an operator would (decimal comma included)
function draftOf(rows = ROWS, observaciones = "Dato de prueba") {
  let n = 0;
  const key = () => `k${++n}`;
  let draft = emptyP111Draft(key);
  const spec = P111_GROUPS[0];
  let list = draft.groups.bobinas;
  while (list.length < rows.length) list = addRow(spec, list, key);
  list = list.map((r, i) => ({ rowKey: r.rowKey, cells: rowCells(rows[i]) }));
  return { observaciones, groups: { bobinas: list } };
}

// ---- especificación ---------------------------------------------------------------------------------------------------------------------------

test("the contract is exactly ONE repeatable group `bobinas` with the five candidate fields; min 1, no declared maximum, two positions only", () => {
  assert.equal(P111_GROUPS.length, 1);
  const [spec] = P111_GROUPS;
  assert.deepEqual([spec.code, spec.repeatable, spec.minRows, spec.maxRows], ["bobinas", true, 1, null]);
  assert.deepEqual(spec.fields.map((f) => [f.key, f.kind, f.required]), [["numero_bobina", "text", true], ["posicion", "choice", true], ["saldo_inicial_kg", "decimal", true], ["ingreso_kg", "decimal", true], ["saldo_final_kg", "decimal", true]]);
  assert.deepEqual(POSICION_OPTIONS.map((o) => o.value), ["superior", "inferior"]); // no «no_aplica»
  assert.equal(emptyP111Draft().groups.bobinas.length, 1); // starts with the minimum row, not three
  assert.equal(ADVISORY, "Ficha candidata no homologada. Los números de bobina y los saldos son declaraciones de prueba: no generan consumo, movimientos de inventario ni vínculos de genealogía.");
});

// ---- separación de formularios en los parsers -------------------------------------------------------------------------------------------

test("P1-11 parsers accept only P1-11 captures; the other forms' parsers never accept them", () => {
  assert.deepEqual(parseP111Capture(p111()).values, P111_VALUES);
  for (const other of [f6(), p112(), p113(), p116()]) assert.equal(parseP111Capture(other), null);
  for (const parser of [parseCapture, parseP110Capture, parseP112Capture, parseP113Capture, parseP116Capture, parseP129Capture]) assert.equal(parser(p111()), null);
  assert.equal(parseP111Capture(envelope(ID, "VINTO-P1-13", P111_VALUES)), null); // right values, wrong form code
  assert.equal(parseP111Capture(envelope(ID, "vinto-p1-11", P111_VALUES)), null);
  assert.equal(parseP111List([p111(), p113()]), null); // a mixed list is rejected as a whole
  assert.equal(parseCaptureList([f6(), p111()]), null);
  assert.equal(parseP111List([p111(), p111("33333333-3333-4333-8333-333333333333")]).length, 2);
  assert.equal(parseP111Submission({ created: true, already_submitted: false, capture: p113() }), null);
  assert.equal(parseP111Submission({ created: true, already_submitted: false, capture: p111() }).capture.form.code, P1_11_CODE);
});

test("the P1-11 values parser is strict about the group (rows, order, positions, decimals) and drops anything computed", () => {
  const parsed = parseP111Capture(p111()).values;
  assert.deepEqual(parsed._groups.bobinas.map((r) => r.numero_bobina), ["BOBINA-FICTICIA-001", "BOBINA-FICTICIA-002", "BOBINA-FICTICIA-003"]); // order preserved
  assert.equal(parseP111Capture(p111(ID, { _groups: { bobinas: [ROWS[0]] } })).values.observaciones, undefined); // observaciones are optional
  const bad = (values) => assert.equal(parseP111Capture(p111(ID, values)), null, JSON.stringify(values).slice(0, 120));
  bad({ _groups: { bobinas: [] } }); // min_rows = 1
  bad({ observaciones: "x" }); bad({ _groups: {} }); bad({ _groups: { bobinas: "x" } }); bad(null); bad([]); bad("x");
  bad({ _groups: { bobinas: [{ ...ROWS[0], posicion: "no_aplica" }] } });
  bad({ _groups: { bobinas: [{ ...ROWS[0], posicion: "Superior" }] } });
  bad({ _groups: { bobinas: [{ ...ROWS[0], saldo_inicial_kg: "12,5" }] } });
  bad({ _groups: { bobinas: [{ ...ROWS[0], ingreso_kg: undefined }] } });
  bad({ _groups: { bobinas: [{ ...ROWS[0], numero_bobina: "" }] } });
  bad({ _groups: { bobinas: [{ ...ROWS[0], consumo_kg: "1" }] } }); // an unknown or computed key inside a row rejects the whole capture
  bad({ _groups: { bobinas: [ROWS[0]], rodelas: [ROWS[0]] } }); // undeclared group
  bad({ observaciones: 5, _groups: { bobinas: [ROWS[0]] } });
  assert.equal(parseP111Capture(p111(ID, { ...P111_VALUES, consumo: 70, saldo_disponible: 1, merma_total: "2" })).values.consumo, undefined); // unknown simple keys are dropped, never kept
  assert.equal(parseP111Capture(p111(ID, { _groups: { bobinas: [{ ...ROWS[0], saldo_final_kg: 3.5 }] } })).values._groups.bobinas[0].saldo_final_kg, "3.5"); // numbers are shown as text; nothing is computed
});

// ---- validación estructural: solo lo estructural ----------------------------------------------------------------------------------------------

test("structural validation: at least one row, coil text, a position from the catalog and three decimals (comma normalized); NO consumption, ordering, uniqueness, range, precision or rounding rule", () => {
  const ok = normalizeP111Draft(draftOf());
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.values, { observaciones: "Dato de prueba", _groups: { bobinas: ROWS } }); // "100,5" -> "100.5"; text and order intact
  assert.equal("observaciones" in normalizeP111Draft(draftOf(ROWS, "   ")).values, false); // blank notes are omitted
  // two rows with the same position AND the same coil number are structurally fine; the final balance may be greater than the initial one; negatives and any precision are not judged
  const odd = [{ ...ROWS[0], saldo_inicial_kg: "10", ingreso_kg: "0", saldo_final_kg: "999999" }, { ...ROWS[0] }, { ...ROWS[0], saldo_inicial_kg: "-5", ingreso_kg: "-1,5", saldo_final_kg: "1.123456789" }];
  const accepted = normalizeP111Draft(draftOf(odd));
  assert.equal(accepted.ok, true);
  assert.equal(accepted.values._groups.bobinas[2].saldo_final_kg, "1.123456789"); // no rounding
  assert.equal(accepted.values._groups.bobinas[2].ingreso_kg, "-1.5");
  assert.equal(accepted.values._groups.bobinas.length, 3);
  const empty = normalizeP111Draft({ observaciones: "", groups: { bobinas: [] } });
  assert.equal(empty.ok, false); // min_rows = 1
  assert.ok(empty.errors.some((e) => e.group === "bobinas" && e.row === null && e.message.includes("al menos 1 filas")));
  const blank = normalizeP111Draft(emptyP111Draft());
  assert.equal(blank.ok, false);
  assert.equal(blank.errors.length, 5); // the one empty row misses its five required cells
  const mark = (key, value) => { const d = draftOf([ROWS[0], ROWS[1]]); d.groups.bobinas = d.groups.bobinas.map((r, i) => (i === 1 ? { rowKey: r.rowKey, cells: { ...r.cells, [key]: value } } : r)); return normalizeP111Draft(d); };
  for (const [key, value] of [["posicion", "no_aplica"], ["posicion", ""], ["saldo_inicial_kg", "abc"], ["ingreso_kg", "1e3"], ["saldo_final_kg", "12."], ["numero_bobina", "   "]]) {
    const result = mark(key, value);
    assert.equal(result.ok, false, `${key}=${value}`);
    assert.ok(result.errors.every((e) => e.group === "bobinas" && e.row === 2), `${key}=${value}`); // the error names the row
  }
  assert.equal(normalizeP111Draft(draftOf(ROWS, "x".repeat(10_001))).ok, false);
});

test("rows are added and removed immutably: at least one row always remains, the technical cap is respected and rows keep their order", () => {
  const [spec] = P111_GROUPS;
  let n = 0;
  const key = () => `r${++n}`;
  const one = emptyP111Draft(key).groups.bobinas;
  assert.equal(canRemoveRow(spec, one), false); // min_rows = 1: the last row cannot be removed
  assert.equal(removeRow(spec, one, one[0].rowKey), one);
  const three = addRow(spec, addRow(spec, one, key), key);
  assert.equal(three.length, 3);
  assert.equal(canAddRow(spec, three), true);
  assert.deepEqual(removeRow(spec, three, three[1].rowKey).map((r) => r.rowKey), [three[0].rowKey, three[2].rowKey]);
  assert.equal(one.length, 1); // the original list is untouched
  let many = one;
  for (let i = 0; i < 999; i += 1) many = addRow(spec, many, key);
  assert.equal(many.length, 1000);
  assert.equal(canAddRow(spec, many), false); // the TECHNICAL cap of the system, not an industrial maximum
  assert.equal(addRow(spec, many, key), many);
  assert.equal(setCell(three, three[0].rowKey, "numero_bobina", "X")[0].cells.numero_bobina, "X");
});

test("the payload carries only the agreed values: observaciones and _groups.bobinas with the five fields; no row keys, ids, consumption, balance, weights or any context", () => {
  const check = normalizeP111Draft(draftOf());
  const payload = buildP111Payload(ID, ASSIGNMENT, DEVICE, check.values);
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(payload.form_code, "VINTO-P1-11");
  assert.deepEqual(Object.keys(payload.values).sort(), ["_groups", "observaciones"]);
  assert.deepEqual(Object.keys(payload.values._groups), ["bobinas"]);
  for (const row of payload.values._groups.bobinas) assert.deepEqual(Object.keys(row).sort(), ["ingreso_kg", "numero_bobina", "posicion", "saldo_final_kg", "saldo_inicial_kg"]);
  assert.equal(/rowKey|row_number|group_row|consumo|saldo_disponible|merma|peso_total|numero_pallet|bobbin_id|operador|turno|maquina|fecha/.test(JSON.stringify(payload.values)), false);
  assert.equal(typeof payload.values._groups.bobinas[0].saldo_inicial_kg, "string"); // decimals travel as text: nothing is converted or rounded in the browser
});

test("no module of the P1-11 contract computes consumption (the legacy formula is nowhere), sums balances, uses legacy recipes/weights or touches the bobbin APIs", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["lib/vinto/p1-11.ts", "lib/vinto/p1-11-api.ts", "components/vinto/p1-11-capture.tsx"]) {
    assert.equal(/product-weights|NOMINAL_WEIGHT|RECIPES_BY_PRODUCT|PAL-|peso_total|peso_nominal|consumo_|bobbins-api|quality-bobbins|\/api\/bobbins|\.reduce\(/.test(code(file)), false, file);
    assert.equal(/Number\([^)]*saldo[^)]*\)\s*[-+]/.test(code(file)), false, file); // no `saldo_inicial + ingreso - saldo_final`
  }
  const historyCode = code("components/vinto/central-form-history.tsx");
  const p111Part = historyCode.slice(historyCode.indexOf("export function P111History"));
  assert.equal(/\.reduce\(|Number\(|parseFloat|toFixed/.test(p111Part), false); // the history only lists what was declared
});

// ---- intento pendiente inmutable --------------------------------------------------------------------------------------------------------------

test("an attempt is immutable and a new attempt gets a new UUIDv4; the typed draft (with row keys) is kept for the retry", () => {
  let n = 0;
  const made = createP111Attempt(draftOf(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.equal(made.ok, true);
  const { attempt } = made;
  assert.equal(attempt.captureId, "00000000-0000-4000-8000-000000000001");
  assert.equal(attempt.payload.capture_id, attempt.captureId);
  assert.equal(attempt.draft.groups.bobinas[0].cells.saldo_inicial_kg, "100,5"); // the draft keeps what was typed; the payload holds the normalized text
  assert.equal(attempt.payload.values._groups.bobinas[0].saldo_inicial_kg, "100.5");
  assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.draft));
  assert.throws(() => { "use strict"; attempt.payload.values._groups.bobinas.push({}); }, TypeError);
  assert.throws(() => { "use strict"; attempt.payload.values._groups.bobinas[0].saldo_final_kg = "1"; }, TypeError);
  assert.notEqual(createP111Attempt(draftOf(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`).attempt.captureId, attempt.captureId);
  assert.match(createP111Attempt(draftOf(), ASSIGNMENT, DEVICE).attempt.captureId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.equal(createP111Attempt(emptyP111Draft(), ASSIGNMENT, DEVICE).ok, false);
});

// ---- flujo: 201/200/409/422/401 y reconciliación tras timeout ---------------------------------------------------------------------------------

const attempt = createP111Attempt(draftOf(), ASSIGNMENT, DEVICE, () => ID).attempt;
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: parseP111Submission({ created, already_submitted: !created, capture: p111() }) });
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });

test("submit: 201 is created, a 200 identical retry is 'already received', both with the exact payload (the same rows, no duplicate on retry)", async () => {
  const sent = [];
  const created = await submitP111Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  assert.equal(sent[0], attempt.payload);
  const again = await submitP111Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(false)) }));
  assert.equal(again.alreadySubmitted, true);
  assert.equal(sent[1], sent[0]);
});

test("submit: 401 / 403 / 404 / 409 / 422 map to the agreed outcomes (a stale assignment is reported as such) and never reconcile", async () => {
  const reject = (status, code) => submitP111Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
  assert.deepEqual(await reject(401), { kind: "session" });
  assert.equal((await reject(403)).reason, "forbidden");
  assert.equal((await reject(404)).reason, "not_found");
  assert.equal((await reject(422, "CAPTURE_VALIDATION")).reason, "invalid");
  assert.equal((await reject(409, "CAPTURE_IDEMPOTENCY_CONFLICT")).reason, "idempotency");
  const stale = await reject(409, "ASSIGNMENT_STALE");
  assert.equal(stale.reason, "stale");
  assert.ok(stale.message.includes("ya no corresponde al turno o fecha actual"));
  assert.equal((await reject(409, "ASSIGNMENT_NOT_ACTIVE")).reason, "not_active");
  assert.equal((await reject(409, "FORM_NOT_AVAILABLE")).reason, "conflict");
});

test("reconciliation after a timeout: GET by the SAME capture id decides saved / not saved / uncertain", async () => {
  const timeout = async () => ({ ok: false, kind: "unavailable", status: 0 });
  const asked = [];
  const saved = await submitP111Attempt(attempt, deps({ post: timeout, get: async (id) => (asked.push(id), { ok: true, status: 200, data: parseP111Capture(p111()) }) }));
  assert.deepEqual(asked, [ID]);
  assert.equal(saved.kind, "submitted");
  assert.equal(saved.reconciled, true);
  assert.equal((await submitP111Attempt(attempt, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await submitP111Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "s", status: 503 }), get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  assert.deepEqual(await reconcileP111(ID, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 401 }) })), { kind: "session" });
  const other = parseP111Capture(p111("33333333-3333-4333-8333-333333333333"));
  assert.equal((await reconcileP111(ID, deps({ post: timeout, get: async () => ({ ok: true, status: 200, data: other }) }))).kind, "uncertain");
});

// ---- cliente HTTP genérico ---------------------------------------------------------------------------------------------------------------------------

function fakeFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, credentials: init.credentials, cache: init.cache }); return handler(String(url), init); };
  return { calls, restore: () => { globalThis.fetch = original; } };
}
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("HTTP: the P1-11 list sends form_code and uses the P1-11 parser; POST and GET use the shared central routes with the cookie session only", async () => {
  const stub = fakeFetch((url, init) => (init.method === "POST" ? json(201, { created: true, already_submitted: false, capture: p111() }) : url.includes("form_code") ? json(200, [p111()]) : json(200, p111())));
  try {
    const listed = await api.listP111(undefined, 10);
    assert.equal(listed.ok, true);
    assert.equal(listed.data[0].form.code, P1_11_CODE);
    assert.equal((await api.submitP111(attempt.payload)).status, 201);
    assert.equal((await api.getP111(ID)).ok, true);
  } finally { stub.restore(); }
  assert.deepEqual(stub.calls.map((c) => [c.method, c.url]), [["GET", "http://127.0.0.1:8190/api/captures?limit=10&form_code=VINTO-P1-11"], ["POST", "http://127.0.0.1:8190/api/captures"], ["GET", `http://127.0.0.1:8190/api/captures/${ID}`]]);
  assert.deepEqual(JSON.parse(stub.calls[1].body), attempt.payload);
  assert.ok(stub.calls.every((c) => c.credentials === "include"));
});

test("HTTP: a response of ANOTHER form is rejected by the P1-11 client (never mistaken)", async () => {
  const wrong = fakeFetch(() => json(200, [p113()]));
  try { assert.equal((await api.listP111()).ok, false); } finally { wrong.restore(); }
  const single = fakeFetch(() => json(200, p116()));
  try { assert.equal((await api.getP111(ID)).ok, false); } finally { single.restore(); }
  const post = fakeFetch(() => json(201, { created: true, already_submitted: false, capture: p112() }));
  try { assert.equal((await api.submitP111(attempt.payload)).ok, false); } finally { post.restore(); }
});

// ---- componente --------------------------------------------------------------------------------------------------------------------------------------

const CONTEXT = { assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "10351", productName: "PERLITA ECO PLUS 4*12",
  machine: "GAMBINI", shift: "Mañana (ficticio)", date: "2026-10-06" };
const html = (props) => server.renderToStaticMarkup(React.createElement(component.P111CaptureForm, { context: CONTEXT, online: true, attempt: null, setAttempt() {}, back() {}, onAssignmentChanged() {}, onSessionLost() {}, ...props }));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const disabledCount = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length;

test("component: the mandatory advisory, ONE initial row with its five declared fields, add / remove controls, server context and the pending decisions", () => {
  const markup = html({ user: { display_name: "Operación DEV" } }), plain = text(markup);
  for (const piece of [ADVISORY, "Consumo de bobinas", "Ficha NO homologada · solo entorno de prueba", "no es la definición de 61 campos ni las tres filas fijas", "Bobinas declaradas", "Fila 1", "Agregar fila", "1 fila · mínimo 1",
    "N.º de bobina (declarado) *", "Posición (declarada) *", "Saldo inicial declarado *", "Ingreso declarado *", "Saldo final declarado *", "Superior", "Inferior", "Observaciones", "OT-2026-0001", "GAMBINI",
    "PERLITA ECO PLUS 4*12", "Mañana (ficticio) · 2026-10-06", "Eliminar", "Enviar registro trazable", "no hay máximo funcional definido"]) assert.ok(plain.includes(piece), piece);
  for (const note of PENDING_NOTES) assert.ok(plain.includes(note.label) && plain.includes(note.pending), note.key);
  assert.equal((markup.match(/data-row="/g) ?? []).length, 1); // one row, not three
  assert.equal((markup.match(/<select/g) ?? []).length, 1);
  assert.equal((markup.match(/<input/g) ?? []).length, 4);
  assert.equal((markup.match(/<textarea/g) ?? []).length, 1);
  assert.equal(plain.includes("No aplica"), false); // no «no_aplica» option
  assert.equal(/Consumo calculado|Consumo \d|Total |Suma|Diferencia|Balance/.test(plain.replace(ADVISORY, "")), false); // nothing computed is shown
  assert.equal(disabledCount(markup, "button") >= 1, true); // «Eliminar» is disabled with a single row (min_rows = 1)
  assert.ok(plain.includes("Operación DEV") && plain.includes("no es una firma ni un grupo"));
  assert.equal(html({}).includes('data-section="session"'), false);
});

test("component: a pending attempt shows ALL its rows in order, locks fields and row controls, and keeps the retry enabled", () => {
  const made = createP111Attempt(draftOf(), ASSIGNMENT, DEVICE, () => ID).attempt;
  const markup = html({ attempt: made }), plain = text(markup);
  assert.equal((markup.match(/data-row="/g) ?? []).length, 3);
  assert.ok(plain.indexOf("Fila 1") < plain.indexOf("Fila 2") && plain.indexOf("Fila 2") < plain.indexOf("Fila 3") && plain.includes("3 filas · mínimo 1"));
  assert.ok(markup.indexOf("BOBINA-FICTICIA-001") < markup.indexOf("BOBINA-FICTICIA-002") && markup.indexOf("BOBINA-FICTICIA-002") < markup.indexOf("BOBINA-FICTICIA-003"));
  assert.match(markup, /value="100,5"/); // the typed draft is restored as typed
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío."));
  assert.equal(disabledCount(markup, "input"), 12);
  assert.equal(disabledCount(markup, "select"), 3);
  assert.equal(disabledCount(markup, "textarea"), 1);
  const buttons = markup.match(/<button[^>]*>[\s\S]*?<\/button>/g) ?? [];
  const retry = buttons.find((b) => b.includes("Reintentar envío"));
  assert.ok(retry && !DISABLED.test(retry.match(/<button[^>]*>/)[0])); // the retry stays enabled
  assert.ok(buttons.filter((b) => b.includes("Agregar fila") || b.includes("Eliminar")).every((b) => DISABLED.test(b.match(/<button[^>]*>/)[0]))); // add / remove are locked
});

test("history: renders the declared rows in order WITHOUT sums, totals or consumption, and states honestly when the backend does not enable the form", () => {
  const render = (resource) => text(server.renderToStaticMarkup(React.createElement(history.P111History, { resource, refresh() {} })));
  const ready = render({ status: "ready", data: [parseP111Capture(p111())] });
  for (const piece of ["Consumo de bobinas (P1-11) · registros centrales", "declaraciones", "No es un libro de existencias", "1. BOBINA-FICTICIA-001 · Superior · inicial 100.5 · ingreso 20 · final 60.25 (declarados)",
    "2. BOBINA-FICTICIA-002 · Superior · inicial 10 · ingreso 0 · final 150.125 (declarados)", "3. BOBINA-FICTICIA-003 · Inferior · inicial 0 · ingreso 5.5 · final 3 (declarados)", "OT-2026-0001", "L1 / PV-1", "GAMBINI", "Mañana (ficticio)", "Dato de prueba"]) assert.ok(ready.includes(piece), piece);
  assert.equal(/Total|Suma|Consumo \d|Diferencia/.test(ready.replace("No es un libro de existencias: no hay consumo, totales ni inventario.", "")), false);
  assert.ok(ready.indexOf("BOBINA-FICTICIA-001") < ready.indexOf("BOBINA-FICTICIA-002") && ready.indexOf("BOBINA-FICTICIA-002") < ready.indexOf("BOBINA-FICTICIA-003"));
  assert.ok(render({ status: "ready", data: [] }).includes("Todavía no hay registros centrales"));
  assert.ok(render({ status: "error", kind: "invalid" }).includes("El backend no habilita este formulario para tu sesión."));
});

test("component and clients never touch business storage; P1-11 is wired only behind the Conversión navigation and only for CONVERSION", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["components/vinto/p1-11-capture.tsx", "lib/vinto/p1-11.ts", "lib/vinto/p1-11-api.ts"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|vinto-ot|vinto-asg|document\.cookie|Authorization/.test(code(file)), false, file);
  assert.equal(/form-definitions/.test(code("components/vinto/p1-11-capture.tsx")) || /form-definitions/.test(code("lib/vinto/p1-11.ts")), false);
  const page = readFileSync(join(root, "app/page.tsx"), "utf8");
  assert.match(page, /convCapture && front === "Conversión" && convCapture\.screen === "p111"/);
  assert.match(page, /P111CaptureForm/);
  assert.equal((page.match(/setP111Attempt\(null\); setP111Context\(null\)/g) ?? []).length, 1); // session loss and logout clear the pending attempt
  for (const dir of ["app/p1-11", "app/preview", "app/qa-harness", "app/__qa", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir);
});
