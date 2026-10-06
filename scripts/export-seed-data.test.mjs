// node --test scripts/export-seed-data.test.mjs
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { DEFAULT_OUT, SeedExportError, buildBundle, compareWithDisk, loadSources, validateBundle, writeBundle } from "./export-seed-data.mjs";

const sources = await loadSources();
const clone = (value) => structuredClone(value);
const mutated = (change) => { const s = { ...sources, texts: { ...sources.texts } }; s.productsByMachine = clone(sources.productsByMachine); s.formDefinitions = clone(sources.formDefinitions); change(s); return s; };
const failsWith = (change, pattern) => assert.throws(() => buildBundle(mutated(change)), (error) => error instanceof SeedExportError && pattern.test(error.message));

test("same input produces byte-identical output (in memory and on disk)", () => {
  const first = buildBundle(sources), second = buildBundle(sources);
  assert.deepEqual([...first.files], [...second.files]);
  const dirs = [mkdtempSync(join(tmpdir(), "seed-a-")), mkdtempSync(join(tmpdir(), "seed-b-"))];
  try {
    writeBundle(dirs[0], first.files);
    writeBundle(dirs[1], second.files);
    for (const name of [...first.files.keys()]) assert.equal(readFileSync(join(dirs[0], name)).compare(readFileSync(join(dirs[1], name))), 0, name);
  } finally { dirs.forEach((d) => rmSync(d, { recursive: true, force: true })); }
});

test("committed bundle is up to date with the sources", () => {
  assert.deepEqual(compareWithDisk(DEFAULT_OUT, buildBundle(sources).files), []);
  assert.deepEqual(readdirSync(DEFAULT_OUT).filter((n) => n.endsWith(".json")).sort(),
    [...buildBundle(sources).files.keys()].filter((n) => !n.includes("/")).sort());
});

test("output has no timestamps, absolute paths or host data", () => {
  const text = [...buildBundle(sources).files.values()].join("\n");
  assert.doesNotMatch(text, /[A-Za-z]:\\|\/Users\/|\/home\/|C:\/|generated_at|hostname/i);
});

test("manifest is consistent with the files", () => {
  const { files, manifest } = buildBundle(sources);
  assert.deepEqual(manifest.files.map((f) => f.path), [...files.keys()].filter((n) => n !== "manifest.json").sort());
  assert.equal(manifest.counts.articles, JSON.parse(files.get("articles.json")).items.length);
  assert.equal(manifest.counts.form_fields, 5);
  assert.equal(manifest.counts.form_options, 5);
});

test("fails clearly when MP1 or MP3 is missing", () => {
  failsWith((s) => { delete s.productsByMachine.MP1; }, /MP1 no existe/);
  failsWith((s) => { delete s.productsByMachine.MP3; }, /MP3 no existe/);
});

test("fails on incompatible duplicate article codes", () => {
  failsWith((s) => { s.productsByMachine.MP3.push({ ...s.productsByMachine.MP1[0], name: "OTRO NOMBRE" }); }, /duplicado con datos incompatibles/);
});

test("fails when an article has no unit", () => {
  failsWith((s) => { s.productsByMachine.MP1[0].unit = ""; }, /sin unidad/);
});

test("fails when a machine does not belong to Bobinas", () => {
  failsWith((s) => { s.texts.page = s.texts.page.replace('Bobinas: ["MP1", "MP3"]', 'Bobinas: ["MP1"]'); }, /GROUPS|no pertenece/);
  failsWith((s) => { s.texts.page = s.texts.page.replace('Bobinas: ["MP1", "MP3"]', 'Bobinas: ["MP1", "MP3", "Beloit"]'); }, /GROUPS/);
});

test("fails when F6 deviates from the canonical contract", () => {
  failsWith((s) => { s.texts.page = s.texts.page.replace('options={["Bobina rechazada","Recorte de máquina"]}', 'options={["Bobina rechazada","Recorte de máquina","Otro"]}'); }, /opciones/);
  failsWith((s) => { s.texts.page = s.texts.page.replace('options={["Bobina rechazada","Recorte de máquina"]}', 'options={["Bobina rechazada","Bobina rechazada"]}'); }, /distintas|duplicadas/);
  failsWith((s) => { s.texts.page = s.texts.page.replace('fld("observaciones", "Observaciones", "textarea", false)', 'fld("observaciones", "Observaciones", "textarea", false), fld("extra", "Extra", "text")'); }, /fuera del contrato/);
  failsWith((s) => { s.formDefinitions.find((f) => f.legacyNumber === 6).code = "VINTO-P1-99"; }, /se esperaba/);
});

test("validateBundle rejects dangling article-machine relations and duplicate options", () => {
  const { files, manifest } = buildBundle(sources);
  const broken = new Map(files);
  const relations = JSON.parse(files.get("article_machines.json"));
  relations.items.push({ article_code: "NO-EXISTE", machine_code: "MP1" });
  broken.set("article_machines.json", JSON.stringify(relations));
  assert.throws(() => validateBundle({ files: broken }), /inexistente/);
  const form = JSON.parse(files.get("forms/VINTO-P1-06.json"));
  form.fields[1].options[1].option_key = form.fields[1].options[0].option_key;
  const duplicate = new Map(files);
  duplicate.set("forms/VINTO-P1-06.json", JSON.stringify(form));
  assert.throws(() => validateBundle({ files: duplicate }), /duplicadas/);
  const stale = new Map(files);
  stale.set("units.json", stale.get("units.json") + " ");
  assert.throws(() => validateBundle({ files: stale, manifest }), /Checksum inconsistente/);
});
