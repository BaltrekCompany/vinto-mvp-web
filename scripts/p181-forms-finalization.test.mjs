// P181 - Nuevas capturas: P1-07 v5, P1-10 v4 y retiro funcional de P1-05.
// Nunca borra las versiones publicadas ni las capturas antiguas.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { P107_FIELDS } from "../lib/vinto/p1-07.ts";
import { labelFor } from "../lib/vinto/candidate-form.ts";
import { P110_TIPOS, P110_V4, EMPTY_P110_DRAFT, normalizeP110Draft, parseP110Values } from "../lib/vinto/p1-10.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const json = path => JSON.parse(readFileSync(join(root, path), "utf8"));

test("P1-07 v5 solo renombra Formato 3 como Cortes, misma clave y tipo", () => {
  const f = P107_FIELDS.find(x => x.key === "formato_3");
  assert.equal(f.label, "Cortes");
  assert.equal(f.kind, "decimal");
  assert.equal(f.required, false);
  assert.equal(labelFor(f, 4), "Formato 3");
  assert.equal(labelFor(f, 5), "Cortes");
  const saved = json("backend/seed_data/forms/VINTO-P1-07.json");
  assert.equal(saved.version_number, 5);
  assert.equal(saved.fields.find(x => x.key === "formato_3").label, "Cortes");
  assert.equal(saved.fields.length, 38, "no se agregaron ni eliminaron campos de rebobinado");
});

test("P1-10 v4 elimina las horas y exige exactamente un tipo aprobado", () => {
  const def = json("backend/seed_data/forms/VINTO-P1-10.json");
  assert.equal(def.version_number, 4);
  assert.deepEqual(def.fields.map(f => f.key), ["peso_fardo", "tipo", "observaciones"]);
  assert.deepEqual(def.fields.find(f => f.key === "tipo").options.map(o => o.option_key), [...P110_TIPOS]);
  assert.equal(def.fields.find(f => f.key === "tipo").required, true);
  assert.equal(P110_V4, 4);
  assert.deepEqual(Object.keys(EMPTY_P110_DRAFT), ["peso_fardo", "tipo", "observaciones"]);
  for (const tipo of P110_TIPOS) {
    const check = normalizeP110Draft({peso_fardo:"55 kg",tipo,observaciones:""});
    assert.equal(check.ok, true);
    assert.deepEqual(check.values, {peso_fardo:"55 kg",tipo});
    assert.deepEqual(parseP110Values(check.values, 4), check.values);
  }
  for (const tipo of ["", "Otro", "Toallas", "Servilleta,Toalla"]) {
    assert.equal(normalizeP110Draft({peso_fardo:"55 kg",tipo,observaciones:""}).ok, false, tipo);
    assert.equal(parseP110Values({peso_fardo:"55 kg",tipo}, 4), null);
  }
  assert.equal(parseP110Values({peso_fardo:"55 kg",hora_inicio:"06:30:00",hora_fin:"07:45:00"},3)?.hora_inicio, "06:30:00");
  assert.deepEqual(parseP110Values({codigo_numero_de_producto:"A",numero_de_fardo:"42",peso_fardo:"55 kg"},1),
    {codigo_numero_de_producto:"A",numero_de_fardo:"42",peso_fardo:"55 kg"});
  const page = readFileSync(join(root, "components/vinto/p1-10-capture.tsx"), "utf8");
  assert.equal(page.includes("draft.hora_inicio") || page.includes("draft.hora_fin"), false);
  assert.match(page, /ChoiceField label=\{P110_LABELS.tipo\}/);
});

test("P1-05 mantiene el bundle histórico y deja de ofrecerse como pantalla de captura", () => {
  const manifest = json("backend/seed_data/manifest.json");
  const old = json("backend/seed_data/forms/VINTO-P1-05.json");
  assert.equal(old.version_number, 2);
  assert.ok(manifest.scope.forms.includes("VINTO-P1-05"), "histórico preservado");
  assert.equal(manifest.counts.form_fields, 567);
  assert.equal(manifest.counts.form_options, 38);
  const policy = readFileSync(join(root, "backend/app/mp3_inspection_policy.py"), "utf8");
  assert.match(policy, /RETIRED_CAPTURE_FORMS = frozenset\(\{"VINTO-P1-05"\}\)/);
  assert.match(policy, /if form_code in RETIRED_CAPTURE_FORMS:/);
});
