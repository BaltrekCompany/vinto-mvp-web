// node --test scripts/pr6-programming-ui.test.mjs
// MF-13-03B PR6: renderiza el componente REAL de Programación (React + react-dom/server) en cada estado y prueba el cliente HTTP con un `fetch` simulado (una sola solicitud, errores 401/403/404/409/422).
// Los TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio que se borra al terminar. Los efectos/eventos no se ejecutan en el render del servidor: la
// lógica interactiva (borrador, validaciones, doble envío, respuestas tardías) está en módulos puros que prueba scripts/pr6-order-draft.test.mjs.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-pr6-ui-test-${process.pid}`);

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

let programming, api, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [programming, api] = await Promise.all([bundle("components/vinto/bobinas-programming.tsx", "programming"), bundle("lib/vinto/work-orders-api.ts", "api")]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const html = (props) => server.renderToStaticMarkup(React.createElement(programming.BobbinasProgramming, props));
const MP1 = { code: "MP1", name: "MP1" }, MP3 = { code: "MP3", name: "MP3" };
const CATALOG = { MP1: [{ code: "A", name: "Producto A" }, { code: "B", name: "Producto B" }], MP3: [{ code: "C", name: "Producto C" }, { code: "A", name: "Producto A" }] };
const creation = { machines: [MP1, MP3], catalog: (machine) => CATALOG[machine] ?? [] };
const noop = () => {};
const line = (n, machine, extra = {}) => ({ id: `00000000-0000-4000-8000-00000000000${n}`, line_code: `L${n}`, pv_reference: `PV-${n}`, machine, article: { code: `ART-${n}`, description: `Descripción ${n}` }, quantity: 10 * n, unit: "KG", due_date: "2026-10-30", ...extra });
const order = (status, lines, extra = {}) => ({ id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0003", status, machine: MP1, baseline: { id: "33333333-3333-4333-8333-333333333333", version_number: 1, published_at: status === "draft" ? null : "2026-10-06T16:00:00Z", lines }, ...extra });
const MULTI_LINES = [line(1, MP1), line(2, MP1), line(3, MP3)];
const ready = (data) => ({ status: "ready", data, refreshing: false });
const props = (o = {}) => ({ machines: ["MP1", "MP3"], creation, workOrders: ready([]), onChanged: noop, onSessionLost: noop, canManageOrders: true, canManageAssignments: false, ...o });
const rows3 = [{ key: "r1", machine: "MP1", pv: "PV-1", code: "A", qty: "10", date: "2026-10-30" }, { key: "r2", machine: "MP1", pv: "PV-2", code: "B", qty: "5", date: "2026-10-30" }, { key: "r3", machine: "MP3", pv: "PV-3", code: "C", qty: "7", date: "2026-10-31" }];
const count = (text, needle) => text.split(needle).length - 1;
const selectTag = (text, label) => (text.match(new RegExp(`<select[^>]*aria-label="${label}"[^>]*>`)) ?? [""])[0];
const isDisabled = (tag) => /\sdisabled(=""|\s|>)/.test(tag);

// ---- creación: compuerta apagada (flujo tradicional) y habilitada --------------------------------------------------------------------------------------------------------

test("with the server gate OFF (default) the form is the traditional single-machine one and says so", () => {
  const text = html(props({ initialRows: rows3.map((r) => ({ ...r, machine: "MP1" })) }));
  assert.ok(text.includes("data-order-draft"));
  assert.ok(text.includes("OT de una sola máquina"));
  assert.ok(text.includes("no están habilitadas por el servidor"));
  assert.equal(count(text, "data-draft-row"), 3, "several rows are still allowed on one machine");
  assert.ok(!isDisabled(selectTag(text, "Máquina de la fila 1")), "the first row picks the machine");
  assert.ok(isDisabled(selectTag(text, "Máquina de la fila 2")) && isDisabled(selectTag(text, "Máquina de la fila 3")), "the others share it");
  assert.ok(!text.includes("Una OT puede contener productos de varios PV y de varias máquinas"));
});

test("a machine-choosing form is NOT offered when the server did not confirm, even with several machines available", () => {
  const text = html(props({ initialRows: rows3, capabilities: { multiMachine: false } }));
  assert.ok(isDisabled(selectTag(text, "Máquina de la fila 3")), "MP3 cannot be picked independently");
});

test("with the server gate ON each row has its own machine and product selectors, plus a summary", () => {
  const text = html(props({ initialRows: rows3, capabilities: { multiMachine: true } }));
  assert.equal(count(text, "data-draft-row"), 3);
  for (const n of [1, 2, 3]) assert.ok(!isDisabled(selectTag(text, `Máquina de la fila ${n}`)) && !isDisabled(selectTag(text, `Producto de la fila ${n}`)), `row ${n}`);
  assert.ok(text.includes("varias máquinas"));
  assert.ok(text.includes("Borrador local: 3 línea(s) · 2 máquina(s): MP1, MP3 · 3 producto(s)"));
  assert.ok(text.includes("Se enviará una sola OT: 3 línea(s) · 2 máquina(s): MP1, MP3 · 3 producto(s)"));
  assert.ok(text.includes("El número y los códigos de línea los asigna el servidor"));
  assert.ok(text.includes(">Agregar línea<") && count(text, "Retirar la fila") === 3);
  assert.ok(/value="MP3" selected/.test(text) || text.includes('<option value="MP3" selected'), "row 3 shows MP3");
  assert.ok(!text.includes("OT de una sola máquina"));
});

test("with the gate ON but a single machine available, the form stays traditional", () => {
  const text = html(props({ creation: { machines: [MP1], catalog: creation.catalog }, capabilities: { multiMachine: true } }));
  assert.ok(text.includes("OT de una sola máquina"));
});

test("the product options depend on the row's machine (backend-provided catalog, not a static list)", () => {
  const text = html(props({ initialRows: [{ key: "r1", machine: "MP3", pv: "", code: "", qty: "", date: "" }], capabilities: { multiMachine: true } }));
  assert.ok(text.includes("C · Producto C") && text.includes("A · Producto A"));
  assert.ok(!text.includes("B · Producto B"), "B is not offered for MP3");
  const empty = html(props({ initialRows: [{ key: "r1", machine: "", pv: "", code: "", qty: "", date: "" }], capabilities: { multiMachine: true } }));
  assert.ok(isDisabled(selectTag(empty, "Producto de la fila 1")), "no product until a machine is chosen");
});

test("while the catalog loads, or if it is unavailable, creation is not offered but existing orders stay visible", () => {
  for (const [state, message] of [["loading", "Consultando las máquinas y productos habilitados"], ["unavailable", "No se pudo consultar el catálogo"]]) {
    const text = html(props({ creation: state, workOrders: ready([order("draft", MULTI_LINES)]) }));
    assert.ok(text.includes(message), state);
    assert.ok(!text.includes("data-order-draft") && !text.includes("Crear OT"), state);
    assert.ok(text.includes("OT-2026-0003"), "the persisted order is still listed");
  }
});

// ---- OT persistidas: máquina por línea, publicación, solo lectura ------------------------------------------------------------------------------------------------------

test("an existing order shows the machine of every line, its machines and the principal machine", () => {
  const text = html(props({ workOrders: ready([order("draft", MULTI_LINES)]) }));
  assert.ok(text.includes("<th class=\"p-3\">Máquina</th>"));
  assert.equal(count(text, "data-line-machine"), 3);
  assert.ok(/data-line-machine="">MP3</.test(text));
  assert.ok(text.includes("máquina(s): MP1, MP3"));
  assert.ok(text.includes("Máquina principal de la OT: MP1"));
  assert.ok(text.includes('<h3 class="font-black">OT-2026-0003</h3>'));
  assert.ok(!text.includes("OT-2026-0003 · MP1"));
});

test("an OLD order (single machine) renders as before, with no multi-machine remark", () => {
  const text = html(props({ workOrders: ready([order("published", [line(1, MP1), line(2, MP1)])]) }));
  assert.ok(text.includes("máquina(s): MP1"));
  assert.ok(!text.includes("Máquina principal de la OT"));
  assert.ok(text.includes('<h3 class="font-black">OT-2026-0003</h3>'));
  assert.ok(!text.includes("OT-2026-0003 · MP1"));
});

test("a draft can be published (with confirmation) and receive another line; a published order cannot", () => {
  const draft = html(props({ workOrders: ready([order("draft", MULTI_LINES)]), capabilities: { multiMachine: true } }));
  assert.ok(draft.includes("Publicar base"));
  assert.ok(draft.includes("Añadir una línea a este borrador"));
  assert.equal(count(draft, "<details"), 4, "three editable persisted lines and one add-line form");
  assert.ok(draft.includes("Editar L1") && draft.includes("Guardar cambios de L1"), "Jefatura can edit saved draft fields");
  assert.ok(draft.includes("data-edit-draft-line=\"L1\""), "editor identifies the persisted line");
  assert.ok(draft.includes("Motivo de la corrección (obligatorio)"));
  const published = html(props({ workOrders: ready([order("published", MULTI_LINES)]), capabilities: { multiMachine: true } }));
  assert.ok(!published.includes("Publicar base") && !published.includes("Añadir una línea"), "the published baseline is immutable");
  assert.ok(!published.includes("data-edit-draft-line") && !published.includes("Guardar cambios"), "published orders cannot edit persisted lines");
  assert.ok(!draft.includes("Eliminar línea") && !draft.includes("Retirar línea"), "E2-A does not delete persisted lines");
});


test("E2-A frontend never permits machine edits on a persisted draft line", async () => {
  const source = (await import("node:fs")).readFileSync(new URL("../components/vinto/bobinas-programming.tsx", import.meta.url), "utf8");
  assert.match(source, /multi=\{false\} lockMachine fixedRows/);
  assert.match(source, /order\.status === "draft"/);
  assert.match(source, /editDraftWorkOrderLine\(order\.id, line\.line_code, expected, replacement, reason\)/);
  const orderDraft = (await import("node:fs")).readFileSync(new URL("../components/vinto/order-draft-editor.tsx", import.meta.url), "utf8");
  assert.match(orderDraft, /disabled=\{disabled \|\| shared \|\| lockMachine\}/);
});
test("E2-B shows current revision without changing baseline line identity or enabling other roles", () => {
  const base = [line(1, MP1, { article: { code: "A", description: "Producto A" }, quantity: 120 })];
  const current = [line(1, MP1, { id: "aaaa0000-0000-4000-8000-000000000001", article: { code: "B", description: "Producto B" }, quantity: 150 })];
  const revised = order("published", base, { programming: { id: "44444444-4444-4444-8444-444444444444", version_number: 2, published_at: "2026-11-07T18:00:00Z", lines: current } });
  const manager = html(props({ workOrders: ready([revised]), canManageAssignments: true }));
  assert.ok(manager.includes("Programación vigente v2"));
  assert.ok(manager.includes("150 KG") && manager.includes("Producto B"));
  assert.ok(manager.includes("data-reprogram-line=\"L1\""));
  assert.ok(manager.includes("Consultar historial de versiones"));
  assert.ok(!manager.includes("data-edit-draft-line"), "do not reuse draft editing");
  const revisedEditor = manager.split('data-reprogram-line="L1"')[1];
  assert.ok(revisedEditor && isDisabled(selectTag(revisedEditor, "Máquina de la fila 1")), "the persisted revision machine is fixed (not the separate new-OT form)");
  const supervisor = html(props({ workOrders: ready([revised]), canManageOrders: false, canManageAssignments: true }));
  assert.ok(supervisor.includes("150 KG"), "supervision sees current programmed quantity");
  assert.ok(!supervisor.includes("data-reprogram-line"), "only Jefatura may edit");
  const operator = html(props({ workOrders: ready([revised]), canManageOrders: false, canManageAssignments: false }));
  assert.ok(!operator.includes("data-reprogram-line"));
  const running = html(props({ workOrders: ready([order("in_progress", base)]) }));
  assert.ok(!running.includes("data-reprogram-line"), "in-production OT remains read-only");
});

test("E2-B HTTP sends expected_version and just four fields; no machine or baseline IDs", async () => {
  const expected = LINES[0];
  const revised = { ...expected, quantity: 150, pvReference: "PV-NEW" };
  const { result, calls } = await withFetch(() => json(200, serverOrder()),
    () => api.reprogramPublishedLine("22222222-2222-4222-8222-222222222222", "L1", 1, expected, revised, "Cambio registrado por Jefatura"));
  assert.ok(result.ok);
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/api\/work-orders\/22222222-2222-4222-8222-222222222222\/lines\/L1\/reprogram$/);
  assert.deepEqual(Object.keys(calls[0].body).sort(), ["expected", "expected_version", "reason", "replacement"]);
  assert.equal(calls[0].body.expected_version, 1);
  assert.deepEqual(Object.keys(calls[0].body.replacement).sort(), ["article_code", "due_date", "pv_reference", "quantity"]);
  assert.equal(calls[0].body.replacement.quantity, 150);
  const blocked = await withFetch(() => json(409, { code: "WORK_ORDER_REPROGRAM_BLOCKED" }),
    () => api.reprogramPublishedLine("22222222-2222-4222-8222-222222222222", "L1", 1, expected, revised, "Cambio registrado por Jefatura"));
  assert.equal(blocked.calls.length, 1, "failed reprogramming is never retried automatically");
  assert.equal(blocked.result.kind, "conflict");
});
test("the publish confirmation warns that the baseline becomes immutable", async () => {
  const source = (await import("node:fs")).readFileSync(new URL("../components/vinto/bobinas-programming.tsx", import.meta.url), "utf8");
  assert.ok(source.includes("Una vez publicada, la línea base es inmutable"));
  assert.ok(/onClick=\{\(\) => setConfirming\(order\)\}/.test(source), "the button opens the confirmation; it does not publish directly");
  assert.ok(/AlertDialogAction onClick=\{\(\) => confirming && publish\(confirming\)\}/.test(source));
});

test("roles: Supervisión and Operación get a read-only programme; only managers create or publish", () => {
  const supervisor = html(props({ canManageOrders: false, canManageAssignments: true, workOrders: ready([order("draft", MULTI_LINES), order("published", [line(1, MP1)], { id: "x", number: "OT-2026-0004" })]), capabilities: { multiMachine: true } }));
  assert.ok(supervisor.includes("Solo lectura"));
  assert.ok(!supervisor.includes("data-order-draft") && !supervisor.includes("Publicar base") && !supervisor.includes("Añadir una línea") && !supervisor.includes("Crear OT"));
  assert.ok(supervisor.includes(">Activar<"), "the individual activation of Supervisión is untouched");
  const operator = html(props({ canManageOrders: false, canManageAssignments: false, workOrders: ready([order("published", MULTI_LINES)]) }));
  assert.ok(operator.includes("Solo lectura") && !operator.includes("Activar") && !operator.includes("data-order-draft"));
});

test("without the server's confirmation there is NO mass activation, only the individual buttons (PR7 adds the mass button only with multi_machine: true)", () => {
  const text = html(props({ canManageAssignments: true, canManageOrders: true, workOrders: ready([order("published", MULTI_LINES)]) }));
  assert.ok(!/activar (todas|todo)|activaci[oó]n masiva|activate-all/i.test(text));
  assert.equal(count(text, ">Activar<"), 3, "only the individual per-line button");
});

test("a failed list shows the status panel instead of the programme (no data of an unreachable order)", () => {
  const text = html(props({ workOrders: { status: "error", kind: "not_found", refreshing: false } }));
  assert.ok(!text.includes("OT-2026") && !text.includes("data-order-draft"));
});

test("the sector shells keep working: legacy props (machines + catalog) still render the single-machine form", () => {
  const text = html({ machines: ["Beloit"], catalog: () => [{ code: "R1", name: "Rebobinado 1" }], workOrders: ready([]), onChanged: noop, onSessionLost: noop, canManageOrders: true, canManageAssignments: true, sectorLabel: "Rebobinado" });
  assert.ok(text.includes("data-order-draft") && text.includes("Beloit") && text.includes("OT de una sola máquina"));
});

// ---- cliente HTTP: una sola solicitud y errores ----------------------------------------------------------------------------------------------------------------------

const serverOrder = () => order("draft", MULTI_LINES);
const withFetch = async (responder, body) => {
  const calls = [], original = globalThis.fetch;
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), method: init?.method, body: init?.body ? JSON.parse(init.body) : undefined }); return responder(calls.length); };
  try { return { result: await body(), calls }; } finally { globalThis.fetch = original; }
};
const json = (status, payload) => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
const LINES = [{ pvReference: "PV-1", articleCode: "A", quantity: 10, dueDate: "2026-10-30", machineCode: "MP1" }, { pvReference: "PV-2", articleCode: "B", quantity: 5, dueDate: "2026-10-30", machineCode: "MP1" }, { pvReference: "PV-3", articleCode: "C", quantity: 7, dueDate: "2026-10-31", machineCode: "MP3" }];

test("creating a three-line multi-machine order is ONE POST /api/work-orders and parses the per-line machines", async () => {
  const { result, calls } = await withFetch(() => json(201, serverOrder()), () => api.createWorkOrderWithLines("MP1", LINES));
  assert.equal(calls.length, 1, "a single HTTP request, never one per line or per machine");
  assert.match(calls[0].url, /\/api\/work-orders$/);
  assert.equal(calls[0].method, "POST");
  assert.deepEqual(calls[0].body.lines.map((l) => [l.machine_code, l.article_code]), [["MP1", "A"], ["MP1", "B"], ["MP3", "C"]]);
  assert.equal(calls[0].body.machine_code, "MP1");
  assert.ok(result.ok);
  assert.equal(result.data.number, "OT-2026-0003", "the number comes from the server");
  assert.deepEqual(result.data.baseline.lines.map((l) => l.machine.code), ["MP1", "MP1", "MP3"]);
});

test("E2-A draft edit sends exactly four fields and never sends machine or IDs", async () => {
  const expected = LINES[0];
  const replacement = { ...expected, quantity: 150, pvReference: "PV-CORREGIDO" };
  const { result, calls } = await withFetch(() => json(200, serverOrder()),
    () => api.editDraftWorkOrderLine("22222222-2222-4222-8222-222222222222", "L1", expected, replacement, "Corrección QA de Jefatura"));
  assert.ok(result.ok);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, "POST");
  assert.match(calls[0].url, /\/api\/work-orders\/22222222-2222-4222-8222-222222222222\/lines\/L1\/edit-draft$/);
  assert.deepEqual(Object.keys(calls[0].body).sort(), ["expected", "reason", "replacement"]);
  assert.deepEqual(Object.keys(calls[0].body.expected).sort(), ["article_code", "due_date", "pv_reference", "quantity"]);
  assert.deepEqual(Object.keys(calls[0].body.replacement).sort(), ["article_code", "due_date", "pv_reference", "quantity"]);
  assert.equal(calls[0].body.replacement.quantity, 150);
  assert.equal(calls[0].body.reason, "Corrección QA de Jefatura");
});
test("every backend error is reported once, with no retry and no second request (no partial orders)", async () => {
  const expected = { 401: "session", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid", 500: "unavailable" };
  for (const [status, kind] of Object.entries(expected)) {
    const { result, calls } = await withFetch(() => json(Number(status), { code: status === "422" ? "MULTI_MACHINE_DISABLED" : "ERROR" }), () => api.createWorkOrderWithLines("MP1", LINES));
    assert.equal(result.ok, false);
    assert.equal(result.kind, kind, status);
    assert.equal(calls.length, 1, `status ${status}: exactly one request`);
  }
});

test("a 422 MULTI_MACHINE_DISABLED is just an error: the client has nothing to switch on", async () => {
  const { result } = await withFetch(() => json(422, { code: "MULTI_MACHINE_DISABLED" }), () => api.createWorkOrderWithLines("MP1", LINES));
  assert.equal(result.kind, "invalid");
  assert.equal(result.code, "MULTI_MACHINE_DISABLED");
  const caps = await import(pathToFileURL(join(root, "lib/vinto/work-order-capabilities.ts")).href);
  assert.equal(caps.parseCapabilities({ code: result.code, kind: result.kind }).multiMachine, false);
});

test("a malformed success body is rejected instead of half-parsed", async () => {
  const bad = { ...serverOrder(), baseline: { ...serverOrder().baseline, lines: [{ ...line(1, MP1), machine: "MP1" }] } };
  const { result } = await withFetch(() => json(201, bad), () => api.createWorkOrderWithLines("MP1", LINES));
  assert.equal(result.ok, false);
});

test("publishing and adding a line use the existing endpoints with their historical bodies", async () => {
  const published = await withFetch(() => json(200, order("published", MULTI_LINES)), () => api.publishWorkOrder("22222222-2222-4222-8222-222222222222"));
  assert.match(published.calls[0].url, /\/api\/work-orders\/22222222-2222-4222-8222-222222222222\/publish$/);
  assert.equal(published.calls[0].method, "POST");
  assert.equal(published.calls[0].body, undefined);
  const added = await withFetch(() => json(201, serverOrder()), () => api.addWorkOrderLine("22222222-2222-4222-8222-222222222222", { pvReference: "PV-9", articleCode: "A", quantity: 3, dueDate: "2026-10-30" }));
  assert.match(added.calls[0].url, /\/lines$/);
  assert.deepEqual(added.calls[0].body, { pv_reference: "PV-9", article_code: "A", quantity: 3, due_date: "2026-10-30" });
});

test("the traditional createWorkOrder call (one line, no machine per line) is unchanged", async () => {
  const { calls } = await withFetch(() => json(201, order("draft", [line(1, MP1)])), () => api.createWorkOrder("MP1", { pvReference: "PV-1", articleCode: "A", quantity: 10, dueDate: "2026-10-30" }));
  assert.deepEqual(calls[0].body, { machine_code: "MP1", lines: [{ pv_reference: "PV-1", article_code: "A", quantity: 10, due_date: "2026-10-30" }] });
});
