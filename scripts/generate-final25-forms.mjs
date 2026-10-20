// CLOUD-DEP G.12-C4-FINAL25: genera backend/seed_data/forms/VINTO-P1-{11,12,13,16,29}.json, los 5
// formularios candidatos que cierran los 25 (sector CONVERSION + TUBETERA ya incorporados por
// merge-conversion-masters.mjs / el sector REBOBINADO existente).
//
// P1-12/13/16 reutilizan el mismo patrón que generate-candidate-forms.mjs: el array FieldSpec[] ya
// agregado a lib/vinto/p1-{12,13,16}.ts (el subconjunto MANUAL EXACTO de su definición legacy en
// form-definitions.ts -- 20/18/8 campos respectivamente -- reemplazando la hipótesis de prueba que
// tenían antes esos mismos archivos, que queda como código muerto sin eliminar).
//
// P1-11/29 son los primeros formularios candidatos con GRUPOS repetibles reales (antes rechazados por
// bundle.py/reference.py; ver ese cambio en el mismo commit). Sus campos y grupos vienen literalmente
// de P111_GROUPS/P129_GROUPS/P129_SIMPLE_FIELDS (lib/vinto/p1-11.ts, p1-29.ts) -- las mismas
// especificaciones (GroupSpec) ya usadas por sus componentes de captura reales. P1-11 no exporta un
// array de campos simples: su único campo no agrupado es `observaciones` (opcional), tal como declara
// el tipo P111Simple y emptyP111Draft en ese mismo archivo -- no se inventa ningún otro campo simple.
// `unit` de un GroupFieldSpec es solo una etiqueta de visualización (igual que `suffix` en FieldSpec):
// nunca se traduce a una referencia real de vinto_master.unit (unit del JSON generado siempre es null).
//
// Uso: node scripts/generate-final25-forms.mjs
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SEED_DIR = `${ROOT}backend/seed_data`;
const MANIFEST_PATH = `${SEED_DIR}/manifest.json`;

const KIND_TO_VALUE_TYPE = { text: "text", textarea: "textarea", decimal: "decimal", time: "time", integer: "integer", choice: "text", date: "date" };

const FLAT_FORMS = [
  { code: "VINTO-P1-12", module: "p1-12", fieldsExport: "P112_FIELDS", codeExport: "P1_12_CODE", machines: ["GAMBINI", "SINCRO_II", "SINCRO_III"] },
  { code: "VINTO-P1-13", module: "p1-13", fieldsExport: "P113_FIELDS", codeExport: "P1_13_CODE",
    machines: ["OMET_I", "OMET_II", "8_2", "8_5", "8002", "SERV_4", "WALLY", "PANUELERA"] },
  { code: "VINTO-P1-16", module: "p1-16", fieldsExport: "P116_FIELDS", codeExport: "P1_16_CODE",
    machines: ["GAMBINI", "SINCRO_II", "SINCRO_III", "OMET_I", "OMET_II", "8_2", "8_5", "8002", "SERV_4", "WALLY", "PANUELERA"] },
];

const GROUPED_FORMS = [
  { code: "VINTO-P1-11", module: "p1-11", groupsExport: "P111_GROUPS", codeExport: "P1_11_CODE", machines: ["GAMBINI", "SINCRO_II", "SINCRO_III"],
    // Único campo simple de P1-11: `observaciones` (opcional), per P111Simple/emptyP111Draft -- ningún otro existe.
    simpleFields: [{ key: "observaciones", label: "Observaciones", kind: "textarea", required: false }] },
  { code: "VINTO-P1-29", module: "p1-29", groupsExport: "P129_GROUPS", codeExport: "P1_29_CODE", machines: ["TUBETERA"], simpleFieldsExport: "P129_SIMPLE_FIELDS" },
];

function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(",")}}`;
}

function sha256Hex(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function toField(f, index) {
  const value_type = KIND_TO_VALUE_TYPE[f.kind];
  if (!value_type) throw new Error(`${f.key}: kind desconocido ${f.kind}`);
  const field = { key: f.key, label: f.label, value_type, source: "manual", required: f.required, unit: null, display_order: index + 1 };
  if (f.options && f.options.length) field.options = f.options.map((o, i) => ({ option_key: o.value, label: o.label, display_order: i + 1 }));
  return field;
}

function buildForm(code, machines, { fields = [], groups = [] }, meta) {
  const form = {
    schema_version: 1, legacy_key: meta.id, code, legacy_number: meta.legacyNumber, name: meta.name, area: meta.area, workflow: meta.workflowId,
    version_number: 1, machines,
    groups: groups.map((g, gi) => ({
      code: g.code, label: g.label, display_order: gi + 1, repeatable: g.repeatable, min_rows: g.minRows, max_rows: g.maxRows,
      fields: g.fields.map(toField),
    })),
    fields: fields.map(toField),
  };
  const { schema_version: _omit, ...definition } = form;
  form.definition_checksum = sha256Hex(canonicalJson(definition));
  return form;
}

async function main() {
  const formDefs = (await import("../lib/vinto/form-definitions.ts")).FORM_DEFINITIONS;
  const generatedForms = [];
  const sourceModules = [];

  for (const spec of FLAT_FORMS) {
    const mod = await import(`../lib/vinto/${spec.module}.ts`);
    const fields = mod[spec.fieldsExport];
    const code = mod[spec.codeExport];
    if (code !== spec.code) throw new Error(`${spec.module}: código inesperado ${code}, se esperaba ${spec.code}`);
    if (!Array.isArray(fields) || fields.length === 0) throw new Error(`${spec.module}: ${spec.fieldsExport} vacío o inexistente`);
    const meta = formDefs.find((f) => f.code === spec.code);
    if (!meta) throw new Error(`${spec.code}: no se encontró en FORM_DEFINITIONS`);
    const form = buildForm(spec.code, spec.machines, { fields }, meta);
    generatedForms.push({ code: spec.code, form, fieldCount: fields.length, groupCount: 0 });
    sourceModules.push(spec.module);
    console.log(`OK  ${spec.code}  (${fields.length} campos planos, máquinas ${spec.machines.join("/")}, legacy #${meta.legacyNumber})`);
  }

  for (const spec of GROUPED_FORMS) {
    const mod = await import(`../lib/vinto/${spec.module}.ts`);
    const groups = mod[spec.groupsExport];
    const code = mod[spec.codeExport];
    if (code !== spec.code) throw new Error(`${spec.module}: código inesperado ${code}, se esperaba ${spec.code}`);
    if (!Array.isArray(groups) || groups.length === 0) throw new Error(`${spec.module}: ${spec.groupsExport} vacío o inexistente`);
    const fields = spec.simpleFieldsExport ? mod[spec.simpleFieldsExport] : spec.simpleFields;
    if (!Array.isArray(fields) || fields.length === 0) throw new Error(`${spec.module}: campos simples vacíos o inexistentes`);
    const meta = formDefs.find((f) => f.code === spec.code);
    if (!meta) throw new Error(`${spec.code}: no se encontró en FORM_DEFINITIONS`);
    const form = buildForm(spec.code, spec.machines, { fields, groups }, meta);
    const groupFieldCount = groups.reduce((sum, g) => sum + g.fields.length, 0);
    generatedForms.push({ code: spec.code, form, fieldCount: fields.length + groupFieldCount, groupCount: groups.length });
    sourceModules.push(spec.module);
    console.log(`OK  ${spec.code}  (${fields.length} campos simples + ${groups.length} grupo(s)/${groupFieldCount} campos, máquinas ${spec.machines.join("/")}, legacy #${meta.legacyNumber})`);
  }

  for (const gf of generatedForms) {
    const text = `${JSON.stringify(gf.form, null, 2)}\n`;
    writeFileSync(`${SEED_DIR}/forms/${gf.code}.json`, text, "utf8");
    gf.path = `forms/${gf.code}.json`;
    gf.text = text;
  }

  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
  const existingPaths = new Set(manifest.files.map((f) => f.path));
  for (const gf of generatedForms) {
    if (existingPaths.has(gf.path)) throw new Error(`manifest ya declara ${gf.path}: abortando`);
    manifest.files.push({ path: gf.path, sha256: sha256Hex(gf.text), bytes: Buffer.byteLength(gf.text, "utf8") });
  }
  manifest.files.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  manifest.scope.forms = [...manifest.scope.forms, ...generatedForms.map((f) => f.code)];

  const addedFieldCount = generatedForms.reduce((sum, f) => sum + f.fieldCount, 0);
  const addedGroupCount = generatedForms.reduce((sum, f) => sum + f.groupCount, 0);
  const addedOptionCount = generatedForms.reduce(
    (sum, f) => sum + f.form.fields.concat(f.form.groups.flatMap((g) => g.fields)).reduce((s, fld) => s + (fld.options?.length || 0), 0), 0);
  manifest.counts.forms += generatedForms.length;
  manifest.counts.form_fields += addedFieldCount;
  manifest.counts.form_groups += addedGroupCount;
  manifest.counts.form_options += addedOptionCount;

  for (const mod of [...new Set(sourceModules)]) {
    const srcPath = `lib/vinto/${mod}.ts`;
    const srcText = readFileSync(`${ROOT}${srcPath}`, "utf8").replace(/\r\n/g, "\n");
    const codes = [...FLAT_FORMS, ...GROUPED_FORMS].filter((f) => f.module === mod).map((f) => f.code);
    manifest.generated_from.push({ path: srcPath, sha256: sha256Hex(srcText), scope: `candidate-fields:${codes.join(",")}` });
  }

  manifest.warnings.push({
    code: "CONVERSION_SECTOR_AND_GROUPS_ENABLED_FOR_QA",
    severity: "warning",
    message: "CLOUD-DEP G.12-C4-FINAL25: sector CONVERSION y sus 11 máquinas Legacy habilitados para QA junto con 5 formularios candidatos (VINTO-P1-11, 12, 13, 16, 29). P1-11/29 son los primeros "
      + "formularios candidatos con grupos de campos repetibles importados por el bundle (antes no soportado). P1-12/13/16 usan ahora el subconjunto MANUAL exacto de su definición legacy (reemplaza la "
      + "hipótesis de prueba anterior de esos mismos módulos). Máquinas, turnos, artículos y relaciones de CONVERSION son candidatos técnicos derivados de PRODUCTS_BY_MACHINE legacy, sin homologación de "
      + "VINTO (los 36 puntos de decisión CV:* de docs/M7-A-conversion-decisiones-VINTO.md siguen 'Pendiente'). Autorizado explícitamente para este piloto de QA con datos sintéticos; no implica "
      + "homologación industrial ni libera ninguna bobina ni control de Calidad.",
    count: generatedForms.length,
  });

  writeFileSync(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(`\nmanifest.json actualizado: +${generatedForms.length} formularios, +${addedFieldCount} campos, +${addedGroupCount} grupos.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
