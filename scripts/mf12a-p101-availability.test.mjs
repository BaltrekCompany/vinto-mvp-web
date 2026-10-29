// node --test scripts/mf12a-p101-availability.test.mjs
// MF-12A · P1-01 versión 4 (MD_Ejec 9 y 14) y P1-05 / P1-31 versión 2 solo para MP3 (MD_Ejec 20). Pantallas reales (React + react-dom/server, sin navegador ni red): Release y Coating con sus frecuencias, campos rojos y azules,
// historial por versión sin mover valores entre claves y oferta de fichas según lo que publica el backend por máquina. Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del
// repositorio que se borra al terminar.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").split(String.fromCharCode(92)).join("/");
const workDir = join(root, `.tmp-mf12a-${process.pid}`);
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
  const rel = `.tmp-mf12a-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), [
    'export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";',
    'export { CandidateHistory } from "@/components/vinto/candidate-history";',
    'export { BOBINAS_CANDIDATES } from "@/lib/vinto/bobinas-candidates";',
    'export { candidateScreensFor, publishedCandidateScreens } from "@/lib/vinto/bobinas-offers";',
    'export { parseAvailability } from "@/lib/vinto/availability";',
    'export { P101, P101_FIELDS, P101_LEGACY_FIELDS, P101_SECTIONS, P101_PENDING, P1_01_CODE } from "@/lib/vinto/p1-01";',
  ].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const CONTEXT = (machine) => ({ assignmentId: "44444444-4444-4444-8444-444444444444", workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1024", productName: "BOBINA 1024", machine, shift: "Día", date: "2026-10-06" });
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const count = (html, text) => html.split(text).length - 1;
const screen = (machine) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.BOBINAS_CANDIDATES.p101, context: CONTEXT(machine), online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));

const RED = ["apertura_purga_prensa", "presion_aceite_guia_tela", "presion_aceite_lubricacion", "vacio_tela"];
const BLUE_DROPPED = ["vacio_prensa", "vacio_fieltro"];
const BLUE_REPLACED = { rodillos_quimicos: "boquillas_quimicos", vacio_pope: "velocidad_pope" };
const RETIRED = [...RED, ...BLUE_DROPPED, ...Object.keys(BLUE_REPLACED)];
const OPTIONAL = ["frecuencia_release", "dosificacion_coating", "frecuencia_coating"];
const LEGACY_LABELS = { apertura_purga_prensa: "Apertura purga prensa", presion_aceite_guia_tela: "Presión aceite guía tela", presion_aceite_lubricacion: "Presión aceite lubricación", vacio_tela: "Vacío tela", rodillos_quimicos: "Rodillos químicos", vacio_prensa: "Vacío prensa", vacio_pope: "Vacío pope", vacio_fieltro: "Vacío fieltro" };

test("P1-01 v4: Release y Coating con sus frecuencias son texto libre opcional, sin unidad, junto a «Dosificación Release» que no cambia", () => {
  const by = Object.fromEntries(ui.P101_FIELDS.map((f) => [f.key, f]));
  assert.equal(ui.P101_FIELDS.length, 70);
  assert.deepEqual({ ...by.dosificacion_release }, { key: "dosificacion_release", label: "Dosificación Release", kind: "text", required: true });
  for (const [key, label] of [["frecuencia_release", "Frecuencia Release"], ["dosificacion_coating", "Dosificación Coating"], ["frecuencia_coating", "Frecuencia Coating"]]) {
    assert.deepEqual({ ...by[key] }, { key, label, kind: "text", required: false, sinceVersion: 4 }, "texto, opcional y sin sufijo de unidad");
  }
  const keys = ui.P101_FIELDS.map((f) => f.key), i = keys.indexOf("dosificacion_release");
  assert.deepEqual(keys.slice(i, i + 5), ["dosificacion_release", ...OPTIONAL.slice(0, 1), "dosificacion_coating", "frecuencia_coating", "dosificacion_fosfato"]);
  const químicos = ui.P101_SECTIONS.find((s) => s.title === "Químicos");
  assert.deepEqual(químicos.keys.slice(0, 5), ["dosificacion_release", "frecuencia_release", "dosificacion_coating", "frecuencia_coating", "dosificacion_fosfato"], "dentro de la sección Químicos existente");
  assert.match(ui.P101_PENDING.find((n) => n.label === "Release y Coating").pending, /sin unidad, rango ni cálculo, y sin relación con P1-31 ni con el catálogo de químicos/);
});

test("P1-01 v4: los campos rojos y dos azules se retiran, los otros dos azules tienen clave nueva y no hay duplicados de velocidad", () => {
  const keys = ui.P101_FIELDS.map((f) => f.key), labels = ui.P101_FIELDS.map((f) => f.label);
  for (const gone of RETIRED) {
    assert.equal(keys.includes(gone), false, gone);
    assert.equal(ui.P101_SECTIONS.some((s) => s.keys.includes(gone)), false, gone);
    assert.equal(Object.keys(ui.P101.emptyDraft()).includes(gone), false, gone);
    const legacy = ui.P101_LEGACY_FIELDS.find((f) => f.key === gone);
    assert.ok(legacy, `${gone}: sigue legible en el historial`);
    assert.equal(legacy.required, false);
    assert.equal(legacy.label, LEGACY_LABELS[gone]);
  }
  const by = Object.fromEntries(ui.P101_FIELDS.map((f) => [f.key, f]));
  assert.deepEqual({ ...by.boquillas_quimicos }, { key: "boquillas_quimicos", label: "Boquillas químicos", kind: "text", required: true, sinceVersion: 4 });
  assert.deepEqual({ ...by.velocidad_pope }, { key: "velocidad_pope", label: "Velocidad pope", kind: "decimal", required: true, sinceVersion: 4 });
  assert.deepEqual(ui.P101_LEGACY_FIELDS.find((f) => f.key === "vacio_pope")?.kind, "decimal", "el valor histórico conserva su clave y su tipo");
  assert.equal(keys.filter((k) => k === "velocidad_secador").length, 1);
  assert.equal(keys.filter((k) => k === "velocidad_fieltro").length, 1);
  assert.equal(new Set(labels).size, labels.length, "ninguna etiqueta repetida");
  assert.equal(keys.some((k) => k.startsWith("vacio_")), false);
  assert.equal(ui.P101_LEGACY_FIELDS.length, 19, "11 de MF-09 y 8 de MF-12A");
});

test("P1-01 v4: la pantalla muestra los campos nuevos en MP1 y MP3, sin los retirados, con las siete secciones y 70 campos", () => {
  for (const machine of ["MP1", "MP3"]) {
    const html = screen(machine), text = textOf(html);
    assert.equal(count(html, "<input"), 70, `${machine}: 70 campos digitables`);
    for (const optional of ["Frecuencia Release", "Dosificación Coating", "Frecuencia Coating"]) {
      assert.ok(text.includes(optional), `${machine}: ${optional}`);
      assert.equal(text.includes(`${optional} *`), false, `${machine}: ${optional} es opcional`);
    }
    for (const required of ["Dosificación Release *", "Boquillas químicos *", "Velocidad pope *", "Velocidad secador *", "Velocidad fieltro *"]) assert.equal(count(text, required), 1, `${machine}: ${required} una sola vez`);
    for (const label of Object.values(LEGACY_LABELS)) assert.equal(text.includes(`${label} *`), false, `${machine}: ${label} ya no se pide`);
    for (const title of ["Materia prima, tanques y pulpeo", "Caudales, mezclas y consistencias", "Químicos", "Secador, presiones y temperaturas", "Prensa, aceite, vacío y filtros", "Limpieza y cambios de cuchillas", "Novedades"]) assert.ok(text.includes(title), title);
    // MD_Ejec 5 y 11 siguen fuera: nombres y orden de secciones y campos de tanques sin cambios
    for (const tank of ["Nivel tanque T-30 *", "Nivel tanque T-30 aguas *", "Nivel tanque T-30 aguas 2 *", "Nivel tanque T-30 accionamientos *"]) assert.ok(text.includes(tank), tank);
  }
  assert.deepEqual(ui.P101_SECTIONS.map((s) => s.title), ["Materia prima, tanques y pulpeo", "Caudales, mezclas y consistencias", "Químicos", "Secador, presiones y temperaturas", "Prensa, aceite, vacío y filtros", "Limpieza y cambios de cuchillas", "Novedades"]);
  const prensa = ui.P101_SECTIONS.find((s) => s.title === "Prensa, aceite, vacío y filtros");
  assert.deepEqual(prensa.keys, ["presion_aceite_alta_tela", "presion_agua_prensa", "presion_aire_prensa", "presion_vacio_prensa", "presion_fuelle_comando", "presion_fuelle_transmision", "caudal_agua_sello_1", "caudal_agua_sello_2", "caudal_agua_sello_3", "filtro_agua_prensa", "filtro_quimicos", "boquillas_quimicos", "velocidad_pope"]);
  assert.equal(ui.P101_SECTIONS.every((s) => s.keys.length > 0), true, "ninguna sección queda vacía");
});

test("el borrador: una captura sin los tres opcionales es válida, los vacíos no viajan y las claves retiradas nunca viajan", () => {
  const fill = Object.fromEntries(ui.P101_FIELDS.map((f) => [f.key, f.kind === "decimal" ? "1,5" : f.kind === "time" ? "06:30" : "texto"]));
  const full = ui.P101.createAttempt({ ...fill, frecuencia_release: "50 Hz", dosificacion_coating: "12", frecuencia_coating: "cada 2 h" }, "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d");
  assert.equal(full.ok, true);
  assert.equal(Object.keys(full.attempt.payload.values).length, 70);
  assert.deepEqual([full.attempt.payload.values.frecuencia_release, full.attempt.payload.values.dosificacion_coating, full.attempt.payload.values.frecuencia_coating], ["50 Hz", "12", "cada 2 h"], "texto tal como se digitó");
  const bare = ui.P101.createAttempt({ ...fill, frecuencia_release: "", dosificacion_coating: "  ", frecuencia_coating: "" }, "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d");
  assert.equal(bare.ok, true);
  assert.equal(Object.keys(bare.attempt.payload.values).length, 67);
  for (const key of [...OPTIONAL, ...RETIRED]) assert.equal(key in bare.attempt.payload.values, false, `${key}`);
  for (const key of ["boquillas_quimicos", "velocidad_pope"]) assert.equal(ui.P101.normalizeDraft({ ...fill, [key]: "" }).ok, false, `${key} es obligatorio`);
  assert.equal(ui.P101.normalizeDraft({ ...fill, velocidad_pope: "rápida" }).ok, false, "decimal");
});

const row = (version, values, id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: ui.P1_01_CODE, version_number: version, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: "a" }, work_order: { id: "w", number: "OT-1" },
  line: { id: "l", line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });
const withHours = (values) => Object.fromEntries(Object.entries(values).map(([k, v]) => [k, /^hora_cambio/.test(k) ? `${v}:00` : v]));

test("historial: la v3 conserva sus valores en las claves antiguas («versión anterior») y las claves nuevas quedan vacías; la v4 hace lo contrario", () => {
  const draft = Object.fromEntries(ui.P101_FIELDS.map((f) => [f.key, f.kind === "decimal" ? "2.5" : f.kind === "time" ? "06:30" : "texto v4"]));
  const v4 = withHours({ ...ui.P101.normalizeDraft({ ...draft, velocidad_pope: "310.5", boquillas_quimicos: "B-3", frecuencia_release: "50 Hz" }).values });
  const legacyValues = { apertura_purga_prensa: "OOOOO", presion_aceite_guia_tela: "11.1", presion_aceite_lubricacion: "12.2", vacio_tela: "13.3", rodillos_quimicos: "RODILLO-ANTIGUO", vacio_prensa: "14.4", vacio_pope: "-0.8", vacio_fieltro: "16.6" };
  const v3Base = Object.fromEntries(Object.entries(v4).filter(([k]) => ![...OPTIONAL, "boquillas_quimicos", "velocidad_pope"].includes(k)));
  const v3 = { ...v3Base, ...legacyValues };
  const parsed = [ui.P101.parseCapture(row(4, v4, "c4")), ui.P101.parseCapture(row(3, v3, "c3"))];
  assert.ok(parsed.every(Boolean), "ambas versiones se leen: la v3 no exige los obligatorios nuevos");
  assert.equal(ui.P101.parseCapture(row(4, v3, "x")), null, "una captura v4 sí los exige");
  assert.equal(ui.P101.parseCapture(row(4, Object.fromEntries(Object.entries(v4).filter(([k]) => !OPTIONAL.includes(k))), "y"))?.id, "y", "y no exige los tres opcionales");
  const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.BOBINAS_CANDIDATES.p101, resource: { status: "ready", data: parsed, refreshing: false }, refresh: noop }));
  const text = textOf(html);
  for (const label of Object.values(LEGACY_LABELS)) assert.ok(text.includes(`${label} (versión anterior)`), label);
  for (const label of ["Frecuencia Release", "Dosificación Coating", "Frecuencia Coating", "Boquillas químicos", "Velocidad pope"]) assert.ok(text.includes(label), label);
  const headers = [...html.split("<thead>")[1].split("</thead>")[0].matchAll(/<th[^>]*>([^<]*)<\/th>/g)].map((m) => m[1]);
  const cells = (id) => [...html.split(`data-capture="${id}"`)[1].split("</tr>")[0].matchAll(/<td[^>]*>([^<]*)<\/td>/g)].map((m) => m[1]);
  const at = (id, header) => cells(id)[headers.indexOf(header)];
  const [c3, c4] = [(h) => at("c3", h), (h) => at("c4", h)];
  assert.equal(c3("Vacío pope (versión anterior)"), "-0.8", "el valor histórico sigue en su clave original");
  assert.equal(c3("Velocidad pope"), "", "no se traslada a la clave nueva");
  assert.equal(c3("Rodillos químicos (versión anterior)"), "RODILLO-ANTIGUO");
  assert.equal(c3("Boquillas químicos"), "");
  assert.equal(c3("Frecuencia Release"), "");
  assert.equal(c4("Velocidad pope"), "310.5");
  assert.equal(c4("Boquillas químicos"), "B-3");
  assert.equal(c4("Frecuencia Release"), "50 Hz");
  assert.equal(c4("Vacío pope (versión anterior)"), "", "la v4 no trae la clave antigua");
});

const availability = (mp1, mp3) => ui.parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines: [{ code: "MP1", name: "MP1", forms: mp1 }, { code: "MP3", name: "MP3", forms: mp3 }] }] });
const form = (code, version) => ({ code, name: code, version_number: version });

test("oferta: las tarjetas salen de lo que el backend publica por máquina; P1-05 y P1-31 desaparecen de MP1 y siguen en MP3 sin lista estática", () => {
  const common = [form("VINTO-P1-01", 4), form("VINTO-P1-02", 1), form("VINTO-P1-04", 1), form("VINTO-P1-06", 2)];
  const both = availability([...common], [...common, form("VINTO-P1-05", 2), form("VINTO-P1-31", 2)]);
  assert.deepEqual(ui.candidateScreensFor(both, "MP1").sort(), ["p101", "p102", "p104"], "MP1 conserva P1-01, P1-02 y P1-04 (P1-06 no es una ficha candidata)");
  assert.deepEqual(ui.candidateScreensFor(both, "MP3").sort(), ["p101", "p102", "p104", "p105", "p131"]);
  assert.deepEqual(ui.publishedCandidateScreens(both), ["p104", "p105", "p131", "p102", "p101"], "el historial de P1-05 y P1-31 sigue disponible porque MP3 las publica");
  const before = availability([...common, form("VINTO-P1-05", 1), form("VINTO-P1-31", 1)], [...common, form("VINTO-P1-05", 1), form("VINTO-P1-31", 1)]);
  assert.ok(ui.candidateScreensFor(before, "MP1").includes("p105"), "antes de la versión 2 MP1 las ofrecía: el cambio sale del backend, no del frontend");
  const source = readFileSync(join(root, "lib/vinto/bobinas-offers.ts"), "utf8");
  assert.equal(/MP1|MP3/.test(source.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n")), false, "ninguna lista estática de máquinas en la decisión de qué se ofrece");
});

test("seed: solo P1-01 v4, P1-05 v2 y P1-31 v2 cambian; P1-05 y P1-31 conservan sus campos y quedan vinculadas solo a MP3", () => {
  const manifest = JSON.parse(readFileSync(join(root, "backend/seed_data/manifest.json"), "utf8"));
  const forms = {};
  for (const entry of manifest.files.filter((f) => f.path.startsWith("forms/"))) forms[entry.path.slice(6, -5)] = JSON.parse(readFileSync(join(root, "backend/seed_data", entry.path), "utf8"));
  const expected = { "VINTO-P1-01": 4, "VINTO-P1-02": 1, "VINTO-P1-03": 1, "VINTO-P1-04": 2, "VINTO-P1-05": 2, "VINTO-P1-06": 2, "VINTO-P1-24": 4, "VINTO-P1-26": 3, "VINTO-P1-27": 2, "VINTO-P1-31": 2, "VINTO-P1-11": 2, "VINTO-P1-12": 3, "VINTO-P1-13": 2, "VINTO-P1-16": 3 };
  for (const [code, version] of Object.entries(expected)) assert.equal(forms[code].version_number, version, code);
  assert.deepEqual(forms["VINTO-P1-05"].machines, ["MP3"]);
  assert.deepEqual(forms["VINTO-P1-31"].machines, ["MP3"]);
  assert.deepEqual(forms["VINTO-P1-01"].machines, ["MP1", "MP3"]);
  for (const code of ["VINTO-P1-02", "VINTO-P1-03", "VINTO-P1-04", "VINTO-P1-06"]) assert.deepEqual(forms[code].machines, ["MP1", "MP3"], code);
  assert.equal(forms["VINTO-P1-05"].fields.length, 10);
  assert.equal(forms["VINTO-P1-31"].fields.length, 9);
  assert.deepEqual(forms["VINTO-P1-01"].fields.map((f) => f.key), ui.P101_FIELDS.map((f) => f.key), "el seed y la pantalla declaran los mismos campos en el mismo orden");
  assert.equal(manifest.counts.form_fields, 464, "MF-12B: P1-04 v2 (7 campos) y P1-16 v3 (7 campos)");
});

test("MF-12A no toca TVC/ETL, migraciones ni la política central: solo seed, definiciones y pruebas", () => {
  const code = (file) => readFileSync(join(root, file), "utf8").split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
  assert.match(code("backend/app/capture_service.py"), /"VINTO-P1-01", "VINTO-P1-02", "VINTO-P1-04", "VINTO-P1-05", "VINTO-P1-31"/, "P1-05 y P1-31 siguen en la política central: el bloqueo sale de los vínculos de máquina de la versión 2");
  assert.equal(/["']MP[13]["']/.test(code("backend/app/capture_service.py") + code("backend/app/production_access.py")), false, "ninguna excepción por máquina en el código del backend");
  assert.equal(/\bvinto-web\b|postgres-vinto|TVC/i.test(code("lib/vinto/p1-01.ts") + code("lib/vinto/p1-05.ts") + code("lib/vinto/p1-31.ts")), false);
});
