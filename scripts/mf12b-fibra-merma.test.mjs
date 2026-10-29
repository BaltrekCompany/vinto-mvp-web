// node --test scripts/mf12b-fibra-merma.test.mjs
// MF-12B · pantallas reales (React + react-dom/server, sin navegador ni red): P1-04 versión 2 (un registro por consumo, listas dependientes y subtotal solo visual; MD_Ejec 17) y P1-16 versión 3 (una pesada por captura con
// listas desplegables, correlativo manual y horas de MF-11; MD_Ejec 44), con el historial por versión y el seed. Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del
// repositorio que se borra al terminar.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").split(String.fromCharCode(92)).join("/");
const workDir = join(root, `.tmp-mf12b-${process.pid}`);
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
  const rel = `.tmp-mf12b-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { CandidateHistory } from "@/components/vinto/candidate-history";',
    'export { BOBINAS_CANDIDATES } from "@/lib/vinto/bobinas-candidates";',
    'export { CONVERSION_CANDIDATES } from "@/lib/vinto/conversion-candidates";',
    'export { P104, P104_FIELDS, P104_LEGACY_FIELDS, P104_ORIGINS_BY_MATERIAL, P104_PRESENTATIONS_BY_MATERIAL, P1_04_CODE } from "@/lib/vinto/p1-04";',
    'export { P116, P116_FIELDS, P116_LEGACY_FIELDS, P116_TIPO_OPTIONS, P116_ORIGEN_OPTIONS, P116_PENDING, P1_16_CODE } from "@/lib/vinto/p1-16";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const CONTEXT = (machine) => ({ assignmentId: "44444444-4444-4444-8444-444444444444", workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1024", productName: "BOBINA 1024", machine, shift: "Día", date: "2026-10-06" });
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const count = (html, text) => html.split(text).length - 1;
const ASSIGNMENT = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const screen = (candidate, machine, attempt = null) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate, context: CONTEXT(machine), online: true, attempt, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const optionsOf = (html, label) => { // opciones (texto) del <select> cuya etiqueta es `label`
  const block = html.split(`>${label}`)[1]; if (!block) return null;
  const select = block.split("<select")[1]?.split("</select>")[0]; if (!select) return null;
  return [...select.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)].map((m) => [m[1], m[2]]);
};
const row = (code, version, values, id, machine = "MP1") => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code, version_number: version, name: "x" },
  machine: { code: machine, name: machine }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" },
  line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });
const cells = (html, id, headers) => { const tds = [...html.split(`data-capture="${id}"`)[1].split("</tr>")[0].matchAll(/<td[^>]*>([^<]*)<\/td>/g)].map((m) => m[1]); return (header) => tds[headers.indexOf(header)]; };
const headersOf = (html) => [...html.split("<thead>")[1].split("</thead>")[0].matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1]);

const P104_DRAFT = { hora_consumo: "07:30", material: "Recorte", origen: "Sauce Rancho", presentacion: "Fardo", cantidad_um: "12", peso_unitario_real: "25,5", observaciones: "" };

test("P1-04 v2: la pantalla muestra los siete campos con sus listas y el subtotal calculado en pantalla (no es un campo)", () => {
  const empty = screen(ui.BOBINAS_CANDIDATES.p104, "MP1"), text = textOf(empty);
  for (const label of ["Hora de consumo *", "Material *", "Origen *", "Presentación *", "Cantidad de UM *", "Peso unitario real *"]) assert.ok(text.includes(label), label);
  assert.ok(text.includes("Observaciones") && !text.includes("Observaciones *"), "las observaciones son opcionales");
  assert.equal(count(empty, 'type="time"'), 1);
  assert.equal(count(empty, "<select"), 3);
  assert.equal(count(empty, "<textarea"), 1);
  assert.deepEqual(optionsOf(empty, "Material *").map((o) => o[1]), ["Seleccionar…", "Fibra larga", "Fibra corta", "Recorte"]);
  assert.deepEqual(optionsOf(empty, "Origen *").map((o) => o[1]), ["Seleccionar…"], "sin material no hay orígenes");
  assert.ok(text.includes("Valores calculados en pantalla (no se guardan)") && text.includes("Subtotal"));
  assert.match(empty, /data-derived="subtotal_kg"[^>]*>.*?—/s, "sin datos el subtotal aparece vacío");
  assert.equal(/Subtotal \*/.test(text), false);
  // con un borrador (intento) el subtotal se calcula y las listas se filtran por el material elegido
  const attempt = ui.P104.createAttempt(P104_DRAFT, ASSIGNMENT, DEVICE, () => "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b").attempt;
  const filled = screen(ui.BOBINAS_CANDIDATES.p104, "MP1", attempt);
  assert.deepEqual(optionsOf(filled, "Origen *").map((o) => o[1]), ["Seleccionar…", "Sauce Rancho", "Máquina"], "Recorte: solo sus orígenes");
  assert.deepEqual(optionsOf(filled, "Presentación *").map((o) => o[1]), ["Seleccionar…", "Fardo"], "Recorte: solo Fardo");
  assert.match(textOf(filled), /Subtotal 306\.00 kg/);
});

test("P1-04 v2: las listas dependientes de la pantalla son exactamente las del MVP anterior para cada material", () => {
  for (const [material, origins] of Object.entries(ui.P104_ORIGINS_BY_MATERIAL)) {
    const attempt = ui.P104.createAttempt({ ...P104_DRAFT, material, origen: origins[0], presentacion: ui.P104_PRESENTATIONS_BY_MATERIAL[material][0] }, ASSIGNMENT, DEVICE, () => "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b").attempt;
    const html = screen(ui.BOBINAS_CANDIDATES.p104, "MP3", attempt);
    assert.deepEqual(optionsOf(html, "Origen *").map((o) => o[1]).slice(1), origins, `${material}: orígenes`);
    assert.deepEqual(optionsOf(html, "Presentación *").map((o) => o[1]).slice(1), ui.P104_PRESENTATIONS_BY_MATERIAL[material], `${material}: presentaciones`);
  }
});

test("historial de P1-04: una columna Subtotal (kg) calculada de lo guardado, los campos de la versión 1 como «versión anterior» y sin subtotal inventado en la versión 1", () => {
  const v2 = ui.P104.normalizeDraft({ ...P104_DRAFT, material: "Fibra larga", origen: "Laja", presentacion: "Caja" }).values;
  const v1 = { fibra_corta_detalle: "corta", fibra_larga_detalle: "larga", recorte_ph: "12.5", recorte_servilleta: "3 bultos", recorte_toalla: "2", materia_prima_ph: "340", materia_prima_servilleta: "10", materia_prima_toalla: "7", observaciones: "ok" };
  const parsed = [ui.P104.parseCapture(row(ui.P1_04_CODE, 2, { ...v2, hora_consumo: "07:30:00" }, "c2")), ui.P104.parseCapture(row(ui.P1_04_CODE, 1, v1, "c1"))];
  assert.ok(parsed.every(Boolean));
  const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.BOBINAS_CANDIDATES.p104, resource: { status: "ready", data: parsed, refreshing: false }, refresh: noop }));
  const headers = headersOf(html), text = textOf(html);
  for (const label of ["Hora de consumo", "Material", "Origen", "Presentación", "Cantidad de UM", "Peso unitario real", "Subtotal (kg)", "Fibra corta - detalle (versión anterior)", "Recorte PH (versión anterior)", "Materia prima toalla (versión anterior)"]) assert.ok(headers.includes(label), label);
  const [c2, c1] = [cells(html, "c2", headers), cells(html, "c1", headers)];
  assert.equal(c2("Subtotal (kg)"), "306.00");
  assert.equal(c2("Material"), "Fibra larga");
  assert.equal(c1("Subtotal (kg)"), "", "la versión 1 no tiene subtotal");
  assert.equal(c1("Material"), "", "ni material: no se inventa nada");
  assert.equal(c1("Recorte PH (versión anterior)"), "12.5");
  assert.equal(c1("Fibra larga - detalle (versión anterior)"), "larga", "valor histórico intacto");
  assert.ok(text.includes("Un registro por consumo"));
});

const P116_DRAFT = { hora_inicio: "06:30", hora_fin: "14:45", numero_correlativo: "M-0001", tipo_merma: "Hoja doble", origen_merma: "Logs", peso_merma_kg: "12,5", observacion: "" };

test("P1-16 v3: una pesada por captura con tipo (6 opciones), origen (3), peso real en kg, correlativo manual, observación opcional y las horas generales de MF-11", () => {
  const html = screen(ui.CONVERSION_CANDIDATES.p116, "GAMBINI"), text = textOf(html);
  for (const label of ["Hora inicio *", "Hora fin *", "Número correlativo *", "Tipo de merma *", "Origen de la merma *", "Peso real *"]) assert.ok(text.includes(label), label);
  assert.ok(text.includes("Observación") && !text.includes("Observación *"));
  assert.ok(text.includes("Horas de producción") && text.includes("Pesada de merma"));
  assert.equal(count(html, 'type="time"'), 2, "un único par de horas");
  assert.equal(count(html, "<select"), 2);
  assert.deepEqual(optionsOf(html, "Tipo de merma *").map((o) => o[1]), ["Seleccionar…", "Hoja doble", "Hoja simple", "Servilleta", "Toalla", "Cartón", "Plástico"]);
  assert.deepEqual(optionsOf(html, "Origen de la merma *").map((o) => o[1]), ["Seleccionar…", "Logs", "Cola", "Máquina"]);
  assert.ok(text.indexOf("Hora inicio *") < text.indexOf("Número correlativo *"), "las horas abren el formulario");
  assert.equal(/Hoja doble kg|Servilleta kg|Toalla kg|Cartón kg|Hoja simple kg|Plástico kg/.test(text), false, "las seis cantidades de las versiones 1 y 2 ya no se piden");
  assert.match(text, /no hay numeración automática ni se comprueba que sea distinto/, "el riesgo del correlativo manual es visible");
  assert.equal(ui.P116.emptyDraft().peso_merma_kg, "");
});

test("P1-16 v3: validación estructural (listas cerradas, peso decimal, correlativo y horas obligatorios, horas sin orden ni duración) y payload sin campos anteriores", () => {
  const ok = ui.P116.normalizeDraft(P116_DRAFT);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.values, { hora_inicio: "06:30", hora_fin: "14:45", numero_correlativo: "M-0001", tipo_merma: "Hoja doble", origen_merma: "Logs", peso_merma_kg: "12.5" }, "textos literales; coma → punto");
  for (const key of ["hora_inicio", "hora_fin", "numero_correlativo", "tipo_merma", "origen_merma", "peso_merma_kg"]) assert.match(ui.P116.normalizeDraft({ ...P116_DRAFT, [key]: "" }).errors.join(" "), /es obligatori|elige una/, key);
  for (const tipo of ui.P116_TIPO_OPTIONS) assert.equal(ui.P116.normalizeDraft({ ...P116_DRAFT, tipo_merma: tipo }).values.tipo_merma, tipo);
  for (const origen of ui.P116_ORIGEN_OPTIONS) assert.equal(ui.P116.normalizeDraft({ ...P116_DRAFT, origen_merma: origen }).values.origen_merma, origen);
  assert.equal(ui.P116.normalizeDraft({ ...P116_DRAFT, tipo_merma: "Otro" }).ok, false);
  assert.equal(ui.P116.normalizeDraft({ ...P116_DRAFT, origen_merma: "Otro" }).ok, false);
  for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(ui.P116.normalizeDraft({ ...P116_DRAFT, peso_merma_kg: bad }).errors.join(" "), /número decimal/, bad);
  for (const [start, end] of [["00:00", "23:59"], ["23:30", "00:15"], ["10:00", "09:00"], ["08:00", "08:00"]]) {
    const check = ui.P116.normalizeDraft({ ...P116_DRAFT, hora_inicio: start, hora_fin: end });
    assert.deepEqual([check.ok, check.values.hora_inicio, check.values.hora_fin], [true, start, end], "tal como se digitó: sin UTC, sin duración, sin orden");
  }
  const { attempt } = ui.P116.createAttempt(P116_DRAFT, ASSIGNMENT, DEVICE, () => "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b");
  for (const key of ["hoja_doble_kg", "servilleta_kg", "toalla_kg", "carton_kg", "hoja_simple_kg", "plastico_kg", "total_merma_kg"]) assert.equal(key in attempt.payload.values, false, key);
  assert.equal(ui.P116.normalizeDraft({ ...P116_DRAFT, numero_correlativo: "M-0001" }).ok, true, "el correlativo se acepta tal como se digita (sin unicidad impuesta aquí)");
});

test("historial de P1-16: v1 y v2 conservan sus seis cantidades como «versión anterior» y v3 muestra tipo, origen y peso; las antiguas no se convierten en pesadas", () => {
  const six = { hoja_doble_kg: "1", servilleta_kg: "2", toalla_kg: "3", carton_kg: "4", hoja_simple_kg: "5", plastico_kg: "6" };
  const v1 = { numero_correlativo: "C-1", ...six, observacion: "viejo" };
  const v2 = { hora_inicio: "06:30:00", hora_fin: "14:45:00", numero_correlativo: "C-2", ...six };
  const v3 = { ...ui.P116.normalizeDraft(P116_DRAFT).values, hora_inicio: "06:30:00", hora_fin: "14:45:00" };
  const parsed = [ui.P116.parseCapture(row(ui.P1_16_CODE, 3, v3, "c3")), ui.P116.parseCapture(row(ui.P1_16_CODE, 2, v2, "c2")), ui.P116.parseCapture(row(ui.P1_16_CODE, 1, v1, "c1"))];
  assert.ok(parsed.every(Boolean), "las tres versiones se leen");
  assert.equal(ui.P116.parseCapture(row(ui.P1_16_CODE, 3, v2, "x")), null, "una v3 exige tipo, origen y peso");
  const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.CONVERSION_CANDIDATES.p116, resource: { status: "ready", data: parsed, refreshing: false }, refresh: noop }));
  const headers = headersOf(html);
  for (const label of ["Hoja doble kg (versión anterior)", "Plástico kg (versión anterior)", "Tipo de merma", "Origen de la merma", "Peso real", "Hora inicio", "Número correlativo"]) assert.ok(headers.includes(label), label);
  const [c3, c2, c1] = ["c3", "c2", "c1"].map((id) => cells(html, id, headers));
  assert.deepEqual([c3("Tipo de merma"), c3("Origen de la merma"), c3("Peso real")], ["Hoja doble", "Logs", "12.5"]);
  assert.deepEqual([c3("Hoja doble kg (versión anterior)"), c3("Plástico kg (versión anterior)")], ["", ""], "la v3 no trae las cantidades antiguas");
  for (const old of [c2, c1]) {
    assert.deepEqual([old("Hoja doble kg (versión anterior)"), old("Servilleta kg (versión anterior)"), old("Plástico kg (versión anterior)")], ["1", "2", "6"], "valores originales intactos");
    assert.deepEqual([old("Tipo de merma"), old("Origen de la merma"), old("Peso real")], ["", "", ""], "no se convierten en pesadas ni se inventan datos");
  }
  assert.equal(c2("Hora inicio"), "06:30:00");
  assert.equal(c1("Hora inicio"), "", "la v1 no tiene horas");
});

test("seed: P1-04 v2 y P1-16 v3 con las opciones y campos de la pantalla; las demás versiones de MF-12A no cambian", () => {
  const manifest = JSON.parse(readFileSync(join(root, "backend/seed_data/manifest.json"), "utf8"));
  const forms = {};
  for (const entry of manifest.files.filter((f) => f.path.startsWith("forms/"))) forms[entry.path.slice(6, -5)] = JSON.parse(readFileSync(join(root, "backend/seed_data", entry.path), "utf8"));
  const expected = { "VINTO-P1-01": 4, "VINTO-P1-04": 2, "VINTO-P1-05": 2, "VINTO-P1-31": 2, "VINTO-P1-16": 3, "VINTO-P1-11": 2, "VINTO-P1-12": 3, "VINTO-P1-13": 2, "VINTO-P1-02": 1 };
  for (const [code, version] of Object.entries(expected)) assert.equal(forms[code].version_number, version, code);
  const p104 = forms["VINTO-P1-04"], p116 = forms["VINTO-P1-16"];
  assert.deepEqual(p104.fields.map((f) => f.key), ui.P104_FIELDS.map((f) => f.key));
  assert.deepEqual(p116.fields.map((f) => f.key), ui.P116_FIELDS.map((f) => f.key));
  const opts = (form, key) => form.fields.find((f) => f.key === key).options.map((o) => [o.option_key, o.label]);
  assert.deepEqual(opts(p104, "material").map((o) => o[0]), ["Fibra larga", "Fibra corta", "Recorte"]);
  assert.deepEqual(opts(p104, "origen").map((o) => o[0]), ["Laja", "Susano", "Dorado", "Cóndor", "Sauce Rancho", "Máquina"]);
  assert.deepEqual(opts(p104, "presentacion").map((o) => o[0]), ["Caja", "Fardo"]);
  assert.deepEqual(opts(p116, "tipo_merma").map((o) => o[0]), [...ui.P116_TIPO_OPTIONS]);
  assert.deepEqual(opts(p116, "origen_merma").map((o) => o[0]), [...ui.P116_ORIGEN_OPTIONS]);
  for (const [form, key] of [[p104, "material"], [p104, "origen"], [p104, "presentacion"], [p116, "tipo_merma"], [p116, "origen_merma"]]) assert.equal(opts(form, key).every(([k, l]) => k === l), true, `${key}: el valor guardado es el texto literal`);
  assert.deepEqual(p104.fields.map((f) => [f.value_type, f.required, f.unit]), [["time", true, null], ["text", true, null], ["text", true, null], ["text", true, null], ["integer", true, null], ["decimal", true, "KG"], ["textarea", false, null]]);
  assert.deepEqual(p116.fields.map((f) => [f.value_type, f.required, f.unit]), [["time", true, null], ["time", true, null], ["text", true, null], ["text", true, null], ["text", true, null], ["decimal", true, "KG"], ["textarea", false, null]]);
  assert.deepEqual(p104.machines, ["MP1", "MP3"]);
  assert.equal(p116.machines.length, 11);
  assert.equal(p104.fields.some((f) => /subtotal|total/.test(f.key)), false, "el subtotal no se persiste");
  assert.equal(manifest.counts.form_fields, 464);
});

test("MF-12B no toca la política central, las máquinas ni TVC/ETL", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
  assert.match(code("backend/app/capture_service.py"), /"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-31"/);
  assert.equal(/\bvinto-web\b|postgres-vinto|TVC/i.test(code("lib/vinto/p1-04.ts") + code("lib/vinto/p1-16.ts") + code("lib/vinto/exact-decimal.ts")), false);
  assert.equal(/localStorage|sessionStorage/.test(code("lib/vinto/p1-04.ts") + code("lib/vinto/exact-decimal.ts")), false);
});
