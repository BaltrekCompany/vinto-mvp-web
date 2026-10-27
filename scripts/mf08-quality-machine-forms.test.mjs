// node --test scripts/mf08-quality-machine-forms.test.mjs
// MF-08 · controles de Calidad por máquina, versión 2: P1-18 (sin punto de muestreo, + % Consistencia opcional y Hora del ensayo obligatoria), P1-22 (sin volumen desplazado) y P1-26 (punto de muestreo como lista
// cerrada y % Cantidad de seco calculado por el backend). Renderiza las pantallas reales (React + react-dom/server, sin navegador ni red) y prueba la lógica pura de los formularios. Los componentes TSX se
// empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio que se borra al terminar.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-mf08-machine-forms-${process.pid}`);
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
  const rel = `.tmp-mf08-machine-forms-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { CandidateHistory } from "@/components/vinto/candidate-history";',
    'export { QUALITY_CANDIDATES } from "@/lib/vinto/quality-candidates";',
    'export { P118, P1_18_CODE } from "@/lib/vinto/p1-18";', 'export { P122, P1_22_CODE } from "@/lib/vinto/p1-22";', 'export { P126, P1_26_CODE, P126_SAMPLING_POINTS, previewP126 } from "@/lib/vinto/p1-26";',
    'export { percentTwoDecimals } from "@/lib/vinto/quality-averages";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const capture = (screen) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.QUALITY_CANDIDATES[screen], machine: { code: "MP1", name: "MP1" }, online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const count = (html, text) => html.split(text).length - 1;
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("P1-18 v2: sin Punto de muestreo; Hora obligatoria (campo de hora) tras Número de cuba; % Consistencia opcional justo después de Masa seca g", () => {
  const html = capture("p118"), text = textOf(html.slice(html.indexOf('data-section="automatic"')));  // solo la zona de campos (las notas pendientes de arriba también nombran «% Consistencia»)
  assert.equal(textOf(html).includes("Punto de muestreo *"), false);
  assert.equal(text.includes("Punto de muestreo"), false);
  const order = ["Producto *", "Número de cuba *", "Hora *", "Masa húmeda g *", "Masa seca g *", "% Consistencia", "Papel filtro g *"].map((label) => text.indexOf(label));
  assert.ok(order.every((n) => n >= 0), "todos los campos están");
  assert.deepEqual([...order].sort((a, b) => a - b), order, "orden aprobado");
  assert.equal(text.includes("% Consistencia *"), false, "% Consistencia es opcional (sin asterisco)");
  assert.equal(count(html, 'type="time"'), 1, "Hora es un campo de hora");
  assert.match(text, /Hora real del ensayo \(HH:MM, hora local de planta\)\. No es la hora de registro del sistema/);
  assert.match(text, /% Consistencia[^%]*%/, "la unidad % es visible");
  assert.equal(count(html, 'data-section="calculated-preview"'), 0, "% Consistencia no se calcula: no hay bloque de calculados");
});

test("P1-22 v2: sin Volumen desplazado y con los demás campos obligatorios", () => {
  const text = textOf(capture("p122"));
  assert.equal(text.includes("Volumen desplazado"), false);
  for (const label of ["Número de cuba *", "Masa húmeda *", "Grado de refinación °SR *", "Amperaje *"]) assert.ok(text.includes(label), label);
});

test("P1-26 v2: Punto de muestreo es una lista obligatoria con las seis opciones exactas y % Cantidad de seco es de solo lectura; sin Absorción de humedad", () => {
  const html = capture("p126"), text = textOf(html);
  assert.equal(count(html, "<select"), 1);
  const options = [...html.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(options.map((o) => o[0]), ["", ...ui.P126_SAMPLING_POINTS]);
  assert.deepEqual(options.slice(1).map((o) => o[1]), ["Caja de formación – Colador", "Tela – Pick up", "Fieltro I", "Fieltro II", "Prensa succión", "Prensa ciega"]);
  assert.ok(text.includes("Punto de muestreo *"));
  const block = html.slice(html.indexOf('data-section="calculated-preview"'));
  assert.ok(block.length > 0);
  assert.match(textOf(block), /% Cantidad de seco —/, "sin masas no hay resultado");
  assert.equal(block.includes("<input") || block.includes("<select") || block.includes("<textarea"), false, "solo lectura");
  assert.equal(/Absorci[oó]n/i.test(text), false, "MD_Ejec 33 queda fuera");
});

test("P1-26: lista cerrada (sin texto libre en capturas nuevas) y lectura de la versión 1 con su texto libre original", () => {
  const { P126 } = ui;
  const ok = (value) => P126.normalizeDraft({ ...P126.emptyDraft(), punto_de_muestreo: value, masa_humeda: "80", masa_seca: "20" });
  for (const point of ui.P126_SAMPLING_POINTS) assert.equal(ok(point).values.punto_de_muestreo, point);
  for (const bad of ["salida", "fieltro i", "Caja de formacion – Colador", "Caja de formación - Colador", "Tela", "Prensa ciega 2"]) assert.match(ok(bad).errors.join(" "), /elige una de las opciones de la lista/, bad);
  assert.match(ok("  ").errors.join(" "), /Punto de muestreo: es obligatorio/);
  const envelope = (version, values) => ({ id: "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.P1_26_CODE, version_number: version, name: "x" },
    machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", recorded_by: null, values });
  const masses = { masa_humeda: "80", masa_seca: "20" };
  assert.equal(P126.parseCapture(envelope(1, { punto_de_muestreo: "texto libre antiguo", ...masses }))?.values.punto_de_muestreo, "texto libre antiguo", "la versión 1 conserva su valor original");
  assert.equal(P126.parseCapture(envelope(2, { punto_de_muestreo: "texto libre antiguo", ...masses })), null, "una captura v2 solo admite las opciones");
  assert.equal(P126.parseCapture(envelope(2, { punto_de_muestreo: "Tela – Pick up", ...masses }))?.values.punto_de_muestreo, "Tela – Pick up");
  assert.equal(P126.parseCapture(envelope(1, { punto_de_muestreo: "", ...masses })), null, "obligatorio también en la v1");
  assert.deepEqual(P126.parseCapture(envelope(2, { punto_de_muestreo: "Fieltro II", ...masses, porcentaje_cantidad_de_seco: "25.00" }))?.values.porcentaje_cantidad_de_seco, "25.00", "el calculado del backend se lee");
  assert.equal(P126.parseCapture(envelope(2, { punto_de_muestreo: "Fieltro II", ...masses, porcentaje_cantidad_de_seco: "abc" })), null);
  const { attempt } = P126.createAttempt({ ...P126.emptyDraft(), punto_de_muestreo: "Fieltro I", ...masses }, "MP3", "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", () => "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b");
  assert.equal("porcentaje_cantidad_de_seco" in attempt.payload.values, false, "el cliente nunca envía el calculado");
});

test("% Cantidad de seco mostrado: masa seca ÷ masa húmeda × 100, dos decimales exactos y sin resultado con masa húmeda 0 o vacía", () => {
  const p = ui.percentTwoDecimals;
  assert.deepEqual([["20", "80"], ["1", "3"], ["2", "3"], ["1", "16"], ["1", "800"], ["1.5", "1.5"], ["0", "50"], ["-1", "3"], ["7.35", "7"]].map(([dry, wet]) => p(dry, wet)), ["25.00", "33.33", "66.67", "6.25", "0.13", "100.00", "0.00", "-33.33", "105.00"]);
  for (const [dry, wet] of [["5", "0"], ["5", "0.0"], ["5", ""], ["5", undefined], ["", "5"], ["abc", "5"], ["5", "abc"]]) assert.equal(p(dry, wet), null, `${dry}/${wet}`);
  assert.equal(p("20,5", "80,25"), "25.55", "coma decimal");
  assert.deepEqual(ui.previewP126({ masa_seca: "20", masa_humeda: "80" }), { porcentaje_cantidad_de_seco: "25.00" });
  assert.deepEqual(ui.previewP126({ masa_seca: "20", masa_humeda: "0" }), { porcentaje_cantidad_de_seco: null });
});

test("P1-18: Hora obligatoria HH:MM (00:00 a 23:59), % Consistencia opcional y decimal; las capturas v1 se leen sin Hora", () => {
  const { P118 } = ui;
  const base = { ...P118.emptyDraft(), producto: "p", numero_de_cuba: "C-1", masa_humeda_g: "10", masa_seca_g: "2", papel_filtro_g: "1", papel_muestra_g: "1", peso_muestra_g: "1" };
  const check = (hour, percent = "") => P118.normalizeDraft({ ...base, hora_del_ensayo: hour, porcentaje_consistencia: percent });
  for (const good of ["00:00", "23:59", "07:05", " 12:30 "]) assert.equal(check(good).ok, true, good);
  assert.equal(check("07:30").values.hora_del_ensayo, "07:30", "se conserva tal cual: sin conversión a UTC");
  for (const bad of ["24:00", "12:60", "7:30", "12:5", "abc", "1230", "12.30"]) assert.match(check(bad).errors.join(" "), /Hora: debe ser una hora válida HH:MM/, bad);
  assert.match(check("").errors.join(" "), /Hora: es obligatorio/);
  assert.match(check("   ").errors.join(" "), /Hora: es obligatorio/);
  assert.equal(check("07:30", "").ok, true, "% Consistencia puede quedar vacío");
  assert.equal("porcentaje_consistencia" in check("07:30", "").values, false);
  assert.equal(check("07:30", "12,75").values.porcentaje_consistencia, "12.75");
  assert.match(check("07:30", "abc").errors.join(" "), /% Consistencia: debe ser un número decimal/);
  const envelope = (version, values) => ({ id: "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.P1_18_CODE, version_number: version, name: "x" },
    machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", recorded_by: null, values });
  const v1 = { producto: "p", numero_de_cuba: "C-1", punto_de_muestreo: "salida", masa_humeda_g: "10", masa_seca_g: "2", papel_filtro_g: "1", papel_muestra_g: "1", peso_muestra_g: "1" };
  assert.deepEqual(P118.parseCapture(envelope(1, v1))?.values, v1, "la versión 1 conserva el punto de muestreo");
  const v2Base = Object.fromEntries(Object.entries(v1).filter(([k]) => k !== "punto_de_muestreo"));
  assert.equal(P118.parseCapture(envelope(2, v2Base)), null, "la versión 2 exige Hora");
  assert.equal(P118.parseCapture(envelope(2, { ...v2Base, hora_del_ensayo: "07:30:00" }))?.values.hora_del_ensayo, "07:30:00", "el backend devuelve HH:MM:SS");
  assert.equal(P118.parseCapture(envelope(2, { ...v2Base, hora_del_ensayo: "25:00:00" })), null);
});

// ---- historial por versión ---------------------------------------------------------------------------------------------------------------------------
const rowOf = (code, version, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code, version_number: version, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", recorded_by: { id: "u", display_name: "Calidad" }, values });
const history = (screen, rows) => server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.QUALITY_CANDIDATES[screen], resource: { status: "ready", data: rows, refreshing: false }, refresh: noop }));

test("historial por máquina: los campos retirados se muestran como «versión anterior» y el calculado de P1-26 solo en las capturas que lo guardaron", () => {
  const h22 = history("p122", [rowOf(ui.P1_22_CODE, 2, { numero_de_cuba: "C-2", masa_humeda: "10", grado_de_refinacion_sr: "30", amperaje: "12" }, "a"), rowOf(ui.P1_22_CODE, 1, { numero_de_cuba: "C-1", masa_humeda: "9", volumen_desplazado: "630", grado_de_refinacion_sr: "28", amperaje: "11" }, "b")]);
  assert.match(textOf(h22), /Volumen desplazado \(versión anterior\)/);
  assert.match(h22, /data-capture="b"[\s\S]*?<td[^>]*>630<\/td>/, "la captura antigua conserva su volumen");
  assert.equal(/data-capture="a"[\s\S]*?630/.test(h22.split('data-capture="b"')[0]), false);
  const h18 = history("p118", [rowOf(ui.P1_18_CODE, 1, { producto: "p", numero_de_cuba: "C", punto_de_muestreo: "salida", masa_humeda_g: "1", masa_seca_g: "1", papel_filtro_g: "1", papel_muestra_g: "1", peso_muestra_g: "1" }, "c")]);
  assert.match(textOf(h18), /Punto de muestreo \(versión anterior\)/);
  assert.match(h18, /<td[^>]*>salida<\/td>/);
  const h26 = history("p126", [rowOf(ui.P1_26_CODE, 2, { punto_de_muestreo: "Fieltro I", masa_humeda: "80", masa_seca: "20", porcentaje_cantidad_de_seco: "25.00" }, "d"), rowOf(ui.P1_26_CODE, 1, { punto_de_muestreo: "libre", masa_humeda: "80", masa_seca: "20" }, "e")]);
  assert.match(textOf(h26), /% Cantidad de seco/);
  assert.match(h26.split('data-capture="e"')[0], /<td[^>]*>25\.00<\/td>/);
  assert.equal(/25\.00/.test(h26.split('data-capture="e"')[1]), false, "la captura v1 no recibe un % inventado");
});
