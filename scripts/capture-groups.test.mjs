// node --test scripts/capture-groups.test.mjs
// Grupos repetibles (M3-A), parte cliente: operaciones de filas, validación/normalización por fila, parser estricto de `_groups`, intento pendiente inmutable y los componentes
// visuales del kit renderizados con React real (sin navegador ni red). El formulario usado aquí es un EJEMPLO tipado y sintético; no es un formulario industrial.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

import { freezeAttempt, parseCaptureOf, submitAttemptOf } from "../lib/vinto/capture-core.ts";
import {
  GROUPS_KEY, TECHNICAL_MAX_GROUP_ROWS, addRow, buildGroupedValues, buildGroups, canAddRow, canRemoveRow, emptyRow, errorsFor, groupedValuesParser, initialDrafts, initialRows, parseGroups, removeRow, setCell, validateGroup,
} from "../lib/vinto/capture-groups.ts";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-capture-groups-test-${process.pid}`);
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
let kit, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  kit = await bundle("components/vinto/capture-kit.tsx", "kit");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

// ---- especificación tipada de ejemplo (SINTÉTICA) -------------------------------------------------------------------------------------------------
const DETALLE = { code: "detalle", label: "Detalle", repeatable: true, minRows: 1, maxRows: 3, fields: [
  { key: "item", label: "Ítem", kind: "text", required: true }, { key: "cantidad", label: "Cantidad", kind: "integer", required: true },
  { key: "peso", label: "Peso", kind: "decimal", required: false, unit: "kg" }, { key: "tipo", label: "Tipo", kind: "choice", required: false, options: [{ value: "a", label: "A" }, { value: "b", label: "B" }] },
] };
const EXTRAS = { code: "extras", label: "Extras", repeatable: true, minRows: 0, maxRows: null, fields: [{ key: "etiqueta", label: "Etiqueta", kind: "text", required: true }, { key: "valor", label: "Valor", kind: "decimal", required: false }] };
const UNICO = { code: "unico", label: "Único", repeatable: false, minRows: 0, maxRows: 1, fields: [{ key: "ref", label: "Referencia", kind: "text", required: true }] };
const SPECS = [DETALLE, EXTRAS, UNICO];
let n = 0;
const key = () => `k${++n}`;
const row = (cells, rowKey = key()) => ({ rowKey, cells });
const noop = () => {};
const html = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const DISABLED = /\sdisabled(=""|\s|>)/;
const tags = (markup, tag) => markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? [];
const code = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n").replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");

// ---- operaciones de filas ------------------------------------------------------------------------------------------------------------------------

test("rows: the initial state has as many empty rows as the declared minimum", () => {
  assert.equal(initialRows(DETALLE, key).length, 1);
  assert.equal(initialRows(EXTRAS, key).length, 0);
  const drafts = initialDrafts(SPECS, key);
  assert.deepEqual(Object.keys(drafts), ["detalle", "extras", "unico"]);
  assert.deepEqual(Object.keys(drafts.detalle[0].cells), ["item", "cantidad", "peso", "tipo"]);
});

test("rows: add respects the declared maximum and non-repeatable groups; remove respects the minimum", () => {
  let rows = initialRows(DETALLE, key);
  assert.equal(canAddRow(DETALLE, rows), true);
  rows = addRow(DETALLE, addRow(DETALLE, rows, key), key);
  assert.equal(rows.length, 3);
  assert.equal(canAddRow(DETALLE, rows), false); // max_rows = 3
  assert.equal(addRow(DETALLE, rows, key), rows); // unchanged: the very same list
  assert.equal(canRemoveRow(DETALLE, rows), true);
  const one = removeRow(DETALLE, removeRow(DETALLE, rows, rows[0].rowKey), rows[1].rowKey);
  assert.equal(one.length, 1);
  assert.equal(canRemoveRow(DETALLE, one), false); // min_rows = 1
  assert.equal(removeRow(DETALLE, one, one[0].rowKey), one);
  assert.equal(canAddRow(UNICO, addRow(UNICO, [], key)), false); // not repeatable: at most one
  assert.equal(canAddRow(EXTRAS, Array.from({ length: 500 }, () => row({}))), true); // no declared maximum: the client invents none
  assert.equal(canRemoveRow(EXTRAS, [row({})]), true);
  const cap = Array.from({ length: TECHNICAL_MAX_GROUP_ROWS }, () => row({ etiqueta: "e" }));
  assert.equal(canAddRow(EXTRAS, cap), false); // no declared maximum: only the TECHNICAL cap (1000) applies, so the UI cannot prepare an impossible capture
  assert.equal(addRow(EXTRAS, cap, key), cap);
  assert.equal(canAddRow(EXTRAS, cap.slice(1)), true);
});

test("rows: operations are immutable and keep the order of the remaining rows", () => {
  const a = row({ item: "A" }), b = row({ item: "B" }), c = row({ item: "C" });
  const original = Object.freeze([a, b, c]);
  const removed = removeRow(EXTRAS, original, b.rowKey);
  assert.deepEqual(removed.map((r) => r.cells.item), ["A", "C"]);
  assert.equal(original.length, 3);
  const edited = setCell(original, b.rowKey, "item", "B2");
  assert.equal(edited[1].cells.item, "B2");
  assert.equal(original[1].cells.item, "B"); // the previous list/row was not touched
  assert.deepEqual(edited.map((r) => r.rowKey), [a.rowKey, b.rowKey, c.rowKey]);
  assert.equal(emptyRow(DETALLE, () => "x").rowKey, "x");
});

// ---- validación y normalización --------------------------------------------------------------------------------------------------------------------

test("validation: types are normalized per field and only known keys are produced (no rowKey, no ids)", () => {
  const result = validateGroup(DETALLE, [row({ item: "  A ", cantidad: "007", peso: "1,50", tipo: "a" }), row({ item: "B", cantidad: "5", peso: "", tipo: "" })]);
  assert.equal(result.ok, true);
  assert.deepEqual(result.rows, [{ item: "A", cantidad: 7, peso: "1.50", tipo: "a" }, { item: "B", cantidad: 5 }]); // integer as number, decimal as TEXT with a dot, blanks omitted
  for (const r of result.rows) assert.equal(Object.keys(r).some((k) => /^(rowKey|row_number|id)$/.test(k)), false);
});

test("validation: required fields, types, options, empty rows and limits are reported with 1-based rows", () => {
  const bad = validateGroup(DETALLE, [row({ item: "A", cantidad: "doce" }), row({ item: "", cantidad: "" }), row({ item: "C", cantidad: "1", peso: "1e3", tipo: "z" })]);
  assert.equal(bad.ok, false);
  const at = (r, f) => bad.errors.filter((e) => e.row === r && e.field === f).map((e) => e.message);
  assert.deepEqual(at(1, "cantidad"), ["Cantidad: ingresa un número entero."]);
  assert.deepEqual(at(2, "item"), ["Ítem: es obligatorio."]);
  assert.deepEqual(at(2, "cantidad"), ["Cantidad: es obligatorio."]);
  assert.deepEqual(at(3, "peso"), ["Peso: ingresa un número decimal."]);
  assert.deepEqual(at(3, "tipo"), ["Tipo: selecciona una opción válida."]);
  assert.equal(validateGroup(DETALLE, []).errors[0].message, "Detalle: se requieren al menos 1 filas.");
  assert.equal(validateGroup(DETALLE, Array.from({ length: 4 }, () => row({ item: "A", cantidad: "1" }))).errors[0].message, "Detalle: máximo 3 filas.");
  assert.equal(validateGroup(UNICO, [row({ ref: "a" }), row({ ref: "b" })]).errors[0].message, "Único: máximo 1 filas.");
  assert.equal(validateGroup(EXTRAS, []).ok, true); // zero rows where the minimum is zero
  const over = validateGroup(EXTRAS, Array.from({ length: TECHNICAL_MAX_GROUP_ROWS + 1 }, () => row({ etiqueta: "e" })));
  assert.equal(over.errors[0].message, "Extras: máximo 1000 filas (límite técnico del sistema).");  // identified as a technical limit, not an industrial one
  assert.equal(validateGroup(DETALLE, Array.from({ length: 4 }, () => row({ item: "A", cantidad: "1" }))).errors[0].message, "Detalle: máximo 3 filas."); // a declared maximum keeps its own message
  const optional = { code: "g", label: "G", repeatable: true, minRows: 0, maxRows: null, fields: [{ key: "x", label: "X", kind: "text", required: false }] };
  assert.equal(validateGroup(optional, [row({ x: "  " })]).errors[0].message, "La fila no tiene valores.");
});

test("buildGroups / buildGroupedValues: every declared group, rows in order, simple fields untouched", () => {
  const drafts = { detalle: [row({ item: "A", cantidad: "1" }), row({ item: "B", cantidad: "2" })], extras: [], unico: [row({ ref: "r" })] };
  const built = buildGroups(SPECS, drafts);
  assert.equal(built.ok, true);
  assert.deepEqual(built.groups, { detalle: [{ item: "A", cantidad: 1 }, { item: "B", cantidad: 2 }], extras: [], unico: [{ ref: "r" }] });
  assert.deepEqual(buildGroupedValues({ lote: "L" }, built.groups), { lote: "L", [GROUPS_KEY]: built.groups });
  const reversed = buildGroups(SPECS, { ...drafts, detalle: [...drafts.detalle].reverse() });
  assert.deepEqual(reversed.groups.detalle.map((r) => r.item), ["B", "A"]); // order is content
  const failed = buildGroups(SPECS, { ...drafts, detalle: [] });
  assert.equal(failed.ok, false);
  assert.deepEqual(errorsFor(failed.errors, "detalle", null), ["Detalle: se requieren al menos 1 filas."]);
});

// ---- lectura estricta ---------------------------------------------------------------------------------------------------------------------------------

test("parseGroups accepts only the declared groups, rows and typed cells", () => {
  const good = { detalle: [{ item: "A", cantidad: 2, peso: "1.50", tipo: "a" }], extras: [], unico: [] };
  assert.deepEqual(parseGroups(SPECS, good), good);
  assert.deepEqual(parseGroups(SPECS, { detalle: [{ item: "A", cantidad: 2, peso: 1.5 }], extras: [], unico: [] }).detalle[0].peso, "1.5"); // a finite JSON number is normalized to text
  for (const bad of [null, [], "x", { ...good, inventado: [] }, { detalle: good.detalle, extras: [] }, { ...good, detalle: {} }, { ...good, detalle: ["x"] },
    { ...good, detalle: [{ item: "A", cantidad: 2, id: "x" }] }, { ...good, detalle: [{ item: "A" }] }, { ...good, detalle: [{ item: "A", cantidad: "2" }] },
    { ...good, detalle: [{ item: "A", cantidad: 2, tipo: "z" }] }, { ...good, detalle: [{}] }, { ...good, extras: [{ etiqueta: "" }] }]) assert.equal(parseGroups(SPECS, bad), null, JSON.stringify(bad));
});

const parseSimple = (v) => (isRecord(v) && typeof v.lote === "string" && v.lote ? { lote: v.lote, ...(typeof v.nota === "string" ? { nota: v.nota } : {}) } : null);
const isRecord = (v) => typeof v === "object" && v !== null && !Array.isArray(v);
const envelope = (id, formCode, values) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "F" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "44444444-4444-4444-8444-444444444444" },
  work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-1" }, line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-1", article: { code: "A", description: "B" } }, values,
});
const ID = "11111111-1111-4111-8111-111111111111";

test("parseGroups verifies the declared cardinality of every group when reading a response", () => {
  const one = { item: "A", cantidad: 1 };
  const base = { detalle: [one], extras: [], unico: [] };
  assert.notEqual(parseGroups(SPECS, base), null);
  assert.equal(parseGroups(SPECS, { ...base, detalle: [] }), null); // min_rows = 1
  assert.notEqual(parseGroups(SPECS, { ...base, detalle: [one, one, one] }), null); // max_rows = 3
  assert.equal(parseGroups(SPECS, { ...base, detalle: [one, one, one, one] }), null);
  assert.equal(parseGroups(SPECS, { ...base, unico: [{ ref: "a" }, { ref: "b" }] }), null); // not repeatable
  assert.notEqual(parseGroups(SPECS, { ...base, extras: Array.from({ length: TECHNICAL_MAX_GROUP_ROWS }, () => ({ etiqueta: "e" })) }), null);
  assert.equal(parseGroups(SPECS, { ...base, extras: Array.from({ length: TECHNICAL_MAX_GROUP_ROWS + 1 }, () => ({ etiqueta: "e" })) }), null); // the technical cap also applies on reads
});

test("a grouped capture is parsed with the form's simple parser + groups and rejected if either part fails", () => {
  const parse = (value) => parseCaptureOf(value, groupedValuesParser(parseSimple, SPECS), "VINTO-TEST-GRP-1");
  const values = { lote: "L", [GROUPS_KEY]: { detalle: [{ item: "A", cantidad: 1 }], extras: [], unico: [] } };
  assert.deepEqual(parse(envelope(ID, "VINTO-TEST-GRP-1", values)).values, values);
  assert.equal(parse(envelope(ID, "VINTO-P1-06", values)), null); // another form code
  assert.equal(parse(envelope(ID, "VINTO-TEST-GRP-1", { ...values, lote: "" })), null); // simple part invalid
  assert.equal(parse(envelope(ID, "VINTO-TEST-GRP-1", { lote: "L" })), null); // groups missing
  assert.equal(parse(envelope(ID, "VINTO-TEST-GRP-1", { ...values, [GROUPS_KEY]: { ...values[GROUPS_KEY], detalle: [{ item: "A", cantidad: "1" }] } })), null);
});

// ---- intento pendiente inmutable --------------------------------------------------------------------------------------------------------------------------

test("adding, removing or editing rows afterwards never changes an already created attempt", () => {
  const drafts = { detalle: [row({ item: "A", cantidad: "1" }), row({ item: "B", cantidad: "2" })], extras: [], unico: [] };
  const built = buildGroups(SPECS, drafts);
  const payload = { capture_id: ID, form_code: "VINTO-TEST-GRP-1", assignment_id: "44444444-4444-4444-8444-444444444444", device_key: "99999999-9999-4999-8999-999999999999", values: buildGroupedValues({ lote: "L" }, built.groups) };
  const attempt = freezeAttempt(payload, { simple: { lote: "L" }, groups: drafts });
  const snapshot = JSON.stringify(attempt);
  // the screen state moves on: a row is added, one removed, a cell edited
  const next = setCell(addRow(DETALLE, removeRow(DETALLE, drafts.detalle, drafts.detalle[0].rowKey), key), drafts.detalle[1].rowKey, "item", "CAMBIADO");
  assert.equal(next.length, 2);
  payload.values._groups.detalle.push({ item: "extra", cantidad: 9 }); // even mutating the ORIGINAL objects must not leak into the attempt
  drafts.detalle[0].cells.item = "MUTADO";
  assert.equal(JSON.stringify(attempt), snapshot);
  assert.equal(attempt.payload.values._groups.detalle.length, 2);
  assert.equal(attempt.draft.groups.detalle[0].cells.item, "A");
  assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.payload.values._groups) && Object.isFrozen(attempt.payload.values._groups.detalle) && Object.isFrozen(attempt.payload.values._groups.detalle[0]) && Object.isFrozen(attempt.draft.groups.detalle[0].cells));
  assert.throws(() => { "use strict"; attempt.payload.values._groups.detalle.push({}); }, TypeError);
  assert.throws(() => { "use strict"; attempt.payload.values._groups.detalle[0].cantidad = 5; }, TypeError);
});

test("a retry sends the very same grouped payload (same capture id, same rows in the same order)", async () => {
  const built = buildGroups(SPECS, { detalle: [row({ item: "A", cantidad: "1" }), row({ item: "B", cantidad: "2" })], extras: [], unico: [] });
  const attempt = freezeAttempt({ capture_id: ID, form_code: "VINTO-TEST-GRP-1", assignment_id: "a", device_key: "d", values: buildGroupedValues({ lote: "L" }, built.groups) }, {});
  const sent = [];
  const parse = (v) => parseCaptureOf(v, groupedValuesParser(parseSimple, SPECS), "VINTO-TEST-GRP-1");
  const capture = parse(envelope(ID, "VINTO-TEST-GRP-1", attempt.payload.values));
  const first = await submitAttemptOf(attempt, { post: async (p) => (sent.push(p), { ok: false, kind: "unavailable", status: 0 }), get: async () => ({ ok: false, kind: "n", status: 404 }) });
  assert.equal(first.kind, "not_saved");
  const retry = await submitAttemptOf(attempt, { post: async (p) => (sent.push(p), { ok: true, status: 201, data: { created: true, already_submitted: false, capture } }), get: async () => { throw new Error("no GET"); } });
  assert.equal(retry.kind, "submitted");
  assert.equal(sent[0], sent[1]);
  assert.deepEqual(retry.capture.values._groups.detalle.map((r) => r.item), ["A", "B"]); // the rows come back in order
});

// ---- componentes visuales -------------------------------------------------------------------------------------------------------------------------------

function Example({ drafts = { detalle: [row({ item: "A", cantidad: "1" }), row({ item: "B", cantidad: "2" })] }, errors = [], disabled = false, spec = DETALLE }) {
  const rows = drafts.detalle;
  return React.createElement(kit.RepeatableGroup, {
    title: spec.label, hint: "Ejemplo tipado", rows: rows.map((r, i) => ({ key: r.rowKey, errors: errorsFor(errors, spec.code, i + 1) })), minRows: spec.minRows, maxRows: spec.maxRows,
    canAdd: canAddRow(spec, rows), canRemove: canRemoveRow(spec, rows), disabled, groupErrors: errorsFor(errors, spec.code, null), onAdd: noop, onRemove: noop,
    renderRow: (i) => [React.createElement(kit.TextField, { key: "item", label: "Ítem", required: true, value: rows[i].cells.item ?? "", onChange: noop, disabled }),
      React.createElement(kit.TextField, { key: "cantidad", label: "Cantidad", required: true, inputMode: "numeric", value: rows[i].cells.cantidad ?? "", onChange: noop, disabled })],
  });
}

test("group component: header, counter and numbered rows in order with their fields", () => {
  const markup = html(Example, {});
  const plain = text(markup);
  assert.ok(plain.includes("Detalle") && plain.includes("Ejemplo tipado") && plain.includes("2 filas · mínimo 1, máximo 3"));
  assert.ok(plain.indexOf("Fila 1") < plain.indexOf("Fila 2"));
  assert.equal((markup.match(/data-row="/g) ?? []).length, 2);
  assert.ok(plain.includes("Ítem *") && plain.includes("Cantidad *"));
  assert.match(markup, /value="A"/);
  assert.match(markup, /aria-label="Eliminar fila 1 de Detalle"/);
  assert.match(markup, /aria-label="Eliminar fila 2 de Detalle"/);
  assert.ok(plain.includes("Agregar fila"));
});

test("group component: add/remove controls follow the declared limits and the disabled state", () => {
  const three = { detalle: [row({}), row({}), row({})] };
  const atMax = html(Example, { drafts: three });
  assert.ok(tags(atMax, "button").find((t) => /Agregar|^<button/.test(t) && DISABLED.test(t))); // add disabled at the maximum (max_rows = 3)
  const addBtn = (markup) => text(markup).includes("Agregar fila") && tags(markup, "button")[0];
  assert.ok(DISABLED.test(addBtn(atMax)));
  assert.equal(DISABLED.test(addBtn(html(Example, {}))), false);
  const atMin = html(Example, { drafts: { detalle: [row({ item: "A" })] } });
  assert.ok(DISABLED.test(tags(atMin, "button").find((t) => t.includes('aria-label="Eliminar fila 1'))), "remove disabled at the minimum (min_rows = 1)");
  const locked = html(Example, { disabled: true });
  assert.ok(tags(locked, "button").every((t) => DISABLED.test(t)));
  assert.equal(tags(locked, "input").every((t) => DISABLED.test(t)), true);
  assert.ok(text(html(Example, { drafts: { detalle: [] }, spec: EXTRAS })).includes("Sin filas."));
  assert.ok(text(html(Example, { drafts: { detalle: [] }, spec: EXTRAS })).includes("0 filas · sin mínimo"));
});

test("group component: group and row errors are associated to their group and row", () => {
  const errors = [{ group: "detalle", row: null, message: "Detalle: se requieren al menos 1 filas." }, { group: "detalle", row: 2, field: "item", message: "Ítem: es obligatorio." }];
  const markup = html(Example, { errors });
  assert.equal((markup.match(/role="alert"/g) ?? []).length, 2);
  const second = markup.slice(markup.indexOf('data-row="2"'));
  assert.ok(text(second).includes("Ítem: es obligatorio."));
  assert.equal(text(markup.slice(markup.indexOf('data-row="1"'), markup.indexOf('data-row="2"'))).includes("es obligatorio"), false);
  assert.ok(text(markup).includes("Detalle: se requieren al menos 1 filas."));
});

test("group component is mobile-first and free of business logic, network and storage", () => {
  const source = code("components/vinto/capture-kit.tsx");
  assert.equal(/(?:min-|max-)?w-\[\d+px\]/.test(source), false);
  assert.equal(/fetch\(|localStorage|sessionStorage|captures-api|central-http|requestJson|document\.cookie/.test(source), false);
  assert.ok(source.includes("md:grid-cols-2"));
  const lib = code("lib/vinto/capture-groups.ts");
  assert.equal(/fetch\(|localStorage|sessionStorage|document\.cookie|Authorization|requestJson/.test(lib), false);
  for (const dir of ["app/qa-harness", "app/groups", "app/e2e"]) assert.equal(existsSync(join(root, dir)), false, dir); // no public route for the example
});
