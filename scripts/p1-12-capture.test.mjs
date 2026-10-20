// node --test scripts/p1-12-capture.test.mjs
// VINTO-P1-12 CANDIDATO central (M6-B, Conversión): contrato del cliente (un pallet = cantidad de jabas + hora de inicio + hora de fin), validación ESTRUCTURAL, payload inmutable, intento pendiente,
// reconciliación, separación de los demás formularios, componente e historial. La red se simula con funciones inyectadas o con un `fetch` de prueba.
// Nada de lo que se prueba aquí decide reglas industriales de P1-12 (número de pallet, peso nominal/total, límites de jabas, firma): siguen pendientes de VINTO.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { parseCapture, parseCaptureList } from "../lib/vinto/captures.ts";
import { parseP110Capture } from "../lib/vinto/p1-10.ts";
import { parseP116Capture } from "../lib/vinto/p1-16.ts";
import {
  EMPTY_P112_DRAFT, P1_12_CODE, PENDING_NOTES, buildP112Payload, createP112Attempt, normalizeP112Draft, parseP112Capture, parseP112List, parseP112Submission, reconcileP112, shortHour,
  submitP112Attempt,
} from "../lib/vinto/p1-12.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-p112-test-${process.pid}`);
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
  [api, component, history] = await Promise.all([bundle("lib/vinto/p1-12-api.ts", "p112api"), bundle("components/vinto/p1-12-capture.tsx", "comp"), bundle("components/vinto/central-form-history.tsx", "history")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444", DEVICE = "99999999-9999-4999-8999-999999999999", ID = "11111111-1111-4111-8111-111111111111";
const P112_VALUES = { cantidad_jabas: 40, hora_inicio: "08:15:00", hora_fin: "09:05:00" }; // PostgreSQL devuelve las horas con segundos
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "GAMBINI", name: "Gambini" }, shift: { code: "FICT_CONV_MANANA", name: "Mañana (ficticio)" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
const p112 = (id = ID, values = P112_VALUES) => envelope(id, P1_12_CODE, values);
const p116 = () => envelope(ID, "VINTO-P1-16", { tipo_merma: "toalla", origen_merma: "logs", peso_merma_kg: "1.500" });
const f6 = () => envelope(ID, "VINTO-P1-06", { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50" });
const draft = (o = {}) => ({ ...EMPTY_P112_DRAFT, cantidad_jabas: "40", hora_inicio: "08:15", hora_fin: "09:05", ...o });

// ---- separación de formularios en los parsers -------------------------------------------------------------------------------------------

test("P1-12 parsers accept only P1-12 captures; the other forms' parsers never accept them", () => {
  assert.deepEqual(parseP112Capture(p112()).values, P112_VALUES);
  for (const other of [f6(), p116()]) assert.equal(parseP112Capture(other), null);
  assert.equal(parseCapture(p112()), null);
  assert.equal(parseP110Capture(p112()), null);
  assert.equal(parseP116Capture(p112()), null);
  assert.equal(parseP112Capture(envelope(ID, "VINTO-P1-16", P112_VALUES)), null); // right values, wrong form code
  assert.equal(parseP112Capture(envelope(ID, "vinto-p1-12", P112_VALUES)), null);
  assert.equal(parseP112List([p112(), p116()]), null); // a mixed list is rejected as a whole
  assert.equal(parseCaptureList([f6(), p112()]), null);
  assert.equal(parseP112List([p112(), p112("33333333-3333-4333-8333-333333333333")]).length, 2);
  assert.equal(parseP112Submission({ created: true, already_submitted: false, capture: p116() }), null);
  assert.equal(parseP112Submission({ created: true, already_submitted: false, capture: p112() }).capture.form.code, P1_12_CODE);
});

test("the P1-12 values parser is strict: integer count and two hours; unknown keys (weights, pallet number) are dropped", () => {
  for (const bad of [{ ...P112_VALUES, cantidad_jabas: "40" }, { ...P112_VALUES, cantidad_jabas: 4.5 }, { ...P112_VALUES, cantidad_jabas: null }, { ...P112_VALUES, hora_inicio: "8:15" },
    { ...P112_VALUES, hora_inicio: "25:00:00" }, { ...P112_VALUES, hora_fin: 905 }, { cantidad_jabas: 1, hora_inicio: "08:00:00" }, null, [], "x"]) assert.equal(parseP112Capture(p112(ID, bad)), null, JSON.stringify(bad));
  const cleaned = parseP112Capture(p112(ID, { ...P112_VALUES, peso_total_pallet: 99, numero_pallet: "PAL-1", peso_nominal_jaba: 2 })).values;
  assert.deepEqual(Object.keys(cleaned).sort(), ["cantidad_jabas", "hora_fin", "hora_inicio"]);
  assert.equal(shortHour("08:15:00"), "08:15");
  assert.equal(parseP112Capture(p112(ID, { ...P112_VALUES, hora_inicio: "08:15", hora_fin: "23:59:59.5" })).values.hora_fin, "23:59:59.5");
});

// ---- validación estructural: solo lo estructural --------------------------------------------------------------------------------------------

test("structural validation: an integer and two HH:MM hours; NO minimum, maximum, ordering or industrial rule is invented", () => {
  assert.deepEqual(normalizeP112Draft(draft({ cantidad_jabas: " 40 " })), { ok: true, values: { cantidad_jabas: 40, hora_inicio: "08:15", hora_fin: "09:05" } });
  for (const jabas of ["0", "1", "007", "100000", "9007199254740991", "-3", "-0", "-9007199254740991"]) assert.equal(normalizeP112Draft(draft({ cantidad_jabas: jabas })).ok, true, jabas); // no min / max: a signed integer is structurally valid
  assert.equal(normalizeP112Draft(draft({ cantidad_jabas: "-3" })).values.cantidad_jabas, -3); // structural only: it does NOT authorize negative quantities in operation (pending VINTO)
  assert.equal(parseP112Capture(p112(ID, { ...P112_VALUES, cantidad_jabas: -3 })).values.cantidad_jabas, -3);
  assert.equal(normalizeP112Draft(draft({ hora_inicio: "22:00", hora_fin: "06:00" })).ok, true); // a pallet may cross midnight: end < start is NOT an error
  assert.equal(normalizeP112Draft(draft({ hora_inicio: "10:00", hora_fin: "10:00" })).ok, true);
  for (const jabas of ["", "  ", "4.5", "4,5", "+3", "--3", "- 3", "-3.5", "-", "abc", "1e3", "-1e3", "40 jabas", "9007199254740993", "-9007199254740993", "99999999999999999999"]) assert.equal(normalizeP112Draft(draft({ cantidad_jabas: jabas })).ok, false, jabas);
  for (const hour of ["", "8:15", "24:00", "12:60", "12:5", "12.30", "1230", "12:30:15", "mediodía"]) { assert.equal(normalizeP112Draft(draft({ hora_inicio: hour })).ok, false, hour); assert.equal(normalizeP112Draft(draft({ hora_fin: hour })).ok, false, hour); }
  const empty = normalizeP112Draft(EMPTY_P112_DRAFT);
  assert.equal(empty.ok, false);
  assert.equal(empty.errors.length, 3);
});

test("the payload carries only the three agreed values: no pallet number, nominal weight, total weight or any context", () => {
  const payload = buildP112Payload(ID, ASSIGNMENT, DEVICE, { cantidad_jabas: 40, hora_inicio: "08:15", hora_fin: "09:05" });
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(payload.form_code, "VINTO-P1-12");
  assert.deepEqual(Object.keys(payload.values).sort(), ["cantidad_jabas", "hora_fin", "hora_inicio"]);
  assert.equal(typeof payload.values.cantidad_jabas, "number");
  for (const key of ["numero_pallet", "peso_nominal_jaba", "peso_total_pallet", "peso_total", "operador", "turno", "maquina", "fecha"]) assert.equal(key in payload.values, false, key);
});

// ---- viabilidad del cálculo de peso: SOLO una prueba pura con pesos sintéticos, fuera del contrato ----------------------------------------

test("synthetic feasibility only: jabas × nominal weight with exact decimal arithmetic (not used by the contract, the client or the backend)", () => {
  // Pesos COMPLETAMENTE sintéticos (no son los del maestro legacy). Aritmética exacta con BigInt escalado; el flotante de JS no sirve para esto.
  const exactTotal = (jabas, nominal) => {
    const [whole, frac = ""] = nominal.split("."), scale = 10n ** BigInt(frac.length), units = BigInt(whole + frac) * BigInt(jabas);
    const intPart = units / scale, rest = (units % scale).toString().padStart(frac.length, "0").replace(/0+$/, "");
    return rest ? `${intPart}.${rest}` : `${intPart}`;
  };
  assert.equal(exactTotal(3, "2.1"), "6.3");
  assert.notEqual(3 * 2.1, 6.3); // el flotante da 6.300000000000001: por eso un peso oficial exigiría decimales exactos
  assert.equal(exactTotal(40, "0.108486"), "4.33944");
  assert.equal(exactTotal(0, "7.25"), "0");
  assert.equal(exactTotal(12, "10"), "120");
  // el contrato NO usa nada de esto
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["lib/vinto/p1-12.ts", "components/vinto/p1-12-capture.tsx"]) assert.equal(/product-weights|NOMINAL_WEIGHT|peso_nominal|peso_total|PAL-/.test(code(file)), false, file);
});

// ---- intento pendiente inmutable --------------------------------------------------------------------------------------------------------------

test("an attempt is immutable and a new attempt gets a new UUIDv4", () => {
  let n = 0;
  const made = createP112Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.equal(made.ok, true);
  const { attempt } = made;
  assert.equal(attempt.captureId, "00000000-0000-4000-8000-000000000001");
  assert.equal(attempt.payload.capture_id, attempt.captureId);
  assert.deepEqual(attempt.payload.values, { cantidad_jabas: 40, hora_inicio: "08:15", hora_fin: "09:05" });
  assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.draft));
  assert.throws(() => { "use strict"; attempt.payload.values.cantidad_jabas = 99; }, TypeError);
  assert.notEqual(createP112Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`).attempt.captureId, attempt.captureId);
  assert.match(createP112Attempt(draft(), ASSIGNMENT, DEVICE).attempt.captureId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.equal(createP112Attempt(EMPTY_P112_DRAFT, ASSIGNMENT, DEVICE).ok, false);
});

// ---- flujo: 201/200/409/422/401 y reconciliación tras timeout ---------------------------------------------------------------------------------

const attempt = createP112Attempt(draft(), ASSIGNMENT, DEVICE, () => ID).attempt;
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: parseP112Submission({ created, already_submitted: !created, capture: p112() }) });
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });

test("submit: 201 is created, a 200 identical retry is 'already received', both with the exact payload (no duplicate on retry)", async () => {
  const sent = [];
  const created = await submitP112Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  assert.equal(sent[0], attempt.payload);
  const again = await submitP112Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(false)) }));
  assert.equal(again.alreadySubmitted, true);
  assert.equal(sent[1], sent[0]);
});

test("submit: 401 / 403 / 404 / 409 / 422 map to the agreed outcomes (a stale assignment is reported as such) and never reconcile", async () => {
  const reject = (status, code) => submitP112Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
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
  const saved = await submitP112Attempt(attempt, deps({ post: timeout, get: async (id) => (asked.push(id), { ok: true, status: 200, data: parseP112Capture(p112()) }) }));
  assert.deepEqual(asked, [ID]);
  assert.equal(saved.kind, "submitted");
  assert.equal(saved.reconciled, true);
  assert.equal((await submitP112Attempt(attempt, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await submitP112Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "s", status: 503 }), get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  assert.deepEqual(await reconcileP112(ID, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 401 }) })), { kind: "session" });
  const other = parseP112Capture(p112("33333333-3333-4333-8333-333333333333"));
  assert.equal((await reconcileP112(ID, deps({ post: timeout, get: async () => ({ ok: true, status: 200, data: other }) }))).kind, "uncertain");
});

// ---- cliente HTTP genérico ---------------------------------------------------------------------------------------------------------------------------

function fakeFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, credentials: init.credentials, cache: init.cache }); return handler(String(url), init); };
  return { calls, restore: () => { globalThis.fetch = original; } };
}
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("HTTP: the P1-12 list sends form_code and uses the P1-12 parser; POST and GET use the shared central routes with the cookie session only", async () => {
  const stub = fakeFetch((url, init) => (init.method === "POST" ? json(201, { created: true, already_submitted: false, capture: p112() }) : url.includes("form_code") ? json(200, [p112()]) : json(200, p112())));
  try {
    const listed = await api.listP112(undefined, 10);
    assert.equal(listed.ok, true);
    assert.equal(listed.data[0].form.code, P1_12_CODE);
    assert.equal((await api.submitP112(attempt.payload)).status, 201);
    assert.equal((await api.getP112(ID)).ok, true);
  } finally { stub.restore(); }
  assert.deepEqual(stub.calls.map((c) => [c.method, c.url]), [["GET", "http://127.0.0.1:8190/api/captures?limit=10&form_code=VINTO-P1-12"], ["POST", "http://127.0.0.1:8190/api/captures"], ["GET", `http://127.0.0.1:8190/api/captures/${ID}`]]);
  assert.deepEqual(JSON.parse(stub.calls[1].body), attempt.payload);
  assert.ok(stub.calls.every((c) => c.credentials === "include"));
});

test("HTTP: a response of ANOTHER form is rejected by the P1-12 client (never mistaken)", async () => {
  const wrong = fakeFetch(() => json(200, [p116()]));
  try { assert.equal((await api.listP112()).ok, false); } finally { wrong.restore(); }
  const single = fakeFetch(() => json(200, f6()));
  try { assert.equal((await api.getP112(ID)).ok, false); } finally { single.restore(); }
  const post = fakeFetch(() => json(201, { created: true, already_submitted: false, capture: p116() }));
  try { assert.equal((await api.submitP112(attempt.payload)).ok, false); } finally { post.restore(); }
});

// ---- componente --------------------------------------------------------------------------------------------------------------------------------------

const CONTEXT = { assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "10351", productName: "PERLITA ECO PLUS 4*12",
  machine: "GAMBINI", shift: "Mañana (ficticio)", date: "2026-10-06" };
const html = (props) => server.renderToStaticMarkup(React.createElement(component.P112CaptureForm, { context: CONTEXT, online: true, attempt: null, setAttempt() {}, back() {}, onAssignmentChanged() {}, onSessionLost() {}, ...props }));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const disabledCount = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length;

test("component: three candidate fields, server context, pallet number pending and the non-homologated notice", () => {
  const markup = html({ user: { display_name: "Operación DEV" } }), plain = text(markup);
  for (const piece of ["Producción diaria de papel higiénico", "Cantidad de jabas *", "Hora inicio del pallet *", "Hora fin del pallet *", "OT-2026-0001", "GAMBINI", "PERLITA ECO PLUS 4*12", "Mañana (ficticio) · 2026-10-06",
    "Ficha NO homologada · solo entorno de prueba", "un pallet por captura", "No es la definición de 37 campos", "Número oficial de pallet", "— pendiente de definición —", "se asigna al enviar", "Enviar registro trazable"]) assert.ok(plain.includes(piece), piece);
  for (const note of PENDING_NOTES) assert.ok(plain.includes(note.label) && plain.includes(note.pending), note.key);
  assert.equal((markup.match(/<input/g) ?? []).length, 3);
  assert.equal((markup.match(/type="time"/g) ?? []).length, 2);
  assert.equal(/<select|<textarea/.test(markup), false);
  assert.equal(/PAL-\d{8}|Peso total calculado|Peso nominal por jaba/i.test(plain), false); // no pallet code and no computed weight is shown as a result
  assert.ok(plain.includes("Operación DEV") && plain.includes("no es una firma ni un grupo"));
  assert.equal(html({}).includes('data-section="session"'), false);
});

test("component: a pending attempt locks every field, keeps the typed draft, shows the technical id and offers the retry", () => {
  const made = createP112Attempt(draft(), ASSIGNMENT, DEVICE, () => ID).attempt;
  const markup = html({ attempt: made }), plain = text(markup);
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío.") && plain.includes(ID));
  assert.equal(disabledCount(markup, "input"), 3);
  assert.equal(disabledCount(markup, "button"), 0);
  assert.match(markup, /value="40"/);
  assert.match(markup, /value="08:15"/);
});

test("history: renders the central P1-12 captures (hours without seconds) and states honestly when the backend does not enable the form", () => {
  const render = (resource) => text(server.renderToStaticMarkup(React.createElement(history.P112History, { resource, refresh() {} })));
  const ready = render({ status: "ready", data: [parseP112Capture(p112())] });
  for (const piece of ["Producción por pallet (P1-12) · registros centrales", "40", "08:15", "09:05", "OT-2026-0001", "L1 / PV-1", "GAMBINI", "Mañana (ficticio)", "pendiente"]) assert.ok(ready.includes(piece), piece);
  assert.equal(ready.includes("08:15:00"), false);
  assert.ok(render({ status: "ready", data: [] }).includes("Todavía no hay registros centrales"));
  assert.ok(render({ status: "error", kind: "invalid" }).includes("El backend no habilita este formulario para tu sesión."));
});

test("component and clients never touch business storage; P1-12 is wired only behind the Conversión navigation and only for CONVERSION", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["components/vinto/p1-12-capture.tsx", "lib/vinto/p1-12.ts", "lib/vinto/p1-12-api.ts"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|vinto-ot|vinto-asg|document\.cookie|Authorization/.test(code(file)), false, file);
  assert.equal(/form-definitions/.test(code("components/vinto/p1-12-capture.tsx")) || /form-definitions/.test(code("lib/vinto/p1-12.ts")), false);
  // G.12-C4-FINAL25: P1-12 pasó al renderizador genérico (CandidateFormCapture + CONVERSION_CANDIDATES); P112CaptureForm queda sin enlazar (código muerto documentado, no eliminado).
  const page = readFileSync(join(root, "app/page.tsx"), "utf8");
  assert.match(page, /convCapture && front === "Conversión" && isConversionCandidate\(convCapture\.screen\)/);
  assert.match(page, /candidate=\{CONVERSION_CANDIDATES\[screen\]\}/);
  assert.equal(/P112CaptureForm/.test(page), false);
  for (const dir of ["app/p1-12", "app/preview", "app/qa-harness", "app/__qa", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir);
});
