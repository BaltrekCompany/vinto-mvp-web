// node --test scripts/p107-contract.test.mjs
// M5-A · hechos verificables de la definición LEGACY de VINTO-P1-07 en lib/vinto/form-definitions.ts (base del mapeo de docs/M5-A-p107-genealogia.md). No es una decisión industrial:
// solo ancla los números que el documento cita, para que un cambio de la fuente haga fallar la prueba. P1-07 NO está en ningún bundle ni en la política central.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

test("P1-07 is not part of the central policy, the approved bundle or the operational sectors", () => {
  const service = readFileSync(join(root, "backend/app/capture_service.py"), "utf8");
  assert.match(service, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  for (const name of ["forms.json", "form_versions.json"]) {
    try { assert.equal(readFileSync(join(root, "backend/seed_data", name), "utf8").includes("VINTO-P1-07"), false); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  assert.match(readFileSync(join(root, "backend/app/sectors.py"), "utf8"), /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
});
