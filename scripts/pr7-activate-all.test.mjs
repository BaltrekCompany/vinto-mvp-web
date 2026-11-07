// node --test scripts/pr7-activate-all.test.mjs
// MF-13-03B PR7: interfaz de Supervisión para la activación masiva. Prueba (1) el parser contra respuestas REALES de la API de PR4 (scripts/fixtures/activate-all/*.json, volcadas del backend) y contra
// variantes malformadas, (2) los cuerpos exactos y el cliente HTTP con `fetch` simulado, (3) la máquina de estados del diálogo, (4) el render real del panel y del botón en cada estado y (5) el cableado.
// No hay navegador ni DOM: lo que aquí se prueba es lógica y render de servidor, NO un E2E; la validación manual queda registrada en docs/MF-13-03B-PR7-ui-activacion-masiva.md.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { PLAN_HASH, confirmPayload, parseActivateAll, parseConfirmation, parsePreview, previewPayload, statusMatchesOutcome } from "../lib/vinto/activate-all.ts";
import {
  CLOSED, PROBLEM_MESSAGES, canConfirmPlan, canRetryPreview, classifyFailure, conflictMessage, flowReducer, groupLines, isActionable, previewHeadline, resultMessage, startPreviewing,
} from "../lib/vinto/activate-all-flow.ts";
import { createMutationGuard, runGuarded } from "../lib/vinto/mutation-guard.ts";
import { NO_CAPABILITIES, massActivationOffered, parseCapabilitiesResponse } from "../lib/vinto/work-order-capabilities.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-pr7-test-${process.pid}`);
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

let api, dialog, programming, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [api, dialog, programming] = await Promise.all([bundle("lib/vinto/work-orders-api.ts", "api"), bundle("components/vinto/activate-all-dialog.tsx", "dialog"), bundle("components/vinto/bobinas-programming.tsx", "programming")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/activate-all/${name}.json`, import.meta.url), "utf8"));
const PREVIEW = fixture("preview"), APPLIED = fixture("applied"), IN_EFFECT = fixture("already_in_effect"), ALL_ACTIVE = fixture("preview_all_active");
const CONFLICT = fixture("preview_conflict"), BLOCKED_ERROR = fixture("error_blocked");
const clone = (value) => structuredClone(value);
const ORDER_ID = PREVIEW.work_order.id;
const read = (file) => readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
const noComments = (text) => text.replace(/\/\/.*$/gm, "");
const render = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));

// ---- 1. parser: contrato real de PR4 --------------------------------------------------------------------------------------------------------------------------------

test("real PR4 responses parse: preview, applied (201), already_in_effect (200), all-active preview and a preview with a conflict", () => {
  const preview = parseActivateAll(PREVIEW);
  assert.ok(preview);
  assert.deepEqual([preview.dry_run, preview.outcome, preview.can_confirm], [true, "preview", true]);
  assert.deepEqual(preview.lines.map((l) => [l.line_code, l.machine.code, l.action]), [["L1", "MP1", "activate"], ["L2", "MP1", "activate"], ["L3", "MP3", "activate"]]);
  assert.match(preview.plan_hash, PLAN_HASH);
  assert.equal(parseActivateAll(APPLIED.body).outcome, "applied");
  assert.equal(parseActivateAll(APPLIED.body).activated.length, 3);
  assert.equal(APPLIED.http_status, 201);
  assert.equal(parseActivateAll(IN_EFFECT.body).outcome, "already_in_effect");
  assert.equal(IN_EFFECT.http_status, 200);
  assert.equal(parseActivateAll(ALL_ACTIVE).summary.already_active, 3);
  const conflict = parseActivateAll(CONFLICT);
  assert.deepEqual([conflict.can_confirm, conflict.summary.conflicts, conflict.summary.blocked], [false, 1, 2]);
  assert.deepEqual(conflict.lines.map((l) => [l.line_code, l.action, l.reason]), [["L1", "blocked", "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"], ["L2", "blocked", "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"], ["L3", "activate", null]]);
});

test("a response is rejected if ANY required top-level key is missing or has the wrong type", () => {
  for (const key of Object.keys(PREVIEW)) {
    const missing = clone(PREVIEW); delete missing[key];
    assert.equal(parseActivateAll(missing), null, `missing ${key}`);
  }
  const wrong = { dry_run: "true", outcome: 1, work_order: [], status: null, plan_hash: 5, can_confirm: "yes", summary: [], lines: {}, expired: "x", conflicts: 3 };
  for (const [key, value] of Object.entries(wrong)) assert.equal(parseActivateAll({ ...clone(PREVIEW), [key]: value }), null, `bad ${key}`);
  assert.equal(parseActivateAll(null), null);
  assert.equal(parseActivateAll([]), null);
  assert.equal(parseActivateAll("preview"), null);
});

test("plan_hash must be exactly 64 lowercase hex characters", () => {
  for (const hash of ["", "a".repeat(63), "a".repeat(65), "A".repeat(64), "g".repeat(64), ` ${"a".repeat(63)}`, null]) assert.equal(parseActivateAll({ ...clone(PREVIEW), plan_hash: hash }), null, String(hash));
  assert.ok(parseActivateAll({ ...clone(PREVIEW), plan_hash: "a".repeat(64) }));
});

test("nested structures and allowed states are validated", () => {
  const mutate = (fn) => { const copy = clone(PREVIEW); fn(copy); return parseActivateAll(copy); };
  assert.equal(mutate((r) => { r.outcome = "done"; }), null, "unknown outcome");
  assert.equal(mutate((r) => { r.status = "weird"; }), null, "unknown order status");
  assert.equal(mutate((r) => { r.lines[0].action = "replace"; }), null, "unknown action");
  assert.equal(mutate((r) => { delete r.lines[0].machine; }), null);
  assert.equal(mutate((r) => { r.lines[0].machine = { code: "MP1" }; }), null);
  assert.equal(mutate((r) => { r.lines[0].article = "A"; }), null);
  assert.equal(mutate((r) => { r.lines[0].shift = { code: "DIA" }; }), null);
  assert.equal(mutate((r) => { r.lines[0].operating_date = "06/10/2026"; }), null);
  assert.equal(mutate((r) => { r.lines[0].reason = "MACHINE_INACTIVE"; }), null, "a reason on a non-blocked line");
  assert.equal(mutate((r) => { r.lines[0].assignment_id = "x"; }), null, "an assignment on a line that is not already active");
  assert.equal(mutate((r) => { r.lines = []; }), null, "an order without lines is not a plan");
  assert.equal(mutate((r) => { r.lines.push(null); }), null);
  assert.equal(mutate((r) => { r.summary.activate = -1; }), null);
  assert.equal(mutate((r) => { r.summary.activate = 1.5; }), null);
  assert.equal(mutate((r) => { r.expired = [{ assignment_id: "x", machine: { code: "MP1", name: "MP1" } }]; r.summary.expired_to_finish = 1; }), null, "expired item without line_code");
  assert.equal(mutate((r) => { r.conflicts = [{ assignment_id: "x", machine: { code: "MP1", name: "MP1" }, work_order: { id: "y" }, line_code: "L1", expired: false }]; r.summary.conflicts = 1; r.can_confirm = false; }), null, "conflict without OT number");
  assert.equal(mutate((r) => { r.conflicts = [{ assignment_id: "x", machine: { code: "MP1", name: "MP1" }, work_order: { id: "y", number: "OT" }, line_code: "L1", expired: "no" }]; r.summary.conflicts = 1; r.can_confirm = false; }), null, "expired must be boolean or null");
});

test("the response must be internally consistent: summary = lists, can_confirm = no blocks and no conflicts, outcome-specific lists", () => {
  const mutate = (base, fn) => { const copy = clone(base); fn(copy); return parseActivateAll(copy); };
  assert.equal(mutate(PREVIEW, (r) => { r.summary.activate = 2; }), null, "summary does not match the lines");
  assert.equal(mutate(PREVIEW, (r) => { r.summary.conflicts = 1; }), null);
  assert.equal(mutate(PREVIEW, (r) => { r.summary.expired_to_finish = 1; }), null);
  assert.equal(mutate(CONFLICT, (r) => { r.can_confirm = true; }), null, "can_confirm=true with conflicts must never be accepted");
  assert.equal(mutate(PREVIEW, (r) => { r.can_confirm = false; }), null, "can_confirm=false with nothing blocking is contradictory");
  assert.equal(mutate(PREVIEW, (r) => { r.dry_run = false; }), null, "dry_run and outcome must agree");
  assert.equal(mutate(APPLIED.body, (r) => { r.dry_run = true; }), null);
  assert.equal(mutate(PREVIEW, (r) => { r.activated = clone(APPLIED.body.activated); }), null, "a preview cannot carry activated assignments");
  assert.equal(mutate(APPLIED.body, (r) => { r.activated.pop(); }), null, "applied must report as many activations as the plan said");
  assert.equal(mutate(APPLIED.body, (r) => { r.finished = clone(APPLIED.body.activated); }), null);
  assert.equal(mutate(IN_EFFECT.body, (r) => { r.activated = clone(APPLIED.body.activated); }), null, "already_in_effect activates nothing");
  assert.equal(mutate(IN_EFFECT.body, (r) => { r.already_active.pop(); }), null);
  assert.equal(mutate(APPLIED.body, (r) => { delete r.activated[0].line; }), null, "a malformed nested assignment invalidates the confirmation");
  assert.equal(mutate(APPLIED.body, (r) => { r.activated[0].status = "pending"; }), null);
  assert.ok(mutate(APPLIED.body, (r) => { r.extra = "ignored"; }), "unknown extra keys never matter");
});

test("each phase accepts only its own kind of response, and a confirmation must echo the hash that was sent", () => {
  assert.ok(parsePreview(PREVIEW));
  assert.equal(parsePreview(APPLIED.body), null);
  assert.equal(parsePreview(IN_EFFECT.body), null);
  const confirm = parseConfirmation(APPLIED.body.plan_hash);
  assert.ok(confirm(APPLIED.body));
  assert.equal(confirm(PREVIEW), null, "a preview is not a confirmation");
  assert.equal(parseConfirmation("b".repeat(64))(APPLIED.body), null, "another hash");
  assert.equal(statusMatchesOutcome(201, "applied"), true);
  assert.equal(statusMatchesOutcome(200, "already_in_effect"), true);
  assert.equal(statusMatchesOutcome(200, "applied"), false);
  assert.equal(statusMatchesOutcome(201, "already_in_effect"), false);
});

// ---- 2. cuerpos exactos y cliente HTTP -----------------------------------------------------------------------------------------------------------------------------------

test("the request bodies are exactly the contract: preview {dry_run:true}; confirmation {dry_run:false, plan_hash} with the server's hash untouched", () => {
  assert.equal(JSON.stringify(previewPayload()), '{"dry_run":true}');
  const hash = PREVIEW.plan_hash;
  assert.equal(JSON.stringify(confirmPayload(hash)), `{"dry_run":false,"plan_hash":"${hash}"}`);
  assert.equal(confirmPayload(hash).plan_hash, hash, "same string, not recomputed");
  for (const bad of ["", "a".repeat(63), "a".repeat(65), "A".repeat(64), null, undefined, 5, {}]) assert.equal(confirmPayload(bad), null, String(bad));
  assert.deepEqual(Object.keys(confirmPayload(hash)).sort(), ["dry_run", "plan_hash"], "no machine, shift, date or operational ids");
});

const json = (status, payload) => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
const withFetch = async (responder, body) => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init, body: init?.body === undefined ? undefined : init.body }); return responder(calls.length); };
  try { return { result: await body(), calls }; } finally { globalThis.fetch = original; }
};
const PATH = new RegExp(`/api/work-orders/${ORDER_ID}/activate-all$`);

test("preview is ONE POST with the exact body and parses the real response", async () => {
  const { result, calls } = await withFetch(() => json(200, PREVIEW), () => api.previewActivateAll(ORDER_ID));
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, PATH);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].body, '{"dry_run":true}');
  assert.equal(calls[0].init.credentials, "include");
  assert.ok(result.ok);
  assert.equal(result.data.plan_hash, PREVIEW.plan_hash);
});

test("confirmation is ONE POST with the server's hash; 201 applied and 200 already_in_effect are both accepted", async () => {
  const applied = await withFetch(() => json(201, APPLIED.body), () => api.confirmActivateAll(ORDER_ID, APPLIED.body.plan_hash));
  assert.equal(applied.calls.length, 1, "one request for three lines on two machines, never one per line");
  assert.equal(applied.calls[0].body, `{"dry_run":false,"plan_hash":"${APPLIED.body.plan_hash}"}`);
  assert.ok(applied.result.ok && applied.result.data.outcome === "applied" && applied.result.status === 201);
  const again = await withFetch(() => json(200, IN_EFFECT.body), () => api.confirmActivateAll(ORDER_ID, IN_EFFECT.body.plan_hash));
  assert.ok(again.result.ok && again.result.data.outcome === "already_in_effect" && again.calls.length === 1);
});

test("a contradictory or foreign success body is NOT a valid confirmation (treated as unavailable, never retried)", async () => {
  const hash = APPLIED.body.plan_hash;
  for (const [status, body] of [[200, APPLIED.body], [201, IN_EFFECT.body], [200, PREVIEW], [201, { ...clone(APPLIED.body), plan_hash: "b".repeat(64) }], [201, { ...clone(APPLIED.body), activated: [] }], [201, {}]]) {
    const { result, calls } = await withFetch(() => json(status, body), () => api.confirmActivateAll(ORDER_ID, hash));
    assert.equal(result.ok, false, `${status}`);
    assert.equal(result.kind, "unavailable");
    assert.equal(calls.length, 1, "no automatic second POST");
  }
});

test("a malformed hash never leaves the browser", async () => {
  const { result, calls } = await withFetch(() => json(201, APPLIED.body), () => api.confirmActivateAll(ORDER_ID, "not-a-hash"));
  assert.equal(calls.length, 0);
  assert.deepEqual([result.ok, result.kind], [false, "invalid"]);
});

test("backend errors keep their stable code and each one costs exactly one request", async () => {
  const hash = PREVIEW.plan_hash;
  const cases = [[401, {}, "session", undefined], [403, { code: "FORBIDDEN" }, "forbidden", "FORBIDDEN"], [404, { code: "WORK_ORDER_NOT_FOUND" }, "not_found", "WORK_ORDER_NOT_FOUND"],
    [409, { code: "ACTIVATION_PLAN_CHANGED" }, "conflict", "ACTIVATION_PLAN_CHANGED"], [409, BLOCKED_ERROR.body, "conflict", "ACTIVATION_BLOCKED"],
    [422, { code: "MULTI_MACHINE_DISABLED" }, "invalid", "MULTI_MACHINE_DISABLED"], [500, {}, "unavailable", undefined], [503, {}, "unavailable", undefined]];
  for (const [status, payload, kind, code] of cases) {
    const { result, calls } = await withFetch(() => json(status, payload), () => api.confirmActivateAll(ORDER_ID, hash));
    assert.equal(result.ok, false, String(status));
    assert.equal(result.kind, kind, String(status));
    assert.equal(result.code, code, String(status));
    assert.equal(calls.length, 1, `status ${status}`);
  }
  assert.equal(BLOCKED_ERROR.http_status, 409);
});

test("a lost response (network error, invalid JSON) is a failure, never a retry; the next request is an explicit read-only preview", async () => {
  const hash = PREVIEW.plan_hash;
  const network = await withFetch(() => { throw new TypeError("network down"); }, () => api.confirmActivateAll(ORDER_ID, hash));
  assert.deepEqual([network.result.ok, network.result.kind, network.calls.length], [false, "unavailable", 1]);
  const notJson = await withFetch(() => new Response("<html>gateway timeout</html>", { status: 200 }), () => api.confirmActivateAll(ORDER_ID, hash));
  assert.deepEqual([notJson.result.ok, notJson.result.kind, notJson.calls.length], [false, "unavailable", 1]);
  const preview = await withFetch(() => json(200, ALL_ACTIVE), () => api.previewActivateAll(ORDER_ID));
  assert.equal(preview.calls[0].body, '{"dry_run":true}', "recovery is read-only");
  assert.ok(preview.result.ok);
  const lost = flowReducer(flowReducer(flowReducer(startPreviewing(ORDER_ID), { type: "preview_ok", orderId: ORDER_ID, plan: parseActivateAll(PREVIEW) }), { type: "confirm_start", orderId: ORDER_ID }), { type: "confirm_failed", orderId: ORDER_ID, failure: { kind: network.result.kind } });
  assert.deepEqual(lost, { phase: "problem", orderId: ORDER_ID, problem: "uncertain" });
  const recovered = flowReducer(flowReducer(lost, { type: "preview_start", orderId: ORDER_ID }), { type: "preview_ok", orderId: ORDER_ID, plan: parseActivateAll(ALL_ACTIVE) });
  assert.equal(recovered.phase, "preview");
  assert.equal(canConfirmPlan(recovered.plan), false, "if the server did apply it, the new preview shows everything active and offers nothing to confirm (no duplicate activation)");
});

// ---- 3. máquina de estados -----------------------------------------------------------------------------------------------------------------------------------------

const plan = () => parseActivateAll(PREVIEW);
const previewed = () => flowReducer(startPreviewing(ORDER_ID), { type: "preview_ok", orderId: ORDER_ID, plan: plan() });

test("the happy path: preview -> confirm with the SAME hash -> done only after the server's success", () => {
  const state = previewed();
  assert.equal(state.phase, "preview");
  const confirming = flowReducer(state, { type: "confirm_start", orderId: ORDER_ID });
  assert.equal(confirming.phase, "confirming");
  assert.equal(confirming.plan.plan_hash, PREVIEW.plan_hash, "the hash in state is the server's, untouched");
  assert.equal(confirming.plan, state.plan);
  assert.notEqual(flowReducer(confirming, { type: "confirm_start", orderId: ORDER_ID }).phase, "done");
  const done = flowReducer(confirming, { type: "confirm_ok", orderId: ORDER_ID, result: parseActivateAll(APPLIED.body) });
  assert.equal(done.phase, "done");
  assert.equal(flowReducer(done, { type: "close" }).phase, "closed");
});

test("there is no confirmation without a current, confirmable preview", () => {
  for (const state of [CLOSED, startPreviewing(ORDER_ID), { phase: "problem", orderId: ORDER_ID, problem: "plan_changed" }, { phase: "done", orderId: ORDER_ID, result: parseActivateAll(APPLIED.body) }]) {
    assert.equal(flowReducer(state, { type: "confirm_start", orderId: ORDER_ID }), state, state.phase);
  }
  const conflict = flowReducer(startPreviewing(ORDER_ID), { type: "preview_ok", orderId: ORDER_ID, plan: parseActivateAll(CONFLICT) });
  assert.equal(flowReducer(conflict, { type: "confirm_start", orderId: ORDER_ID }), conflict, "can_confirm=false");
  const nothing = flowReducer(startPreviewing(ORDER_ID), { type: "preview_ok", orderId: ORDER_ID, plan: parseActivateAll(ALL_ACTIVE) });
  assert.equal(flowReducer(nothing, { type: "confirm_start", orderId: ORDER_ID }), nothing, "everything already active: nothing to confirm");
  assert.equal(flowReducer(previewed(), { type: "confirm_start", orderId: "other-order" }).phase, "preview", "another order's confirmation");
});

test("answers for another order, or out of phase, are ignored (late responses)", () => {
  assert.equal(flowReducer(startPreviewing(ORDER_ID), { type: "preview_ok", orderId: "other", plan: plan() }).phase, "previewing");
  assert.equal(flowReducer(startPreviewing(ORDER_ID), { type: "preview_failed", orderId: "other", failure: { kind: "conflict" } }).phase, "previewing");
  assert.equal(flowReducer(CLOSED, { type: "preview_ok", orderId: ORDER_ID, plan: plan() }), CLOSED, "after closing, a late preview cannot reopen anything");
  const confirming = flowReducer(previewed(), { type: "confirm_start", orderId: ORDER_ID });
  assert.equal(flowReducer(confirming, { type: "confirm_ok", orderId: "other", result: parseActivateAll(APPLIED.body) }), confirming);
  assert.equal(flowReducer(previewed(), { type: "confirm_ok", orderId: ORDER_ID, result: parseActivateAll(APPLIED.body) }).phase, "preview", "a confirmation answer without a confirmation in flight");
  const foreignPlan = { ...plan(), work_order: { id: "x", number: "OT-X" } };
  assert.equal(flowReducer(startPreviewing(ORDER_ID), { type: "preview_ok", orderId: ORDER_ID, plan: foreignPlan }).problem, "unavailable", "a preview of another OT is rejected");
  const mismatch = { ...parseActivateAll(APPLIED.body), plan_hash: "c".repeat(64) };
  assert.equal(flowReducer(confirming, { type: "confirm_ok", orderId: ORDER_ID, result: mismatch }).problem, "uncertain", "an answer that does not echo the confirmed hash is not trusted");
});

test("closing and refreshing are impossible while a confirmation is in flight", () => {
  const confirming = flowReducer(previewed(), { type: "confirm_start", orderId: ORDER_ID });
  assert.equal(flowReducer(confirming, { type: "close" }), confirming);
  assert.equal(flowReducer(confirming, { type: "preview_start", orderId: ORDER_ID }), confirming);
});

test("failure classification: every status maps to the documented behaviour", () => {
  const c = classifyFailure;
  assert.equal(c("preview", { kind: "session" }), "session");
  assert.equal(c("confirm", { kind: "session" }), "session");
  assert.equal(c("confirm", { kind: "conflict", code: "ACTIVATION_PLAN_CHANGED" }), "plan_changed");
  assert.equal(c("confirm", { kind: "conflict", code: "ACTIVATION_BLOCKED" }), "blocked");
  assert.equal(c("confirm", { kind: "conflict" }), "plan_changed", "an unknown 409 forces a new preview");
  assert.equal(c("preview", { kind: "conflict", code: "WORK_ORDER_NOT_ACTIVATABLE" }), "plan_changed");
  assert.equal(c("confirm", { kind: "forbidden" }), "not_available");
  assert.equal(c("confirm", { kind: "not_found" }), "not_available");
  assert.equal(c("preview", { kind: "forbidden" }), "not_available");
  assert.equal(c("confirm", { kind: "invalid", code: "MULTI_MACHINE_DISABLED" }), "disabled");
  assert.equal(c("preview", { kind: "invalid", code: "MULTI_MACHINE_DISABLED" }), "disabled");
  assert.equal(c("confirm", { kind: "invalid" }), "invalid");
  assert.equal(c("confirm", { kind: "unavailable" }), "uncertain", "after confirming, no answer = the server may have applied it");
  assert.equal(c("preview", { kind: "unavailable" }), "unavailable");
});

test("after a failed confirmation the old plan and hash are gone and cannot be reused or resent", () => {
  const confirming = flowReducer(previewed(), { type: "confirm_start", orderId: ORDER_ID });
  for (const failure of [{ kind: "conflict", code: "ACTIVATION_PLAN_CHANGED" }, { kind: "conflict", code: "ACTIVATION_BLOCKED" }, { kind: "unavailable" }, { kind: "forbidden" }, { kind: "invalid", code: "MULTI_MACHINE_DISABLED" }]) {
    const next = flowReducer(confirming, { type: "confirm_failed", orderId: ORDER_ID, failure });
    assert.equal(next.phase, "problem");
    assert.ok(!("plan" in next), "no plan, hence no hash");
    assert.equal(flowReducer(next, { type: "confirm_start", orderId: ORDER_ID }), next, "cannot confirm again without a new preview");
  }
  assert.equal(flowReducer(confirming, { type: "confirm_failed", orderId: ORDER_ID, failure: { kind: "session" } }), CLOSED, "a lost session closes everything");
});

test("messages: the documented texts, the conflict wording, only real results as results", () => {
  assert.equal(PROBLEM_MESSAGES.plan_changed, "La programación o el turno cambió; vuelve a consultar la vista previa.");
  const conflict = parseActivateAll(CONFLICT).conflicts[0];
  assert.equal(conflictMessage(conflict), `La máquina MP1 tiene líneas activas de otra OT (${conflict.work_order.number}). Finaliza esas asignaciones desde Supervisión antes de continuar.`);
  assert.equal(resultMessage(parseActivateAll(APPLIED.body)), "Se activaron 3 línea(s); 0 ya estaban activas; se finalizaron 0 asignación(es) vencida(s).");
  assert.match(resultMessage(parseActivateAll(IN_EFFECT.body)), /^El plan ya estaba aplicado: las 3 línea\(s\) ya están activas.*No se realizó ninguna activación nueva\.$/);
  for (const message of Object.values(PROBLEM_MESSAGES)) assert.ok(!/realizada|se activaron/i.test(message), "no success wording in a problem");
  assert.equal(canRetryPreview("disabled"), false);
  assert.equal(canRetryPreview("not_available"), false);
  for (const problem of ["plan_changed", "blocked", "uncertain", "unavailable", "invalid"]) assert.equal(canRetryPreview(problem), true, problem);
  assert.ok(previewHeadline(plan()).startsWith(`${PREVIEW.work_order.number}: 3 línea(s) · 3 por activar`));
  assert.deepEqual(Object.values(groupLines(parseActivateAll(CONFLICT))).map((g) => g.length), [1, 0, 2]);
  assert.equal(isActionable(parseActivateAll(ALL_ACTIVE)), false);
});

// ---- 4. doble clic, sesión y respuestas tardías -------------------------------------------------------------------------------------------------------------------

const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };

test("a double click sends ONE confirmation request", async () => {
  const guard = createMutationGuard(), pending = deferred(), log = [];
  let sent = 0;
  const action = () => { sent += 1; return pending.promise; };
  const handlers = { onStart: () => log.push("start"), onOk: () => log.push("ok"), onSession: () => log.push("session"), onFailure: () => log.push("fail"), onSettled: () => log.push("settled") };
  const first = runGuarded(guard, action, handlers);
  assert.equal(await runGuarded(guard, action, handlers), "skipped");
  assert.equal(guard.busy(), true);
  pending.resolve({ ok: true, data: 1 });
  assert.equal(await first, "ok");
  assert.equal(sent, 1);
});

test("session end, user change or closing the dialog discards the plan; a late answer changes nothing", async () => {
  const guard = createMutationGuard(), pending = deferred(), log = [];
  const run = runGuarded(guard, () => pending.promise, { onStart: () => log.push("start"), onOk: () => log.push("ok"), onSession: () => log.push("session"), onFailure: () => log.push("fail"), onSettled: () => log.push("settled") });
  guard.reset(); // lo que hace el desmontaje del diálogo (cierre, otra OT o cambio de sesión)
  pending.resolve({ ok: true, data: 1 });
  assert.equal(await run, "stale");
  assert.deepEqual(log, ["start"]);
  const lateFailure = deferred(), log2 = [];
  const run2 = runGuarded(guard, () => lateFailure.promise, { onStart: () => log2.push("start"), onOk: () => log2.push("ok"), onSession: () => log2.push("session"), onFailure: () => log2.push("fail"), onSettled: () => log2.push("settled") });
  guard.reset();
  lateFailure.resolve({ ok: false, kind: "session" });
  assert.equal(await run2, "stale");
  assert.deepEqual(log2, ["start"], "not even a late 401 from the previous session reaches the screen");
});

test("a 401 goes to the existing lost-session handler and the failure carries the backend code", async () => {
  const seen = [];
  await runGuarded(createMutationGuard(), () => Promise.resolve({ ok: false, kind: "session", status: 401 }), { onStart: () => {}, onOk: () => seen.push("ok"), onSession: () => seen.push("session"), onFailure: () => seen.push("fail"), onSettled: () => seen.push("settled") });
  assert.deepEqual(seen, ["session", "settled"]);
  let received;
  await runGuarded(createMutationGuard(), () => Promise.resolve({ ok: false, kind: "invalid", status: 422, code: "MULTI_MACHINE_DISABLED" }), { onStart: () => {}, onOk: () => {}, onSession: () => {}, onFailure: (kind, failure) => { received = [kind, failure.code]; }, onSettled: () => {} });
  assert.deepEqual(received, ["invalid", "MULTI_MACHINE_DISABLED"]);
});

// ---- 5. render del panel ---------------------------------------------------------------------------------------------------------------------------------------------

const noop = () => {};
const panel = (state) => render(dialog.ActivateAllPanel, { state, onConfirm: noop, onRefresh: noop, onClose: noop });
const button = (text, label) => (text.match(new RegExp(`<button[^>]*>${label}</button>`)) ?? [""])[0];
const isDisabled = (tag) => /\sdisabled(=""|\s|>)/.test(tag);
const stateOf = (phase, response, extra = {}) => ({ phase, orderId: ORDER_ID, ...(phase === "done" ? { result: response } : { plan: response }), ...extra });

test("preview: OT, lines, machines, products, PV, shift and date are shown and Confirm is enabled with the real count", () => {
  const text = panel(stateOf("preview", parseActivateAll(PREVIEW)));
  assert.ok(text.includes(PREVIEW.work_order.number));
  for (const line of PREVIEW.lines) for (const expected of [line.line_code, line.machine.code, line.article.code, line.pv_reference, line.shift.name, line.operating_date]) assert.ok(text.includes(expected), expected);
  assert.ok(text.includes("data-section=\"activate\"") && !text.includes("data-section=\"blocked\"") && !text.includes("data-section=\"conflicts\""));
  assert.ok(text.includes("Esta vista previa es informativa: no modifica asignaciones"));
  const confirm = button(text, "Confirmar activación de 3 línea\\(s\\)");
  assert.ok(confirm && !isDisabled(confirm));
  assert.ok(button(text, "Actualizar vista previa") && button(text, "Cerrar"));
  assert.ok(!/Se activaron|Activación realizada|activación realizada/i.test(text), "no success before the server's success");
});

test("preview with a conflict: blocked lines with reasons, the exact conflict wording, Confirm disabled", () => {
  const response = parseActivateAll(CONFLICT);
  const text = panel(stateOf("preview", response));
  assert.ok(text.includes("data-section=\"conflicts\"") && text.includes("data-section=\"blocked\"") && text.includes("data-section=\"activate\""));
  assert.ok(text.includes(conflictMessage(response.conflicts[0])));
  assert.equal(text.split("Ocupada por otra OT").length - 1, 2);
  assert.ok(text.includes("la activación está bloqueada"));
  assert.ok(isDisabled(button(text, "Confirmar activación de 1 línea\\(s\\)")));
  assert.ok(button(text, "Actualizar vista previa"), "the user can refresh or close");
  assert.ok(!text.includes("reemplaz") && !text.includes("Sustituir") && !text.includes("replace_assignment_ids"), "no automatic replacement");
});

test("preview with already-active lines, expired assignments of the same OT and nothing to do", () => {
  const withExpired = clone(PREVIEW);
  withExpired.expired = [{ assignment_id: "11111111-1111-4111-8111-111111111111", machine: { code: "MP1", name: "MP1" }, line_code: "L1" }];
  withExpired.summary.expired_to_finish = 1;
  const expiredText = panel(stateOf("preview", parseActivateAll(withExpired)));
  assert.ok(expiredText.includes("data-section=\"expired\"") && expiredText.includes("Asignaciones vencidas de esta OT que se finalizarán (1)"));
  const mixed = clone(PREVIEW);
  mixed.lines[0] = { ...mixed.lines[0], action: "already_active", assignment_id: "22222222-2222-4222-8222-222222222222" };
  mixed.summary.activate = 2; mixed.summary.already_active = 1;
  const mixedText = panel(stateOf("preview", parseActivateAll(mixed)));
  assert.ok(mixedText.includes("data-section=\"already_active\"") && mixedText.includes("data-section=\"activate\""));
  assert.ok(!isDisabled(button(mixedText, "Confirmar activación de 2 línea\\(s\\)")));
  const none = panel(stateOf("preview", parseActivateAll(ALL_ACTIVE)));
  assert.ok(none.includes("data-nothing") && none.includes("no hay nada que confirmar"));
  assert.ok(isDisabled(button(none, "Confirmar activación de 0 línea\\(s\\)")));
});

test("states: previewing and confirming announce progress and block the buttons; done shows the real result", () => {
  const previewing = panel({ phase: "previewing", orderId: ORDER_ID });
  assert.ok(previewing.includes("Consultando la vista previa (solo lectura)") && previewing.includes('aria-live="polite"'));
  assert.ok(!previewing.includes("Confirmar activación"));
  const confirming = panel(stateOf("confirming", parseActivateAll(PREVIEW)));
  assert.ok(confirming.includes("Enviando la confirmación al servidor"));
  assert.ok(isDisabled(button(confirming, "Activando…")) && isDisabled(button(confirming, "Cerrar")));
  assert.ok(!/Se activaron|realizada/i.test(confirming));
  const applied = panel(stateOf("done", parseActivateAll(APPLIED.body)));
  assert.ok(applied.includes("Se activaron 3 línea(s); 0 ya estaban activas; se finalizaron 0 asignación(es) vencida(s).") && applied.includes("data-section=\"activated\""));
  assert.ok(!applied.includes("Confirmar activación"), "no second confirmation after success");
  const inEffect = panel(stateOf("done", parseActivateAll(IN_EFFECT.body)));
  assert.ok(inEffect.includes("El plan ya estaba aplicado") && !inEffect.includes("data-section=\"activated\""), "no fictitious second activation");
});

test("problems: the documented message, an alert role, and read-only recovery only when it makes sense", () => {
  for (const problem of Object.keys(PROBLEM_MESSAGES)) {
    const text = panel({ phase: "problem", orderId: ORDER_ID, problem });
    assert.ok(text.includes(PROBLEM_MESSAGES[problem]) && text.includes('role="alert"'), problem);
    assert.ok(!text.includes("Confirmar activación"), `${problem}: no confirm without a new preview`);
    const retry = text.includes("Consultar de nuevo la vista previa") || text.includes("Consultar la situación (solo lectura)");
    assert.equal(retry, canRetryPreview(problem), problem);
  }
  assert.ok(panel({ phase: "problem", orderId: ORDER_ID, problem: "uncertain" }).includes("Consultar la situación (solo lectura)"));
});

test("accessibility of the content: real buttons, labelled sections, captioned tables with scoped headers, no clickable non-controls", () => {
  const text = panel(stateOf("preview", parseActivateAll(CONFLICT)));
  assert.ok(/<button[^>]*type="button"/.test(text));
  assert.ok(/<section[^>]*aria-labelledby="aa-activate"/.test(text) && text.includes('id="aa-activate"'));
  assert.ok(/<caption class="sr-only">/.test(text) && /<th scope="col"/.test(text));
  assert.ok(/<h3/.test(text));
  assert.ok(text.indexOf(">Cerrar<") < text.indexOf("Confirmar activación"), "tab order: the harmless Cerrar first, so the initial focus never lands on the confirmation");
  const source = noComments(read("components/vinto/activate-all-dialog.tsx"));
  assert.ok(!/<(div|span|li|tr|td|p|section)\b[^>]*onClick/.test(source), "every interaction is a <button>");
  assert.match(source, /<Dialog open onOpenChange/, "Radix Dialog: focus trap, Escape, aria-modal and focus return");
  assert.match(source, /onEscapeKeyDown=\{event => \{ if \(state\.phase === "confirming"\) event\.preventDefault\(\); \}\}/, "Escape cannot abandon an in-flight confirmation");
  assert.match(source, /onInteractOutside=\{event => \{ if \(state\.phase === "confirming"\) event\.preventDefault\(\); \}\}/);
  assert.match(source, /DialogTitle/);
  assert.match(source, /DialogDescription/);
});

// ---- 6. botón y permisos en la programación ------------------------------------------------------------------------------------------------------------------------

const MP1 = { code: "MP1", name: "MP1" }, MP3 = { code: "MP3", name: "MP3" };
const line = (n, machine) => ({ id: `00000000-0000-4000-8000-00000000000${n}`, line_code: `L${n}`, pv_reference: `PV-${n}`, machine, article: { code: `ART-${n}`, description: `Producto ${n}` }, quantity: 10, unit: "KG", due_date: "2026-10-30" });
const order = (status) => ({ id: ORDER_ID, number: "OT-2026-0003", status, machine: MP1, baseline: { id: "33333333-3333-4333-8333-333333333333", version_number: 1, published_at: status === "draft" ? null : "2026-10-06T16:00:00Z", lines: [line(1, MP1), line(2, MP1), line(3, MP3)] } });
const ON = parseCapabilitiesResponse({ multi_machine: true });
const view = (status, o = {}) => render(programming.BobbinasProgramming, { machines: ["MP1", "MP3"], creation: { machines: [MP1, MP3], catalog: () => [] }, workOrders: { status: "ready", data: [order(status)], refreshing: false },
  onChanged: noop, onSessionLost: noop, canManageOrders: false, canManageAssignments: true, capabilities: ON, capabilityStatus: "ready", scope: "user:test", ...o });
const MASS = "Activar todas las líneas";

test("the mass button needs the server's true, assignment.manage and a published or in-progress order", () => {
  assert.ok(view("published").includes(MASS));
  assert.ok(view("in_progress").includes(MASS));
  assert.ok(!view("draft").includes(MASS), "a draft has no baseline to activate");
  assert.ok(!view("closed").includes(MASS));
  assert.ok(!view("published", { capabilities: NO_CAPABILITIES }).includes(MASS), "flag off / unconfirmed / error");
  assert.ok(!view("published", { capabilities: NO_CAPABILITIES, capabilityStatus: "error" }).includes(MASS));
  assert.ok(!view("published", { capabilities: NO_CAPABILITIES, capabilityStatus: "loading" }).includes(MASS));
  assert.equal(massActivationOffered(ON, true, "published"), true);
  assert.equal(massActivationOffered(ON, false, "published"), false);
  assert.equal(massActivationOffered(NO_CAPABILITIES, true, "published"), false);
  assert.equal(massActivationOffered(ON, true, "draft"), false);
});

test("roles: Supervisión (assignment.manage) sees it; Jefatura without it and Operación do not; creating or publishing stays work_order.manage only", () => {
  const supervisor = view("published");
  assert.ok(supervisor.includes(MASS));
  assert.ok(!supervisor.includes("data-order-draft") && !supervisor.includes("Publicar base") && !supervisor.includes("Añadir una línea"), "Supervisión cannot create, edit or publish the baseline");
  const jefatura = view("published", { canManageOrders: true, canManageAssignments: false });
  assert.ok(!jefatura.includes(MASS), "Jefatura without assignment.manage");
  assert.ok(jefatura.includes("data-order-draft"));
  const operator = view("published", { canManageOrders: false, canManageAssignments: false });
  assert.ok(!operator.includes(MASS) && !operator.includes("Activar<"));
  const both = view("draft", { canManageOrders: true, canManageAssignments: true });
  assert.ok(both.includes("Publicar base") && !both.includes(MASS));
});

test("the mass button lives next to the individual activation, which is untouched", () => {
  const text = view("published");
  assert.equal(text.split(">Activar<").length - 1, 3, "one individual button per line");
  assert.equal(text.split(MASS).length - 1, 1, "one mass button per order");
});

test("wiring: session-scoped dialog, hash only in memory, capability refresh after MULTI_MACHINE_DISABLED, no storage", () => {
  const prog = noComments(read("components/vinto/bobinas-programming.tsx"));
  assert.match(prog, /massOrder && massOrder\.scope === scope && <ActivateAllDialog key=\{`\$\{massOrder\.scope\}:\$\{massOrder\.id\}`\}/, "another session or order remounts and discards the plan");
  assert.match(prog, /onDisabled=\{\(\) => \{ setBlockedBy\(capabilities\); onCapabilitiesStale\?\.\(\); \}\}/);
  assert.match(prog, /blockedBy !== capabilities && massActivationOffered\(capabilities, canManageAssignments, order\.status\)/);
  assert.match(prog, /onApplied=\{\(\) => \{ setExecutionRevision\(n => n \+ 1\); onChanged\(\); \}\}/, "the lists and E1 logical execution projection are refreshed only after confirmed activation");
  const sources = ["components/vinto/activate-all-dialog.tsx", "lib/vinto/activate-all.ts", "lib/vinto/activate-all-flow.ts", "components/vinto/bobinas-programming.tsx", "components/vinto/bobinas-programming-source.tsx", "lib/vinto/work-orders-api.ts"].map((f) => noComments(read(f))).join("\n");
  assert.ok(!/localStorage|sessionStorage|indexedDB|document\.cookie|NEXT_PUBLIC|console\./.test(sources), "no storage, no logging, no public flag");
  assert.ok(!/replace_assignment_ids|crypto\.|createHash|sha256|digest\(/i.test(sources), "the browser never builds or recomputes a hash, and has no replacement option");
  const source = noComments(read("components/vinto/bobinas-programming-source.tsx"));
  assert.match(source, /useWorkOrderCapabilities\(rest\.canManageOrders \|\| rest\.canManageAssignments, rest\.onSessionLost, scope\)/);
  assert.match(source, /onCapabilitiesStale=\{capabilityResource\.refresh\}/);
});

test("Rebobinado and Conversión use the same backend-confirmed multi-machine and mass-activation gate as Bobinas", () => {
  const shell = noComments(read("components/vinto/sector-central.tsx"));
  assert.match(shell, /useWorkOrderCapabilities\(/, "sector programming reads the server capability");
  assert.match(shell, /capabilitiesOf\(multiMachineResource\.view\)/, "invalid responses remain OFF");
  assert.match(shell, /capabilities=\{multiMachine\.capabilities\}/, "shared programming receives only confirmed values");
  assert.match(shell, /capabilityStatus=\{multiMachine\.status\}/, "fail-closed on loading/error");
  assert.match(shell, /onCapabilitiesStale=\{multiMachineResource\.refresh\}/, "422 triggers refresh");
  assert.match(shell, /canManageOrders \|\| canManageAssignments/, "only permitted roles read capability");
  assert.match(shell, /module === "programacion"\) return <Programming/, "both sectors share the programming implementation");
  const page = noComments(read("app/page.tsx"));
  assert.match(page, /<BobbinasProgrammingSource scope=\{scope\}/, "Bobinas retains its existing source");
});
