// node --test scripts/pr8-line-selection.test.mjs
// MF-13-03B PR8: selección de línea activa en Operación. Prueba (1) el parser de /active-lines con asignaciones REALES de la API (fixtures de PR4), (2) la selección derivada (nunca automática, caduca con
// sesión/máquina/turno/finalización), (3) el cliente con `fetch` simulado (flujo histórico = UNA solicitud; /active-lines solo con MULTIPLE_ACTIVE_ASSIGNMENTS), (4) el render del selector y (5) el cableado.
// No hay navegador ni DOM: lógica y render de servidor, NO un E2E (ver docs/MF-13-03B-PR8-operacion-seleccion-linea.md).
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { contextFromSelection, isSelectable, parseActiveLines, selectionFromLines, selectionKey, unselectableReason, validSelection } from "../lib/vinto/active-lines.ts";
import { CONTEXT_MESSAGES, contextFromActive } from "../lib/vinto/orders.ts";
import { activeAssignmentKey, deriveView, operationSelectionKey } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-pr8-test-${process.pid}`);
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

let api, selector, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [api, selector] = await Promise.all([bundle("lib/vinto/assignments-api.ts", "api"), bundle("components/vinto/line-selector.tsx", "selector")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const APPLIED = JSON.parse(readFileSync(new URL("./fixtures/activate-all/applied.json", import.meta.url), "utf8")).body;
const [L1, L2, L3] = APPLIED.activated; // asignaciones REALES de la API: L1 y L2 en MP1, L3 en MP3
const clone = (value) => structuredClone(value);
const SHIFT = { code: "DIA", name: "Día", operating_date: L1.operating_date };
const LINES = (items = [{ assignment: L1, stale: false }, { assignment: L2, stale: false }]) => ({ current_shift: SHIFT, assignments: items });
const read = (file) => readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
const noComments = (text) => text.replace(/\/\/.*$/gm, "");
const render = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));
const json = (status, payload) => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
const withFetch = async (responder, body) => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push({ url: new URL(String(url), "http://x").pathname + new URL(String(url), "http://x").search, method: init?.method ?? "GET", body: init?.body }); return responder(calls.length, String(url)); };
  try { return { result: await body(), calls }; } finally { globalThis.fetch = original; }
};
const ACTIVE_OK = { assignment: L1, current_shift: SHIFT, stale: false };
const MULTIPLE = { code: "MULTIPLE_ACTIVE_ASSIGNMENTS", message: "x" };

// ---- 1. parser -------------------------------------------------------------------------------------------------------------------------------------------------------------

test("/active-lines parses real assignments; malformed or ambiguous shapes are rejected", () => {
  const lines = parseActiveLines(LINES());
  assert.ok(lines);
  assert.deepEqual(lines.items.map((i) => [i.assignment.line.line_code, i.stale]), [["L1", false], ["L2", false]]);
  assert.equal(parseActiveLines({ ...LINES(), current_shift: null }).current_shift, null);
  for (const bad of [null, [], {}, { current_shift: null }, { assignments: [] }, LINES([{ assignment: L1, stale: "no" }]), LINES([{ assignment: { ...L1, id: "" }, stale: false }]),
    LINES([{ assignment: L1, stale: false }, { assignment: clone(L1), stale: false }]), // misma asignación dos veces: ambiguo
    LINES([{ assignment: "x", stale: false }]), { current_shift: { code: "DIA" }, assignments: [] }]) assert.equal(parseActiveLines(bad), null, JSON.stringify(bad)?.slice(0, 60));
});

test("0 or 1 line keeps the historical single contract; 2+ requires an explicit choice", () => {
  const two = selectionFromLines(parseActiveLines(LINES()));
  assert.equal(two.kind, "multiple");
  const one = selectionFromLines(parseActiveLines(LINES([{ assignment: L1, stale: false }])));
  assert.deepEqual([one.kind, one.active.assignment.id, one.active.stale], ["single", L1.id, false]);
  const none = selectionFromLines(parseActiveLines(LINES([])));
  assert.deepEqual([none.kind, none.active.assignment, none.active.stale], ["single", null, null]);
  assert.equal(contextFromActive(none.active).reason, "none");
});

// ---- 2. selección derivada ---------------------------------------------------------------------------------------------------------------------------------------------

const lines = () => parseActiveLines(LINES());
const KEY = selectionKey("user:1", "MP1");

test("nothing is ever selected automatically and without a valid choice there is no capture context", () => {
  assert.equal(validSelection(null, KEY, lines()), null);
  const check = contextFromSelection(lines(), null);
  assert.deepEqual([check.ok, check.reason, check.assignment], [false, "unselected", null]);
  assert.match(CONTEXT_MESSAGES.unselected, /elige la línea/i);
  assert.equal(contextFromSelection(lines(), "not-a-line").reason, "unselected");
});

test("a valid choice yields the context of THAT assignment (its id goes to the capture), not of its sibling", () => {
  const id = validSelection({ key: KEY, assignmentId: L2.id }, KEY, lines());
  assert.equal(id, L2.id);
  const check = contextFromSelection(lines(), id);
  assert.ok(check.ok);
  assert.deepEqual([check.context.assignmentId, check.context.lineId, check.context.machine, check.context.workOrderId], [L2.id, "L2", "MP1", L2.work_order.id]);
});

test("a choice expires when the machine or the session changes, the line is finished, or the shift/date makes it stale", () => {
  const choice = { key: KEY, assignmentId: L1.id };
  assert.equal(validSelection(choice, selectionKey("user:1", "MP3"), lines()), null, "otra máquina");
  assert.equal(validSelection(choice, selectionKey("user:2", "MP1"), lines()), null, "otra sesión");
  const finished = parseActiveLines(LINES([{ assignment: L2, stale: false }]));
  assert.equal(validSelection(choice, KEY, finished), null, "la línea ya no está activa");
  const stale = parseActiveLines(LINES([{ assignment: L1, stale: true }, { assignment: L2, stale: false }]));
  assert.equal(validSelection(choice, KEY, stale), null, "cambio de turno o fecha");
  assert.equal(contextFromSelection(stale, L1.id).reason, "stale");
  const unresolved = parseActiveLines(LINES([{ assignment: L1, stale: null }, { assignment: L2, stale: false }]));
  assert.equal(validSelection(choice, KEY, unresolved), null);
  assert.equal(contextFromSelection(unresolved, L1.id).reason, "unresolvable");
  assert.equal(validSelection(choice, KEY, lines()), L1.id, "y sigue valiendo mientras nada cambie");
});

test("only fresh lines are selectable; the reason for an unselectable one is explicit", () => {
  assert.deepEqual([isSelectable({ assignment: L1, stale: false }), isSelectable({ assignment: L1, stale: true }), isSelectable({ assignment: L1, stale: null })], [true, false, false]);
  assert.match(unselectableReason({ assignment: L1, stale: true }), /otro turno/i);
  assert.match(unselectableReason({ assignment: L1, stale: null }), /turno vigente/i);
  assert.equal(unselectableReason({ assignment: L1, stale: false }), null);
});

test("resource keys carry the session and the machine: a late answer of another account or machine is never shown", () => {
  const stored = { key: operationSelectionKey("MP1", "user:1"), attempt: 0, result: { ok: true, data: "x" } };
  assert.equal(deriveView(operationSelectionKey("MP1", "user:1"), true, 0, stored).status, "ready");
  assert.equal(deriveView(operationSelectionKey("MP1", "user:2"), true, 0, stored).status, "loading");
  assert.equal(deriveView(operationSelectionKey("MP3", "user:1"), true, 0, stored).status, "loading");
  assert.notEqual(operationSelectionKey("MP1", "user:1"), activeAssignmentKey("MP1", "user:1"));
});

// ---- 3. cliente --------------------------------------------------------------------------------------------------------------------------------------------------------------

test("flag off / one active line: ONE GET /active, no extra step and no /active-lines", async () => {
  const { result, calls } = await withFetch(() => json(200, ACTIVE_OK), () => api.getOperationSelection("MP1"));
  assert.deepEqual(calls.map((c) => [c.method, c.url]), [["GET", "/api/assignments/active?machine_code=MP1"]]);
  assert.ok(result.ok);
  assert.deepEqual([result.data.kind, result.data.active.assignment.id], ["single", L1.id]);
  const empty = await withFetch(() => json(200, { assignment: null, current_shift: null, stale: null }), () => api.getOperationSelection("MP1"));
  assert.ok(empty.result.ok && empty.result.data.kind === "single" && empty.result.data.active.assignment === null);
});

test("several active lines: 409 MULTIPLE_ACTIVE_ASSIGNMENTS on /active triggers exactly one GET /active-lines, and nothing is chosen", async () => {
  const { result, calls } = await withFetch((n) => (n === 1 ? json(409, MULTIPLE) : json(200, LINES())), () => api.getOperationSelection("MP1"));
  assert.deepEqual(calls.map((c) => [c.method, c.url]), [["GET", "/api/assignments/active?machine_code=MP1"], ["GET", "/api/assignments/active-lines?machine_code=MP1"]]);
  assert.ok(calls.every((c) => c.body === undefined), "solo lecturas: nunca se envía ni se activa nada");
  assert.ok(result.ok);
  assert.deepEqual([result.data.kind, result.data.lines.items.length], ["multiple", 2]);
});

test("any other failure is returned as is (no fallback, no guessing a line)", async () => {
  for (const [status, payload, kind] of [[409, { code: "SOMETHING_ELSE" }, "conflict"], [409, {}, "conflict"], [403, { code: "FORBIDDEN" }, "forbidden"], [404, {}, "not_found"], [401, {}, "session"], [500, {}, "unavailable"]]) {
    const { result, calls } = await withFetch(() => json(status, payload), () => api.getOperationSelection("MP1"));
    assert.equal(calls.length, 1, `${status} ${JSON.stringify(payload)}`);
    assert.ok(!result.ok);
    assert.equal(result.kind, kind);
  }
});

test("a failing or malformed /active-lines is a failure, never a selection (revoked permission between the two reads, bad JSON, network)", async () => {
  for (const second of [() => json(403, {}), () => json(401, {}), () => json(200, { current_shift: null }), () => json(200, LINES([{ assignment: L1, stale: 1 }])), () => { throw new TypeError("network"); }]) {
    const { result } = await withFetch((n) => (n === 1 ? json(409, MULTIPLE) : second()), () => api.getOperationSelection("MP1"));
    assert.ok(!result.ok);
  }
  const oneLeft = await withFetch((n) => (n === 1 ? json(409, MULTIPLE) : json(200, LINES([{ assignment: L1, stale: false }]))), () => api.getOperationSelection("MP1"));
  assert.ok(oneLeft.result.ok && oneLeft.result.data.kind === "single", "una carrera que deja una sola línea vuelve al contrato histórico");
});

// ---- 4. render ---------------------------------------------------------------------------------------------------------------------------------------------------------------

const props = (over = {}) => ({ machine: "MP1", lines: parseActiveLines(LINES()), selectedId: null, onChoose: () => undefined, onRefresh: () => undefined, ...over });

test("the selector lists every line with enough data to tell them apart and preselects none", () => {
  const html = render(selector.LineSelector, props());
  assert.equal((html.match(/type="radio"/g) ?? []).length, 2);
  assert.doesNotMatch(html, /checked/);
  for (const a of [L1, L2]) for (const text of [a.work_order.number, a.line.line_code, a.line.article.description, `PV ${a.line.pv_reference}`, a.line.article.code]) assert.ok(html.includes(text), text);
  assert.match(html, /No se selecciona ninguna automáticamente/);
  assert.match(html, /<fieldset[^>]*>\s*<legend[^>]*>Líneas activas en MP1/);
  assert.match(html, /type="button"[^>]*>Actualizar líneas/);
});

test("the chosen line is the only checked radio; a stale line is disabled and says why", () => {
  const html = render(selector.LineSelector, props({ selectedId: L2.id, lines: parseActiveLines(LINES([{ assignment: L1, stale: true }, { assignment: L2, stale: false }])) }));
  assert.equal((html.match(/checked/g) ?? []).length, 1);
  assert.match(html, new RegExp(`value="${L2.id}"[^>]*checked|checked[^>]*value="${L2.id}"`));
  assert.match(html, new RegExp(`disabled[^>]*value="${L1.id}"|value="${L1.id}"[^>]*disabled`));
  assert.match(html, /Otro turno o fecha operativa/);
  assert.match(html, /Línea elegida/);
});

// ---- 5. cableado -------------------------------------------------------------------------------------------------------------------------------------------------------------

test("wiring: Ejecución reads through the new hook, derives the choice from state, and the new modules never persist or log it", () => {
  const page = noComments(read("app/page.tsx"));
  assert.match(page, /useOperationSelection\(machine,/);
  assert.match(page, /validSelection\(lineChoice, lineKey, operation\.data\.lines\)/);
  assert.match(page, /contextFromSelection\(resource\.data\.lines, chosenLineId\)/);
  assert.match(page, /<LineSelector /);
  assert.doesNotMatch(page, /useActiveAssignment\(/, "la pantalla de Ejecución ya no usa la lectura de una sola asignación");
  for (const file of ["lib/vinto/active-lines.ts", "components/vinto/line-selector.tsx", "lib/vinto/assignments-api.ts"]) {
    const text = noComments(read(file));
    assert.doesNotMatch(text, /localStorage|sessionStorage|document\.cookie|console\./, file);
  }
  const apiSource = noComments(read("lib/vinto/assignments-api.ts"));
  assert.match(apiSource, /single\.code !== "MULTIPLE_ACTIVE_ASSIGNMENTS"/);
});

test("the selection never sends anything but the assignment id the capture already used (no new body, no client-chosen machine)", () => {
  const text = noComments(read("lib/vinto/active-lines.ts"));
  assert.doesNotMatch(text, /requestJson|fetch\(|method:\s*"POST"/);
});
