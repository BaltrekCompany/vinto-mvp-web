// node --test scripts/mf11-calidad-conversion.test.mjs
// MF-11 · pantallas reales (React + react-dom/server, sin navegador ni red): P1-26 v3 «Absorción de humedad» (MD_Ejec 33), P1-27 v2 «Alcalinidad total» (MD_Ejec 35), P1-24 v4 «Crepado (%)» (MD_Ejec 51) y las horas GENERALES de
// producción de Conversión (MD_Ejec 46 y 48): P1-11 v2, P1-12 v3, P1-13 v2 y P1-16 v2. Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio que se borra al terminar.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").split(String.fromCharCode(92)).join("/");
const workDir = join(root, `.tmp-mf11-${process.pid}`);
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
  const rel = `.tmp-mf11-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { CandidateHistory } from "@/components/vinto/candidate-history";',
    'export { QualityBobbinHistory } from "@/components/vinto/quality-bobbin-history";',
    'export { P111CaptureForm } from "@/components/vinto/p1-11-capture";',
    'export { P111History } from "@/components/vinto/central-form-history";',
    'export { QUALITY_CANDIDATES } from "@/lib/vinto/quality-candidates";',
    'export { QUALITY_BOBBIN_CANDIDATES } from "@/lib/vinto/quality-bobbin-candidates";',
    'export { CONVERSION_CANDIDATES } from "@/lib/vinto/conversion-candidates";',
    'export { candidateViewer, parseQualityBobbinHistory, qualityHistoryLoad } from "@/lib/vinto/quality-history";',
    'export { P126, P1_26_CODE } from "@/lib/vinto/p1-26";', 'export { P127, P127_FIELDS, P1_27_CODE } from "@/lib/vinto/p1-27";',
    'export { P124, P124_FIELDS, P1_24_CODE } from "@/lib/vinto/p1-24";', 'export { P125, P125_FIELDS } from "@/lib/vinto/p1-25";',
    'export { labelFor } from "@/lib/vinto/candidate-form";',
    'export { P112, P112_FIELDS, P112_LABELS, P1_12_CODE } from "@/lib/vinto/p1-12";', 'export { P113, P113_FIELDS, P1_13_CODE } from "@/lib/vinto/p1-13";', 'export { P116, P116_FIELDS, P1_16_CODE } from "@/lib/vinto/p1-16";',
    'export { P111_HOUR_FIELDS, P1_11_CODE, emptyP111Draft, normalizeP111Draft, parseP111Capture } from "@/lib/vinto/p1-11";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const count = (html, text) => html.split(text).length - 1;
const UUID = (n) => `${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;

// ---- Calidad por máquina (P1-26, P1-27) -------------------------------------------------------------------------------------------------------------------
const machineScreen = (screen) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.QUALITY_CANDIDATES[screen], machine: { code: "MP1", name: "MP1" }, online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const machineEnvelope = (code, version, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code, version_number: version, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", recorded_by: null, values });
const machineHistory = (screen, parsed) => server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.QUALITY_CANDIDATES[screen], resource: { status: "ready", data: parsed, refreshing: false }, refresh: noop }));

test("P1-26 v3: «Absorción de humedad» es un decimal opcional con la unidad %, justo después de Masa seca; «% Cantidad de seco» sigue siendo de solo lectura", () => {
  const html = machineScreen("p126"), text = textOf(html.slice(html.indexOf('data-section="automatic"')));
  const order = ["Punto de muestreo *", "Masa húmeda *", "Masa seca *", "Absorción de humedad", "Observaciones"].map((label) => text.indexOf(label));
  assert.ok(order.every((n) => n >= 0), "todos los campos están");
  assert.deepEqual([...order].sort((a, b) => a - b), order, "orden: la absorción va tras Masa seca");
  assert.equal(textOf(html).includes("Absorción de humedad *"), false, "opcional: sin asterisco");
  assert.match(text, /Absorción de humedad[^%]*%/, "la unidad % es visible");
  assert.equal(count(html, 'data-section="calculated-preview"'), 1, "el bloque calculado de % Cantidad de seco sigue ahí");
  assert.match(textOf(html.slice(html.indexOf('data-section="calculated-preview"'))), /% Cantidad de seco/);
  assert.equal(textOf(html.slice(html.indexOf('data-section="calculated-preview"'))).includes("Absorción"), false, "la absorción no es un campo calculado");
});

test("P1-26 v3: el borrador acepta la absorción como decimal digitado (coma o punto), puede ir vacía, y no se deriva de las masas", () => {
  const base = { punto_de_muestreo: "Fieltro I", masa_humeda: "80", masa_seca: "20" };
  assert.deepEqual(ui.P126.normalizeDraft({ ...base, absorcion_de_humedad: "3,5" }).values, { ...base, absorcion_de_humedad: "3.5" });
  for (const empty of ["", "   "]) assert.equal("absorcion_de_humedad" in ui.P126.normalizeDraft({ ...base, absorcion_de_humedad: empty }).values, false, "vacía: no se envía");
  assert.equal(ui.P126.normalizeDraft(base).ok, true);
  assert.match(ui.P126.normalizeDraft({ ...base, absorcion_de_humedad: "abc" }).errors.join(" "), /Absorción de humedad: debe ser un número decimal/);
  assert.equal(ui.P126.normalizeDraft({ ...base, absorcion_de_humedad: "250" }).ok, true, "sin rango aprobado");
  assert.equal(ui.P126.normalizeDraft({ ...base, absorcion_de_humedad: "0" }).values.absorcion_de_humedad, "0");
});

test("historial de P1-26: la captura v2 se lee sin absorción (no se inventa un valor) y la v3 la muestra", () => {
  const v2 = { punto_de_muestreo: "Tela – Pick up", masa_humeda: "80", masa_seca: "20", porcentaje_cantidad_de_seco: "25.00" };
  const v3 = { ...v2, absorcion_de_humedad: "7.5" };
  const parsed = [ui.P126.parseCapture(machineEnvelope(ui.P1_26_CODE, 3, v3, UUID(3))), ui.P126.parseCapture(machineEnvelope(ui.P1_26_CODE, 2, v2, UUID(2)))];
  assert.ok(parsed.every(Boolean), "ambas versiones se leen");
  assert.equal("absorcion_de_humedad" in parsed[1].values, false);
  const html = machineHistory("p126", parsed);
  const newer = html.split(`data-capture="${UUID(3)}"`)[1].split(`data-capture="${UUID(2)}"`)[0], older = html.split(`data-capture="${UUID(2)}"`)[1];
  assert.ok(textOf(html).includes("Absorción de humedad"), "columna propia en el encabezado");
  assert.ok(newer.includes("7.5"));
  assert.equal(older.includes("7.5"), false);
  assert.ok(older.includes("25.00") && newer.includes("25.00"), "el % de cantidad de seco se conserva en ambas");
});

test("P1-27 v2: «Alcalinidad total» es un decimal opcional SIN unidad dentro de «Purga de caldero»; los demás campos no cambian", () => {
  const html = machineScreen("p127"), text = textOf(html.slice(html.indexOf('data-section="automatic"')));
  const order = ["Purga caldero conductividad *", "Purga caldero cloruros *", "Alcalinidad total", "Condensado MP1 pH *"].map((label) => text.indexOf(label));
  assert.ok(order.every((n) => n >= 0), "todos los campos están");
  assert.deepEqual([...order].sort((a, b) => a - b), order, "Alcalinidad total sigue a Purga caldero cloruros y precede al condensado");
  assert.equal(textOf(html).includes("Alcalinidad total *"), false, "opcional");
  assert.equal(/Alcalinidad total\s*(%|ppm|mg|g\/l|mmol|meq)/i.test(textOf(html.slice(html.indexOf('data-section="automatic"')))), false, "ninguna unidad por suposición");
  assert.equal(ui.P127_FIELDS.filter((f) => f.suffix).length, 0);
  assert.equal(ui.P127_FIELDS.length, 24);
  const fill = Object.fromEntries(ui.P127_FIELDS.filter((f) => f.required).map((f) => [f.key, f.kind === "decimal" ? "7,25" : "texto"]));
  assert.equal(ui.P127.normalizeDraft(fill).ok, true, "sin alcalinidad se puede registrar");
  assert.equal(ui.P127.normalizeDraft({ ...fill, alcalinidad_total: "120,5" }).values.alcalinidad_total, "120.5");
  assert.equal(ui.P127.normalizeDraft({ ...fill, alcalinidad_total: "  " }).ok, true);
  assert.match(ui.P127.normalizeDraft({ ...fill, alcalinidad_total: "alta" }).errors.join(" "), /Alcalinidad total: debe ser un número decimal/);
  assert.equal("purga_caldero_alcalinidad_total" in ui.P127.normalizeDraft({ ...fill, alcalinidad_total: "1" }).values, false, "no se envía la clave calculada legacy");
});

test("historial de P1-27: la captura v1 se lee sin alcalinidad y la v2 la muestra", () => {
  const v1 = Object.fromEntries(ui.P127_FIELDS.filter((f) => f.required).map((f) => [f.key, f.kind === "decimal" ? "7.25" : "texto"]));
  const parsed = [ui.P127.parseCapture(machineEnvelope(ui.P1_27_CODE, 2, { ...v1, alcalinidad_total: "88.5" }, UUID(3))), ui.P127.parseCapture(machineEnvelope(ui.P1_27_CODE, 1, v1, UUID(2)))];
  assert.ok(parsed.every(Boolean));
  const html = machineHistory("p127", parsed);
  const newer = html.split(`data-capture="${UUID(3)}"`)[1].split(`data-capture="${UUID(2)}"`)[0], older = html.split(`data-capture="${UUID(2)}"`)[1];
  assert.ok(textOf(html).includes("Alcalinidad total"), "columna propia en el encabezado");
  assert.ok(newer.includes("88.5"));
  assert.equal(older.includes("88.5"), false);
});

// ---- P1-24 (por bobina) -----------------------------------------------------------------------------------------------------------------------------
const BOBBIN_ID = "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b";
const item = {
  bobbin: { id: BOBBIN_ID, code: "1", machine: { code: "MP1", name: "MP1" }, management_start_year: 2026, sequence_number: 1, start_time: "", end_time: "", diameter_mm: "1", weight_kg: "1", grammage_g_m2: null, number_of_cuts: "1", notes: null },
  production: { capture_id: "c", captured_at: "2026-10-08T14:05:09Z", operating_date: "2026-10-07", shift: { code: "DIA", name: "Día" }, work_order: { id: "w", number: "OT-1" },
    line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1031", description: "M1-BOBINA" } } },
  quality: { status: "pending" },
};
const bobbinScreen = (screen) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.QUALITY_BOBBIN_CANDIDATES[screen], bobbin: item, online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const bobbinEnvelope = (code, version, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-08T14:05:09Z", submitted_at: "2026-10-08T14:05:10Z", form: { code, version_number: version, name: "x" }, bobbin: { id: BOBBIN_ID, code: "1" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-07", work_order: { id: "w", number: "OT-1" },
  line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "M1-1031", description: "M1-BOBINA" } }, values });

test("P1-24 v4: «Crepado (%)» con la unidad %, misma clave, tipo y obligatoriedad; P1-25 conserva «Crepado» sin cambios", () => {
  const crepado = ui.P124_FIELDS.find((f) => f.key === "crepado");
  assert.deepEqual({ ...crepado }, { key: "crepado", label: "Crepado (%)", kind: "decimal", required: true, suffix: "%", renamedAt: { version: 4, previous: "Crepado" } });
  const text = textOf(bobbinScreen("p124"));
  assert.ok(text.includes("Crepado (%) *"), "obligatorio, con la etiqueta nueva");
  assert.match(text, /Crepado \(%\) \*[^A-Za-z]*%/, "la unidad % se muestra junto al campo");
  assert.equal(ui.P125_FIELDS.find((f) => f.key === "crepado").label, "Crepado");
  assert.equal(ui.P125_FIELDS.find((f) => f.key === "crepado").suffix, undefined);
  assert.equal(textOf(bobbinScreen("p125")).includes("Crepado (%)"), false, "P1-25 no cambia");
  assert.equal(ui.P124_FIELDS.length, 10);
});

test("P1-24 v4: Crepado no recibe rango ni conversión: el valor digitado viaja tal cual (coma → punto es la única normalización existente)", () => {
  const draft = Object.fromEntries(ui.P124_FIELDS.map((f) => [f.key, f.kind === "decimal" ? "1,5" : "nota"]));
  for (const typed of ["0", "12,5", "250", "-3"]) assert.equal(ui.P124.normalizeDraft({ ...draft, crepado: typed }).values.crepado, typed.replace(",", "."), typed);
  assert.match(ui.P124.normalizeDraft({ ...draft, crepado: "" }).errors.join(" "), /Crepado \(%\): es obligatorio/);
  assert.equal(ui.labelFor(ui.P124_FIELDS[0], 3), "Crepado");
  assert.equal(ui.labelFor(ui.P124_FIELDS[0], 4), "Crepado (%)");
});

test("historial de P1-24: la captura v3 se muestra como «Crepado» con su valor almacenado y la v4 como «Crepado (%)»", () => {
  const values = { crepado: "12.5", gramaje: "18", resistencia_longitudinal_humeda_centro: "0.05", resistencia_longitudinal_humeda_medio: "0.05", resistencia_longitudinal_humeda_extremo: "0.05", resistencia_transversal_humeda_centro: "0.03",
    resistencia_transversal_humeda_medio: "0.03", resistencia_transversal_humeda_extremo: "0.03", tiempo_de_curado_condicion: "5" };
  const captures = [bobbinEnvelope("VINTO-P1-24", 4, { ...values, crepado: "14.2" }, UUID(4)), bobbinEnvelope("VINTO-P1-24", 3, values, UUID(3))];
  const parsed = ui.parseQualityBobbinHistory(captures, { id: BOBBIN_ID, code: "1" }, { "VINTO-P1-24": ui.candidateViewer(ui.P124.parseCapture) });
  assert.ok(parsed, "el historial se lee");
  const load = ui.qualityHistoryLoad(BOBBIN_ID, { ok: true, status: 200, data: parsed });
  const html = server.renderToStaticMarkup(React.createElement(ui.QualityBobbinHistory, { item, resource: { status: "ready", data: load, refreshing: false }, refresh: noop, back: noop }));
  const parts = html.split("<li ");
  const find = (id) => parts.find((p) => p.includes(id)) ?? "";
  const [v4, v3] = [textOf(find(UUID(4))), textOf(find(UUID(3)))];
  assert.ok(v4.includes("Crepado (%)") && v4.includes("14.2"), "v4: etiqueta nueva y su valor");
  assert.ok(v3.includes("Crepado") && !v3.includes("Crepado (%)") && v3.includes("12.5"), "v3: etiqueta de entonces y su valor sin transformar");
});

// ---- Conversión: horas generales de producción -------------------------------------------------------------------------------------------------------
const CONTEXT = (machine) => ({ assignmentId: "44444444-4444-4444-8444-444444444444", workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1024", productName: "BOBINA 1024", machine, shift: "Día", date: "2026-10-06" });
const convScreen = (screen, machine) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.CONVERSION_CANDIDATES[screen], context: CONTEXT(machine), online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const forms = () => [["p112", ui.P112, "GAMBINI", 22, 3], ["p113", ui.P113, "OMET_I", 20, 2], ["p116", ui.P116, "OMET_I", 10, 2]];

test("P1-12, P1-13 y P1-16: sección «Horas de producción» con Hora inicio y Hora fin obligatorias (campos de hora), antes de los demás campos; un único par", () => {
  for (const [screen, , machine, total] of forms()) {
    const html = convScreen(screen, machine), text = textOf(html);
    assert.ok(text.includes("Horas de producción"), screen);
    assert.ok(text.includes("Hora inicio *") && text.includes("Hora fin *"), screen);
    assert.equal(count(html, 'type="time"'), 2, `${screen}: exactamente dos campos de hora (sin duplicados)`);
    assert.equal(count(text, "Hora inicio *"), 1);
    assert.match(text, /Hora local de planta \(HH:MM\), digitada\. No es la hora de registro del sistema ni la hora de un pallet\./);
    assert.ok(text.indexOf("Hora inicio *") < text.indexOf("Hora fin *"));
    const first = text.indexOf("Hora inicio *"), other = ui.CONVERSION_CANDIDATES[screen].form.fields.find((f) => f.key !== "hora_inicio" && f.key !== "hora_fin");
    assert.ok(first < text.indexOf(`${other.label}${other.required ? " *" : ""}`, first), `${screen}: las horas abren el formulario`);
    assert.equal(count(html, "<input") + count(html, "<textarea"), total, `${screen}: ${total} campos`);
  }
});

test("P1-12, P1-13 y P1-16: horas obligatorias HH:MM; aceptan 00:00 y 23:59; rechazan formatos incorrectos; fin anterior a inicio se acepta y se guarda tal cual", () => {
  for (const [, form] of forms()) {
    const draft = Object.fromEntries(form.fields.map((f) => [f.key, f.kind === "time" ? "07:30" : f.key === "formato" ? "4*12" : f.kind === "decimal" ? "1,5" : "dato"]));
    assert.equal(form.normalizeDraft(draft).ok, true);
    for (const [start, end] of [["00:00", "23:59"], ["23:30", "00:15"], ["10:00", "09:00"], ["08:00", "08:00"]]) {
      const check = form.normalizeDraft({ ...draft, hora_inicio: start, hora_fin: end });
      assert.equal(check.ok, true, `${start}-${end}`);
      assert.deepEqual([check.values.hora_inicio, check.values.hora_fin], [start, end], "tal como se digitó: sin UTC, sin duración, sin orden");
    }
    for (const key of ["hora_inicio", "hora_fin"]) {
      assert.match(form.normalizeDraft({ ...draft, [key]: "" }).errors.join(" "), new RegExp(`${key === "hora_inicio" ? "Hora inicio" : "Hora fin"}: es obligatori`));
      for (const bad of ["24:00", "12:60", "7:30", "abc", "12:5"]) assert.equal(form.normalizeDraft({ ...draft, [key]: bad }).ok, false, `${key}=${bad}`);
    }
  }
});

test("P1-12, P1-13 y P1-16: la captura de la versión anterior se lee sin horas y la nueva las trae; ninguna se inventa", () => {
  for (const [screen, form, machine, , version] of forms()) {
    const base = Object.fromEntries(form.fields.filter((f) => f.kind !== "time").map((f) => [f.key, f.kind === "decimal" ? "1.5" : "dato"]));
    const env = (v, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.CONVERSION_CANDIDATES[screen].code, version_number: v, name: "x" },
      machine: { code: machine, name: machine }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" },
      line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });
    const old = form.parseCapture(env(version - 1, base, UUID(2))), next = form.parseCapture(env(version, { ...base, hora_inicio: "06:30:00", hora_fin: "14:45:00" }, UUID(3)));
    assert.ok(old && next, screen);
    assert.equal("hora_inicio" in old.values, false, `${screen}: sin horas inventadas`);
    assert.deepEqual([next.values.hora_inicio, next.values.hora_fin], ["06:30:00", "14:45:00"]);
    assert.equal(form.parseCapture(env(version, base, UUID(4))), null, `${screen}: la versión nueva exige las horas`);
    const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.CONVERSION_CANDIDATES[screen], resource: { status: "ready", data: [next, old], refreshing: false }, refresh: noop }));
    const newer = html.split(`data-capture="${UUID(3)}"`)[1].split(`data-capture="${UUID(2)}"`)[0], older = html.split(`data-capture="${UUID(2)}"`)[1];
    assert.ok(textOf(html).includes("Hora inicio") && textOf(html).includes("Hora fin"), `${screen}: columnas de horas`);
    assert.ok(newer.includes("06:30:00") || newer.includes("06:30"), `${screen}: la nueva muestra sus horas`);
    assert.equal(older.includes("06:30"), false);
  }
});

test("las horas generales no sustituyen a las del pallet de la hipótesis anterior de P1-12 (sus etiquetas siguen distintas)", () => {
  assert.deepEqual({ ...ui.P112_LABELS }, { cantidad_jabas: "Cantidad de jabas", hora_inicio: "Hora inicio del pallet", hora_fin: "Hora fin del pallet" });
  for (const [, form] of forms()) assert.equal(form.fields.filter((f) => /pallet/i.test(f.key + f.label)).length, 0, "la definición vigente no tiene campos de pallet");
});

// ---- P1-11 (grupo repetible de bobinas, componente propio) ------------------------------------------------------------------------------------------
test("P1-11 v2: sección «Horas de producción» con Hora inicio y Hora fin obligatorias antes del grupo de bobinas, que sigue igual", () => {
  const html = server.renderToStaticMarkup(React.createElement(ui.P111CaptureForm, { context: CONTEXT("GAMBINI"), online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
  const text = textOf(html);
  assert.equal(count(html, 'type="time"'), 2);
  assert.ok(text.includes("Hora inicio *") && text.includes("Hora fin *"));
  assert.ok(text.indexOf("Hora inicio *") < text.indexOf("Bobinas declaradas"), "las horas van antes del grupo");
  assert.equal(count(html, "<select"), 1, "una fila inicial de bobinas, sin cambios");
  assert.deepEqual(ui.P111_HOUR_FIELDS.map((f) => f.key), ["hora_inicio", "hora_fin"]);
});

test("P1-11 v2: el borrador exige las horas HH:MM, las envía tal como se digitaron y no calcula duración ni orden", () => {
  const row = { numero_bobina: "B-1", posicion: "superior", saldo_inicial_kg: "1", ingreso_kg: "1", saldo_final_kg: "1" };
  const draft = (hours) => { const d = ui.emptyP111Draft(() => "k1"); return { ...d, ...hours, groups: { bobinas: [{ rowKey: "k1", cells: row }] } }; };
  for (const [start, end] of [["00:00", "23:59"], ["23:30", "00:15"], ["09:00", "09:00"]]) {
    const check = ui.normalizeP111Draft(draft({ hora_inicio: start, hora_fin: end }));
    assert.equal(check.ok, true, `${start}-${end}`);
    assert.deepEqual([check.values.hora_inicio, check.values.hora_fin], [start, end]);
  }
  assert.equal(ui.normalizeP111Draft(draft({ hora_inicio: "", hora_fin: "10:00" })).ok, false);
  assert.match(ui.normalizeP111Draft(draft({ hora_inicio: "", hora_fin: "10:00" })).errors.map((e) => e.message).join(" "), /Hora inicio: es obligatoria/);
  for (const bad of ["24:00", "12:60", "7:30", "abc"]) assert.equal(ui.normalizeP111Draft(draft({ hora_inicio: bad, hora_fin: "10:00" })).ok, false, bad);
});

test("P1-11: la captura v1 se lee sin horas, la v2 las exige, y el historial muestra ambas", () => {
  const rows = { bobinas: [{ numero_bobina: "B-1", posicion: "superior", saldo_inicial_kg: "1", ingreso_kg: "1", saldo_final_kg: "1" }] };
  const env = (v, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.P1_11_CODE, version_number: v, name: "x" },
    machine: { code: "GAMBINI", name: "Gambini" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" },
    line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });
  const old = ui.parseP111Capture(env(1, { _groups: rows }, UUID(2))), next = ui.parseP111Capture(env(2, { hora_inicio: "06:30:00", hora_fin: "14:45:00", _groups: rows }, UUID(3)));
  assert.ok(old && next);
  assert.equal("hora_inicio" in old.values, false);
  assert.equal(ui.parseP111Capture(env(2, { _groups: rows }, UUID(4))), null, "la versión 2 exige las horas");
  const html = server.renderToStaticMarkup(React.createElement(ui.P111History, { resource: { status: "ready", data: [next, old], refreshing: false }, refresh: noop }));
  const text = textOf(html);
  assert.ok(text.includes("Hora inicio") && text.includes("Hora fin"));
  assert.ok(text.includes("06:30") && text.includes("14:45"));
});

// ---- alcance: el seed solo trae las siete versiones nuevas y no se tocó TVC/ETL -----------------------------------------------------------------------
test("el seed publica exactamente P1-26 v3, P1-27 v2, P1-24 v4, P1-11 v2, P1-12 v3, P1-13 v2 y P1-16 v2 y P1-20 / P1-25 no cambian", () => {
  const manifest = JSON.parse(readFileSync(join(root, "backend/seed_data/manifest.json"), "utf8"));
  const versions = {};
  for (const entry of manifest.files.filter((f) => f.path.startsWith("forms/"))) versions[entry.path.slice(6, -5)] = JSON.parse(readFileSync(join(root, "backend/seed_data", entry.path), "utf8")).version_number;
  const expected = { "VINTO-P1-26": 3, "VINTO-P1-27": 2, "VINTO-P1-24": 4, "VINTO-P1-11": 2, "VINTO-P1-12": 3, "VINTO-P1-13": 2, "VINTO-P1-16": 2 };
  for (const [code, version] of Object.entries(expected)) assert.equal(versions[code], version, code);
  assert.equal(versions["VINTO-P1-20"], 1);
  assert.equal(versions["VINTO-P1-25"], 3);
  assert.equal(manifest.counts.form_fields, 472);
});
