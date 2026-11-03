// node --test scripts/pr61-capabilities.test.mjs
// MF-13-03B PR6.1: la interfaz de Jefatura ya consulta GET /api/work-orders/capabilities. Prueba el parser estricto, el cliente HTTP (fetch simulado), el aislamiento por sesión del recurso, el render real del
// componente según el estado de la consulta y el cableado. Sin DOM ni navegador: los efectos no se ejecutan en el render del servidor, por eso la lógica del hook (claves, deriveView) se prueba aparte.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { deriveView, sessionScope, workOrderCapabilitiesKey, workOrdersKey } from "../lib/vinto/resource-view.ts";
import { NO_CAPABILITIES, capabilitiesOf, multiMachineOffered, parseCapabilities, parseCapabilitiesResponse } from "../lib/vinto/work-order-capabilities.ts";
import { normalizeForMode } from "../lib/vinto/order-draft.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-pr61-test-${process.pid}`);
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

let api, programming, source, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [api, programming, source] = await Promise.all([bundle("lib/vinto/work-orders-api.ts", "api"), bundle("components/vinto/bobinas-programming.tsx", "programming"), bundle("components/vinto/bobinas-programming-source.tsx", "source")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const read = (file) => readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
const noComments = (text) => text.replace(/\/\/.*$/gm, "");
const render = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));

// ---- 1. parser estricto y vista efectiva ------------------------------------------------------------------------------------------------------------------------------

test("the endpoint response is parsed strictly: only a boolean multi_machine is valid", () => {
  assert.equal(parseCapabilitiesResponse({ multi_machine: true }).multiMachine, true);
  assert.equal(parseCapabilitiesResponse({ multi_machine: false }).multiMachine, false);
  assert.equal(parseCapabilitiesResponse({ multi_machine: true, extra: "ignored", enabled: false }).multiMachine, true, "extra keys never widen or narrow anything");
  for (const bad of [null, undefined, [], "true", 1, true, {}, { multi_machine: "true" }, { multi_machine: 1 }, { multi_machine: null }, { multiMachine: true }, { detail: "MULTI_MACHINE_DISABLED" }]) {
    assert.equal(parseCapabilitiesResponse(bad), null, JSON.stringify(bad));
  }
  assert.equal(Object.isFrozen(parseCapabilitiesResponse({ multi_machine: true })), true);
});

test("the effective capability is on only for a ready resource that says true; idle, loading and error are off", () => {
  const on = Object.freeze({ multiMachine: true });
  assert.deepEqual(capabilitiesOf({ status: "ready", data: on }), { capabilities: on, status: "ready" });
  assert.deepEqual(capabilitiesOf({ status: "ready", data: NO_CAPABILITIES }), { capabilities: NO_CAPABILITIES, status: "ready" });
  for (const status of ["idle", "loading", "error"]) assert.deepEqual(capabilitiesOf({ status }), { capabilities: NO_CAPABILITIES, status }, status);
  assert.equal(capabilitiesOf({ status: "ready", data: { multiMachine: "true" } }).capabilities.multiMachine, false, "a malformed ready value never enables");
  assert.equal(capabilitiesOf({ status: "error", kind: "invalid" }).capabilities.multiMachine, false);
});

test("multi-machine is offered only with the server's true, work_order.manage and more than one eligible machine", () => {
  const on = parseCapabilitiesResponse({ multi_machine: true });
  assert.equal(multiMachineOffered(on, true, 2), true);
  assert.equal(multiMachineOffered(on, false, 2), false, "Supervisión never");
  assert.equal(multiMachineOffered(on, true, 1), false);
  assert.equal(multiMachineOffered(parseCapabilitiesResponse({ multi_machine: false }), true, 3), false);
  assert.equal(multiMachineOffered(NO_CAPABILITIES, true, 3), false);
  assert.equal(parseCapabilities({ multi_machine: true }).multiMachine, true, "the PR6 lenient parser keeps working");
});

// ---- 2. cliente HTTP ------------------------------------------------------------------------------------------------------------------------------------------------

const json = (status, payload) => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
const withFetch = async (responder, body) => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return responder(calls.length); };
  try { return { result: await body(), calls }; } finally { globalThis.fetch = original; }
};

test("the client sends one plain authenticated GET and parses true and false", async () => {
  for (const flag of [true, false]) {
    const { result, calls } = await withFetch(() => json(200, { multi_machine: flag }), () => api.getWorkOrderCapabilities());
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/work-orders\/capabilities$/, "no query string");
    assert.equal(calls[0].init.method ?? "GET", "GET");
    assert.equal(calls[0].init.credentials, "include");
    assert.equal(calls[0].init.body, undefined);
    assert.equal(calls[0].init.cache, "no-store");
    assert.ok(result.ok);
    assert.equal(result.data.multiMachine, flag);
  }
});

test("401, 403, 404, 422, 5xx, a network error, invalid JSON and a wrong shape all leave the capability OFF", async () => {
  const expectations = [[401, "session"], [403, "forbidden"], [404, "not_found"], [422, "invalid"], [500, "unavailable"], [503, "unavailable"]];
  for (const [status, kind] of expectations) {
    const { result } = await withFetch(() => json(status, { code: "MULTI_MACHINE_DISABLED", multi_machine: true }), () => api.getWorkOrderCapabilities());
    assert.equal(result.ok, false, String(status));
    assert.equal(result.kind, kind, String(status));
    assert.equal(capabilitiesOf({ status: "error" }).capabilities.multiMachine, false);
  }
  const network = await withFetch(() => { throw new TypeError("network down"); }, () => api.getWorkOrderCapabilities());
  assert.deepEqual([network.result.ok, network.result.kind], [false, "unavailable"]);
  const notJson = await withFetch(() => new Response("<html>proxy error</html>", { status: 200 }), () => api.getWorkOrderCapabilities());
  assert.deepEqual([notJson.result.ok, notJson.result.kind], [false, "unavailable"]);
  const empty = await withFetch(() => new Response("", { status: 200 }), () => api.getWorkOrderCapabilities());
  assert.equal(empty.result.ok, false);
  for (const payload of [{}, { multi_machine: "true" }, { multi_machine: 1 }, [true], "true", null]) {
    const { result } = await withFetch(() => json(200, payload), () => api.getWorkOrderCapabilities());
    assert.equal(result.ok, false, JSON.stringify(payload));
  }
});

test("an aborted request surfaces as an abort and never as an enabled capability", async () => {
  const controller = new AbortController();
  const { result } = await withFetch(() => { throw new DOMException("aborted", "AbortError"); }, () => api.getWorkOrderCapabilities(controller.signal).then(() => "resolved", (error) => error.name));
  assert.equal(result, "AbortError");
});

// ---- 3. sesión: claves y respuestas tardías ------------------------------------------------------------------------------------------------------------------------

test("the capability belongs to the session: keys differ per user, and a stored answer of another account is never shown", () => {
  const a = sessionScope({ id: "user-a" }), b = sessionScope({ id: "user-b" });
  assert.notEqual(workOrderCapabilitiesKey(a), workOrderCapabilitiesKey(b));
  assert.notEqual(workOrderCapabilitiesKey(a), workOrdersKey(a), "no collision with the work order list");
  assert.ok(!/cookie|token|secret|password/i.test(workOrderCapabilitiesKey(a)));
  const storedByA = { key: workOrderCapabilitiesKey(a), attempt: 0, result: { ok: true, data: { multiMachine: true } } };
  assert.equal(deriveView(workOrderCapabilitiesKey(a), true, 0, storedByA).status, "ready");
  assert.equal(deriveView(workOrderCapabilitiesKey(b), true, 0, storedByA).status, "loading", "a late answer for user A cannot enable user B");
  assert.equal(capabilitiesOf(deriveView(workOrderCapabilitiesKey(b), true, 0, storedByA)).capabilities.multiMachine, false);
  assert.equal(capabilitiesOf(deriveView(workOrderCapabilitiesKey(sessionScope(null)), false, 0, storedByA)).capabilities.multiMachine, false, "logged out: disabled and nothing queried");
  assert.equal(deriveView(workOrderCapabilitiesKey(a), false, 0, storedByA).status, "idle");
});

test("the hook asks only when the session may manage orders or activate them, scopes the key by session and reports 401 as a lost session", () => {
  const hooks = noComments(read("lib/vinto/use-central.ts"));
  assert.match(hooks, /useWorkOrderCapabilities = \(enabled: boolean, onUnauthorized: \(\) => void, scope: string\) =>/);
  assert.match(hooks, /useResource<WorkOrderCapabilities>\(workOrderCapabilitiesKey\(scope\), enabled, \(signal\) => getWorkOrderCapabilities\(signal\), onUnauthorized, true\)/);
  const wrapper = noComments(read("components/vinto/bobinas-programming-source.tsx"));
  assert.match(wrapper, /useWorkOrderCapabilities\(rest\.canManageOrders \|\| rest\.canManageAssignments, rest\.onSessionLost, scope\)/, "enabled for work_order.manage (create) or assignment.manage (PR7 mass activation); 401 goes to the session handler");
  assert.match(wrapper, /capabilitiesOf\(/);
  assert.ok(!/NEXT_PUBLIC|localStorage|sessionStorage|process\.env/.test(wrapper + hooks + noComments(read("lib/vinto/work-order-capabilities.ts"))));
  const page = noComments(read("app/page.tsx"));
  assert.match(page, /<BobbinasProgrammingSource scope=\{scope\}/, "the session scope reaches the container");
});

test("the late-answer guard of useResource is the one in force: it aborts and ignores results once the key or the session changed", () => {
  const hook = read("lib/vinto/use-central.ts");
  assert.match(hook, /if \(controller\.signal\.aborted\) return;/);
  assert.match(hook, /return \(\) => controller\.abort\(\);/);
  assert.match(hook, /if \(!result\.ok && result\.kind === "session"\) latest\.current\.onUnauthorized\(\);/);
});

// ---- 4. componente según el estado de la consulta ----------------------------------------------------------------------------------------------------------------------

const MP1 = { code: "MP1", name: "MP1" }, MP3 = { code: "MP3", name: "MP3" };
const CATALOG = { MP1: [{ code: "A", name: "Producto A" }, { code: "B", name: "Producto B" }], MP3: [{ code: "C", name: "Producto C" }, { code: "A", name: "Producto A" }] };
const creation = { machines: [MP1, MP3], catalog: (machine) => CATALOG[machine] ?? [] };
const noop = () => {};
const props = (o = {}) => ({ machines: ["MP1", "MP3"], creation, workOrders: { status: "ready", data: [], refreshing: false }, onChanged: noop, onSessionLost: noop, canManageOrders: true, canManageAssignments: false, ...o });
const rows3 = [{ key: "r1", machine: "MP1", pv: "PV-1", code: "A", qty: "10", date: "2026-10-30" }, { key: "r2", machine: "MP1", pv: "PV-2", code: "B", qty: "5", date: "2026-10-30" }, { key: "r3", machine: "MP3", pv: "PV-3", code: "C", qty: "7", date: "2026-10-31" }];
const html = (o) => render(programming.BobbinasProgramming, props(o));
const selectTag = (text, label) => (text.match(new RegExp(`<select[^>]*aria-label="${label}"[^>]*>`)) ?? [""])[0];
const isDisabled = (tag) => /\sdisabled(=""|\s|>)/.test(tag);

test("while the capability is loading or failed, the form stays traditional and says why", () => {
  const loading = html({ initialRows: rows3, capabilities: NO_CAPABILITIES, capabilityStatus: "loading" });
  assert.ok(loading.includes('data-capability="loading"') && loading.includes("Confirmando con el servidor"));
  assert.ok(isDisabled(selectTag(loading, "Máquina de la fila 3")), "no per-row machine choice while unconfirmed");
  const failed = html({ initialRows: rows3, capabilities: NO_CAPABILITIES, capabilityStatus: "error" });
  assert.ok(failed.includes('data-capability="error"') && failed.includes("No se pudo confirmar si el servidor admite"));
  assert.ok(isDisabled(selectTag(failed, "Máquina de la fila 3")));
  const off = html({ initialRows: rows3, capabilities: NO_CAPABILITIES, capabilityStatus: "ready" });
  assert.ok(off.includes("no están habilitadas por el servidor"));
});

test("with the server's true and permission, each row chooses its machine; the traditional note disappears", () => {
  const on = html({ initialRows: rows3, capabilities: parseCapabilitiesResponse({ multi_machine: true }), capabilityStatus: "ready" });
  for (const n of [1, 2, 3]) assert.ok(!isDisabled(selectTag(on, `Máquina de la fila ${n}`)), `row ${n}`);
  assert.ok(!on.includes("data-multi-off"));
  assert.ok(on.includes("Borrador local: 3 línea(s) · 2 máquina(s): MP1, MP3 · 3 producto(s)"));
});

test("the capability never reaches a profile that cannot manage orders (Supervisión, Operación)", () => {
  const readOnly = html({ canManageOrders: false, canManageAssignments: true, capabilities: parseCapabilitiesResponse({ multi_machine: true }), capabilityStatus: "ready" });
  assert.ok(readOnly.includes("Solo lectura") && !readOnly.includes("data-order-draft"));
});

test("if the server stops confirming, a multi-machine draft collapses to a single machine instead of sending mixed machines", () => {
  const catalog = creation.catalog;
  const normalized = normalizeForMode(rows3, false, catalog);
  assert.deepEqual(normalized.map((r) => [r.machine, r.code]), [["MP1", "A"], ["MP1", "B"], ["MP1", ""]], "row 3 keeps its PV/quantity but loses the product MP1 does not offer");
  assert.equal(normalizeForMode(rows3, true, catalog).length, 3);
  assert.deepEqual(normalizeForMode(rows3, true, catalog), rows3, "multi leaves the rows untouched");
  const text = html({ initialRows: rows3, capabilities: NO_CAPABILITIES, capabilityStatus: "ready" });
  assert.ok(!/<option value="MP3" selected/.test(text), "no row shows MP3 once multi is off");
  assert.ok(text.includes("Borrador local: 3 línea(s) · 1 máquina(s): MP1"));
});

test("the container renders safely before any answer exists (hooks do not run on the server): creation not offered, existing orders visible", () => {
  const text = render(source.BobbinasProgrammingSource, { scope: "user:test", machines: ["MP1", "MP3"], workOrders: { status: "ready", data: [], refreshing: false }, onChanged: noop, onSessionLost: noop, canManageOrders: true, canManageAssignments: false });
  assert.ok(text.includes("Consultando las máquinas y productos habilitados"));
  assert.ok(!text.includes("data-order-draft") && !text.includes("Crear OT"));
  const supervisor = render(source.BobbinasProgrammingSource, { scope: "user:test", machines: ["MP1", "MP3"], workOrders: { status: "ready", data: [], refreshing: false }, onChanged: noop, onSessionLost: noop, canManageOrders: false, canManageAssignments: true });
  assert.ok(supervisor.includes("Solo lectura"));
});
