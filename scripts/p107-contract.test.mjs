// node --test scripts/p107-contract.test.mjs
// M5-A · hechos verificables de la definición LEGACY de VINTO-P1-07 en lib/vinto/form-definitions.ts (base del mapeo de docs/M5-A-p107-genealogia.md). No es una decisión industrial:
// solo ancla los números que el documento cita, para que un cambio de la fuente haga fallar la prueba. P1-07 NO está en ningún bundle ni en la política central.
import assert from "node:assert/strict";
import { cpSync, existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";

import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";

const root = resolve(import.meta.dirname, "..");
const form = FORM_DEFINITIONS.find((f) => f.legacyNumber === 7);
const keys = form.fields.map((f) => f.key);

test("P1-07 legacy: identity, machines and field count", () => {
  assert.equal(form.code, "VINTO-P1-07");
  assert.equal(form.name, "Registro de producción de bobinas refiladas");
  assert.deepEqual(form.allowedMachineIds, ["copasa", "beloit", "over"]);
  assert.equal(form.fields.length, 41);
  assert.equal(new Set(keys).size, 41);
  assert.deepEqual(form.fields.map((f) => f.order), Array.from({ length: 41 }, (_, i) => i + 1));
});

test("P1-07 legacy: 5 automatic fields, 35 manual required, 1 optional manual (observaciones)", () => {
  const automatic = form.fields.filter((f) => f.source === "automatic").map((f) => f.key);
  assert.deepEqual(automatic, ["fecha", "hora_inicio", "hora_final", "turno", "operador"]);
  assert.equal(form.fields.filter((f) => f.source === "manual" && f.required).length, 35);
  assert.deepEqual(form.fields.filter((f) => !f.required).map((f) => f.key), ["observaciones"]);
});

test("P1-07 legacy: peso_cria_1..11 and 13..22 exist and peso_cria_12 does NOT (gap in the source numbering)", () => {
  const cria = keys.filter((k) => k.startsWith("peso_cria_")).map((k) => Number(k.slice("peso_cria_".length)));
  assert.equal(cria.length, 21);
  assert.deepEqual(cria, [...Array(11).keys()].map((i) => i + 1).concat([...Array(10).keys()].map((i) => i + 13)));
  assert.equal(keys.includes("peso_cria_12"), false);
  for (const f of form.fields.filter((x) => x.key.startsWith("peso_cria_"))) assert.deepEqual([f.type, f.unit, f.required, f.classification], ["decimal", "kg", true, "Condicional / repetible"]);
});

test("P1-07 legacy: there is NO field that identifies a mother (input) bobbin or any quantity consumed/left over", () => {
  assert.equal(keys.some((k) => /madre|origen|consum|sobrante|merma|entrada/.test(k)), false);
  assert.equal(keys.includes("etiqueta_numero_de_bobina"), true); // identifica «la bobina» del registro; la fuente no dice si es de entrada o de salida
});

// Detector sobre un directorio de bundle: declara P1-07 si el manifest (scope.forms o files[]), el nombre de algún archivo bajo forms/ o el CONTENIDO de cualquier .json (incluidos
// forms/*.json con legacy_number 7) lo mencionan. No depende de que el manifest esté actualizado: un archivo añadido sin declarar también se detecta.
function p107InBundle(dir) {
  const hits = [];
  const walk = (current) => {
    for (const name of readdirSync(current)) {
      const path = join(current, name);
      if (statSync(path).isDirectory()) { walk(path); continue; }
      if (/P1-07/.test(name)) hits.push(`archivo ${name}`);
      if (!name.endsWith(".json")) continue;
      const text = readFileSync(path, "utf8");
      if (text.includes("VINTO-P1-07")) hits.push(`contenido ${name}`);
      const json = JSON.parse(text);
      if (json && json.legacy_number === 7) hits.push(`legacy_number 7 en ${name}`);
    }
  };
  walk(dir);
  const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
  if ((manifest.scope?.forms ?? []).includes("VINTO-P1-07")) hits.push("manifest.scope.forms");
  if ((manifest.files ?? []).some((f) => /P1-07/.test(f.path))) hits.push("manifest.files");
  return hits;
}

test("P1-07 is not in the approved bundle (manifest, declared forms/ files and every json), and the detector reads the real paths", () => {
  const dir = join(root, "backend/seed_data");
  const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
  const declared = manifest.files.filter((f) => f.path.startsWith("forms/VINTO-P1-")).map((f) => f.path);
  assert.deepEqual(declared, ["forms/VINTO-P1-03.json", "forms/VINTO-P1-06.json", "forms/VINTO-P1-19.json", "forms/VINTO-P1-20.json"]); // las rutas reales existen: el detector no puede quedar vacío
  for (const path of declared) assert.equal(existsSync(join(dir, path)), true, path);
  assert.deepEqual(manifest.scope.forms.sort(), ["VINTO-P1-03", "VINTO-P1-06", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.deepEqual(p107InBundle(dir), []);
});

test("the detector fails on synthetic bundles that contain P1-07 (declared in the manifest or not); the approved bundle is never modified", () => {
  const scratch = mkdtempSync(join(tmpdir(), "p107-detector-"));
  try {
    const copy = (name) => { const d = join(scratch, name); cpSync(join(root, "backend/seed_data"), d, { recursive: true }); return d; };
    assert.deepEqual(p107InBundle(copy("clean")), []);
    const form = JSON.parse(readFileSync(join(root, "backend/seed_data/forms/VINTO-P1-06.json"), "utf8"));
    const synthetic = { ...form, code: "VINTO-P1-07", legacy_number: 7 };

    const declared = copy("declared"); // añadido Y declarado correctamente en el manifest
    writeFileSync(join(declared, "forms/VINTO-P1-07.json"), JSON.stringify(synthetic));
    const m = JSON.parse(readFileSync(join(declared, "manifest.json"), "utf8"));
    m.files.push({ path: "forms/VINTO-P1-07.json", sha256: "0".repeat(64), bytes: 1 });
    m.scope.forms.push("VINTO-P1-07");
    writeFileSync(join(declared, "manifest.json"), JSON.stringify(m));
    assert.ok(p107InBundle(declared).length >= 3);

    const undeclared = copy("undeclared"); // archivo añadido sin tocar el manifest
    writeFileSync(join(undeclared, "forms/VINTO-P1-07.json"), JSON.stringify(synthetic));
    assert.ok(p107InBundle(undeclared).length >= 1);

    const renamed = copy("renamed"); // contenido de P1-07 bajo otro nombre de archivo
    writeFileSync(join(renamed, "forms/otro.json"), JSON.stringify(synthetic));
    assert.ok(p107InBundle(renamed).length >= 1);

    const scopeOnly = copy("scope-only"); // solo en scope.forms
    const sm = JSON.parse(readFileSync(join(scopeOnly, "manifest.json"), "utf8"));
    sm.scope.forms.push("VINTO-P1-07");
    writeFileSync(join(scopeOnly, "manifest.json"), JSON.stringify(sm));
    assert.deepEqual(p107InBundle(scopeOnly), ["contenido manifest.json", "manifest.scope.forms"]);
  } finally { rmSync(scratch, { recursive: true, force: true }); }
});

test("P1-07 is not part of the central policy or the operational sectors", () => {
  const service = readFileSync(join(root, "backend/app/capture_service.py"), "utf8");
  assert.match(service, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  assert.equal(/CENTRAL_FORM_CODES[^\n]*P1-07/.test(service), false);
  assert.match(readFileSync(join(root, "backend/app/sectors.py"), "utf8"), /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
});
