// node --test scripts/pr6-order-draft.test.mjs
// MF-13-03B PR6: pruebas PURAS de la creación de OT multimáquina en la interfaz de Jefatura: parseo de la máquina por línea (y compatibilidad con OT antiguas), payload de UNA sola solicitud,
// borrador local (agregar, retirar, cambiar máquina/producto, validaciones), capacidades confirmadas por el servidor y guarda de escritura (doble envío, respuestas tardías).
import assert from "node:assert/strict";
import test from "node:test";

import { MAX_ORDER_LINES, addLinePayload, createWorkOrderLinesPayload, createWorkOrderPayload, lineBody, parseAssignment, parseLine, parseWorkOrder, parseWorkOrderList, toDisplayOt } from "../lib/vinto/orders.ts";
import { addRow, emptyRow, isRealDate, removeRow, setField, setMachine, summarize, summaryText, validateRows } from "../lib/vinto/order-draft.ts";
import { NO_CAPABILITIES, multiMachineOffered, parseCapabilities } from "../lib/vinto/work-order-capabilities.ts";
import { createMutationGuard, runGuarded } from "../lib/vinto/mutation-guard.ts";

const MP1 = { code: "MP1", name: "MP1" }, MP3 = { code: "MP3", name: "MP3" };
const line = (n, machine, overrides = {}) => ({
  id: `00000000-0000-4000-8000-00000000000${n}`, line_code: `L${n}`, pv_reference: `PV-${n}`, machine,
  article: { code: `ART-${n}`, description: `Producto ${n}` }, quantity: 10 * n, unit: "KG", due_date: "2026-10-30", ...overrides,
});
const order = (lines, overrides = {}) => ({
  id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0003", status: "draft", machine: MP1,
  baseline: { id: "33333333-3333-4333-8333-333333333333", version_number: 1, published_at: null, lines }, ...overrides,
});
const CATALOG = { MP1: [{ code: "A" }, { code: "B" }], MP3: [{ code: "C" }, { code: "A" }] };
const catalog = (machine) => CATALOG[machine] ?? [];
const MACHINES = ["MP1", "MP3"];
const row = (key, machine, code, extra = {}) => ({ key, machine, pv: `PV-${key}`, code, qty: "10", date: "2026-10-30", ...extra });
const three = () => [row("a", "MP1", "A"), row("b", "MP1", "B"), row("c", "MP3", "C")];

// ---- 1. parseo: la máquina de cada línea se conserva ----------------------------------------------------------------------------------------------------------------

test("a PR2 work order keeps the machine of EVERY line and the header machine", () => {
  const parsed = parseWorkOrder(order([line(1, MP1), line(2, MP1), line(3, MP3)]));
  assert.deepEqual(parsed.baseline.lines.map((l) => l.machine.code), ["MP1", "MP1", "MP3"]);
  assert.equal(parsed.machine.code, "MP1");
  assert.deepEqual(parsed.baseline.lines[2].machine, { code: "MP3", name: "MP3" });
  assert.ok(!("machine" in toDisplayOt(parsed).lines[0]), "the Seguimiento adapter keeps its historical shape");
});

test("an OLD work order (lines without machine) falls back to the header machine instead of being rejected", () => {
  const legacy = order([line(1, undefined), line(2, undefined)].map(({ machine, ...rest }) => rest));
  const parsed = parseWorkOrder(legacy);
  assert.ok(parsed, "the old contract still parses");
  assert.deepEqual(parsed.baseline.lines.map((l) => l.machine.code), ["MP1", "MP1"]);
  assert.equal(parseWorkOrderList([legacy, order([line(1, MP3)], { machine: MP3 })]).length, 2);
});

test("a machine that is present must be valid: it is never dropped or replaced", () => {
  for (const machine of [null, "MP3", { code: "", name: "x" }, { code: "MP3" }, [], 7]) assert.equal(parseWorkOrder(order([line(1, machine)])), null, JSON.stringify(machine));
  assert.equal(parseLine(line(1, MP3)).machine.code, "MP3");
  assert.equal(parseLine((({ machine, ...rest }) => rest)(line(1, MP3))), null, "without a fallback a bare line has no machine");
});

test("the line of an assignment takes the machine of the assignment (its line has no machine key)", () => {
  const bare = (({ machine, ...rest }) => rest)(line(1, MP1));
  const assignment = { id: "44444444-4444-4444-8444-444444444444", status: "active", operating_date: "2026-10-06", created_at: "2026-10-06T16:00:00Z", finished_at: null,
    machine: MP3, shift: { code: "DIA", name: "Día" }, work_order: { id: order([]).id, number: "OT-2026-0003" }, operational: { version_number: 2 }, line: bare,
    assigned_by: { id: "66666666-6666-4666-8666-666666666666", display_name: "Supervisión" } };
  assert.equal(parseAssignment(assignment).line.machine.code, "MP3");
});

// ---- 2. payloads ----------------------------------------------------------------------------------------------------------------------------------------------------

test("a line without machineCode produces exactly the historical body (old clients and servers are unaffected)", () => {
  assert.deepEqual(lineBody({ pvReference: " PV-1 ", articleCode: "A", quantity: 5, dueDate: "2026-10-30" }), { pv_reference: "PV-1", article_code: "A", quantity: 5, due_date: "2026-10-30" });
  assert.deepEqual(addLinePayload({ pvReference: "PV-1", articleCode: "A", quantity: 5, dueDate: "2026-10-30" }), { pv_reference: "PV-1", article_code: "A", quantity: 5, due_date: "2026-10-30" });
  assert.deepEqual(createWorkOrderPayload("MP1", { pvReference: "PV-1", articleCode: "A", quantity: 5, dueDate: "2026-10-30" }), { machine_code: "MP1", lines: [{ pv_reference: "PV-1", article_code: "A", quantity: 5, due_date: "2026-10-30" }] });
});

test("the multi-machine payload is ONE request with the machine code on every line, in the order of the draft", () => {
  const checked = validateRows(three(), { multi: true, machines: MACHINES, catalog });
  assert.ok(checked.ok);
  const payload = createWorkOrderLinesPayload(checked.machineCode, checked.lines);
  assert.equal(payload.machine_code, "MP1", "the first machine is the legacy header machine");
  assert.deepEqual(payload.lines.map((l) => [l.machine_code, l.article_code]), [["MP1", "A"], ["MP1", "B"], ["MP3", "C"]]);
  assert.deepEqual(Object.keys(payload).sort(), ["lines", "machine_code"]);
});

test("the payload never carries identifiers, numbers, line codes, units or versions: those belong to the server", () => {
  const checked = validateRows(three(), { multi: true, machines: MACHINES, catalog });
  const text = JSON.stringify(createWorkOrderLinesPayload(checked.machineCode, checked.lines));
  for (const forbidden of ["machine_id", "number", "line_code", "unit", "version", "work_order", "id\":", "status", "operational", "description"]) assert.ok(!text.includes(forbidden), forbidden);
  for (const l of createWorkOrderLinesPayload("MP1", checked.lines).lines) assert.deepEqual(Object.keys(l).sort(), ["article_code", "due_date", "machine_code", "pv_reference", "quantity"]);
});

test("single-machine mode sends the historical payload even with several rows (no machine_code per line)", () => {
  const rows = [row("a", "MP1", "A"), row("b", "MP1", "B")];
  const checked = validateRows(rows, { multi: false, machines: MACHINES, catalog });
  assert.ok(checked.ok);
  assert.equal(checked.machineCode, "MP1");
  assert.ok(createWorkOrderLinesPayload(checked.machineCode, checked.lines).lines.every((l) => !("machine_code" in l)));
});

// ---- 3. borrador local ----------------------------------------------------------------------------------------------------------------------------------------------

test("three local rows MP1/MP1/MP3 validate in multi mode and keep their order", () => {
  const checked = validateRows(three(), { multi: true, machines: MACHINES, catalog });
  assert.ok(checked.ok);
  assert.deepEqual(checked.lines.map((l) => [l.machineCode, l.articleCode, l.pvReference]), [["MP1", "A", "PV-a"], ["MP1", "B", "PV-b"], ["MP3", "C", "PV-c"]]);
  assert.deepEqual(summarize(three()), { lines: 3, machines: ["MP1", "MP3"], products: ["A", "B", "C"], perMachine: { MP1: 2, MP3: 1 } });
  assert.equal(summaryText(summarize(three())), "3 línea(s) · 2 máquina(s): MP1, MP3 · 3 producto(s)");
});

test("removing an unsaved row only changes the local draft (and never leaves it empty)", () => {
  const rows = three();
  const next = removeRow(rows, "b");
  assert.deepEqual(next.map((r) => r.key), ["a", "c"]);
  assert.equal(rows.length, 3, "the original array is not mutated");
  assert.deepEqual(removeRow([row("a", "MP1", "A")], "a").map((r) => r.key), ["a"]);
});

test("adding rows: multi inherits the last machine, single the first, and the backend maximum is respected", () => {
  assert.equal(addRow(three(), "d", true).at(-1).machine, "MP3");
  assert.equal(addRow(three(), "d", false).at(-1).machine, "MP1");
  const full = Array.from({ length: MAX_ORDER_LINES }, (_, i) => emptyRow(`k${i}`, "MP1"));
  assert.equal(addRow(full, "x", true).length, MAX_ORDER_LINES);
  assert.equal(MAX_ORDER_LINES, 200);
  assert.equal(validateRows([...full, emptyRow("y", "MP1")], { multi: true, machines: MACHINES, catalog }).ok, false);
});

test("changing a row's machine invalidates a product that no longer belongs to it, and keeps one that still does", () => {
  const rows = [row("a", "MP1", "B"), row("b", "MP1", "A")];
  const moved = setMachine(rows, "a", "MP3", catalog, true);
  assert.equal(moved[0].machine, "MP3");
  assert.equal(moved[0].code, "", "B is not offered for MP3");
  assert.equal(setMachine(rows, "b", "MP3", catalog, true)[1].code, "A", "A is offered for both machines");
  assert.equal(moved[1].machine, "MP1", "only that row changes in multi mode");
  const single = setMachine(rows, "a", "MP3", catalog, false);
  assert.deepEqual(single.map((r) => [r.machine, r.code]), [["MP3", ""], ["MP3", "A"]], "single mode moves the whole draft to the chosen machine");
});

test("changing the product of a row only changes that row", () => {
  const rows = setField(three(), "b", "code", "A");
  assert.deepEqual(rows.map((r) => r.code), ["A", "A", "C"]);
});

test("quantity, date, PV, product and machine are validated per row", () => {
  const check = (patch) => validateRows([row("a", "MP1", "A", patch)], { multi: true, machines: MACHINES, catalog });
  for (const qty of ["", "0", "-1", "abc", "1e3", "1,5", "1.2345", "1234567890123", " "]) assert.equal(check({ qty }).ok, false, `qty ${JSON.stringify(qty)}`);
  for (const qty of ["1", "0.001", "12.5", "999999999999.999", " 7 "]) assert.equal(check({ qty }).ok, true, `qty ${JSON.stringify(qty)}`);
  for (const date of ["", "2026-02-30", "2026-13-01", "30/10/2026", "2026-1-1"]) assert.equal(check({ date }).ok, false, `date ${date}`);
  assert.equal(check({ date: "2028-02-29" }).ok, true);
  assert.equal(isRealDate("2026-02-29"), false);
  assert.equal(check({ pv: "   " }).ok, false);
  assert.equal(check({ pv: "x".repeat(101) }).ok, false);
  assert.equal(check({ pv: "x".repeat(100) }).ok, true);
  assert.equal(check({ code: "ZZZ" }).ok, false, "a product that the machine does not offer");
  assert.equal(check({ machine: "RB1" }).ok, false, "a machine outside the offered list");
  const failed = check({ qty: "0", pv: "" });
  assert.deepEqual(failed.errors.map((e) => e.field).sort(), ["pv", "qty"]);
});

test("single-machine mode rejects a draft whose rows mix machines", () => {
  const checked = validateRows(three(), { multi: false, machines: MACHINES, catalog });
  assert.equal(checked.ok, false);
  assert.deepEqual(checked.errors.map((e) => [e.key, e.field]), [["c", "machine"]]);
  assert.equal(validateRows([], { multi: true, machines: MACHINES, catalog }).ok, false);
});

// ---- 4. capacidades confirmadas por el servidor ---------------------------------------------------------------------------------------------------------------------

test("multi-machine creation is off unless the server says exactly true", () => {
  assert.equal(NO_CAPABILITIES.multiMachine, false);
  assert.equal(Object.isFrozen(NO_CAPABILITIES), true);
  assert.equal(parseCapabilities({ multi_machine: true }).multiMachine, true);
  for (const value of [undefined, null, {}, [], "true", 1, { multi_machine: "true" }, { multi_machine: 1 }, { multi_machine: false }, { multiMachine: true }, { detail: "MULTI_MACHINE_DISABLED" }]) {
    assert.equal(parseCapabilities(value).multiMachine, false, JSON.stringify(value));
  }
});

test("the multi-machine form is offered only with server confirmation, permission to manage and more than one machine", () => {
  const on = parseCapabilities({ multi_machine: true });
  assert.equal(multiMachineOffered(on, true, 2), true);
  assert.equal(multiMachineOffered(on, false, 2), false, "Supervisión / Operación never");
  assert.equal(multiMachineOffered(on, true, 1), false);
  assert.equal(multiMachineOffered(NO_CAPABILITIES, true, 5), false, "no confirmation, no multi-machine");
});

test("the interface has no purely visual switch for the feature (no NEXT_PUBLIC flag, no 422-driven toggle)", async () => {
  const { readFileSync } = await import("node:fs");
  const sources = ["lib/vinto/work-order-capabilities.ts", "components/vinto/bobinas-programming.tsx", "components/vinto/bobinas-programming-source.tsx", "components/vinto/order-draft-editor.tsx"]
    .map((file) => readFileSync(new URL(`../${file}`, import.meta.url), "utf8")).join("\n");
  assert.ok(!/NEXT_PUBLIC/.test(sources.replace(/\/\/.*$/gm, "")), "no compiled flag");
  assert.ok(!/MULTI_MACHINE_DISABLED|status === 422|kind === "invalid"/.test(sources.replace(/\/\/.*$/gm, "")), "an error never enables anything");
  assert.ok(!/localStorage|sessionStorage/.test(sources), "the draft is never stored in the browser");
});

// ---- 5. escritura única, doble envío y respuestas tardías ---------------------------------------------------------------------------------------------------------

const handlers = (log) => ({ onStart: () => log.push("start"), onOk: (d) => log.push(`ok:${d}`), onSession: () => log.push("session"), onFailure: (k) => log.push(`fail:${k}`), onSettled: () => log.push("settled") });
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };

test("a double submit sends ONE write: the second call is skipped while the first is pending", async () => {
  const guard = createMutationGuard(), log = [], pending = deferred();
  let sent = 0;
  const action = () => { sent += 1; return pending.promise; };
  const first = runGuarded(guard, action, handlers(log));
  assert.equal(await runGuarded(guard, action, handlers(log)), "skipped");
  pending.resolve({ ok: true, data: "OT-1" });
  assert.equal(await first, "ok");
  assert.equal(sent, 1);
  assert.deepEqual(log, ["start", "ok:OT-1", "settled"]);
  assert.equal(await runGuarded(guard, () => Promise.resolve({ ok: true, data: "OT-2" }), handlers([])), "ok", "a new write is possible once the first finished");
});

test("a late response (screen unmounted or session changed) changes nothing", async () => {
  const guard = createMutationGuard(), log = [], pending = deferred();
  const run = runGuarded(guard, () => pending.promise, handlers(log));
  guard.reset();
  pending.resolve({ ok: true, data: "OT-1" });
  assert.equal(await run, "stale");
  assert.deepEqual(log, ["start"], "no draft reset, no toast, no refresh, no state update");
  const failing = deferred(), log2 = [];
  const run2 = runGuarded(guard, () => failing.promise, handlers(log2));
  guard.reset();
  failing.resolve({ ok: false, kind: "conflict" });
  assert.equal(await run2, "stale");
  assert.deepEqual(log2, ["start"]);
});

test("errors keep the draft: every failure kind is reported once and a 401 goes to the session handler", async () => {
  for (const kind of ["forbidden", "not_found", "conflict", "invalid", "unavailable"]) {
    const log = [];
    assert.equal(await runGuarded(createMutationGuard(), () => Promise.resolve({ ok: false, kind }), handlers(log)), "failure");
    assert.deepEqual(log, ["start", `fail:${kind}`, "settled"], kind);
  }
  const log = [];
  assert.equal(await runGuarded(createMutationGuard(), () => Promise.resolve({ ok: false, kind: "session" }), handlers(log)), "session");
  assert.deepEqual(log, ["start", "session", "settled"]);
  const thrown = [];
  assert.equal(await runGuarded(createMutationGuard(), () => Promise.reject(new Error("network")), handlers(thrown)), "failure");
  assert.deepEqual(thrown, ["start", "fail:unavailable", "settled"]);
});

test("a failed write releases the guard so the user can retry", async () => {
  const guard = createMutationGuard();
  await runGuarded(guard, () => Promise.resolve({ ok: false, kind: "invalid" }), handlers([]));
  assert.equal(guard.busy(), false);
  assert.equal(await runGuarded(guard, () => Promise.resolve({ ok: true, data: "x" }), handlers([])), "ok");
});
