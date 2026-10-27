// node --test scripts/mf10-rebobinado-conversion.test.mjs
// MF-10 · pantallas reales de Rebobinado y Conversión (React + react-dom/server, sin navegador ni red): P1-07 «bobinas rebobinadas» con horas, P1-30 con Lote y sin gramaje / resistencias / MRP, P1-12 con «Formato» de texto libre y
// el historial por versión de las fichas genéricas. P1-10 y P1-29 se prueban en sus propios archivos (p1-10-capture / p1-29-capture). Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal
// dentro del repositorio que se borra al terminar.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").split(String.fromCharCode(92)).join("/");
const workDir = join(root, `.tmp-mf10-${process.pid}`);
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

let React, server, ui;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  const rel = `.tmp-mf10-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { CandidateHistory } from "@/components/vinto/candidate-history";',
    'export { REBOBINADO_CANDIDATES } from "@/lib/vinto/rebobinado-candidates";',
    'export { CONVERSION_CANDIDATES } from "@/lib/vinto/conversion-candidates";',
    'export { P107, P1_07_CODE } from "@/lib/vinto/p1-07";', 'export { P130, P1_30_CODE } from "@/lib/vinto/p1-30";', 'export { P112, P1_12_CODE, P112_FIELDS } from "@/lib/vinto/p1-12";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const CONTEXT = (machine) => ({ assignmentId: "44444444-4444-4444-8444-444444444444", workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1024", productName: "BOBINA 1024", machine, shift: "Día", date: "2026-10-06" });
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const count = (html, text) => html.split(text).length - 1;
const screen = (candidate, machine) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate, context: CONTEXT(machine), online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));

test("P1-07: el formulario de producción se llama «bobinas rebobinadas» y muestra Hora inicio y Hora fin obligatorias (campos de hora) sin cambiar los demás campos", () => {
  for (const machine of ["COPASA", "BELOIT", "OVER"]) {
    const html = screen(ui.REBOBINADO_CANDIDATES.p107, machine), text = textOf(html);
    assert.match(html, /<h1[^>]*>Registro de producción de bobinas rebobinadas<\/h1>/, machine);
    assert.equal(text.includes("bobinas refiladas"), false, `${machine}: el título de producción ya no dice «refiladas»`);
    assert.ok(text.includes("Hora inicio *") && text.includes("Hora fin *"));
    assert.equal(count(html, 'type="time"'), 2);
    assert.ok(text.indexOf("Hora inicio *") < text.indexOf("Etiqueta / número de bobina *"), "las horas abren el formulario");
    assert.equal(count(html, "<input"), 2 + 36 - 1, "36 campos manuales (35 inputs + 1 textarea) + las dos horas");
    assert.ok(text.includes("Peso cría 22 *") && !text.includes("Peso cría 12"));
  }
});

test("P1-30: sin Gramaje, Resistencias ni Número MRP; Lote obligatorio donde estaba la resistencia longitudinal y las horas obligatorias", () => {
  const html = screen(ui.REBOBINADO_CANDIDATES.p130, "PERICHUN"), text = textOf(html);
  const form = text.slice(text.indexOf("Hora inicio *"));
  for (const gone of ["Gramaje g/m² *", "Resistencia longitudinal *", "Resistencia transversal *", "Número MRP *"]) assert.equal(form.includes(gone), false, gone);
  const order = ["Hora inicio *", "Hora fin *", "Número de bobina *", "Peso de bobina *", "Formato MP1 *", "Formato de salida *", "Lote *", "Velocidad *"].map((l) => form.indexOf(l));
  assert.ok(order.every((n) => n >= 0), "todos los campos están");
  assert.deepEqual([...order].sort((a, b) => a - b), order, "Lote entre Formato de salida y Velocidad; horas primero");
  assert.equal(count(html, 'type="time"'), 2);
  assert.match(html, /<h1[^>]*>Producción Perichun<\/h1>/);
});

test("P1-12: «Formato» es texto libre y se conserva exactamente (4*12, 4X12, 4x12, 4.12); las demás reglas no cambian", () => {
  const { P112, P112_FIELDS } = ui;
  const formato = P112_FIELDS.find((f) => f.key === "formato");
  assert.deepEqual({ ...formato }, { key: "formato", label: "Formato", kind: "text", required: true });
  assert.equal(P112_FIELDS.length, 20);
  const draft = Object.fromEntries(P112_FIELDS.map((f) => [f.key, "x"]));
  for (const typed of ["4*12", "4X12", "4x12", "4.12", "4,12", "12 x 4"]) assert.equal(P112.normalizeDraft({ ...draft, formato: typed }).values.formato, typed, "sin normalizar mayúsculas, símbolos ni coma");
  assert.match(P112.normalizeDraft({ ...draft, formato: "  " }).errors.join(" "), /Formato: es obligatorio/);
  const html = screen(ui.CONVERSION_CANDIDATES.p112, "GAMBINI");
  assert.ok(textOf(html).includes("Formato *"));
  const envelope = (version, values) => ({ id: "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.P1_12_CODE, version_number: version, name: "x" },
    machine: { code: "GAMBINI", name: "Gambini" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" }, line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });
  const base = Object.fromEntries(P112_FIELDS.map((f) => [f.key, "x"]));
  assert.equal(P112.parseCapture(envelope(1, { ...base, formato: "4.12" }))?.values.formato, "4.12", "la captura histórica con formato decimal se lee sin conversión");
  assert.equal(P112.parseCapture(envelope(2, { ...base, formato: "4*12" }))?.values.formato, "4*12");
});

const row = (code, version, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code, version_number: version, name: "x" },
  machine: { code: "PERICHUN", name: "Perichun" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" },
  line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });

test("historial de P1-30: la versión 1 muestra gramaje, resistencias y número MRP como «versión anterior»; la versión 2 muestra Lote y las horas", () => {
  const v1 = { numero_de_bobina: "B1", peso_de_bobina: "280", formato_mp1: "1", formato_de_salida: "2", velocidad: "3", gramaje_g_m2: "81.5", resistencia_longitudinal: "1.2", resistencia_transversal: "0.8", numero_mrp: "MRP-77" };
  const v2 = { hora_inicio: "06:30:00", hora_fin: "14:45:00", numero_de_bobina: "B2", peso_de_bobina: "290", formato_mp1: "1", formato_de_salida: "2", lote: "LOTE-9", velocidad: "3" };
  const parsed = [ui.P130.parseCapture(row(ui.P1_30_CODE, 2, v2, "c2")), ui.P130.parseCapture(row(ui.P1_30_CODE, 1, v1, "c1"))];
  assert.ok(parsed.every(Boolean));
  const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.REBOBINADO_CANDIDATES.p130, resource: { status: "ready", data: parsed, refreshing: false }, refresh: noop }));
  const text = textOf(html);
  for (const label of ["Gramaje g/m² (versión anterior)", "Resistencia longitudinal (versión anterior)", "Resistencia transversal (versión anterior)", "Número MRP (versión anterior)", "Lote", "Hora inicio", "Hora fin"]) assert.ok(text.includes(label), label);
  const newer = html.split('data-capture="c2"')[1].split('data-capture="c1"')[0], older = html.split('data-capture="c1"')[1];
  assert.ok(newer.includes("LOTE-9") && !newer.includes("MRP-77"));
  assert.ok(older.includes("MRP-77") && older.includes("81.5") && !older.includes("LOTE-9"), "la v1 conserva sus valores y no recibe un Lote inventado");
});

test("MF-10 no toca TVC/ETL ni el resto del código: el seed solo trae las cinco versiones nuevas", () => {
  const manifest = JSON.parse(readFileSync(join(root, "backend/seed_data/manifest.json"), "utf8"));
  const versions = {};
  for (const entry of manifest.files.filter((f) => f.path.startsWith("forms/"))) versions[entry.path.slice(6, -5)] = JSON.parse(readFileSync(join(root, "backend/seed_data", entry.path), "utf8")).version_number;
  const expected = { "VINTO-P1-07": 2, "VINTO-P1-10": 2, "VINTO-P1-12": 2, "VINTO-P1-29": 2, "VINTO-P1-30": 2 };
  for (const [code, version] of Object.entries(expected)) assert.equal(versions[code], version, code);
  assert.equal(versions["VINTO-P1-11"], 1, "P1-11 no cambia");
  assert.equal(versions["VINTO-P1-13"], 1, "P1-13 no cambia");
  assert.equal(versions["VINTO-P1-16"], 1, "P1-16 no cambia");
});
