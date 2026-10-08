// node --test scripts/export-seed-data.test.mjs
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { DEFAULT_OUT, PAGE_FINGERPRINT_SCOPE, SeedExportError, buildBundle, compareWithDisk, grammageFromDescription, loadSources, pageFingerprint, pageSemantics, validateBundle, writeBundle } from "./export-seed-data.mjs";

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
  assert.equal(manifest.counts.forms, 3);
  assert.equal(manifest.counts.form_fields, 18);
  assert.equal(manifest.counts.form_options, 5);
  assert.equal(manifest.pending_forms, undefined);
});

test("grammage is derived from the official description with a narrow G-<number> rule", () => {
  assert.equal(grammageFromDescription("M1-BOBINA PH G-17 CR-25% R-540640"), 17);
  assert.equal(grammageFromDescription("M1-BOBINA PH G-15.5 CR-22% R-540640"), 15.5);
  assert.equal(grammageFromDescription("M3-BOBINA PH G-14,5 CR-13% R-9109"), 14.5);
  assert.equal(grammageFromDescription("M3-BOBINA TOALLA G-19,5 CR-11%"), 19.5);
  assert.equal(grammageFromDescription("TB-TUBETE Ø 75 MM FORMATO 2730 MM"), null);
  assert.equal(grammageFromDescription("M1-BOBINA SEGUNDA"), null);
  assert.equal(grammageFromDescription("CR-25% R-540640"), null);   // not a G-<number>
  assert.equal(grammageFromDescription("PAG-17 BOBINA"), null);     // glued to a letter
  assert.equal(grammageFromDescription("BOBINA G-"), null);
  assert.equal(grammageFromDescription("BOBINA G-0"), null);
});

test("articles carry the derived grammage (null when absent) and the counts agree", () => {
  const { files, manifest } = buildBundle(sources);
  const items = JSON.parse(files.get("articles.json")).items;
  for (const a of items) assert.equal(a.version.grammage_g_m2, grammageFromDescription(a.version.description), a.code);
  assert.equal(manifest.counts.articles_with_grammage, items.filter((a) => a.version.grammage_g_m2 !== null).length);
  assert.ok(items.some((a) => a.version.grammage_g_m2 === null), "at least one article has no grammage");
  assert.ok(items.some((a) => a.version.grammage_g_m2 === 15.5));
});

test("F3 is published in the bundle with only the six manual fields and the MM unit", () => {
  const { files, manifest } = buildBundle(sources);
  const form = JSON.parse(files.get("forms/VINTO-P1-03.json"));
  assert.equal(form.code, "VINTO-P1-03");
  assert.deepEqual(form.machines, ["MP1", "MP3"]);
  assert.deepEqual(form.fields.map((f) => [f.key, f.value_type, f.required, f.unit, f.source]), [
    ["hora_inicio", "time", true, null, "manual"],
    ["hora_fin", "time", true, null, "manual"],
    ["diametro", "decimal", true, "MM", "manual"],
    ["peso_kg", "decimal", true, "KG", "manual"],
    ["numero_de_cortes", "text", true, null, "manual"],
    ["observaciones", "textarea", false, null, "manual"],
  ]);
  assert.ok(JSON.parse(files.get("units.json")).items.some((u) => u.code === "MM"));
  assert.ok(manifest.files.some((f) => f.path === "forms/VINTO-P1-03.json"));
});

test("fails when F3 changes the type or unit of a canonical field in the source", () => {
  failsWith((s) => { s.formDefinitions.find((f) => f.legacyNumber === 3).fields.find((f) => f.key === "diametro").type = "text"; }, /F3: diametro/);
  failsWith((s) => { s.formDefinitions.find((f) => f.legacyNumber === 3).fields.find((f) => f.key === "peso_kg").unit = "g"; }, /F3: la unidad de peso_kg/);
  failsWith((s) => { s.formDefinitions.find((f) => f.legacyNumber === 3).fields = s.formDefinitions.find((f) => f.legacyNumber === 3).fields.filter((f) => f.key !== "numero_de_cortes"); }, /F3: FORM_DEFINITIONS ya no define numero_de_cortes/);
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
  failsWith((s) => { s.texts.page = s.texts.page.replaceAll('fld("observaciones", "Observaciones", "textarea", false)', 'fld("observaciones", "Observaciones", "textarea", false), fld("extra", "Extra", "text")'); }, /fuera del contrato/); // replaceAll: el override de F3 en page.tsx usa el mismo literal y aparece antes que el de F6
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

// ---- app/page.tsx fingerprint: semantic values only ---------------------------------------------------------

const PAGE = sources.texts.page;
const fingerprint = (page) => pageFingerprint(page);
const withPage = (change) => mutated((s) => { s.texts.page = change(s.texts.page); });
const replaceOnce = (page, from, to) => {
  assert.equal(page.split(from).length - 1, 1, `fixture text not found exactly once: ${from.slice(0, 50)}`);
  return page.replace(from, to);
};
const pageEntry = (bundle) => bundle.manifest.generated_from.find((entry) => entry.path === "app/page.tsx");

test("the manifest fingerprints app/page.tsx semantically, not by file hash", () => {
  const { manifest } = buildBundle(sources);
  const entry = manifest.generated_from.find((e) => e.path === "app/page.tsx");
  assert.equal(entry.sha256, fingerprint(PAGE));
  assert.equal(entry.scope, PAGE_FINGERPRINT_SCOPE);
  assert.notEqual(entry.sha256, createHash("sha256").update(PAGE).digest("hex"));
  assert.deepEqual(Object.keys(pageSemantics(PAGE)).sort(), ["f6_choices", "f6_override", "groups_bobinas", "q19_override", "shift_night_rule"]);
  for (const other of manifest.generated_from.filter((e) => e.path !== "app/page.tsx")) assert.equal(other.scope, undefined);
});

test("unrelated page edits (authentication, UI text, new components, comments) do not change the fingerprint or the manifest", () => {
  const base = buildBundle(sources);
  const edits = [
    (page) => page + "\n// cambio irrelevante de autenticación\n",
    (page) => replaceOnce(page, "MVP To-Be actualizado", "MVP To-Be con autenticación real"),
    (page) => replaceOnce(page, "export default function Home() {", "function AuthBanner() { return <p>Sesión</p>; }\nexport default function Home() {"),
    (page) => page.replace(/\n/g, "\r\n"),
    (page) => replaceOnce(page, 'import { Toaster, toast }', 'import { toast, Toaster }').replace("import { toast, Toaster }", "import { Toaster, toast }"),
  ];
  for (const [index, edit] of edits.entries()) {
    let edited;
    try { edited = edit(PAGE); } catch { continue; } // an optional fixture that does not apply to this file layout
    if (index === 3) assert.equal(fingerprint(edited.replace(/\r\n/g, "\n")), fingerprint(PAGE)); // CRLF checkouts are normalised before hashing
    else assert.equal(fingerprint(edited), fingerprint(PAGE), `edit ${index}`);
    if (index !== 3) assert.equal(pageEntry(buildBundle(withPage(() => edited))).sha256, pageEntry(base).sha256);
  }
  const unrelated = buildBundle(withPage((page) => page + "\n// otro cambio\n"));
  assert.deepEqual([...unrelated.files], [...base.files]); // every file, manifest included, is byte-identical
});

test("formatting of the consumed blocks does not change the fingerprint, only their values do", () => {
  const spaced = replaceOnce(PAGE, 'fld("cantidad_fardos", "Cantidad de fardos", "integer")', 'fld("cantidad_fardos",    "Cantidad de fardos",\n        "integer")');
  assert.equal(fingerprint(spaced), fingerprint(PAGE));
  assert.deepEqual(buildBundle(withPage(() => spaced)).files, buildBundle(sources).files);
});

test("changing GROUPS.Bobinas changes the fingerprint", () => {
  const changed = replaceOnce(PAGE, 'Bobinas: ["MP1", "MP3"]', 'Bobinas: ["MP1", "MP3", "MP9"]');
  assert.notEqual(fingerprint(changed), fingerprint(PAGE));
  assert.throws(() => buildBundle(withPage(() => changed)), SeedExportError); // and the export stops: the pilot scope no longer matches
  const reordered = replaceOnce(PAGE, 'Bobinas: ["MP1", "MP3"]', 'Bobinas: ["MP3", "MP1"]');
  assert.notEqual(fingerprint(reordered), fingerprint(PAGE));
});

test("changing a consumed F6 label, type, unit or requirement changes the fingerprint and the output", () => {
  const relabelled = replaceOnce(PAGE, 'fld("cantidad_fardos", "Cantidad de fardos", "integer")', 'fld("cantidad_fardos", "Cantidad total de fardos", "integer")');
  assert.notEqual(fingerprint(relabelled), fingerprint(PAGE));
  const bundle = buildBundle(withPage(() => relabelled));
  assert.notEqual(bundle.files.get("forms/VINTO-P1-06.json"), buildBundle(sources).files.get("forms/VINTO-P1-06.json"));
  assert.notEqual(pageEntry(bundle).sha256, pageEntry(buildBundle(sources)).sha256);
  const f6Tail = 'fld("peso_kg", "Peso real total", "decimal", true, "kg"), fld("observaciones", "Observaciones", "textarea", false)';
  const optional = replaceOnce(PAGE, f6Tail, f6Tail.replace('"textarea", false', '"textarea", true'));
  assert.notEqual(fingerprint(optional), fingerprint(PAGE));
  const otherUnit = replaceOnce(PAGE, f6Tail, f6Tail.replace('true, "kg"', 'true, "lb"'));
  assert.notEqual(fingerprint(otherUnit), fingerprint(PAGE));
  assert.throws(() => buildBundle(withPage(() => otherUnit)), SeedExportError); // peso_kg must stay in KG
  const retyped = replaceOnce(PAGE, 'fld("cantidad_fardos", "Cantidad de fardos", "integer")', 'fld("cantidad_fardos", "Cantidad de fardos", "decimal")');
  assert.notEqual(fingerprint(retyped), fingerprint(PAGE));
});

test("changing the BobbinBales selectors or options changes the fingerprint", () => {
  const relabelledOption = replaceOnce(PAGE, '"Recorte de máquina"', '"Recorte de máquina (nuevo)"');
  assert.notEqual(fingerprint(relabelledOption), fingerprint(PAGE));
  assert.equal(buildBundle(withPage(() => relabelledOption)).files.get("forms/VINTO-P1-06.json").includes("Recorte de máquina (nuevo)"), true);
  const addedOption = replaceOnce(PAGE, 'options={["Bobina rechazada","Recorte de máquina"]}', 'options={["Bobina rechazada","Recorte de máquina","Otro"]}');
  assert.notEqual(fingerprint(addedOption), fingerprint(PAGE));
  assert.throws(() => buildBundle(withPage(() => addedOption)), SeedExportError);
  const relabelledSelector = replaceOnce(PAGE, '<Choice label="Tipo de producto" value={v.tipo_producto} set={x=>set("tipo_producto",x)} options={["Servilleta","Hoja doble","Hoja simple"]}/>',
    '<Choice label="Tipo de producto final" value={v.tipo_producto} set={x=>set("tipo_producto",x)} options={["Servilleta","Hoja doble","Hoja simple"]}/>');
  assert.notEqual(fingerprint(relabelledSelector), fingerprint(PAGE));
});

test("the night-shift rule in ctx() is part of the fingerprint", () => {
  const changed = replaceOnce(PAGE, "else if (h < 7 || h >= 19)", "else if (h < 8 || h >= 20)");
  assert.notEqual(fingerprint(changed), fingerprint(PAGE));
  const warned = buildBundle(withPage(() => changed)).manifest.warnings.map((w) => w.code);
  assert.ok(warned.includes("SHIFT_SOURCE_CHANGED"));
});

test("business data of the bundle does not depend on how page.tsx is fingerprinted", () => {
  const bundle = buildBundle(sources);
  const form = JSON.parse(bundle.files.get("forms/VINTO-P1-06.json"));
  assert.equal(form.definition_checksum, "fe0bf83fb710" + form.definition_checksum.slice(12));
  assert.equal(form.fields.length, 5);
});

test("VINTO-P1-19 is published in the bundle with only the seven manual source fields", () => {
  const { files, manifest } = buildBundle(sources);
  const form = JSON.parse(files.get("forms/VINTO-P1-19.json"));
  assert.deepEqual([form.code, form.name, form.area, form.workflow, form.version_number, form.machines, form.groups], ["VINTO-P1-19", "Control de humedad", "quality", "quality-release", 1, ["MP1", "MP3"], []]);
  assert.deepEqual(form.fields.map((f) => [f.key, f.value_type, f.required, f.unit, f.source]), [
    ["peso_humedo_comando", "decimal", true, "KG", "manual"], ["peso_seco_comando", "decimal", true, "KG", "manual"],
    ["peso_humedo_medio", "decimal", true, "KG", "manual"], ["peso_seco_medio", "decimal", true, "KG", "manual"],
    ["peso_humedo_transversal", "decimal", true, "KG", "manual"], ["peso_seco_transversal", "decimal", true, "KG", "manual"],
    ["observaciones", "textarea", false, null, "manual"],
  ]);
  const text = JSON.stringify(form);
  for (const derived of ["humedad_comando", "humedad_medio", "humedad_transversal", "promedio_humedad", "muestra_", "calculated", "automatic", "numero_de_bobina", "responsable", "maquina"]) assert.equal(text.includes(derived), false, derived);
  assert.ok(manifest.files.some((f) => f.path === "forms/VINTO-P1-19.json"));
  assert.ok(JSON.parse(files.get("workflows.json")).items.some((w) => w.code === "quality-release"));
});

test("fails when the P1-19 override in the page changes the canonical contract", () => {
  failsWith((s) => { s.texts.page = s.texts.page.replace('fld("peso_seco_medio", "Peso seco · Medio", "decimal", true, "kg")', 'fld("peso_seco_medio", "Peso seco · Medio", "text", true, "kg")'); }, /P1-19: peso_seco_medio/);
  failsWith((s) => { s.texts.page = s.texts.page.replace('fld("peso_seco_medio", "Peso seco · Medio", "decimal", true, "kg")', 'fld("peso_seco_medio", "Peso seco · Medio", "decimal", true, "g")'); }, /P1-19: la unidad de peso_seco_medio/);
  failsWith((s) => { s.texts.page = s.texts.page.replaceAll('fld("observaciones", "Observaciones", "textarea", false)', 'fld("observaciones", "Observaciones", "textarea", false), fld("extra", "Extra", "text")'); }, /fuera del contrato/); // replaceAll: el literal se repite en los overrides de F3, F6 y P1-19
});
