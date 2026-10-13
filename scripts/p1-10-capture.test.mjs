// node --test scripts/p1-10-capture.test.mjs
// VINTO-P1-10 central (M2-B2): contrato del cliente (valores, validación ESTRUCTURAL, payload inmutable, intento pendiente, reconciliación), separación F6/P1-10 en los
// parsers y en el cliente HTTP genérico, y el componente de captura renderizado. La red se simula con funciones inyectadas o con un `fetch` de prueba.
// Nada de lo que se prueba aquí decide reglas industriales de P1-10 (numeración, peso, responsable, firma, máquinas): siguen pendientes.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { EMPTY_DRAFT, parseCapture, parseCaptureList } from "../lib/vinto/captures.ts";
import {
  CONTEXT_NOTES, EMPTY_P110_DRAFT, MAX_TEXT_LENGTH, P1_10_CODE, buildP110Payload, createP110Attempt, normalizeP110Draft, parseP110Capture, parseP110List, parseP110Submission,
  reconcileP110, submitP110Attempt,
} from "../lib/vinto/p1-10.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-p110-test-${process.pid}`);
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
  [api, f6api, component] = await Promise.all([bundle("lib/vinto/p1-10-api.ts", "p110api"), bundle("lib/vinto/captures-api.ts", "f6api"), bundle("components/vinto/p1-10-capture.tsx", "comp")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const ASSIGNMENT = "44444444-4444-4444-8444-444444444444", DEVICE = "99999999-9999-4999-8999-999999999999", ID = "11111111-1111-4111-8111-111111111111";
const P110_VALUES = { codigo_numero_de_producto: "EJ-PROD", numero_de_fardo: "00-0042", peso_fardo: "12,5 kg", observaciones: "x" };
const F6_VALUES = { cantidad_fardos: 2, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50" };
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "Formulario" },
  machine: { code: "COPASA", name: "Copasa" }, shift: { code: "FICT_DIA", name: "Día (ficticio)" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1024", description: "BOBINA" } }, values,
});
const p110 = (id = ID, values = P110_VALUES) => envelope(id, P1_10_CODE, values);
const f6 = (id = ID) => envelope(id, "VINTO-P1-06", F6_VALUES);
const draft = (o = {}) => ({ ...EMPTY_P110_DRAFT, codigo_numero_de_producto: "EJ-PROD", numero_de_fardo: "00-0042", peso_fardo: "12,5 kg", observaciones: "x", ...o });

// ---- separación F6 / P1-10 en los parsers -------------------------------------------------------------------------------------

test("P1-10 parsers accept only P1-10 captures; F6 parsers accept only F6 captures", () => {
  assert.deepEqual(parseP110Capture(p110()).values, P110_VALUES);
  assert.equal(parseP110Capture(f6()), null); // an F6 response is never a P1-10 capture
  assert.equal(parseCapture(p110()), null); // and a P1-10 response is never an F6 capture
  assert.equal(parseP110Capture(envelope(ID, "VINTO-P1-06", P110_VALUES)), null); // P1-10 values under another form code: rejected by the expected code
  assert.equal(parseP110Capture(envelope(ID, "vinto-p1-10", P110_VALUES)), null);
  assert.equal(parseP110List([p110(), f6()]), null); // a mixed list is rejected as a whole
  assert.equal(parseCaptureList([f6(), p110()]), null);
  assert.equal(parseP110List([p110(), p110("33333333-3333-4333-8333-333333333333")]).length, 2);
  assert.equal(parseP110Submission({ created: true, already_submitted: false, capture: f6() }), null);
  assert.equal(parseP110Submission({ created: true, already_submitted: false, capture: p110() }).capture.form.code, P1_10_CODE);
});

test("the P1-10 values parser is strict about the three required texts and the optional notes", () => {
  for (const bad of [{ ...P110_VALUES, codigo_numero_de_producto: "" }, { ...P110_VALUES, numero_de_fardo: 42 }, { ...P110_VALUES, peso_fardo: 12.5 }, { ...P110_VALUES, peso_fardo: null },
    { ...P110_VALUES, observaciones: 5 }, { numero_de_fardo: "1", peso_fardo: "1" }, null, [], "x"]) assert.equal(parseP110Capture(p110(ID, bad)), null, JSON.stringify(bad));
  const without = { ...P110_VALUES };
  delete without.observaciones;
  assert.equal("observaciones" in parseP110Capture(p110(ID, without)).values, false);
  assert.equal("extra" in parseP110Capture(p110(ID, { ...P110_VALUES, extra: 1 })).values, false); // unknown value keys are dropped
});

// ---- validación estructural: solo lo estructural -----------------------------------------------------------------------------------

test("structural validation: trims, requires the three texts and invents no format, range, unit or uniqueness rule", () => {
  const ok = normalizeP110Draft(draft({ codigo_numero_de_producto: "  Ab 1/2  ", numero_de_fardo: " 00-0042 ", peso_fardo: " 12,50 kg ", observaciones: "  " }));
  assert.deepEqual(ok, { ok: true, values: { codigo_numero_de_producto: "Ab 1/2", numero_de_fardo: "00-0042", peso_fardo: "12,50 kg" } }); // blank notes are omitted
  for (const weight of ["12,5", "12.5", "abc", "-3", "0", "1e3", "doce kilos", "9".repeat(60)]) assert.equal(normalizeP110Draft(draft({ peso_fardo: weight })).ok, true, weight); // the weight is TEXT
  for (const bale of ["1", "A", "ñandú-1", "0000000001", "x y z"]) assert.equal(normalizeP110Draft(draft({ numero_de_fardo: bale })).ok, true, bale); // no format, no numbering
  const empty = normalizeP110Draft(EMPTY_P110_DRAFT);
  assert.equal(empty.ok, false);
  assert.equal(empty.errors.length, 3);
  assert.ok(empty.errors.every((e) => e.endsWith("es obligatorio.")));
  assert.equal(normalizeP110Draft(draft({ numero_de_fardo: "   " })).ok, false);
  assert.equal(normalizeP110Draft(draft({ codigo_numero_de_producto: "x".repeat(MAX_TEXT_LENGTH + 1) })).ok, false);
  assert.equal(normalizeP110Draft(draft({ observaciones: "x".repeat(MAX_TEXT_LENGTH + 1) })).ok, false);
  assert.equal(normalizeP110Draft(draft({ codigo_numero_de_producto: "x".repeat(MAX_TEXT_LENGTH) })).ok, true);
});

test("the payload carries only the agreed fields: no date, machine, responsible, signature or any context", () => {
  const payload = buildP110Payload(ID, ASSIGNMENT, DEVICE, { codigo_numero_de_producto: "A", numero_de_fardo: "B", peso_fardo: "C" });
  assert.deepEqual(Object.keys(payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
  assert.equal(payload.form_code, "VINTO-P1-10");
  assert.deepEqual(Object.keys(payload.values).sort(), ["codigo_numero_de_producto", "numero_de_fardo", "peso_fardo"]);
  for (const key of ["fecha", "maquina", "responsable", "firma"]) assert.equal(key in payload.values, false, key);
});

// ---- intento pendiente inmutable --------------------------------------------------------------------------------------------------------

test("an attempt is immutable and a new attempt gets a new UUIDv4", () => {
  let n = 0;
  const made = createP110Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.equal(made.ok, true);
  const { attempt } = made;
  assert.equal(attempt.captureId, "00000000-0000-4000-8000-000000000001");
  assert.equal(attempt.payload.capture_id, attempt.captureId);
  assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.draft));
  assert.throws(() => { "use strict"; attempt.payload.values.peso_fardo = "otro"; }, TypeError);
  assert.deepEqual(attempt.draft, draft()); // the typed draft is kept exactly (it restores the form after a Volver)
  const another = createP110Attempt(draft(), ASSIGNMENT, DEVICE, () => `00000000-0000-4000-8000-00000000000${++n}`);
  assert.notEqual(another.attempt.captureId, attempt.captureId);
  const real = createP110Attempt(draft(), ASSIGNMENT, DEVICE);
  assert.match(real.attempt.captureId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.equal(createP110Attempt(EMPTY_P110_DRAFT, ASSIGNMENT, DEVICE).ok, false);
});

// ---- flujo: 201/200/409/422/401 y reconciliación tras timeout ------------------------------------------------------------------------------

const attempt = createP110Attempt(draft(), ASSIGNMENT, DEVICE, () => ID).attempt;
const okSubmission = (created) => ({ ok: true, status: created ? 201 : 200, data: parseP110Submission({ created, already_submitted: !created, capture: p110() }) });
const deps = ({ post, get }) => ({ post, get: get ?? (async () => { throw new Error("no GET expected"); }) });

test("submit: 201 is created, a 200 identical retry is 'already received', both with the exact payload", async () => {
  const sent = [];
  const created = await submitP110Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(true)) }));
  assert.equal(created.kind, "submitted");
  assert.equal(created.created, true);
  assert.equal(sent[0], attempt.payload);
  const again = await submitP110Attempt(attempt, deps({ post: async (p) => (sent.push(p), okSubmission(false)) }));
  assert.equal(again.alreadySubmitted, true);
  assert.equal(sent[1], sent[0]); // the retry sends the very same immutable payload (same capture_id)
});

test("submit: 401 / 403 / 404 / 409 / 422 map to the agreed outcomes and never reconcile", async () => {
  const reject = (status, code) => submitP110Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "x", status, code }) }));
  assert.deepEqual(await reject(401), { kind: "session" });
  assert.equal((await reject(403)).reason, "forbidden");
  assert.equal((await reject(404)).reason, "not_found");
  assert.equal((await reject(422, "CAPTURE_VALIDATION")).reason, "invalid");
  assert.equal((await reject(422, "UNSUPPORTED_FORM")).reason, "invalid");
  assert.equal((await reject(409, "CAPTURE_IDEMPOTENCY_CONFLICT")).reason, "idempotency");
  assert.equal((await reject(409, "ASSIGNMENT_STALE")).reason, "stale");
  assert.equal((await reject(409, "ASSIGNMENT_NOT_ACTIVE")).reason, "not_active");
  assert.equal((await reject(409, "FORM_NOT_AVAILABLE")).reason, "conflict");
});

test("reconciliation after a timeout: GET by the SAME capture id decides saved / not saved / uncertain", async () => {
  const timeout = async () => ({ ok: false, kind: "unavailable", status: 0 });
  const asked = [];
  const saved = await submitP110Attempt(attempt, deps({ post: timeout, get: async (id) => (asked.push(id), { ok: true, status: 200, data: parseP110Capture(p110()) }) }));
  assert.deepEqual(asked, [ID]);
  assert.equal(saved.kind, "submitted");
  assert.equal(saved.reconciled, true);
  assert.equal((await submitP110Attempt(attempt, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 404 }) }))).kind, "not_saved");
  assert.equal((await submitP110Attempt(attempt, deps({ post: async () => ({ ok: false, kind: "s", status: 503 }), get: async () => ({ ok: false, kind: "n", status: 500 }) }))).kind, "uncertain");
  assert.deepEqual(await reconcileP110(ID, deps({ post: timeout, get: async () => ({ ok: false, kind: "n", status: 401 }) })), { kind: "session" });
  const other = parseP110Capture(p110("33333333-3333-4333-8333-333333333333"));
  assert.equal((await reconcileP110(ID, deps({ post: timeout, get: async () => ({ ok: true, status: 200, data: other }) }))).kind, "uncertain"); // a different id is never accepted
});

// ---- cliente HTTP genérico: sin duplicar la implementación y sin cruzar parsers ----------------------------------------------------------------

function fakeFetch(handler) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), method: init.method ?? "GET", body: init.body, credentials: init.credentials, cache: init.cache }); return handler(String(url), init); };
  return { calls, restore: () => { globalThis.fetch = original; } };
}
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("HTTP: P1-10 list sends form_code and uses the P1-10 parser; F6 list keeps its historic URL and parser", async () => {
  const stub = fakeFetch((url) => (url.includes("form_code") ? json(200, [p110()]) : json(200, [f6()])));
  try {
    const listed = await api.listP110(undefined, 10);
    assert.equal(listed.ok, true);
    assert.equal(listed.data[0].form.code, P1_10_CODE);
    const historic = await f6api.listCaptures();
    assert.equal(historic.ok, true);
    assert.equal(historic.data[0].form.code, "VINTO-P1-06");
  } finally { stub.restore(); }
  assert.deepEqual(stub.calls.map((c) => c.url), ["http://127.0.0.1:8190/api/captures?limit=10&form_code=VINTO-P1-10", "http://127.0.0.1:8190/api/captures?limit=50"]);
  assert.ok(stub.calls.every((c) => c.credentials === "include" && c.cache === "no-store" && c.method === "GET"));
});

test("HTTP: a response of the OTHER form is rejected by each client (never mistaken)", async () => {
  const wrong = fakeFetch(() => json(200, [f6()]));
  try { assert.equal((await api.listP110()).ok, false); } finally { wrong.restore(); }
  const wrong2 = fakeFetch(() => json(200, [p110()]));
  try { assert.equal((await f6api.listCaptures()).ok, false); } finally { wrong2.restore(); }
  const single = fakeFetch(() => json(200, f6()));
  try { assert.equal((await api.getP110(ID)).ok, false); } finally { single.restore(); }
  const single2 = fakeFetch(() => json(200, p110()));
  try { assert.equal((await f6api.getCapture(ID)).ok, false); } finally { single2.restore(); }
  const post = fakeFetch(() => json(201, { created: true, already_submitted: false, capture: f6() }));
  try { assert.equal((await api.submitP110(attempt.payload)).ok, false); } finally { post.restore(); }
});

test("HTTP: P1-10 POST and GET use the shared central routes with the cookie session only", async () => {
  const stub = fakeFetch((url, init) => (init.method === "POST" ? json(201, { created: true, already_submitted: false, capture: p110() }) : json(200, p110())));
  try {
    const created = await api.submitP110(attempt.payload);
    assert.equal(created.ok, true);
    assert.equal(created.status, 201);
    assert.equal((await api.getP110(ID)).ok, true);
  } finally { stub.restore(); }
  assert.equal(stub.calls[0].url, "http://127.0.0.1:8190/api/captures");
  assert.equal(stub.calls[0].method, "POST");
  assert.deepEqual(JSON.parse(stub.calls[0].body), attempt.payload);
  assert.equal(stub.calls[1].url, `http://127.0.0.1:8190/api/captures/${ID}`);
  assert.ok(stub.calls.every((c) => c.credentials === "include"));
});

test("HTTP: F6 public API is unchanged (same names, POST shape and F6-only list)", () => {
  assert.deepEqual(Object.keys(f6api).sort(), ["getCapture", "getCaptureOf", "listCaptures", "listCapturesOf", "postCaptureOf", "submitCapture"]);
  assert.equal(f6api.listCaptures.length, 1); // (signal, limit = 50): no form-code parameter on the F6 list any more
});

// ---- componente ------------------------------------------------------------------------------------------------------------------------------

const CONTEXT = { assignmentId: ASSIGNMENT, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1024", productName: "BOBINA 1024",
  machine: "COPASA", shift: "Día (ficticio)", date: "2026-10-06" };
const html = (props) => server.renderToStaticMarkup(React.createElement(component.P110CaptureForm, { context: CONTEXT, online: true, attempt: null, setAttempt() {}, back() {}, onAssignmentChanged() {}, onSessionLost() {}, ...props }));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const disabledCount = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length;

test("component: manual fields, server context, pending contextual fields and the non-homologated notice", () => {
  const markup = html({ user: { display_name: "Operación DEV" } }), plain = text(markup);
  for (const piece of ["Registro de fardos", "Código / número de producto *", "Número de fardo *", "Peso fardo *", "Observaciones", "OT-2026-0001", "COPASA", "Día (ficticio) · 2026-10-06",
    "Ficha NO homologada · solo entorno de prueba", "Fecha · automático", "Máquina · automático", "Responsable", "Firma", "— pendiente de definición —",
    "Por confirmar: no se asume que el responsable sea el operador que captura.", "no existe firma digital en el sistema y no se simula una", "Sin correlativo, formato ni unicidad confirmados.",
    "Tipo declarado: texto", "Enviar registro trazable"]) assert.ok(plain.includes(piece), piece);
  assert.equal(disabledCount(markup, "input") + disabledCount(markup, "textarea"), 0);
  assert.equal((markup.match(/<input/g) ?? []).length, 3);
  assert.equal((markup.match(/<textarea/g) ?? []).length, 1);
  // the authenticated user is shown as information only, never as responsible/signature
  assert.ok(plain.includes("Operación DEV") && plain.includes("no es el responsable aprobado ni una firma"));
  assert.equal(/Responsable\s*Operación DEV|Firma\s*Operación DEV/.test(plain), false);
});

test("component: contextual fields are not editable inputs and the form has no way to send them", () => {
  const markup = html({});
  const contextual = markup.slice(markup.indexOf('data-section="contextual"'), markup.indexOf("Campos manuales"));
  assert.equal(/<(input|select|textarea)/.test(contextual), false);
  assert.equal(markup.includes('data-section="session"'), false); // no session line without a user
});

test("component: a pending attempt locks every field, keeps the typed draft and offers the retry", () => {
  const made = createP110Attempt(draft({ peso_fardo: "12,5 kg" }), ASSIGNMENT, DEVICE, () => ID).attempt;
  const markup = html({ attempt: made }), plain = text(markup);
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío."));
  assert.equal(disabledCount(markup, "input"), 3);
  assert.equal(disabledCount(markup, "textarea"), 1);
  assert.equal(disabledCount(markup, "button"), 0); // the retry button stays enabled
  assert.match(markup, /value="12,5 kg"/);
});

test("component and clients never touch business storage or credentials; P1-10 is wired only behind the backend-verified Rebobinado navigation (M4-A)", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (const file of ["components/vinto/p1-10-capture.tsx", "lib/vinto/p1-10.ts", "lib/vinto/p1-10-api.ts", "lib/vinto/captures-api.ts", "lib/vinto/capture-core.ts"]) {
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie|Authorization/.test(code(file)), false, file);
  }
  assert.equal(/form-definitions/.test(code("components/vinto/p1-10-capture.tsx")) || /form-definitions/.test(code("lib/vinto/p1-10.ts")), false); // the capture does not bundle the 8,900-line definitions
  const page = readFileSync(join(root, "app/page.tsx"), "utf8");
  assert.match(page, /P110CaptureForm/); // M4-A: reachable only from the Rebobinado front, whose visibility the backend decides
  assert.match(readFileSync(join(root, "components/vinto/rebobinado-central.tsx"), "utf8"), /useAvailability/);
  for (const dir of ["app/p1-10", "app/preview", "app/qa-harness", "app/__qa", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir);
  assert.ok(Object.keys(CONTEXT_NOTES).join() === "fecha,maquina,responsable,firma");
});

test("F6 draft and values are not affected by the P1-10 additions", () => {
  assert.deepEqual(Object.keys(EMPTY_DRAFT), ["cantidad_fardos", "punto_merma", "tipo_producto", "peso_kg", "observaciones"]);
});
