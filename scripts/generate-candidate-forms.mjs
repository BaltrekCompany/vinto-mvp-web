// CLOUD-DEP G.12-C4: genera backend/seed_data/forms/VINTO-P1-NN.json para los 13 formularios candidatos
// que SÍ tienen dependencias satisfechas (máquinas MP1/MP3 ya existen en el maestro del piloto de Bobinas):
// Bobinas (P1-01/02/04/05/31, contexto "assignment") y Calidad (P1-18/21/22/24/25/26/27/28, contexto
// "machine"/"bobbin"). NO genera nada para Rebobinado/Conversión (P1-07/10/11/12/13/16/29/30): esos 8
// formularios no tienen ninguna máquina real en el maestro (el piloto es exclusivamente Bobinas), y dos de
// ellos (P1-11, P1-29) usan grupos repetibles que el importador Python no soporta (bundle.py:347: "los
// grupos de campos no están soportados por este importador") -- habilitarlos exigiría o bien inventar
// máquinas (prohibido por el encargo G.12-C4 sección C.3) o bien ampliar el importador (desarrollo nuevo,
// fuera del alcance de "máxima reutilización, mínima burocracia").
//
// Fuente de los campos: los arrays FieldSpec[] ya existentes y ya usados por la pantalla candidata real
// (lib/vinto/p1-NN.ts) -- son exactamente el subconjunto MANUAL ya decidido por ese código (los campos
// automáticos/calculados/sin fuente aprobada ya quedaron fuera de esos arrays, documentado en cada archivo
// como "PENDIENTE DE VINTO"). Nunca se re-derivan desde form-definitions.ts (la matriz legacy completa,
// con automáticos/calculados): eso sería repetir una decisión ya tomada y revisada en el código candidato.
// form-definitions.ts SÍ se usa, pero solo para tres metadatos que el array de campos no lleva: el nombre
// oficial, el área (production/quality) y el número legacy -- nunca para los campos en sí.
//
// Nunca inventa catálogo de unidades: todo field.unit del JSON generado es null (un FieldSpec candidato
// solo tiene como mucho un "suffix" de visualización, nunca una referencia real a vinto_master.unit).
//
// Uso: node scripts/generate-candidate-forms.mjs
// Escribe backend/seed_data/forms/VINTO-P1-NN.json (13 archivos) y actualiza backend/seed_data/manifest.json
// de forma ADITIVA (nunca toca los 4 formularios ya publicados ni ningún otro archivo del bundle).

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SEED_DIR = `${ROOT}backend/seed_data`;
const MANIFEST_PATH = `${SEED_DIR}/manifest.json`;

// kind (FieldSpec, lib/vinto/candidate-form.ts) -> value_type (vinto_config.field_definition, backend/app/seed/bundle.py VALUE_TYPES)
const KIND_TO_VALUE_TYPE = { text: "text", textarea: "textarea", decimal: "decimal", time: "time" };

// Los 13 formularios con dependencias satisfechas (MP1/MP3 ya existen). "module"/"fieldsExport"/"codeExport"
// son exactamente los nombres ya exportados por el archivo candidato correspondiente -- nunca inventados.
const FORMS = [
  { code: "VINTO-P1-01", module: "p1-01", fieldsExport: "P101_FIELDS", codeExport: "P1_01_CODE" },
  { code: "VINTO-P1-02", module: "p1-02", fieldsExport: "P102_FIELDS", codeExport: "P1_02_CODE" },
  { code: "VINTO-P1-04", module: "p1-04", fieldsExport: "P104_FIELDS", codeExport: "P1_04_CODE" },
  { code: "VINTO-P1-05", module: "p1-05", fieldsExport: "P105_FIELDS", codeExport: "P1_05_CODE" },
  { code: "VINTO-P1-31", module: "p1-31", fieldsExport: "P131_FIELDS", codeExport: "P1_31_CODE" },
  { code: "VINTO-P1-18", module: "p1-18", fieldsExport: "P118_FIELDS", codeExport: "P1_18_CODE" },
  { code: "VINTO-P1-21", module: "p1-21", fieldsExport: "P121_FIELDS", codeExport: "P1_21_CODE" },
  { code: "VINTO-P1-22", module: "p1-22", fieldsExport: "P122_FIELDS", codeExport: "P1_22_CODE" },
  { code: "VINTO-P1-24", module: "p1-24", fieldsExport: "P124_FIELDS", codeExport: "P1_24_CODE" },
  { code: "VINTO-P1-25", module: "p1-25", fieldsExport: "P125_FIELDS", codeExport: "P1_25_CODE" },
  { code: "VINTO-P1-26", module: "p1-26", fieldsExport: "P126_FIELDS", codeExport: "P1_26_CODE" },
  { code: "VINTO-P1-27", module: "p1-27", fieldsExport: "P127_FIELDS", codeExport: "P1_27_CODE" },
  { code: "VINTO-P1-28", module: "p1-28", fieldsExport: "P128_FIELDS", codeExport: "P1_28_CODE" },
];

// Idéntico a backend/app/seed/bundle.py::canonical_json (sort_keys=True, separators sin espacios,
// ensure_ascii=False) -- necesario para que definition_checksum coincida exactamente con lo que
// compute_definition_checksum() recalculará al cargar el bundle en Python.
function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(",")}}`;
}

function sha256Hex(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

async function main() {
  const formDefs = (await import("../lib/vinto/form-definitions.ts")).FORM_DEFINITIONS;
  const generatedForms = [];

  for (const spec of FORMS) {
    const mod = await import(`../lib/vinto/${spec.module}.ts`);
    const fields = mod[spec.fieldsExport];
    const code = mod[spec.codeExport];
    if (code !== spec.code) throw new Error(`${spec.module}: código inesperado ${code}, se esperaba ${spec.code}`);
    if (!Array.isArray(fields) || fields.length === 0) throw new Error(`${spec.module}: ${spec.fieldsExport} vacío o inexistente`);

    const meta = formDefs.find((f) => f.code === spec.code);
    if (!meta) throw new Error(`${spec.code}: no se encontró en FORM_DEFINITIONS (lib/vinto/form-definitions.ts)`);

    const form = {
      schema_version: 1,
      legacy_key: meta.id,
      code: spec.code,
      legacy_number: meta.legacyNumber,
      name: meta.name,
      area: meta.area,
      workflow: meta.workflowId,
      version_number: 1,
      machines: ["MP1", "MP3"],
      groups: [],
      fields: fields.map((f, index) => {
        const value_type = KIND_TO_VALUE_TYPE[f.kind];
        if (!value_type) throw new Error(`${spec.code}/${f.key}: kind desconocido ${f.kind}`);
        return { key: f.key, label: f.label, value_type, source: "manual", required: f.required, unit: null, display_order: index + 1 };
      }),
    };
    // Igual que compute_definition_checksum (bundle.py): excluye schema_version y el propio checksum.
    const { schema_version: _omit, ...definition } = form;
    form.definition_checksum = sha256Hex(canonicalJson(definition));

    const text = `${JSON.stringify(form, null, 2)}\n`;
    // "manifestPath" es relativo a backend/seed_data/ (lo que manifest.json::files declara); "diskPath" es
    // relativo a la raíz del repo (dónde escribe este script). Nunca el mismo valor para los dos usos.
    const manifestPath = `forms/${spec.code}.json`;
    const diskPath = `backend/seed_data/${manifestPath}`;
    writeFileSync(`${ROOT}${diskPath}`, text, "utf8");
    generatedForms.push({ code: spec.code, path: manifestPath, text, fieldCount: fields.length });
    console.log(`OK  ${spec.code}  (${fields.length} campos, ${meta.area}, legacy #${meta.legacyNumber})`);
  }

  // --- actualizar manifest.json de forma aditiva ------------------------------------------------------
  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
  const existingPaths = new Set(manifest.files.map((f) => f.path));
  for (const gf of generatedForms) {
    if (existingPaths.has(gf.path)) throw new Error(`manifest ya declara ${gf.path}: abortando (nunca se sobreescribe silenciosamente)`);
    manifest.files.push({ path: gf.path, sha256: sha256Hex(gf.text), bytes: Buffer.byteLength(gf.text, "utf8") });
  }
  manifest.files.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));

  manifest.scope.forms = [...manifest.scope.forms, ...generatedForms.map((f) => f.code)];

  const addedFieldCount = generatedForms.reduce((sum, f) => sum + f.fieldCount, 0);
  manifest.counts.forms += generatedForms.length;
  manifest.counts.form_fields += addedFieldCount;
  // form_options no cambia: ningún FieldSpec candidato tiene opciones (kind nunca es "choice").

  // Procedencia de los 13 archivos fuente usados (nunca los de los 4 formularios ya publicados).
  for (const spec of FORMS) {
    const srcPath = `lib/vinto/${spec.module}.ts`;
    const srcText = readFileSync(`${ROOT}${srcPath}`, "utf8").replace(/\r\n/g, "\n");
    manifest.generated_from.push({ path: srcPath, sha256: sha256Hex(srcText), scope: `candidate-fields:${spec.code}` });
  }
  const formDefsText = readFileSync(`${ROOT}lib/vinto/form-definitions.ts`, "utf8").replace(/\r\n/g, "\n");
  manifest.generated_from.push({ path: "lib/vinto/form-definitions.ts", sha256: sha256Hex(formDefsText), scope: "candidate-metadata:name,area,legacy_number,workflow (NUNCA los campos)" });

  manifest.warnings.push({
    code: "CANDIDATE_FORMS_ENABLED_FOR_QA",
    severity: "warning",
    message: "CLOUD-DEP G.12-C4: 13 formularios candidatos (Bobinas P1-01/02/04/05/31, Calidad P1-18/21/22/24/25/26/27/28) habilitados exclusivamente para QA interno sobre MP1/MP3. Ninguno homologado por VINTO (contrato, catálogos, rangos ni unidades aprobados). No implica liberación/rechazo de Calidad. No activa Rebobinado ni Conversión.",
    count: generatedForms.length,
  });

  writeFileSync(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(`\nmanifest.json actualizado: +${generatedForms.length} formularios, +${addedFieldCount} campos.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
