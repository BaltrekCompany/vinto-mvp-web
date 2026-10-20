// CLOUD-DEP G.12-C4-COMPLETE: genera backend/seed_data/forms/VINTO-P1-{07,10,30}.json para los 3
// formularios candidatos de Rebobinado con dependencias satisfechas tras incorporar el sector REBOBINADO
// y sus máquinas BELOIT/OVER/COPASA/PERICHUN (M.4-B1; TUBETERA queda excluida por la ambigüedad abierta
// de TB-4001 y porque ninguno de estos 3 formularios la necesita).
//
// P1-07 y P1-30 reutilizan el mismo patrón que scripts/generate-candidate-forms.mjs: el array FieldSpec[]
// ya existente en lib/vinto/p1-07.ts / p1-30.ts (el subconjunto MANUAL ya decidido por ese código). P1-10
// NO usa defineCandidateForm/FieldSpec (implementación a mano sobre capture-core.ts): sus 4 campos se
// toman literalmente del parser de lib/vinto/p1-10.ts (parseValues: codigo_numero_de_producto/numero_de_fardo/
// peso_fardo como texto obligatorio, observaciones como texto opcional) y del tipo "textarea" declarado
// para observaciones en la definición legacy (form-definitions.ts, form_10_registro_de_fardos) -- nunca
// inventados; ningún campo se re-tipifica a decimal.
//
// Uso: node scripts/generate-rebobinado-forms.mjs
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SEED_DIR = `${ROOT}backend/seed_data`;
const MANIFEST_PATH = `${SEED_DIR}/manifest.json`;

const KIND_TO_VALUE_TYPE = { text: "text", textarea: "textarea", decimal: "decimal", time: "time" };

const FORMS = [
  { code: "VINTO-P1-07", module: "p1-07", fieldsExport: "P107_FIELDS", codeExport: "P1_07_CODE", machines: ["BELOIT", "OVER", "COPASA"] },
  { code: "VINTO-P1-30", module: "p1-30", fieldsExport: "P130_FIELDS", codeExport: "P1_30_CODE", machines: ["PERICHUN"] },
];
// P1-10: sin FieldSpec[] exportado (lib/vinto/p1-10.ts usa un parser a mano); campos tomados literalmente
// de ese parser (parseValues) y del tipo "textarea" de observaciones en form-definitions.ts/form_10.
const P110_FIELDS = [
  { key: "codigo_numero_de_producto", label: "Código / número de producto", kind: "text", required: true },
  { key: "numero_de_fardo", label: "Número de fardo", kind: "text", required: true },
  { key: "peso_fardo", label: "Peso fardo", kind: "text", required: true },
  { key: "observaciones", label: "Observaciones", kind: "textarea", required: false },
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

function buildForm(code, machines, fields, meta) {
  const form = {
    schema_version: 1,
    legacy_key: meta.id,
    code,
    legacy_number: meta.legacyNumber,
    name: meta.name,
    area: meta.area,
    workflow: meta.workflowId,
    version_number: 1,
    machines,
    groups: [],
    fields: fields.map((f, index) => {
      const value_type = KIND_TO_VALUE_TYPE[f.kind];
      if (!value_type) throw new Error(`${code}/${f.key}: kind desconocido ${f.kind}`);
      return { key: f.key, label: f.label, value_type, source: "manual", required: f.required, unit: null, display_order: index + 1 };
    }),
  };
  const { schema_version: _omit, ...definition } = form;
  form.definition_checksum = sha256Hex(canonicalJson(definition));
  return form;
}

async function main() {
  const formDefs = (await import("../lib/vinto/form-definitions.ts")).FORM_DEFINITIONS;
  const generatedForms = [];
  const sourceModules = [];

  for (const spec of FORMS) {
    const mod = await import(`../lib/vinto/${spec.module}.ts`);
    const fields = mod[spec.fieldsExport];
    const code = mod[spec.codeExport];
    if (code !== spec.code) throw new Error(`${spec.module}: código inesperado ${code}, se esperaba ${spec.code}`);
    if (!Array.isArray(fields) || fields.length === 0) throw new Error(`${spec.module}: ${spec.fieldsExport} vacío o inexistente`);
    const meta = formDefs.find((f) => f.code === spec.code);
    if (!meta) throw new Error(`${spec.code}: no se encontró en FORM_DEFINITIONS`);
    const form = buildForm(spec.code, spec.machines, fields, meta);
    generatedForms.push({ code: spec.code, form, fieldCount: fields.length });
    sourceModules.push(spec.module);
    console.log(`OK  ${spec.code}  (${fields.length} campos, máquinas ${spec.machines.join("/")}, legacy #${meta.legacyNumber})`);
  }

  // P1-10 aparte: campos a mano, sin módulo FieldSpec que validar contra sí mismo.
  {
    const code = "VINTO-P1-10";
    const meta = formDefs.find((f) => f.code === code);
    if (!meta) throw new Error(`${code}: no se encontró en FORM_DEFINITIONS`);
    const form = buildForm(code, ["COPASA"], P110_FIELDS, meta);
    generatedForms.push({ code, form, fieldCount: P110_FIELDS.length });
    console.log(`OK  ${code}  (${P110_FIELDS.length} campos, máquinas COPASA, legacy #${meta.legacyNumber}, campos a mano desde lib/vinto/p1-10.ts::parseValues)`);
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
  manifest.counts.forms += generatedForms.length;
  manifest.counts.form_fields += addedFieldCount;

  for (const mod of sourceModules) {
    const srcPath = `lib/vinto/${mod}.ts`;
    const srcText = readFileSync(`${ROOT}${srcPath}`, "utf8").replace(/\r\n/g, "\n");
    manifest.generated_from.push({ path: srcPath, sha256: sha256Hex(srcText), scope: `candidate-fields:${FORMS.find((f) => f.module === mod).code}` });
  }
  {
    const srcPath = "lib/vinto/p1-10.ts";
    const srcText = readFileSync(`${ROOT}${srcPath}`, "utf8").replace(/\r\n/g, "\n");
    manifest.generated_from.push({ path: srcPath, sha256: sha256Hex(srcText), scope: "candidate-fields:VINTO-P1-10 (campos a mano desde parseValues, sin FieldSpec[] exportado)" });
  }

  manifest.warnings.push({
    code: "REBOBINADO_SECTOR_ENABLED_FOR_QA",
    severity: "warning",
    message: "CLOUD-DEP G.12-C4-COMPLETE: sector REBOBINADO y máquinas BELOIT/OVER/COPASA/PERICHUN (TUBETERA excluida) habilitados para QA junto con 3 formularios candidatos (VINTO-P1-07, VINTO-P1-10, VINTO-P1-30). Máquinas, turnos, artículos y relaciones son CANDIDATOS técnicos derivados de PRODUCTS_BY_MACHINE legacy, sin homologación de VINTO (docs/M4-B1-homologacion-rebobinado.md). Autorizado explícitamente para este piloto con datos sintéticos (CLOUD-DEP G.12-C4-COMPLETE sección A); no implica homologación industrial ni libera ninguna bobina ni control de Calidad.",
    count: generatedForms.length,
  });

  writeFileSync(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(`\nmanifest.json actualizado: +${generatedForms.length} formularios, +${addedFieldCount} campos.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
