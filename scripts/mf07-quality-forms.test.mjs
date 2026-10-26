// node --test scripts/mf07-quality-forms.test.mjs
// MF-07 · pantallas reales de Calidad (React + react-dom/server, sin navegador ni red): P1-21 como UNA tabla editable de 27 posiciones numeradas, promedios de solo lectura en P1-24 / P1-25 y el historial por versión
// (etiquetas de la versión de la captura, tabla de posiciones con sus promedios, campos retirados «versión anterior»). Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal
// dentro del repositorio que se borra al terminar. Los efectos no se ejecutan en el render del servidor.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-mf07-quality-forms-${process.pid}`);
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
  const rel = `.tmp-mf07-quality-forms-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { QualityBobbinHistory } from "@/components/vinto/quality-bobbin-history";',
    'export { QUALITY_BOBBIN_CANDIDATES } from "@/lib/vinto/quality-bobbin-candidates";',
    'export { candidateViewer, parseQualityBobbinHistory, qualityHistoryLoad } from "@/lib/vinto/quality-history";',
    'export { P121 } from "@/lib/vinto/p1-21";', 'export { P124 } from "@/lib/vinto/p1-24";', 'export { P125 } from "@/lib/vinto/p1-25";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const BOBBIN_ID = "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b";
const item = {
  bobbin: { id: BOBBIN_ID, code: "1", machine: { code: "MP1", name: "MP1" }, management_start_year: 2026, sequence_number: 1, start_time: "", end_time: "", diameter_mm: "1", weight_kg: "1", grammage_g_m2: null, number_of_cuts: "1", notes: null },
  production: { capture_id: "c", captured_at: "2026-10-08T14:05:09Z", operating_date: "2026-10-07", shift: { code: "DIA", name: "Día" }, work_order: { id: "w", number: "OT-1" },
    line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1031", description: "M1-BOBINA" } } },
  quality: { status: "pending" },
};
const noop = () => {};
const capture = (screen) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.QUALITY_BOBBIN_CANDIDATES[screen], bobbin: item, online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const count = (html, text) => html.split(text).length - 1;
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("P1-21: una tabla editable de 27 posiciones numeradas (Posición, Gramaje, Peso seco (kg), % Humedad), sin Número de bobina ni Posición de texto libre", () => {
  const html = capture("p121");
  assert.equal(count(html, 'data-section="profile-table"'), 1);
  for (const column of ["Gramaje", "Peso seco (kg)", "% Humedad"]) assert.equal(count(html, `aria-label="${column} posición `), 27, column);
  assert.equal(count(html, "<tr "), 1 + 27, "encabezado + una fila por posición");
  for (const n of [1, 14, 27]) assert.match(html, new RegExp(`<th[^>]*scope="row"[^>]*>${n}</th>`));
  assert.match(html, /aria-label="Gramaje posición 27"/);
  assert.equal(html.includes('aria-label="Gramaje posición 28"'), false);
  assert.equal(count(html, "<input"), 81, "81 celdas numéricas dentro de la tabla (no 81 campos sueltos)");
  const text = textOf(html);
  for (const gone of ["Número de bobina *", "Posición de perfil"]) assert.equal(text.includes(gone), false, gone);
  assert.match(text, /Registra al menos una fila completa/);
  assert.match(text, /Bobina 1 · f96d57a1/, "la captura sigue ligada a la bobina seleccionada");
  // Observaciones al final, después de la tabla y de los promedios
  assert.ok(html.indexOf('data-section="profile-table"') < html.indexOf('data-section="calculated-preview"') && html.indexOf('data-section="calculated-preview"') < html.indexOf("Observaciones"));
});

test("P1-21: los tres promedios y las posiciones utilizadas son de solo lectura (sin campo editable) y arrancan vacíos, sin ceros", () => {
  const html = capture("p121");
  const block = html.slice(html.indexOf('data-section="calculated-preview"'), html.indexOf("Observaciones"));
  for (const key of ["promedio_gramaje", "promedio_peso_seco", "promedio_humedad", "posiciones_utilizadas"]) assert.equal(count(block, `data-calculated="${key}"`), 1, key);
  assert.equal(block.includes("<input") || block.includes("<textarea"), false, "los promedios no se digitan");
  assert.equal(count(block, ">—<"), 3, "sin filas completas no hay promedio (no se muestra 0)");
  assert.match(textOf(block), /Posiciones utilizadas en los promedios 0 de 27/);
  assert.match(textOf(block), /Solo se usan las filas completas/);
});

test("P1-24: posiciones Comando / Medio / Transversal, promedios de solo lectura y sin Número de bobina ni Producto", () => {
  const text = textOf(capture("p124"));
  for (const label of ["Resistencia longitudinal húmeda – Comando *", "Resistencia longitudinal húmeda – Medio *", "Resistencia longitudinal húmeda – Transversal *", "Resistencia transversal húmeda – Comando *", "Resistencia transversal húmeda – Medio *", "Resistencia transversal húmeda – Transversal *"]) assert.ok(text.includes(label), label);
  assert.match(text, /Promedio resistencia longitudinal húmeda/);
  assert.match(text, /Promedio resistencia transversal húmeda/);
  for (const gone of ["Número de bobina *", "Producto *", " centro", " extremo"]) assert.equal(text.includes(gone), false, gone);
  const html = capture("p124");
  assert.equal(count(html, 'data-section="calculated-preview"'), 1);
  assert.equal(html.includes('data-section="profile-table"'), false);
});

test("P1-25: Comando / Medio / Transversal, promedios de resistencia longitudinal, elongaciones sin duplicar y los ajustes de MF-06 intactos", () => {
  const html = capture("p125"), text = textOf(html);
  for (const label of ["Resistencia longitudinal – Comando kgf *", "Resistencia longitudinal – Medio kgf *", "Resistencia longitudinal – Transversal kgf *", "Resistencia longitudinal húmeda – Comando kgf *", "Resistencia longitudinal húmeda – Medio kgf *", "Resistencia longitudinal húmeda – Transversal kgf *"]) assert.ok(text.includes(label), label);
  assert.match(text, /Promedio resistencia longitudinal kgf/);
  assert.match(text, /Promedio resistencia longitudinal húmeda kgf/);
  assert.equal(count(text, "Elongación media longitudinal *"), 1);
  assert.equal(count(text, "Elongación media transversal *"), 1);
  assert.ok(text.indexOf("Caudal RH [ml/min]") < text.indexOf("Crepado *"), "Caudal RH al inicio");
  assert.ok(text.indexOf("# Cortes *") < text.indexOf("Observaciones") && text.indexOf("Elongación media transversal *") < text.indexOf("# Cortes *"), "# Cortes inmediatamente antes de Observaciones");
  for (const gone of ["Número de bobina *", "Producto *", "Gramaje laboratorio"]) assert.equal(text.includes(gone), false, gone);
});

// ---- historial por versión ---------------------------------------------------------------------------------------------------------------------------
const base = (code, version, values, id) => ({
  id, status: "submitted", revision: 1, captured_at: "2026-10-08T14:05:09Z", submitted_at: "2026-10-08T14:05:10Z", form: { code, version_number: version, name: "x" }, bobbin: { id: BOBBIN_ID, code: "1" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-07", work_order: { id: "w", number: "OT-1" },
  line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1031", description: "M1-BOBINA" } }, values,
});
function history(captures) {
  const viewers = { "VINTO-P1-21": ui.candidateViewer(ui.P121.parseCapture), "VINTO-P1-24": ui.candidateViewer(ui.P124.parseCapture), "VINTO-P1-25": ui.candidateViewer(ui.P125.parseCapture) };
  const parsed = ui.parseQualityBobbinHistory(captures, { id: BOBBIN_ID, code: "1" }, viewers);
  assert.ok(parsed, "el historial se lee");
  const load = ui.qualityHistoryLoad(BOBBIN_ID, { ok: true, status: 200, data: parsed });
  return server.renderToStaticMarkup(React.createElement(ui.QualityBobbinHistory, { item, resource: { status: "ready", data: load, refreshing: false }, refresh: noop, back: noop }));
}

test("historial P1-21: la versión 2 muestra solo las posiciones registradas con sus promedios y cuántas se usaron; la versión 1 conserva sus campos como «versión anterior»", () => {
  const v2 = base("VINTO-P1-21", 2, { gramaje_01: "18.250", peso_seco_01: "0.095", humedad_01: "6.5", gramaje_27: "0", peso_seco_27: "0", humedad_27: "0", promedio_gramaje: "9.13", promedio_peso_seco: "0.05", promedio_humedad: "3.25", posiciones_utilizadas: 2, observaciones: "ok" }, "11111111-1111-4111-8111-111111111111");
  const v1 = base("VINTO-P1-21", 1, { numero_de_bobina: "1", posicion_de_perfil: "centro", gramaje: "81.2", peso_seco: "1.9" }, "22222222-2222-4222-8222-222222222222");
  const html = history([v2, v1]);
  const [newer, older] = html.split('aria-labelledby="quality-control-22222222').length > 1 ? [html.split("<li ")[1], html.split("<li ")[2]] : [html, ""];
  const t2 = textOf(newer), t1 = textOf(older);
  assert.equal(count(newer, 'data-section="profile-history"'), 1);
  assert.equal(count(newer, '<th scope="row"'), 2, "solo las posiciones con valores (1 y 27)");
  assert.match(t2, /27 0 0 0/, "un 0 registrado se muestra como 0, no como vacío");
  assert.match(t2, /Promedio gramaje 9\.13 g\/m²/);
  assert.match(t2, /Promedio peso seco 0\.05 kg/);
  assert.match(t2, /Promedio % humedad 3\.25 %/);
  assert.match(t2, /Posiciones utilizadas en los promedios 2 de 27/);
  assert.match(t2, /Versión 2/);
  assert.equal(t2.includes("(versión anterior)"), false);
  assert.match(t1, /Versión 1/);
  assert.match(t1, /Posición de perfil \(versión anterior\) centro/);
  assert.match(t1, /Gramaje \(versión anterior\) 81\.2 g\/m²/);
  assert.match(t1, /Peso seco \(versión anterior\) 1\.9 kg/);
  assert.equal(older.includes('data-section="profile-history"'), false);
  assert.equal(t1.includes("Promedio"), false, "no se inventan promedios para registros históricos");
});

test("historial P1-24 / P1-25: cada captura se muestra con las etiquetas de SU versión y los promedios solo si la versión los guardó", () => {
  const v24 = { crepado: "12", gramaje: "18", resistencia_longitudinal_humeda_centro: "0.050", resistencia_longitudinal_humeda_medio: "0.051", resistencia_longitudinal_humeda_extremo: "0.049", resistencia_transversal_humeda_centro: "0.030", resistencia_transversal_humeda_medio: "0.031", resistencia_transversal_humeda_extremo: "0.029", tiempo_de_curado_condicion: "5" };
  const v25 = { caudal_rh_ml_min: "9.5", crepado: "12", curado_min: "5", resistencia_longitudinal_centro_kgf: "1", resistencia_longitudinal_medio_kgf: "2", resistencia_longitudinal_extremo_kgf: "3", elongacion_media_longitudinal: "3.5",
    resistencia_longitudinal_humeda_centro_kgf: "4", resistencia_longitudinal_humeda_medio_kgf: "5", resistencia_longitudinal_humeda_extremo_kgf: "6", elongacion_media_transversal: "2.1", n_cortes: 3 };
  const html = history([
    base("VINTO-P1-24", 3, { ...v24, promedio_longitudinal_humedo: "0.05", promedio_transversal_humedo: "0.03" }, "33333333-3333-4333-8333-333333333333"),
    base("VINTO-P1-24", 2, v24, "44444444-4444-4444-8444-444444444444"),
    base("VINTO-P1-25", 3, { ...v25, promedio_resistencia_longitudinal_kgf: "2.00", promedio_resistencia_longitudinal_humeda_kgf: "5.00" }, "55555555-5555-4555-8555-555555555555"),
    base("VINTO-P1-25", 2, v25, "66666666-6666-4666-8666-666666666666"),
  ]);
  const [c24v3, c24v2, c25v3, c25v2] = html.split("<li ").slice(1).map(textOf);
  assert.match(c24v3, /Resistencia longitudinal húmeda – Comando 0\.050/);
  assert.match(c24v3, /Resistencia transversal húmeda – Transversal 0\.029/);
  assert.match(c24v3, /Promedio resistencia longitudinal húmeda 0\.05/);
  assert.match(c24v3, /Promedio resistencia transversal húmeda 0\.03/);
  assert.match(c24v2, /Resistencia longitudinal húmeda centro 0\.050/, "la versión 2 conserva su etiqueta");
  assert.match(c24v2, /Resistencia transversal húmeda extremo 0\.029/);
  assert.equal(c24v2.includes("Comando") || c24v2.includes("Promedio"), false);
  assert.match(c25v3, /Resistencia longitudinal – Comando kgf 1/);
  assert.match(c25v3, /Resistencia longitudinal húmeda – Transversal kgf 6/);
  assert.match(c25v3, /Promedio resistencia longitudinal kgf 2\.00/);
  assert.match(c25v3, /Promedio resistencia longitudinal húmeda kgf 5\.00/);
  assert.match(c25v2, /Resistencia longitudinal centro kgf 1/);
  assert.match(c25v2, /Resistencia longitudinal húmeda extremo kgf 6/);
  assert.equal(c25v2.includes("Comando") || c25v2.includes("Promedio"), false);
  assert.match(c25v2, /Caudal RH \[ml\/min\] 9\.5/);
  assert.match(c25v2, /# Cortes 3/);
});

// ---- reglas de la tabla de P1-21 (lógica pura, mismas reglas que el backend) -----------------------------------------------------------------------
test("P1-21: al menos una fila completa; una fila a medias se rechaza y nombra su posición; las filas vacías no se rellenan; un 0 es un valor", async () => {
  const { P121, completePositions, previewP121, p121Key } = await import(pathToFileURL(join(root, "lib/vinto/p1-21.ts")).href);
  const row = (n, g, p, h) => ({ [p121Key("gramaje", n)]: g, [p121Key("peso_seco", n)]: p, [p121Key("humedad", n)]: h });
  const draft = (...rows) => ({ ...P121.emptyDraft(), ...Object.assign({}, ...rows) });
  // sin filas
  assert.deepEqual(P121.normalizeDraft(P121.emptyDraft()).errors, ["Registra al menos una fila completa."]);
  assert.deepEqual(P121.normalizeDraft(draft({ observaciones: "solo texto" })).errors, ["Registra al menos una fila completa."]);
  assert.deepEqual(P121.normalizeDraft(draft(row(1, " ", "", " "))).errors, ["Registra al menos una fila completa."], "espacios = vacío");
  // una fila completa
  const one = P121.normalizeDraft(draft(row(5, "81,2", "1.9", "6,5")));
  assert.equal(one.ok, true);
  assert.deepEqual(one.values, { gramaje_05: "81.2", peso_seco_05: "1.9", humedad_05: "6.5" }, "las 26 filas vacías no viajan (nada de ceros)");
  // varias filas completas, con una fila vacía en medio
  const many = P121.normalizeDraft(draft(row(1, "1", "2", "3"), row(3, "4", "5", "6"), row(27, "7", "8", "9")));
  assert.equal(many.ok, true);
  assert.equal(Object.keys(many.values).length, 9);
  // fila a medias
  for (const partial of [row(2, "1", "", ""), row(2, "", "1", ""), row(2, "", "", "1"), row(2, "1", "2", ""), row(2, "0", "0", "")]) {
    const out = P121.normalizeDraft(draft(row(1, "1", "2", "3"), partial));
    assert.equal(out.ok, false);
    assert.match(out.errors.join(" "), /Posición 2: fila incompleta/);
  }
  // cero ≠ vacío
  const zero = P121.normalizeDraft(draft(row(9, "0", "0", "0")));
  assert.equal(zero.ok, true);
  assert.deepEqual(zero.values, { gramaje_09: "0", peso_seco_09: "0", humedad_09: "0" });
  assert.deepEqual(completePositions(draft(row(9, "0", "0", "0"), row(10, "0", "", "0"))), [9]);
  // un número inválido sigue siendo un error de la celda
  assert.match(P121.normalizeDraft(draft(row(1, "abc", "2", "3"))).errors.join(" "), /debe ser un número decimal/);
  // promedios mostrados: solo filas completas, exactos y con dos decimales; sin filas, vacío (no 0)
  assert.deepEqual(previewP121(draft(row(1, "10.00", "1", "4"), row(2, "10.01", "2", "5"), row(3, "99", "", "")) ), { promedio_gramaje: "10.01", promedio_peso_seco: "1.50", promedio_humedad: "4.50", posiciones_utilizadas: "2" });
  assert.deepEqual(previewP121(P121.emptyDraft()), { promedio_gramaje: null, promedio_peso_seco: null, promedio_humedad: null, posiciones_utilizadas: null });
  assert.equal(previewP121(draft(row(1, "0", "0", "0"))).promedio_gramaje, "0.00");
});
