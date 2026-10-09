// node --test scripts/export-seed-data.test.mjs
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { DEFAULT_OUT, PAGE_FINGERPRINT_SCOPE, SeedExportError, buildBundle, compareWithDisk, grammageFromDescription, loadSources, pageFingerprint, pageSemantics, q20Label, validateBundle, writeBundle } from "./export-seed-data.mjs";

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
  assert.equal(manifest.counts.forms, 4);
  assert.equal(manifest.counts.form_fields, 30); // F6 5 + F3 6 + P1-19 7 + P1-20 12
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
  assert.deepEqual(Object.keys(pageSemantics(PAGE)).sort(), ["f6_choices", "f6_override", "groups_bobinas", "q19_override", "q20_override", "shift_night_rule"]);
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

// ---- VINTO-P1-20 (Propiedades físicas de bobina): provisional canonical contract ------------------------------------------

const Q20_EXPECTED = [
  ["crepado", "decimal", true, null, "manual"], ["gramaje", "decimal", true, null, "manual"],
  ["resistencia_longitudinal_centro", "decimal", true, null, "manual"], ["resistencia_longitudinal_medio", "decimal", true, null, "manual"],
  ["resistencia_longitudinal_extremo", "decimal", true, null, "manual"], ["resistencia_transversal_centro", "decimal", true, null, "manual"],
  ["resistencia_transversal_medio", "decimal", true, null, "manual"], ["resistencia_transversal_extremo", "decimal", true, null, "manual"],
  ["espesor_centro", "decimal", true, "MM", "manual"], ["espesor_medio", "decimal", true, "MM", "manual"], ["espesor_extremo", "decimal", true, "MM", "manual"],
  ["observaciones", "textarea", false, null, "manual"],
];
const q20Of = (s) => s.formDefinitions.find((f) => f.legacyNumber === 20);

test("VINTO-P1-20 is published for MP1/MP3 with exactly the twelve manual fields", () => {
  const { files, manifest } = buildBundle(sources);
  const form = JSON.parse(files.get("forms/VINTO-P1-20.json"));
  assert.deepEqual([form.legacy_key, form.code, form.legacy_number, form.name, form.area, form.workflow, form.version_number, form.machines, form.groups],
    ["form_20_propiedades_fisicas_de_bobina", "VINTO-P1-20", 20, "Propiedades físicas de bobina", "quality", "quality-release", 1, ["MP1", "MP3"], []]);
  assert.deepEqual(form.fields.map((f) => [f.key, f.value_type, f.required, f.unit, f.source]), Q20_EXPECTED);
  assert.deepEqual(form.fields.map((f) => f.display_order), Array.from({ length: 12 }, (_, i) => i + 1));
  assert.equal(form.fields.filter((f) => f.value_type === "decimal").length, 11);
  assert.ok(form.fields.every((f) => f.options === undefined), "no options");
  assert.ok(manifest.files.some((f) => f.path === "forms/VINTO-P1-20.json"));
  assert.ok(manifest.scope.forms.includes("VINTO-P1-20"));
  assert.ok(manifest.warnings.some((w) => w.code === "P1_20_PROVISIONAL_CONTRACT"));
  assert.ok(manifest.authority_rules.p1_20_labels_units);
});

test("VINTO-P1-20 excludes automatic data, bobbin/F3 context and averages; no catalog unit is invented for g/m²", () => {
  const form = JSON.parse(buildBundle(sources).files.get("forms/VINTO-P1-20.json"));
  const keys = form.fields.map((f) => f.key);
  for (const excluded of ["fecha", "hora", "maquina", "responsable", "numero_de_bobina", "producto", "numero_de_cortes",
    "promedio_resistencia_longitudinal", "promedio_resistencia_transversal", "promedio_espesor"]) assert.equal(keys.includes(excluded), false, excluded);
  const text = JSON.stringify(form);
  for (const word of ["promedio", "calculated", "automatic", "minimo", "maximo", "tolerancia", "conforme", "default"]) assert.equal(text.toLowerCase().includes(word), false, word);
  assert.equal(form.fields.find((f) => f.key === "gramaje").unit, null);
  const units = JSON.parse(buildBundle(sources).files.get("units.json")).items.map((u) => u.code);
  assert.deepEqual(units, JSON.parse(readFileSync(join(DEFAULT_OUT, "units.json"), "utf8")).items.map((u) => u.code), "no new unit code");
  assert.equal(units.length, 3);
  assert.equal(units.some((u) => /G.?M2|GM2|G\/M/i.test(u)), false);
  // the technical *_centro keys stay intact
  assert.deepEqual(keys.filter((k) => k.endsWith("_centro")), ["resistencia_longitudinal_centro", "resistencia_transversal_centro", "espesor_centro"]);
});

test("adding P1-20 does not alter the already published forms (byte-identical checksums)", () => {
  const { files } = buildBundle(sources);
  const checksum = (code) => JSON.parse(files.get(`forms/${code}.json`)).definition_checksum;
  assert.equal(checksum("VINTO-P1-03"), "816b1d78081592a76d74dce87e4c83ca345246020806a064150f391ce87c0c13");
  assert.equal(checksum("VINTO-P1-06"), "fe0bf83fb71057d8debbd014d20bfd3cd13aa4a6310c2b94be56ce2d2eb4f45f");
  assert.equal(checksum("VINTO-P1-19"), "682908dee7878ce55313011a9a62ef9c0b82dbae404ed129bacaf2366c8a22ff");
  assert.equal(checksum("VINTO-P1-20"), "1145b41c568e4616dddbfb9f2c5eff21e253a3840df36a87fa416871e30fbbe0"); // con las etiquetas visibles «comando»
});

const Q20_LABELS = [
  ["crepado", "Crepado"], ["gramaje", "Gramaje"],
  ["resistencia_longitudinal_centro", "Resistencia longitudinal comando"], ["resistencia_longitudinal_medio", "Resistencia longitudinal medio"],
  ["resistencia_longitudinal_extremo", "Resistencia longitudinal extremo"], ["resistencia_transversal_centro", "Resistencia transversal comando"],
  ["resistencia_transversal_medio", "Resistencia transversal medio"], ["resistencia_transversal_extremo", "Resistencia transversal extremo"],
  ["espesor_centro", "Espesor comando"], ["espesor_medio", "Espesor medio"], ["espesor_extremo", "Espesor extremo"], ["observaciones", "Observaciones"],
];

test("VINTO-P1-20 publishes the visible labels of the effectiveForms override while keeping the *_centro keys", () => {
  const form = JSON.parse(buildBundle(sources).files.get("forms/VINTO-P1-20.json"));
  assert.deepEqual(form.fields.map((f) => [f.key, f.label]), Q20_LABELS);
  assert.equal(form.fields.some((f) => /centro/i.test(f.label)), false, "no visible label says centro");
  assert.equal(form.fields.filter((f) => f.key.endsWith("_centro")).length, 3, "technical keys are not renamed");
  // the published labels are exactly what effectiveForms() would show (same transformation as app/page.tsx), without touching the page
  const legacy = q20Of(sources);
  for (const f of form.fields) assert.equal(f.label, q20Label(f.key, legacy.fields.find((x) => x.key === f.key).label, { from: "centro", to: "comando" }), f.key);
});

test("fails when the P1-20 source deviates from the canonical contract", () => {
  failsWith((s) => { q20Of(s).fields.find((f) => f.key === "crepado").type = "text"; }, /P1-20: crepado/);
  failsWith((s) => { q20Of(s).fields.find((f) => f.key === "espesor_medio").required = false; }, /P1-20: espesor_medio cambió su obligatoriedad/);
  failsWith((s) => { q20Of(s).fields.find((f) => f.key === "gramaje").unit = "kg"; }, /P1-20: la unidad de gramaje/);
  failsWith((s) => { q20Of(s).fields.find((f) => f.key === "espesor_centro").unit = "mm"; }, /P1-20: la unidad de espesor_centro/);
  failsWith((s) => { q20Of(s).fields = q20Of(s).fields.filter((f) => f.key !== "resistencia_transversal_extremo"); }, /P1-20: FORM_DEFINITIONS ya no define resistencia_transversal_extremo/);
  failsWith((s) => { q20Of(s).fields.push({ ...q20Of(s).fields.find((f) => f.key === "crepado"), key: "brillo", id: "brillo" }); }, /P1-20: FORM_DEFINITIONS define campos fuera del contrato canónico: brillo/);
  failsWith((s) => { q20Of(s).fields = q20Of(s).fields.filter((f) => f.key !== "promedio_espesor"); }, /campos excluidos promedio_espesor/);
  failsWith((s) => { q20Of(s).fields.find((f) => f.key === "espesor_centro").source = "calculated"; }, /P1-20: espesor_centro es calculated/);
  failsWith((s) => { q20Of(s).allowedMachineIds = ["mp1"]; }, /P1-20 no admite la máquina MP3/);
  failsWith((s) => { q20Of(s).area = "production"; }, /P1-20 debe tener area quality/);
});

test("the P1-20 espesor unit comes from the page override and is part of the fingerprint", () => {
  assert.deepEqual(pageSemantics(PAGE).q20_override, { espesor_unit: "mm", relabel: { from: "centro", to: "comando" } });
  const changed = replaceOnce(PAGE, 'x.key.includes("espesor") ? { ...x, unit: "mm"', 'x.key.includes("espesor") ? { ...x, unit: "cm"');
  assert.notEqual(fingerprint(changed), fingerprint(PAGE));
  assert.throws(() => buildBundle(withPage(() => changed)), (e) => e instanceof SeedExportError && /P1-20: el override de app\/page\.tsx fija espesor en "cm"/.test(e.message));
  const removed = replaceOnce(PAGE, 'x.key.includes("espesor") ? { ...x, unit: "mm"', 'x.key.includes("grosor") ? { ...x, unit: "mm"');
  assert.throws(() => pageSemantics(removed), /P1-20: el override de app\/page\.tsx ya no fija la unidad de espesor/);
});

test("the P1-20 relabelling comes from the page override, is fingerprinted and must be consistent", () => {
  const P20 = 'needsValidation: false, label: x.label.replace("centro", "comando") } : x.label.toLowerCase().includes("centro") ? { ...x, label: x.label.replace("centro", "comando") }';
  const renamed = replaceOnce(PAGE, P20, P20.replaceAll('"comando"', '"mando"'));
  assert.notEqual(fingerprint(renamed), fingerprint(PAGE));
  const form = JSON.parse(buildBundle(withPage(() => renamed)).files.get("forms/VINTO-P1-20.json"));
  assert.deepEqual(form.fields.filter((f) => f.key.endsWith("_centro")).map((f) => f.label), ["Resistencia longitudinal mando", "Resistencia transversal mando", "Espesor mando"]);
  assert.notEqual(form.definition_checksum, JSON.parse(buildBundle(sources).files.get("forms/VINTO-P1-20.json")).definition_checksum);
  const inconsistent = replaceOnce(PAGE, P20, P20.replace('x.label.replace("centro", "comando") }', 'x.label.replace("centro", "punta") }'));
  assert.throws(() => pageSemantics(inconsistent), /P1-20: el override de app\/page\.tsx reetiqueta espesor y el resto de campos de forma distinta/);
  const dropped = replaceOnce(PAGE, P20, P20.replace(' : x.label.toLowerCase().includes("centro") ? { ...x, label: x.label.replace("centro", "comando") }', ''));
  assert.throws(() => pageSemantics(dropped), /P1-20: el override de app\/page\.tsx ya no reetiqueta/);
});
