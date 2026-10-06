#!/usr/bin/env node
// Deterministic exporter of the VINTO reference-data bundle (pilot: sector Bobinas, MP1 + MP3).
//
//   node scripts/export-seed-data.mjs            write backend/seed_data/
//   node scripts/export-seed-data.mjs --check    fail if the committed bundle is stale
//   node scripts/export-seed-data.mjs --out DIR  write somewhere else
//
// Reads the existing TypeScript sources (nothing is copied by hand) and writes canonical JSON.
// It never touches PostgreSQL. Requires Node with TypeScript type stripping enabled by default
// (>= 22.18, >= 23.6 or 24); the repository already requires Node >= 22.13.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const DEFAULT_OUT = join(ROOT, "backend", "seed_data");
export const SCHEMA_VERSION = 1;

const SOURCE_FILES = {
  catalogs: "lib/vinto/catalogs.ts",
  forms: "lib/vinto/form-definitions.ts",
  weights: "lib/vinto/product-weights.ts",
  recipes: "lib/vinto/recipes.ts",
  page: "app/page.tsx",
};

// Pilot scope (project decision). Everything below is validated against the sources.
const SECTOR_NAME = "Bobinas";
const SECTOR_CODE = "BOBINAS";
const MACHINES = ["MP1", "MP3"];
const PILOT_FORM = { legacyNumber: 6, legacyKey: "form_6_registro_de_control_de_fardos", code: "VINTO-P1-06" };
const NEXT_FORM = { legacyNumber: 3, legacyKey: "form_3_registro_de_produccion_de_bobinas", code: "VINTO-P1-03" };
const PROFILES = [
  ["JEFATURA", "Jefatura"],
  ["SUPERVISION", "Supervisión"],
  ["OPERACION", "Operación"],
  ["CALIDAD", "Calidad"],
  ["DATA_BALTREK", "Data Baltrek"],
];
// Declarative reference data requested for the pilot. Not read from the sources: the only
// source is the ctx() function in app/page.tsx, which is cross-checked below.
const SHIFTS = [["DIA", "Día", "07:00", "19:00"], ["NOCHE", "Noche", "19:00", "07:00"]];
const SHIFT_TIMEZONE = "America/La_Paz";
const SHIFT_VALID_FROM = "2026-01-01";
// Canonical F6 contract (project decision). Labels, units and option labels are read from app/page.tsx.
const F6_FIELDS = [
  { key: "cantidad_fardos", value_type: "integer", required: true },
  { key: "punto_merma", value_type: "text", required: true, options: ["bobina_rechazada", "recorte_maquina"] },
  { key: "tipo_producto", value_type: "text", required: true, options: ["servilleta", "hoja_doble", "hoja_simple"] },
  { key: "peso_kg", value_type: "decimal", required: true, unit: "KG" },
  { key: "observaciones", value_type: "textarea", required: false },
];

export class SeedExportError extends Error {}

const fail = (message) => { throw new SeedExportError(message); };
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");
const slug = (text) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const json = (value) => JSON.stringify(value, null, 2) + "\n";

function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export async function loadSources(root = ROOT) {
  const texts = {};
  for (const [name, rel] of Object.entries(SOURCE_FILES)) {
    const path = join(root, rel);
    if (!existsSync(path)) fail(`Fuente ausente: ${rel}`);
    texts[name] = readFileSync(path, "utf8").replace(/\r\n/g, "\n"); // CRLF checkouts hash the same
  }
  const load = async (rel) => {
    try { return await import(pathToFileURL(join(root, rel)).href); }
    catch (error) {
      fail(`No se pudo importar ${rel} (${error.code ?? error.name}). Usa Node >= 22.18 / 24, con type stripping.`);
    }
  };
  const catalogs = await load(SOURCE_FILES.catalogs);
  const forms = await load(SOURCE_FILES.forms);
  const weights = await load(SOURCE_FILES.weights);
  const recipes = await load(SOURCE_FILES.recipes);
  return {
    texts,
    productsByMachine: catalogs.PRODUCTS_BY_MACHINE,
    materials: catalogs.MATERIALS,
    formDefinitions: forms.FORM_DEFINITIONS,
    nominalWeights: weights.NOMINAL_WEIGHT_BY_PRODUCT,
    recipes: recipes.RECIPES_BY_PRODUCT,
  };
}

// ---- extraction from app/page.tsx (fails loudly if the layout changes) -------------------------

function groupMachines(page, sector) {
  const match = page.match(new RegExp(`const GROUPS\\b[^=]*=\\s*\\{[^;]*?\\b${sector}:\\s*\\[([^\\]]*)\\]`));
  if (!match) fail(`No se encontró GROUPS.${sector} en app/page.tsx`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function functionBody(page, name) {
  const start = page.indexOf(`function ${name}(`);
  if (start < 0) fail(`No se encontró la función ${name} en app/page.tsx`);
  const next = page.indexOf("\nfunction ", start + 1);
  return page.slice(start, next < 0 ? undefined : next);
}

function f6Override(page) {
  const start = page.indexOf(`f.id === "${PILOT_FORM.legacyKey}"`);
  if (start < 0) fail("F6: no se encontró su override en effectiveForms() de app/page.tsx");
  const next = page.indexOf("if (f.id", start + 10);
  const block = page.slice(start, next < 0 ? undefined : next);
  const fields = {};
  for (const m of block.matchAll(/fld\("(\w+)",\s*"([^"]+)",\s*"(\w+)"(?:,\s*(true|false))?(?:,\s*"([^"]*)")?\)/g)) {
    fields[m[1]] = { label: m[2], type: m[3], required: m[4] !== "false", unit: m[5] ?? null };
  }
  return fields;
}

function f6Choices(page) {
  const body = functionBody(page, "BobbinBales");
  const choices = {};
  for (const key of ["punto_merma", "tipo_producto"]) {
    const m = body.match(new RegExp(`<Choice label="([^"]+)" value=\\{v\\.${key}\\}\\s+set=\\{[^}]*\\}\\s+options=\\{\\[([^\\]]*)\\]\\}`));
    if (!m) fail(`F6: BobbinBales ya no define el selector ${key}`);
    choices[key] = { label: m[1], options: [...m[2].matchAll(/"([^"]+)"/g)].map((o) => o[1]) };
  }
  for (const key of ["cantidad_fardos", "peso_kg"]) {
    if (!body.includes(`v.${key}`)) fail(`F6: BobbinBales ya no escribe ${key}`);
  }
  return choices;
}

// ---- bundle construction ------------------------------------------------------------------------

export function buildBundle(sources) {
  const { texts, productsByMachine, materials, formDefinitions, nominalWeights, recipes } = sources;
  const warnings = [];
  const warn = (code, severity, message, count) =>
    warnings.push(count === undefined ? { code, severity, message } : { code, severity, message, count });

  // Sector and machines
  const groupBobinas = groupMachines(texts.page, SECTOR_NAME);
  for (const machine of MACHINES) {
    if (!productsByMachine || !(machine in productsByMachine)) fail(`La máquina ${machine} no existe en PRODUCTS_BY_MACHINE`);
    if (!groupBobinas.includes(machine)) fail(`La máquina ${machine} no pertenece a ${SECTOR_NAME} en GROUPS de app/page.tsx`);
  }
  if (groupBobinas.length !== MACHINES.length || groupBobinas.some((m, i) => m !== MACHINES[i])) {
    fail(`GROUPS.${SECTOR_NAME} es [${groupBobinas}] y el alcance del piloto es [${MACHINES}]`);
  }

  // Materials index (authoritative for material class and for "is also a material")
  const materialByCode = new Map();
  for (const item of materials) {
    const known = materialByCode.get(item.code);
    if (known && (known.name !== item.name || known.unit !== item.unit || known.className !== item.className)) {
      fail(`MATERIALS tiene el código ${item.code} duplicado con datos distintos`);
    }
    materialByCode.set(item.code, item);
  }

  // Articles (authoritative for description and unit: PRODUCTS_BY_MACHINE)
  const articles = new Map();
  const relations = [];
  for (const machine of MACHINES) {
    const seenInMachine = new Set();
    for (const product of productsByMachine[machine]) {
      const { code, name, unit } = product;
      if (typeof code !== "string" || !code.trim()) fail(`${machine}: producto sin código`);
      if (typeof name !== "string" || !name.trim()) fail(`${machine}/${code}: producto sin nombre`);
      if (typeof unit !== "string" || !unit.trim()) fail(`${machine}/${code}: artículo sin unidad (obligatoria)`);
      const known = articles.get(code);
      if (known && (known.name !== name || known.unit !== unit)) {
        fail(`Código de artículo ${code} duplicado con datos incompatibles (${known.machines[0]}: "${known.name}"/${known.unit} frente a ${machine}: "${name}"/${unit})`);
      }
      if (seenInMachine.has(code)) { warn("DUPLICATE_PRODUCT_IN_MACHINE", "warning", `${machine} repite el producto ${code} con datos idénticos; se deduplica`); continue; }
      seenInMachine.add(code);
      if (known) known.machines.push(machine);
      else articles.set(code, { code, name, unit, machines: [machine] });
      relations.push({ article_code: code, machine_code: machine });
    }
  }

  const unitCodes = [...new Set([...articles.values()].map((a) => a.unit))].sort(cmp);
  const classNames = new Map(); // slug -> className
  let alsoMaterial = 0, withoutMaterial = 0, withWeight = 0;
  const articleItems = [...articles.values()].sort((a, b) => cmp(a.code, b.code)).map((a) => {
    const material = materialByCode.get(a.code) ?? null;
    if (material) {
      alsoMaterial++;
      if (material.name !== a.name || material.unit !== a.unit) {
        warn("MATERIAL_CONFLICT", "warning", `${a.code}: PRODUCTS_BY_MACHINE ("${a.name}"/${a.unit}) difiere de MATERIALS ("${material.name}"/${material.unit}); se conserva PRODUCTS_BY_MACHINE`);
      }
    } else withoutMaterial++;
    let classCode = null;
    if (material?.className) {
      classCode = slug(material.className);
      if (!classCode) fail(`${a.code}: className de MATERIALS no produce un código válido`);
      if (classNames.has(classCode) && classNames.get(classCode) !== material.className) {
        fail(`Las clases "${classNames.get(classCode)}" y "${material.className}" producen el mismo código ${classCode}`);
      }
      classNames.set(classCode, material.className);
    }
    const weight = nominalWeights?.[a.code];
    if (weight !== undefined && !(typeof weight === "number" && weight >= 0)) fail(`${a.code}: peso nominal inválido`);
    if (weight !== undefined) withWeight++;
    return {
      code: a.code,
      is_product: true,
      is_material: material !== null,
      version: {
        version_number: 1,
        description: a.name,
        unit: a.unit,
        material_class: classCode,
        nominal_weight_kg: weight ?? null,
      },
    };
  });
  const articleCodes = new Set(articleItems.map((a) => a.code));
  for (const r of relations) if (!articleCodes.has(r.article_code)) fail(`Relación article-machine hacia un artículo inexistente: ${r.article_code}`);
  relations.sort((a, b) => cmp(a.article_code, b.article_code) || cmp(a.machine_code, b.machine_code));

  // Forms
  const find = (spec) => {
    const form = (formDefinitions ?? []).find((f) => f.legacyNumber === spec.legacyNumber);
    if (!form) fail(`No se encontró el formulario ${spec.legacyKey} en FORM_DEFINITIONS`);
    if (form.id !== spec.legacyKey || form.code !== spec.code) fail(`El formulario ${spec.legacyNumber} es ${form.id}/${form.code}, se esperaba ${spec.legacyKey}/${spec.code}`);
    return form;
  };
  const f6 = find(PILOT_FORM), f3 = find(NEXT_FORM);
  if (f6.area !== "production") fail(`F6 debe tener area production y tiene ${f6.area}`);
  const allowed = new Set(f6.allowedMachineIds.map((m) => m.toLowerCase()));
  for (const machine of MACHINES) if (!allowed.has(machine.toLowerCase())) fail(`F6 no admite la máquina ${machine} en allowedMachineIds`);

  const override = f6Override(texts.page);
  const choices = f6Choices(texts.page);
  const unitFromSource = (override.peso_kg?.unit ?? "").toUpperCase();
  const fields = F6_FIELDS.map((spec, index) => {
    const fromOverride = override[spec.key];
    const fromChoice = choices[spec.key];
    const label = fromOverride?.label ?? fromChoice?.label;
    if (!label) fail(`F6: no se encontró la etiqueta de ${spec.key} en app/page.tsx`);
    if (fromOverride && fromOverride.required !== spec.required) fail(`F6: ${spec.key} cambió su obligatoriedad en app/page.tsx`);
    const field = { key: spec.key, label, value_type: spec.value_type, source: "manual", required: spec.required, unit: spec.unit ?? null, display_order: index + 1 };
    if (spec.key === "peso_kg" && unitFromSource !== spec.unit) fail(`F6: la unidad de peso_kg en app/page.tsx es "${unitFromSource}", se esperaba ${spec.unit}`);
    if (spec.unit && !unitCodes.includes(spec.unit)) fail(`F6: la unidad ${spec.unit} no está entre las unidades del alcance (${unitCodes})`);
    if (spec.options) {
      if (new Set(spec.options).size !== spec.options.length) fail(`F6: opciones duplicadas en ${spec.key}`);
      if (fromChoice.options.length !== spec.options.length || new Set(fromChoice.options).size !== fromChoice.options.length) {
        fail(`F6: ${spec.key} tiene ${fromChoice.options.length} opciones en app/page.tsx y el contrato canónico espera ${spec.options.length} distintas`);
      }
      field.options = spec.options.map((option_key, i) => ({ option_key, label: fromChoice.options[i], display_order: i + 1 }));
    }
    return field;
  });
  for (const key of ["cantidad_fardos", "peso_kg", "observaciones"]) if (!override[key]) fail(`F6: el override de app/page.tsx ya no define ${key}`);
  const extra = Object.keys(override).filter((k) => !F6_FIELDS.some((f) => f.key === k));
  if (extra.length) fail(`F6: app/page.tsx define campos fuera del contrato canónico: ${extra}`);
  if (fields.length !== 5 || fields.reduce((n, f) => n + (f.options?.length ?? 0), 0) !== 5) fail("F6 debe tener exactamente 5 campos y 5 opciones");

  const definition = {
    legacy_key: f6.id,
    code: f6.code,
    legacy_number: f6.legacyNumber,
    name: f6.name,
    area: "production",
    workflow: f6.workflowId,
    version_number: 1,
    machines: [...MACHINES],
    groups: [],
    fields,
  };
  const form = { schema_version: SCHEMA_VERSION, ...definition, definition_checksum: sha256(canonical(definition)) };

  // Workflows used by F6/F3 only
  const workflowCodes = [...new Set([f6.workflowId, f3.workflowId])].sort(cmp);
  if (workflowCodes.some((c) => typeof c !== "string" || !c)) fail("Workflow sin código en F6/F3");

  // Shifts: declarative, cross-checked against ctx() in app/page.tsx
  if (!/else if \(h < 7 \|\| h >= 19\)/.test(texts.page)) {
    warn("SHIFT_SOURCE_CHANGED", "warning", "ctx() en app/page.tsx ya no define Noche como h<7 || h>=19; revisar los horarios declarativos de Bobinas");
  }

  // ---- entity files ----
  const wrap = (entity, items) => ({ schema_version: SCHEMA_VERSION, entity, items });
  const files = new Map();
  files.set("units.json", json(wrap("unit", unitCodes.map((code) => ({ code, label: code })))));
  files.set("material_classes.json", json(wrap("material_class", [...classNames].sort((a, b) => cmp(a[0], b[0])).map(([code, name]) => ({ code, name })))));
  files.set("sectors.json", json(wrap("sector", [{ code: SECTOR_CODE, name: SECTOR_NAME }])));
  files.set("machines.json", json(wrap("machine", MACHINES.map((code) => ({ code, name: code, sector: SECTOR_CODE })))));
  files.set("articles.json", json(wrap("article", articleItems)));
  files.set("article_machines.json", json(wrap("article_machine", relations)));
  files.set("profiles.json", json(wrap("profile", PROFILES.map(([code, name]) => ({ code, name })))));
  files.set("workflows.json", json(wrap("workflow_definition", workflowCodes.map((code) => ({ code, name: code })))));
  files.set("shifts.json", json({
    schema_version: SCHEMA_VERSION,
    entity: "shift",
    note: "Vigencia valid_from provisional (fecha técnica). La vigencia funcional real debe recibirse antes de producción. No se define valid_to.",
    shifts: SHIFTS.map(([code, name]) => ({ code, name })),
    schedules: SHIFTS.map(([shift, , starts_at, ends_at]) => ({
      shift, sector: SECTOR_CODE, starts_at, ends_at, timezone: SHIFT_TIMEZONE, valid_from: SHIFT_VALID_FROM, valid_to: null,
    })),
  }));
  files.set(`forms/${PILOT_FORM.code}.json`, json(form));

  // ---- warnings and out-of-scope information ----
  if (alsoMaterial) warn("ARTICLE_ALSO_MATERIAL", "info", "Artículos del alcance que también figuran en MATERIALS (is_product e is_material)", alsoMaterial);
  if (withoutMaterial) warn("ARTICLE_NOT_IN_MATERIALS", "info", "Artículos del alcance ausentes de MATERIALS: sin clase de material", withoutMaterial);
  if (articleItems.length - withWeight) warn("NOMINAL_WEIGHT_MISSING", "info", "Artículos sin peso nominal en product-weights.ts; nominal_weight_kg queda null (no se inventa)", articleItems.length - withWeight);
  warn("UNIT_LABEL_PLACEHOLDER", "warning", "unit.label usa el código de la fuente (no existe etiqueta real); Data Baltrek debe proveerla", unitCodes.length);
  warn("MACHINE_NAME_FROM_CODE", "warning", "machine.name usa el código de la fuente (no existe otro nombre)", MACHINES.length);
  warn("WORKFLOW_NAME_PLACEHOLDER", "warning", "workflow_definition.name usa el código de la fuente (no existe nombre real)", workflowCodes.length);
  warn("SHIFT_VALIDITY_PROVISIONAL", "warning", `valid_from=${SHIFT_VALID_FROM} y timezone=${SHIFT_TIMEZONE} son datos técnicos provisionales; producción debe recibir la vigencia funcional real`);
  const otherMachines = Object.keys(productsByMachine).filter((m) => !MACHINES.includes(m));
  warn("OUT_OF_SCOPE_MACHINES", "info", "Máquinas de PRODUCTS_BY_MACHINE fuera del piloto (otros frentes)", otherMachines.length);
  warn("OUT_OF_SCOPE_FORMS", "info", `Definiciones de FORM_DEFINITIONS fuera del piloto; F3 (${NEXT_FORM.code}) queda como definición pendiente`, formDefinitions.length - 1);
  warn("OUT_OF_SCOPE_RECIPES", "info", "Artículos del alcance con receta en recipes.ts; las recetas no se exportan en este piloto", articleItems.filter((a) => recipes?.[a.code]).length);
  warn("OUT_OF_SCOPE_MATERIALS", "info", "Entradas de MATERIALS que no son artículos del alcance", materials.length - alsoMaterial);
  warnings.sort((a, b) => cmp(a.code, b.code) || cmp(a.message, b.message));

  const counts = {
    units: unitCodes.length,
    material_classes: classNames.size,
    sectors: 1,
    machines: MACHINES.length,
    articles: articleItems.length,
    article_machines: relations.length,
    articles_also_material: alsoMaterial,
    articles_with_nominal_weight: withWeight,
    profiles: PROFILES.length,
    workflows: workflowCodes.length,
    shifts: SHIFTS.length,
    shift_schedules: SHIFTS.length,
    forms: 1,
    form_fields: fields.length,
    form_options: fields.reduce((n, f) => n + (f.options?.length ?? 0), 0),
  };
  const manifest = {
    schema_version: SCHEMA_VERSION,
    bundle: "vinto-reference-bobinas-pilot",
    scope: { sector: SECTOR_NAME, machines: [...MACHINES], first_form: PILOT_FORM.code },
    generated_from: Object.entries(SOURCE_FILES).map(([name, path]) => ({ path, sha256: sha256(texts[name]) })).sort((a, b) => cmp(a.path, b.path)),
    files: [...files].sort((a, b) => cmp(a[0], b[0])).map(([path, text]) => ({ path, sha256: sha256(text), bytes: Buffer.byteLength(text, "utf8") })),
    counts,
    pending_forms: [{ code: NEXT_FORM.code, legacy_key: f3.id, name: f3.name, workflow: f3.workflowId, status: "canonical_definition_pending" }],
    authority_rules: {
      article_description_and_unit: "PRODUCTS_BY_MACHINE",
      article_is_material_and_material_class: "MATERIALS",
      nominal_weight_kg: "product-weights.ts (null when absent)",
      sector_and_machines: "GROUPS in app/page.tsx",
      f6_labels_units_and_options: "app/page.tsx (effectiveForms override and BobbinBales)",
    },
    warnings,
  };
  const bundle = { files, manifest };
  validateBundle(bundle);
  files.set("manifest.json", json(manifest));
  return { files, manifest };
}

// Structural checks over the generated data (also used by tests against mutated bundles).
export function validateBundle({ files, manifest }) {
  const read = (name) => JSON.parse(files.get(name));
  const machines = read("machines.json").items.map((m) => m.code);
  const articles = read("articles.json").items;
  const codes = new Set();
  for (const a of articles) {
    if (codes.has(a.code)) fail(`Código de artículo duplicado en el bundle: ${a.code}`);
    codes.add(a.code);
    if (!a.version.unit) fail(`Artículo sin unidad: ${a.code}`);
  }
  for (const r of read("article_machines.json").items) {
    if (!codes.has(r.article_code)) fail(`Relación article-machine hacia un artículo inexistente: ${r.article_code}`);
    if (!machines.includes(r.machine_code)) fail(`Relación article-machine hacia una máquina inexistente: ${r.machine_code}`);
  }
  const unitCodes = new Set(read("units.json").items.map((u) => u.code));
  for (const a of articles) if (!unitCodes.has(a.version.unit)) fail(`Unidad no declarada: ${a.version.unit}`);
  const form = JSON.parse(files.get(`forms/${PILOT_FORM.code}.json`));
  for (const f of form.fields) {
    const keys = (f.options ?? []).map((o) => o.option_key);
    if (new Set(keys).size !== keys.length) fail(`Opciones duplicadas en ${f.key}`);
  }
  if (manifest) {
    for (const f of manifest.files) if (sha256(files.get(f.path)) !== f.sha256) fail(`Checksum inconsistente en el manifest: ${f.path}`);
  }
}

// ---- IO ---------------------------------------------------------------------------------------

export function writeBundle(outDir, files) {
  mkdirSync(join(outDir, "forms"), { recursive: true });
  for (const [path, text] of files) writeFileSync(join(outDir, path), text, { encoding: "utf8" });
  for (const dir of [outDir, join(outDir, "forms")]) { // drop stale generated files
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const rel = relative(outDir, join(dir, entry.name)).replaceAll("\\", "/");
      if (entry.isFile() && entry.name.endsWith(".json") && !files.has(rel)) rmSync(join(dir, entry.name));
    }
  }
}

export function compareWithDisk(outDir, files) {
  const stale = [];
  for (const [path, text] of files) {
    const target = join(outDir, path);
    if (!existsSync(target) || readFileSync(target, "utf8").replace(/\r\n/g, "\n") !== text) stale.push(path);
  }
  return stale;
}

async function main(argv) {
  const outIndex = argv.indexOf("--out");
  const outDir = outIndex >= 0 ? resolve(argv[outIndex + 1] ?? fail("--out requiere un directorio")) : DEFAULT_OUT;
  const { files, manifest } = buildBundle(await loadSources());
  if (argv.includes("--check")) {
    const stale = compareWithDisk(outDir, files);
    if (stale.length) { console.error(`Bundle desactualizado: ${stale.join(", ")}. Ejecuta node scripts/export-seed-data.mjs`); return 1; }
    console.log(`Bundle al día (${files.size} archivos).`);
    return 0;
  }
  writeBundle(outDir, files);
  console.log(`Bundle escrito: ${files.size} archivos en ${relative(ROOT, outDir) || "."}`);
  for (const [name, value] of Object.entries(manifest.counts)) console.log(`  ${name}: ${value}`);
  for (const w of manifest.warnings) console.log(`  [${w.severity}] ${w.code}${w.count === undefined ? "" : ` (${w.count})`}: ${w.message}`);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (error) => {
    if (error instanceof SeedExportError) { console.error(`Exportación detenida: ${error.message}`); process.exitCode = 1; }
    else throw error;
  });
}
