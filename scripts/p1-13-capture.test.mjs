// node --test scripts/p1-13-capture.test.mjs
// VINTO-P1-13 CANDIDATO central (M6-C, Conversión): contrato de ocho campos (bobina DECLARADA + tres saldos DECLARADOS + un pallet + observaciones), validación ESTRUCTURAL, payload inmutable, intento pendiente,
// reconciliación, separación de los demás formularios, componente e historial. La red se simula con funciones inyectadas o con un `fetch` de prueba.
// Nada de lo que se prueba aquí decide reglas industriales de P1-13 (consumo, balance, inventario, genealogía, receta, número de pallet, pesos): siguen pendientes de VINTO y NO se calculan.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { parseCapture, parseCaptureList } from "../lib/vinto/captures.ts";
import { parseP110Capture } from "../lib/vinto/p1-10.ts";
import { normalizeP112Draft, parseP112Capture } from "../lib/vinto/p1-12.ts";
import { parseP116Capture } from "../lib/vinto/p1-16.ts";
import {
  ADVISORY, EMPTY_P113_DRAFT, P1_13_CODE, PENDING_NOTES, buildP113Payload, createP113Attempt, normalizeP113Draft, parseP113Capture, parseP113List, parseP113Submission, reconcileP113,
  submitP113Attempt,
} from "../lib/vinto/p1-13.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-p113-test-${process.pid}`);
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
  [api, component, history] = await Promise.all([bundle("lib/vinto/p1-13-api.ts", "p113api"), bundle("components/vinto/p1-13-capture.tsx", "comp"), bundle("components/vinto/central-form-history.tsx", "history")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444", DEVICE = "99999999-9999-4999-8999-999999999999", ID = "11111111-1111-4111-8111-111111111111";
const P113_VALUES = { numero_bobina: "BOBINA-FICTICIA-001", saldo_inicial_kg: "100.500", ingreso_kg: "20", saldo_final_kg: "150.25", cantidad_jabas: 40, hora_inicio: "08:15:00", hora_fin: "09:05:00", observaciones: "Dato de prueba" };
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "WALLY", name: "Wally" }, shift: { code: "FICT_CONV_MANANA", name: "Mañana (ficticio)" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
const p113 = (id = ID, values = P113_VALUES) => envelope(id, P1_13_CODE, values);
const p112 = () => envelope(ID, "VINTO-P1-12", { cantidad_jabas: 40, hora_inicio: "08:15:00", hora_fin: "09:05:00" });
const p116 = () => envelope(ID, "VINTO-P1-16", { tipo_merma: "toalla", origen_merma: "logs", peso_merma_kg: "1.500" });
const f6 = () => envelope(ID, "VINTO-P1-06", { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50" });
const draft = (o = {}) => ({ ...EMPTY_P113_DRAFT, numero_bobina: "BOBINA-FICTICIA-001", saldo_inicial_kg: "100,5", ingreso_kg: "20", saldo_final_kg: "150.25", cantidad_jabas: "40", hora_inicio: "08:15", hora_fin: "09:05", observaciones: "Dato de prueba", ...o });

// ---- separación de formularios en los parsers -------------------------------------------------------------------------------------------

test("P1-13 parsers accept only P1-13 captures; the other forms' parsers never accept them", () => {
  assert.deepEqual(parseP113Capture(p113()).values, P113_VALUES);
  for (const other of [f6(), p112(), p116()]) assert.equal(parseP113Capture(other), null);
  for (const parser of [parseCapture, parseP110Capture, parseP112Capture, parseP116Capture]) assert.equal(parser(p113()), null);
  assert.equal(parseP113Capture(envelope(ID, "VINTO-P1-12", P113_VALUES)), null); // right values, wrong form code
  assert.equal(parseP113Capture(envelope(ID, "vinto-p1-13", P113_VALUES)), null);
  assert.equal(parseP113List([p113(), p112()]), null); // a mixed list is rejected as a whole
  assert.equal(parseCaptureList([f6(), p113()]), null);
  assert.equal(parseP113List([p113(), p113("33333333-3333-4333-8333-333333333333")]).length, 2);
  assert.equal(parseP113Submission({ created: true, already_submitted: false, capture: p112() }), null);
  assert.equal(parseP113Submission({ created: true, already_submitted: false, capture: p113() }).capture.form.code, P1_13_CODE);
});

test("the P1-13 values parser is strict: coil text, three decimal texts, the P1-12 pallet and optional notes; consumption or weights are dropped, never kept", () => {
  const withoutNotes = Object.fromEntries(Object.entries(P113_VALUES).filter(([key]) => key !== "observaciones"));
  assert.equal("observaciones" in parseP113Capture(p113(ID, withoutNotes)).values, false);
  for (const bad of [{ ...P113_VALUES, numero_bobina: "" }, { ...P113_VALUES, numero_bobina: 7 }, { ...P113_VALUES, saldo_inicial_kg: "12,5" }, { ...P113_VALUES, saldo_inicial_kg: 12.5 }, { ...P113_VALUES, ingreso_kg: "" },
    { ...P113_VALUES, saldo_final_kg: null }, { ...P113_VALUES, cantidad_jabas: "40" }, { ...P113_VALUES, cantidad_jabas: 4.5 }, { ...P113_VALUES, hora_inicio: "8:15" }, { ...P113_VALUES, hora_fin: 905 },
    { ...P113_VALUES, observaciones: 5 }, { ...withoutNotes, ingreso_kg: undefined }, null, [], "x"]) assert.equal(parseP113Capture(p113(ID, bad)), null, JSON.stringify(bad));
  const cleaned = parseP113Capture(p113(ID, { ...P113_VALUES, consumo_bobina: 70.25, peso_total_pallet: 99, numero_pallet: "PAL-1", saldo_disponible: 1 })).values;
  assert.deepEqual(Object.keys(cleaned).sort(), ["cantidad_jabas", "hora_fin", "hora_inicio", "ingreso_kg", "numero_bobina", "observaciones", "saldo_final_kg", "saldo_inicial_kg"]);
  assert.equal(parseP113Capture(p113(ID, { ...P113_VALUES, cantidad_jabas: -3 })).values.cantidad_jabas, -3); // a signed integer is structurally valid, as in P1-12
});

// ---- validación estructural: solo lo estructural --------------------------------------------------------------------------------------------

test("structural validation: coil text, three decimals (comma normalized), the P1-12 pallet and optional notes; NO consumption, ordering, range, precision or rounding rule is invented", () => {
  assert.deepEqual(normalizeP113Draft(draft()), { ok: true, values: { numero_bobina: "BOBINA-FICTICIA-001", saldo_inicial_kg: "100.5", ingreso_kg: "20", saldo_final_kg: "150.25", cantidad_jabas: 40, hora_inicio: "08:15", hora_fin: "09:05", observaciones: "Dato de prueba" } });
  assert.equal("observaciones" in normalizeP113Draft(draft({ observaciones: "   " })).values, false); // blank notes are omitted
  // the final balance may be GREATER than the initial one; negatives, zero and any precision are structurally valid and are NOT rounded
  for (const [i, n, f] of [["10", "0", "999999"], ["0", "0", "0"], ["-5", "-1.5", "-0.25"], ["1.123456789", "7", "3.14159"], ["007", "00.50", "0"]]) assert.equal(normalizeP113Draft(draft({ saldo_inicial_kg: i, ingreso_kg: n, saldo_final_kg: f })).ok, true, `${i}/${n}/${f}`);
  assert.equal(normalizeP113Draft(draft({ saldo_final_kg: "3.14159" })).values.saldo_final_kg, "3.14159");
  for (const text of ["", "  ", "abc", "1e3", "12 kg", "1,2,3", "12.", ".5", "+5", "9".repeat(41)]) for (const key of ["saldo_inicial_kg", "ingreso_kg", "saldo_final_kg"]) assert.equal(normalizeP113Draft(draft({ [key]: text })).ok, false, `${key}=${text}`);
  assert.equal(normalizeP113Draft(draft({ numero_bobina: "cualquier cosa 123 / ñ" })).ok, true); // free text: no format, no existence check
  assert.equal(normalizeP113Draft(draft({ numero_bobina: "   " })).ok, false);
  assert.equal(normalizeP113Draft(draft({ numero_bobina: "x".repeat(10_001) })).ok, false);
  assert.equal(normalizeP113Draft(draft({ observaciones: "x".repeat(10_001) })).ok, false);
  const empty = normalizeP113Draft(EMPTY_P113_DRAFT);
  assert.equal(empty.ok, false);
  assert.equal(empty.errors.length, 7); // coil + three balances + jabas + two hours (observaciones is optional)
});

test("the pallet uses EXACTLY the P1-12 validators (same result, same messages) and P1-12's behaviour is unchanged", () => {
  const trio = (o) => ({ cantidad_jabas: "40", hora_inicio: "08:15", hora_fin: "09:05", ...o });
  for (const o of [{}, { cantidad_jabas: "-3" }, { cantidad_jabas: "4.5" }, { cantidad_jabas: "" }, { hora_inicio: "25:00" }, { hora_fin: "8:5" }, { hora_inicio: "22:00", hora_fin: "06:00" }]) {
    const reference = normalizeP112Draft(trio(o)), mine = normalizeP113Draft(draft(o));
    assert.equal(mine.ok, reference.ok, JSON.stringify(o));
    if (reference.ok) assert.deepEqual({ cantidad_jabas: mine.values.cantidad_jabas, hora_inicio: mine.values.hora_inicio, hora_fin: mine.values.hora_fin }, reference.values);
    else for (const error of reference.errors) assert.ok(mine.errors.includes(error), error);
  }
  assert.equal(normalizeP112Draft(trio({ cantidad_jabas: "-3" })).ok, true); // P1-12 keeps accepting signed integers
  assert.equal(normalizeP112Draft(trio({ cantidad_jabas: "+3" })).ok, false);
});

test("the payload carries only the eight agreed values: no consumption, balance, weight, pallet number, recipe or any context", () => {
  const payload = buildP113Payload(ID, ASSIGNMENT, DEVICE, normalizeP113Draft(draft()).values);
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(payload.form_code, "VINTO-P1-13");
  assert.deepEqual(Object.keys(payload.values).sort(), ["cantidad_jabas", "hora_fin", "hora_inicio", "ingreso_kg", "numero_bobina", "observaciones", "saldo_final_kg", "saldo_inicial_kg"]);
  assert.equal(typeof payload.values.cantidad_jabas, "number");
  assert.equal(typeof payload.values.saldo_inicial_kg, "string"); // decimals travel as text: nothing is converted or rounded in the browser
  for (const key of ["consumo", "consumo_bobina", "consumo_kg", "saldo_disponible", "merma_bobina", "numero_pallet", "peso_nominal_jaba", "peso_total_pallet", "insumo", "tipo_bobina", "operador", "turno", "maquina", "fecha"]) assert.equal(key in payload.values, false, key);
});

test("no module of the P1-13 contract computes consumption (the legacy formula is nowhere) or uses legacy weights, recipes, pallet codes or the bobbin APIs", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["lib/vinto/p1-13.ts", "lib/vinto/p1-13-api.ts", "components/vinto/p1-13-capture.tsx"]) {
    assert.equal(/product-weights|NOMINAL_WEIGHT|RECIPES_BY_PRODUCT|PAL-|peso_total|peso_nominal|consumo_|bobbins-api|quality-bobbins|\/api\/bobbins/.test(code(file)), false, file);
    assert.equal(/Number\([^)]*saldo[^)]*\)\s*[-+]/.test(code(file)), false, file); // no `saldo_inicial + ingreso - saldo_final`
  }
});

// ---- intento pendiente inmutable --------------------------------------------------------------------------------------------------------------

test("an attempt is immutable and a new attempt gets a new UUIDv4", () => {
  let n = 0;
  const made = createP113Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.equal(made.ok, true);
  const { attempt } = made;
  assert.equal(attempt.captureId, "00000000-0000-4000-8000-000000000001");
  assert.equal(attempt.payload.capture_id, attempt.captureId);
  assert.equal(attempt.payload.values.saldo_inicial_kg, "100.5"); // the payload holds the normalized text; the draft keeps what was typed
  assert.equal(attempt.draft.saldo_inicial_kg, "100,5");
  assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.draft));
  assert.throws(() => { "use strict"; attempt.payload.values.saldo_final_kg = "1"; }, TypeError);
  assert.notEqual(createP113Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`).attempt.captureId, attempt.captureId);
  assert.match(createP113Attempt(draft(), ASSIGNMENT, DEVICE).attempt.captureId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.equal(createP113Attempt(EMPTY_P113_DRAFT, ASSIGNMENT, DEVICE).ok, false);
});

// ---- flujo: 201/200/409/422/401 y reconciliación tras timeout ---------------------------------------------------------------------------------

const attempt = createP113Attempt(draft(), ASSIGNMENT, DEVICE, () => ID).attempt;
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: parseP113Submission({ created, already_submitted: !created, capture: p113() }) });
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });

test("submit: 201 is created, a 200 identical retry is 'already received', both with the exact payload (no duplicate on retry)", async () => {
  const sent = [];
  const created = await submitP113Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  assert.equal(sent[0], attempt.payload);
  const again = await submitP113Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(false)) }));
  assert.equal(again.alreadySubmitted, true);
  assert.equal(sent[1], sent[0]);
});

test("submit: 401 / 403 / 404 / 409 / 422 map to the agreed outcomes (a stale assignment is reported as such) and never reconcile", async () => {
  const reject = (status, code) => submitP113Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
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
  const saved = await submitP113Attempt(attempt, deps({ post: timeout, get: async (id) => (asked.push(id), { ok: true, status: 200, data: parseP113Capture(p113()) }) }));
  assert.deepEqual(asked, [ID]);
  assert.equal(saved.kind, "submitted");
  assert.equal(saved.reconciled, true);
  assert.equal((await submitP113Attempt(attempt, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await submitP113Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "s", status: 503 }), get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  assert.deepEqual(await reconcileP113(ID, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 401 }) })), { kind: "session" });
  const other = parseP113Capture(p113("33333333-3333-4333-8333-333333333333"));
  assert.equal((await reconcileP113(ID, deps({ post: timeout, get: async () => ({ ok: true, status: 200, data: other }) }))).kind, "uncertain");
});

// ---- cliente HTTP genérico ---------------------------------------------------------------------------------------------------------------------------

function fakeFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, credentials: init.credentials, cache: init.cache }); return handler(String(url), init); };
  return { calls, restore: () => { globalThis.fetch = original; } };
}
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("HTTP: the P1-13 list sends form_code and uses the P1-13 parser; POST and GET use the shared central routes with the cookie session only", async () => {
  const stub = fakeFetch((url, init) => (init.method === "POST" ? json(201, { created: true, already_submitted: false, capture: p113() }) : url.includes("form_code") ? json(200, [p113()]) : json(200, p113())));
  try {
    const listed = await api.listP113(undefined, 10);
    assert.equal(listed.ok, true);
    assert.equal(listed.data[0].form.code, P1_13_CODE);
    assert.equal((await api.submitP113(attempt.payload)).status, 201);
    assert.equal((await api.getP113(ID)).ok, true);
  } finally { stub.restore(); }
  assert.deepEqual(stub.calls.map((c) => [c.method, c.url]), [["GET", "http://127.0.0.1:8190/api/captures?limit=10&form_code=VINTO-P1-13"], ["POST", "http://127.0.0.1:8190/api/captures"], ["GET", `http://127.0.0.1:8190/api/captures/${ID}`]]);
  assert.deepEqual(JSON.parse(stub.calls[1].body), attempt.payload);
  assert.ok(stub.calls.every((c) => c.credentials === "include"));
});

test("HTTP: a response of ANOTHER form is rejected by the P1-13 client (never mistaken)", async () => {
  const wrong = fakeFetch(() => json(200, [p112()]));
  try { assert.equal((await api.listP113()).ok, false); } finally { wrong.restore(); }
  const single = fakeFetch(() => json(200, p116()));
  try { assert.equal((await api.getP113(ID)).ok, false); } finally { single.restore(); }
  const post = fakeFetch(() => json(201, { created: true, already_submitted: false, capture: p112() }));
  try { assert.equal((await api.submitP113(attempt.payload)).ok, false); } finally { post.restore(); }
});

// ---- componente --------------------------------------------------------------------------------------------------------------------------------------

const CONTEXT = { assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "11319", productName: "SERVILLETA DECO BULLA 3*333",
  machine: "WALLY", shift: "Mañana (ficticio)", date: "2026-10-06" };
const html = (props) => server.renderToStaticMarkup(React.createElement(component.P113CaptureForm, { context: CONTEXT, online: true, attempt: null, setAttempt() {}, back() {}, onAssignmentChanged() {}, onSessionLost() {}, ...props }));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const disabledCount = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length;

test("component: eight candidate fields labelled as DECLARED, the mandatory advisory, server context and the pending decisions", () => {
  const markup = html({ user: { display_name: "Operación DEV" } }), plain = text(markup);
  assert.equal(ADVISORY, "Ficha candidata no homologada. Los saldos y el número de bobina son declaraciones de prueba: no generan consumo ni modifican inventario.");
  for (const piece of [ADVISORY, "Producción diaria de servilletas y especiales", "N.º de bobina (declarado) *", "Saldo inicial declarado *", "Ingreso declarado *", "Saldo final declarado *", "Cantidad de jabas *", "Hora inicio del pallet *",
    "Hora fin del pallet *", "Observaciones", "OT-2026-0001", "WALLY", "SERVILLETA DECO BULLA 3*333", "Mañana (ficticio) · 2026-10-06", "Ficha NO homologada · solo entorno de prueba", "No es la definición de 31 campos",
    "Número oficial de pallet", "— pendiente de definición —", "se asigna al enviar", "no se consulta ni se valida contra ninguna bobina", "Sin cálculo de consumo", "Enviar registro trazable"]) assert.ok(plain.includes(piece), piece);
  for (const note of PENDING_NOTES) assert.ok(plain.includes(note.label) && plain.includes(note.pending), note.key);
  assert.equal((markup.match(/data-section="pallet-id"/g) ?? []).length, 1); // the technical-id block appears exactly ONCE, right before the «Pallet» section
  assert.ok(markup.indexOf('data-section="pallet-id"') > markup.indexOf("Bobina declarada") && markup.indexOf('data-section="pallet-id"') < markup.indexOf("Mismos campos y validaciones que P1-12"));
  assert.equal((markup.match(/<input/g) ?? []).length, 7);
  assert.equal((markup.match(/<textarea/g) ?? []).length, 1);
  assert.equal((markup.match(/type="time"/g) ?? []).length, 2);
  assert.equal(/<select/.test(markup), false); // no recipe-driven lists
  assert.equal(/PAL-\d{8}|Consumo calculado|Peso total calculado|Consumo \d|Readout/i.test(plain), false); // nothing computed is shown
  assert.ok(plain.includes("Operación DEV") && plain.includes("no es una firma ni un grupo"));
  assert.equal(html({}).includes('data-section="session"'), false);
});

test("component: a pending attempt locks every field, keeps the typed draft, shows the technical id and offers the retry", () => {
  const made = createP113Attempt(draft(), ASSIGNMENT, DEVICE, () => ID).attempt;
  const markup = html({ attempt: made }), plain = text(markup);
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío.") && plain.includes(ID));
  assert.equal((markup.match(/data-section="pallet-id"/g) ?? []).length, 1); // still a single block while the attempt is pending (the technical id is the attempt's)
  assert.equal(disabledCount(markup, "input"), 7);
  assert.equal(disabledCount(markup, "textarea"), 1);
  assert.equal(disabledCount(markup, "button"), 0);
  assert.match(markup, /value="100,5"/);
  assert.match(markup, /value="BOBINA-FICTICIA-001"/);
});

test("history: renders the central P1-13 captures as DECLARED data (hours without seconds) and states honestly when the backend does not enable the form", () => {
  const render = (resource) => text(server.renderToStaticMarkup(React.createElement(history.P113History, { resource, refresh() {} })));
  const ready = render({ status: "ready", data: [parseP113Capture(p113())] });
  for (const piece of ["Servilletas y especiales (P1-13) · registros centrales", "declaraciones", "BOBINA-FICTICIA-001", "100.500", "150.25", "08:15", "09:05", "OT-2026-0001", "L1 / PV-1", "WALLY", "Mañana (ficticio)", "(decl.)"]) assert.ok(ready.includes(piece), piece);
  assert.equal(ready.includes("08:15:00"), false);
  assert.ok(render({ status: "ready", data: [] }).includes("Todavía no hay registros centrales"));
  assert.ok(render({ status: "error", kind: "invalid" }).includes("El backend no habilita este formulario para tu sesión."));
});

test("component and clients never touch business storage; P1-13 is wired only behind the Conversión navigation and only for CONVERSION", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["components/vinto/p1-13-capture.tsx", "lib/vinto/p1-13.ts", "lib/vinto/p1-13-api.ts"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|vinto-ot|vinto-asg|document\.cookie|Authorization/.test(code(file)), false, file);
  assert.equal(/form-definitions/.test(code("components/vinto/p1-13-capture.tsx")) || /form-definitions/.test(code("lib/vinto/p1-13.ts")), false);
  const page = readFileSync(join(root, "app/page.tsx"), "utf8");
  assert.match(page, /convCapture && front === "Conversión" && convCapture\.screen === "p113"/);
  assert.match(page, /P113CaptureForm/);
  for (const dir of ["app/p1-13", "app/preview", "app/qa-harness", "app/__qa", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir);
});
