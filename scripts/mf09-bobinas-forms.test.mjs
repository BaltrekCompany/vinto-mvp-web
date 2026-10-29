// node --test scripts/mf09-bobinas-forms.test.mjs
// MF-09 · pantallas reales de Bobinas (React + react-dom/server, sin navegador ni red): P1-01 v3 sin los 11 campos aprobados (MD_Ejec 10, 12, 13 y 15), sin encabezados vacíos y con el historial por versión, y P1-06 v2
// con «Toalla» como cuarta y última opción de «Tipo de producto» (MD_Ejec 18). Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio que se borra al terminar.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-mf09-bobinas-forms-${process.pid}`);
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
  const rel = `.tmp-mf09-bobinas-forms-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { CandidateHistory } from "@/components/vinto/candidate-history";',
    'export { F6Capture } from "@/components/vinto/f6-capture";',
    'export { BOBINAS_CANDIDATES } from "@/lib/vinto/bobinas-candidates";',
    'export { P101, P101_FIELDS, P101_LEGACY_FIELDS, P101_SECTIONS, P1_01_CODE } from "@/lib/vinto/p1-01";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const CONTEXT = { assignmentId: "44444444-4444-4444-8444-444444444444", workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1",
  productCode: "M1-1024", productName: "BOBINA 1024", machine: "MP3", shift: "Día", date: "2026-10-06" };
const RETIRED = ["presion_cocedores", "nivel_tanque_h_20_aguas", "nivel_tanque_h_20_aguas_2", "nivel_tanque_h_20_accionamientos", "opertado", "produccion", "presion_pope", "apertura_campana", "presion_regaderas", "limpieza_sala_de_control", "limpieza_mezzanine"];
const RETIRED_LABELS = ["Presión cocedores", "Nivel tanque H-20 aguas", "Nivel tanque H-20 aguas 2", "Nivel tanque H-20 accionamientos", "Opertado", "Producción", "Presión pope", "Apertura campana", "Presión regaderas", "Limpieza sala de control", "Limpieza mezzanine"];
// MF-12A (versión 4): los seis campos que retira y los dos que sustituye por claves nuevas, solo legibles en el historial
const MF12A_LEGACY = ["apertura_purga_prensa", "presion_aceite_guia_tela", "presion_aceite_lubricacion", "vacio_tela", "rodillos_quimicos", "vacio_prensa", "vacio_pope", "vacio_fieltro"];
const MF12A_LEGACY_LABELS = ["Apertura purga prensa", "Presión aceite guía tela", "Presión aceite lubricación", "Vacío tela", "Rodillos químicos", "Vacío prensa", "Vacío pope", "Vacío fieltro"];
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
const count = (html, text) => html.split(text).length - 1;
const p101 = () => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.BOBINAS_CANDIDATES.p101, context: CONTEXT, online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));

test("P1-01 (v3 y v4): los 11 campos de MF-09 siguen sin mostrarse, no hay encabezado «Presión cocedores» ni secciones vacías y los demás campos siguen", () => {
  const html = p101(), text = textOf(html);
  for (const label of RETIRED_LABELS) {
    assert.equal(text.includes(`${label} *`), false, `${label}: no se muestra como campo`);
  }
  assert.equal(text.includes("Presión cocedores"), false, "ni como campo ni como encabezado");
  // cada sección (h2) tiene al menos un campo; 7 secciones, 70 campos desde MF-12A (v4)
  const sections = html.split("<h2").slice(1).map((chunk) => chunk.split("</h2>")[0].replace(/<[^>]+>/g, "").replace(/^[^>]*>/, ""));
  assert.equal(count(html, "<input"), 70, "70 campos digitables (v4)");
  for (const title of ["Materia prima, tanques y pulpeo", "Caudales, mezclas y consistencias", "Químicos", "Secador, presiones y temperaturas", "Prensa, aceite, vacío y filtros", "Limpieza y cambios de cuchillas", "Novedades"]) assert.ok(text.includes(title), title);
  assert.ok(sections.length >= 7);
  for (const chunk of html.split('class="border-b p-6"').slice(1)) assert.ok(chunk.includes("<input"), "una sección sin campos");
  // campos vecinos que NO se retiran (aunque aparezcan marcados en otras imágenes del Excel)
  for (const keep of ["Nivel tanque T-30 aguas *", "Nivel tanque T-30 aguas 2 *", "Nivel tanque T-30 accionamientos *", "Limpieza *", "Limpieza escalera *", "Limpieza lado transmisión *", "Novedades *", "Consistencia *", "Ángulo caja *", "Nivel tanque PIT *"]) assert.ok(text.includes(keep), keep);
});

test("P1-01: la definición declara como solo lectura los 11 de MF-09 y los 8 de MF-12A y ningún campo de captura los repite", () => {
  assert.equal(ui.P101_FIELDS.length, 70);
  assert.deepEqual(ui.P101_LEGACY_FIELDS.map((f) => f.key).sort(), [...RETIRED, ...MF12A_LEGACY].sort());
  assert.equal(ui.P101_FIELDS.some((f) => [...RETIRED, ...MF12A_LEGACY].includes(f.key)), false);
  assert.equal(ui.P101_SECTIONS.flatMap((s) => s.keys).some((k) => [...RETIRED, ...MF12A_LEGACY].includes(k)), false);
  assert.equal(ui.P101_SECTIONS.every((s) => s.keys.length > 0), true);
});

const row = (version, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.P1_01_CODE, version_number: version, name: "x" },
  machine: { code: "MP3", name: "MP3" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" },
  line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });

test("historial de P1-01: la versión 2 conserva los 11 valores retirados como «versión anterior»; la versión 3 los deja vacíos", () => {
  const { P101 } = ui;
  const v3 = Object.fromEntries(Object.entries(P101.normalizeDraft(Object.fromEntries(ui.P101_FIELDS.map((f) => [f.key, f.kind === "decimal" ? "1,5" : f.kind === "time" ? "06:30" : "texto"]))).values).map(([k, v]) => [k, f_time(k, v)]));
  function f_time(k, v) { return /^hora_cambio/.test(k) ? `${v}:00` : v; }
  const v2 = { ...v3, ...Object.fromEntries(ui.P101_LEGACY_FIELDS.map((f) => [f.key, f.kind === "decimal" ? "77.5" : "valor histórico"])) };
  const parsed = [P101.parseCapture(row(3, v3, "c3")), P101.parseCapture(row(2, v2, "c2"))];
  assert.ok(parsed.every(Boolean), "ambas versiones se leen");
  const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.BOBINAS_CANDIDATES.p101, resource: { status: "ready", data: parsed, refreshing: false }, refresh: noop }));
  const text = textOf(html);
  for (const label of [...RETIRED_LABELS, ...MF12A_LEGACY_LABELS]) assert.ok(text.includes(`${label} (versión anterior)`), label);
  const [newer, older] = [html.split('data-capture="c3"')[1].split('data-capture="c2"')[0], html.split('data-capture="c2"')[1]];
  assert.equal(count(older, "77.5"), 12, "los 12 decimales retirados (6 de MF-09 y 6 de MF-12A) de la captura anterior se conservan");
  assert.equal(count(older, "valor histórico"), 7, "los 7 textos retirados (5 de MF-09 y 2 de MF-12A) de la captura anterior se conservan");
  assert.equal(newer.includes("77.5") || newer.includes("valor histórico"), false, "la captura v3 no tiene esos valores");
});

const f6 = () => server.renderToStaticMarkup(React.createElement(ui.F6Capture, { context: CONTEXT, online: true, attempt: null, setAttempt: noop, back: noop, onSubmitted: noop, onAssignmentChanged: noop, onSessionLost: noop }));

test("P1-06 v2: Tipo de producto muestra cuatro opciones y «Toalla» es la última; punto de merma y demás campos no cambian", () => {
  const html = f6();
  const selects = html.split("<select").slice(1).map((s) => s.split("</select>")[0]);
  assert.equal(selects.length, 2);
  const options = (s) => [...s.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(options(selects[0]), [["", "Seleccionar…"], ["bobina_rechazada", "Bobina rechazada"], ["recorte_maquina", "Recorte de máquina"]], "punto de merma sin cambios");
  assert.deepEqual(options(selects[1]), [["", "Seleccionar…"], ["servilleta", "Servilleta"], ["hoja_doble", "Hoja doble"], ["hoja_simple", "Hoja simple"], ["toalla", "Toalla"]], "tres opciones originales en su orden y Toalla al final");
  const text = textOf(html);
  for (const piece of ["Cantidad de fardos *", "Punto de merma *", "Tipo de producto *", "Peso real total *", "Observaciones", "Enviar registro trazable"]) assert.ok(text.includes(piece), piece);
  assert.equal(count(html, "<input"), 2);
  assert.equal(count(html, "<textarea"), 1);
});
