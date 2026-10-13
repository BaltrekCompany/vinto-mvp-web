// node --test scripts/p1-16-capture.test.mjs
// VINTO-P1-16 CANDIDATO central (M6-A, Conversión): contrato del cliente (valores, validación ESTRUCTURAL, payload inmutable, intento pendiente, reconciliación), separación F6/P1-10/P1-16
// en los parsers y en el cliente HTTP genérico, y el componente de captura renderizado. La red se simula con funciones inyectadas o con un `fetch` de prueba.
// Nada de lo que se prueba aquí decide reglas industriales de P1-16 (correlativo, firma, grupo, totales, unidad/rango del peso): siguen pendientes de VINTO.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { parseCapture, parseCaptureList } from "../lib/vinto/captures.ts";
import { parseP110Capture } from "../lib/vinto/p1-10.ts";
import {
  EMPTY_P116_DRAFT, ORIGEN_MERMA_OPTIONS, P1_16_CODE, PENDING_NOTES, TIPO_MERMA_OPTIONS, buildP116Payload, createP116Attempt, normalizeP116Draft, parseP116Capture, parseP116List,
  parseP116Submission, reconcileP116, submitP116Attempt,
} from "../lib/vinto/p1-16.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-p116-test-${process.pid}`);
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
  [api, component, history] = await Promise.all([bundle("lib/vinto/p1-16-api.ts", "p116api"), bundle("components/vinto/p1-16-capture.tsx", "comp"), bundle("components/vinto/central-form-history.tsx", "history")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444", DEVICE = "99999999-9999-4999-8999-999999999999", ID = "11111111-1111-4111-8111-111111111111";
const P116_VALUES = { tipo_merma: "hoja_doble", origen_merma: "logs", peso_merma_kg: "12.500" };
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "GAMBINI", name: "Gambini" }, shift: { code: "FICT_CONV_MANANA", name: "Mañana (ficticio)" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
const p116 = (id = ID, values = P116_VALUES) => envelope(id, P1_16_CODE, values);
const f6 = (id = ID) => envelope(id, "VINTO-P1-06", { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50" });
const draft = (o = {}) => ({ ...EMPTY_P116_DRAFT, tipo_merma: "hoja_doble", origen_merma: "logs", peso_merma_kg: "12,5", ...o });

// ---- separación F6 / P1-10 / P1-16 en los parsers ---------------------------------------------------------------------------------

test("P1-16 parsers accept only P1-16 captures; F6 and P1-10 parsers never accept them", () => {
  assert.deepEqual(parseP116Capture(p116()).values, P116_VALUES);
  assert.equal(parseP116Capture(f6()), null);
  assert.equal(parseCapture(p116()), null);
  assert.equal(parseP110Capture(p116()), null);
  assert.equal(parseP116Capture(envelope(ID, "VINTO-P1-10", P116_VALUES)), null); // right values, wrong form code
  assert.equal(parseP116Capture(envelope(ID, "vinto-p1-16", P116_VALUES)), null);
  assert.equal(parseP116List([p116(), f6()]), null); // a mixed list is rejected as a whole
  assert.equal(parseCaptureList([f6(), p116()]), null);
  assert.equal(parseP116List([p116(), p116("33333333-3333-4333-8333-333333333333")]).length, 2);
  assert.equal(parseP116Submission({ created: true, already_submitted: false, capture: f6() }), null);
  assert.equal(parseP116Submission({ created: true, already_submitted: false, capture: p116() }).capture.form.code, P1_16_CODE);
});

test("the P1-16 values parser is strict: known options and a decimal text; unknown keys are dropped", () => {
  for (const bad of [{ ...P116_VALUES, tipo_merma: "Hoja doble" }, { ...P116_VALUES, tipo_merma: "papel" }, { ...P116_VALUES, origen_merma: "planta" }, { ...P116_VALUES, peso_merma_kg: 12.5 },
    { ...P116_VALUES, peso_merma_kg: "12,5" }, { ...P116_VALUES, peso_merma_kg: "" }, { ...P116_VALUES, peso_merma_kg: null }, { tipo_merma: "toalla", origen_merma: "cola" }, null, [], "x"]) {
    assert.equal(parseP116Capture(p116(ID, bad)), null, JSON.stringify(bad));
  }
  assert.equal("extra" in parseP116Capture(p116(ID, { ...P116_VALUES, extra: 1 })).values, false);
  assert.equal(parseP116Capture(p116(ID, { ...P116_VALUES, peso_merma_kg: "0.250" })).values.peso_merma_kg, "0.250");
});

test("the options are exactly those of the legacy WasteCapture screen", () => {
  assert.deepEqual(TIPO_MERMA_OPTIONS.map((o) => o.label), ["Hoja doble", "Hoja simple", "Servilleta", "Toalla", "Cartón", "Plástico"]);
  assert.deepEqual(ORIGEN_MERMA_OPTIONS.map((o) => o.label), ["Logs", "Cola", "Máquina"]);
});

// ---- validación estructural: solo lo estructural ------------------------------------------------------------------------------------

test("structural validation: options and a decimal weight; the comma is normalized and NO range, unit or rounding rule is invented", () => {
  assert.deepEqual(normalizeP116Draft(draft({ peso_merma_kg: " 12,5 " })), { ok: true, values: { tipo_merma: "hoja_doble", origen_merma: "logs", peso_merma_kg: "12.5" } });
  for (const weight of ["0", "0.001", "1234567.891", "007", "12.50"]) assert.equal(normalizeP116Draft(draft({ peso_merma_kg: weight })).ok, true, weight); // no range, no decimals rule
  assert.equal(normalizeP116Draft(draft({ peso_merma_kg: "12.50" })).values.peso_merma_kg, "12.50"); // no rounding
  for (const weight of ["", "   ", "abc", "1e3", "12 kg", "1,2,3", "12.", ".5", "9".repeat(41)]) assert.equal(normalizeP116Draft(draft({ peso_merma_kg: weight })).ok, false, weight);
  const empty = normalizeP116Draft(EMPTY_P116_DRAFT);
  assert.equal(empty.ok, false);
  assert.equal(empty.errors.length, 3);
  assert.equal(normalizeP116Draft(draft({ tipo_merma: "Hoja doble" })).ok, false); // the label is not the key
  assert.equal(normalizeP116Draft(draft({ tipo_merma: "" })).ok, false);
  assert.equal(normalizeP116Draft(draft({ origen_merma: "planta" })).ok, false);
});

test("the payload carries only the three agreed values: no correlative, total, signature, group or any context", () => {
  const payload = buildP116Payload(ID, ASSIGNMENT, DEVICE, P116_VALUES);
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(payload.form_code, "VINTO-P1-16");
  assert.deepEqual(Object.keys(payload.values).sort(), ["origen_merma", "peso_merma_kg", "tipo_merma"]);
  for (const key of ["numero_correlativo", "total_merma_kg", "firma", "grupo", "operador", "turno", "maquina", "fecha"]) assert.equal(key in payload.values, false, key);
});

// ---- intento pendiente inmutable ----------------------------------------------------------------------------------------------------

test("an attempt is immutable and a new attempt gets a new UUIDv4", () => {
  let n = 0;
  const made = createP116Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.equal(made.ok, true);
  const { attempt } = made;
  assert.equal(attempt.captureId, "00000000-0000-4000-8000-000000000001");
  assert.equal(attempt.payload.capture_id, attempt.captureId);
  assert.equal(attempt.payload.values.peso_merma_kg, "12.5"); // the payload holds the normalized weight; the draft keeps what was typed
  assert.equal(attempt.draft.peso_merma_kg, "12,5");
  assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.draft));
  assert.throws(() => { "use strict"; attempt.payload.values.peso_merma_kg = "99"; }, TypeError);
  const another = createP116Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.notEqual(another.attempt.captureId, attempt.captureId);
  assert.match(createP116Attempt(draft(), ASSIGNMENT, DEVICE).attempt.captureId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.equal(createP116Attempt(EMPTY_P116_DRAFT, ASSIGNMENT, DEVICE).ok, false);
});

// ---- flujo: 201/200/409/422/401 y reconciliación tras timeout --------------------------------------------------------------------------

const attempt = createP116Attempt(draft(), ASSIGNMENT, DEVICE, () => ID).attempt;
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: parseP116Submission({ created, already_submitted: !created, capture: p116() }) });
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });

test("submit: 201 is created, a 200 identical retry is 'already received', both with the exact payload (no duplicate on retry)", async () => {
  const sent = [];
  const created = await submitP116Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  assert.equal(sent[0], attempt.payload);
  const again = await submitP116Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(false)) }));
  assert.equal(again.alreadySubmitted, true);
  assert.equal(sent[1], sent[0]); // the retry sends the very same immutable payload (same capture_id)
});

test("submit: 401 / 403 / 404 / 409 / 422 map to the agreed outcomes (a stale assignment is reported as such) and never reconcile", async () => {
  const reject = (status, code) => submitP116Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
  assert.deepEqual(await reject(401), { kind: "session" });
  assert.equal((await reject(403)).reason, "forbidden");
  assert.equal((await reject(404)).reason, "not_found");
  assert.equal((await reject(422, "CAPTURE_VALIDATION")).reason, "invalid");
  assert.equal((await reject(422, "UNSUPPORTED_FORM")).reason, "invalid");
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
  const saved = await submitP116Attempt(attempt, deps({ post: timeout, get: async (id) => (asked.push(id), { ok: true, status: 200, data: parseP116Capture(p116()) }) }));
  assert.deepEqual(asked, [ID]);
  assert.equal(saved.kind, "submitted");
  assert.equal(saved.reconciled, true);
  assert.equal((await submitP116Attempt(attempt, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await submitP116Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "s", status: 503 }), get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  assert.deepEqual(await reconcileP116(ID, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 401 }) })), { kind: "session" });
  const other = parseP116Capture(p116("33333333-3333-4333-8333-333333333333"));
  assert.equal((await reconcileP116(ID, deps({ post: timeout, get: async () => ({ ok: true, status: 200, data: other }) }))).kind, "uncertain"); // a different id is never accepted
});

// ---- cliente HTTP genérico ---------------------------------------------------------------------------------------------------------------------

function fakeFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, credentials: init.credentials, cache: init.cache }); return handler(String(url), init); };
  return { calls, restore: () => { globalThis.fetch = original; } };
}
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("HTTP: the P1-16 list sends form_code and uses the P1-16 parser; POST and GET use the shared central routes with the cookie session only", async () => {
  const stub = fakeFetch((url, init) => (init.method === "POST" ? json(201, { created: true, already_submitted: false, capture: p116() }) : url.includes("form_code") ? json(200, [p116()]) : json(200, p116())));
  try {
    const listed = await api.listP116(undefined, 10);
    assert.equal(listed.ok, true);
    assert.equal(listed.data[0].form.code, P1_16_CODE);
    assert.equal((await api.submitP116(attempt.payload)).status, 201);
    assert.equal((await api.getP116(ID)).ok, true);
  } finally { stub.restore(); }
  assert.deepEqual(stub.calls.map((c) => [c.method, c.url]), [["GET", "http://127.0.0.1:8190/api/captures?limit=10&form_code=VINTO-P1-16"], ["POST", "http://127.0.0.1:8190/api/captures"], ["GET", `http://127.0.0.1:8190/api/captures/${ID}`]]);
  assert.deepEqual(JSON.parse(stub.calls[1].body), attempt.payload);
  assert.ok(stub.calls.every((c) => c.credentials === "include"));
});

test("HTTP: a response of ANOTHER form is rejected by the P1-16 client (never mistaken)", async () => {
  const wrong = fakeFetch(() => json(200, [f6()]));
  try { assert.equal((await api.listP116()).ok, false); } finally { wrong.restore(); }
  const single = fakeFetch(() => json(200, f6()));
  try { assert.equal((await api.getP116(ID)).ok, false); } finally { single.restore(); }
  const post = fakeFetch(() => json(201, { created: true, already_submitted: false, capture: f6() }));
  try { assert.equal((await api.submitP116(attempt.payload)).ok, false); } finally { post.restore(); }
});

// ---- componente ------------------------------------------------------------------------------------------------------------------------------------

const CONTEXT = { assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "10351", productName: "PERLITA ECO PLUS 4*12",
  machine: "GAMBINI", shift: "Mañana (ficticio)", date: "2026-10-06" };
const html = (props) => server.renderToStaticMarkup(React.createElement(component.P116CaptureForm, { context: CONTEXT, online: true, attempt: null, setAttempt() {}, back() {}, onAssignmentChanged() {}, onSessionLost() {}, ...props }));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const disabledCount = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length;

test("component: three candidate fields, server context, the pending decisions and the non-homologated notice", () => {
  const markup = html({ user: { display_name: "Operación DEV" } }), plain = text(markup);
  for (const piece of ["Registro de control de merma", "Tipo de merma *", "Origen de la merma *", "Peso real *", "Hoja doble", "Cartón", "Plástico", "Logs", "Cola", "Máquina", "OT-2026-0001", "GAMBINI",
    "PERLITA ECO PLUS 4*12", "Mañana (ficticio) · 2026-10-06", "Ficha NO homologada · solo entorno de prueba", "hipótesis de prueba", "Enviar registro trazable"]) assert.ok(plain.includes(piece), piece);
  for (const note of PENDING_NOTES) assert.ok(plain.includes(note.label) && plain.includes(note.pending), note.key);
  assert.equal((markup.match(/<select/g) ?? []).length, 2);
  assert.equal((markup.match(/<input/g) ?? []).length, 1);
  assert.equal(disabledCount(markup, "input") + disabledCount(markup, "select"), 0);
  assert.ok(plain.includes("Operación DEV") && plain.includes("no es una firma ni un grupo"));
  assert.equal(markup.includes('data-section="session"'), true);
  assert.equal(html({}).includes('data-section="session"'), false);
});

test("component: a pending attempt locks every field, keeps the typed draft and offers the retry", () => {
  const made = createP116Attempt(draft({ peso_merma_kg: "12,5" }), ASSIGNMENT, DEVICE, () => ID).attempt;
  const markup = html({ attempt: made }), plain = text(markup);
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío."));
  assert.equal(disabledCount(markup, "input"), 1);
  assert.equal(disabledCount(markup, "select"), 2);
  assert.equal(disabledCount(markup, "button"), 0); // the retry button stays enabled
  assert.match(markup, /value="12,5"/);
  assert.match(markup, /<option value="hoja_doble" selected/);
});

test("history: renders the central P1-16 captures with labels, and states honestly when the backend does not enable the form", () => {
  const render = (resource) => text(server.renderToStaticMarkup(React.createElement(history.P116History, { resource, refresh() {} })));
  const ready = render({ status: "ready", data: [parseP116Capture(p116())] });
  for (const piece of ["Control de merma (P1-16) · registros centrales", "Hoja doble", "Logs", "12.500", "OT-2026-0001", "L1 / PV-1", "GAMBINI", "Mañana (ficticio)"]) assert.ok(ready.includes(piece), piece);
  assert.ok(render({ status: "ready", data: [] }).includes("Todavía no hay registros centrales"));
  assert.ok(render({ status: "error", kind: "invalid" }).includes("El backend no habilita este formulario para tu sesión."));
});

test("component and clients never touch business storage or credentials; P1-16 is wired only behind the backend-verified Conversión navigation", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["components/vinto/p1-16-capture.tsx", "components/vinto/conversion-central.tsx", "lib/vinto/p1-16.ts", "lib/vinto/p1-16-api.ts"]) {
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|vinto-ot|vinto-asg|document\.cookie|Authorization/.test(code(file)), false, file);
  }
  assert.equal(/form-definitions|WasteCapture/.test(code("components/vinto/p1-16-capture.tsx")) || /form-definitions/.test(code("lib/vinto/p1-16.ts")), false);
  const page = readFileSync(join(root, "app/page.tsx"), "utf8");
  assert.match(page, /P116CaptureForm/);
  assert.match(page, /front === "Conversión" \? <ConversionCentral/); // the legacy Conversión screens are no longer reachable from the navigation (and are NOT a fallback)
  for (const dir of ["app/p1-16", "app/preview", "app/qa-harness", "app/__qa", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir);
});
