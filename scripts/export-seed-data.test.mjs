// node --test scripts/export-seed-data.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";
import test from "node:test";

import { CANDIDATE_REBOBINADO_SCOPE, CANDIDATE_SCOPE, DEFAULT_OUT, ROOT, assertSafeCandidateOut, DEFAULT_SCOPE, SCOPES, PAGE_FINGERPRINT_SCOPE, SeedExportError, buildBundle, compareWithDisk, grammageFromDescription, loadSources, pageFingerprint, pageFingerprintScope, pageSemantics, q20Label, validateBundle, validateSchedules, writeBundle } from "./export-seed-data.mjs";

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
  const committedUnits = JSON.parse(readFileSync(join(DEFAULT_OUT, "units.json"), "utf8")).items.map((u) => u.code);
  for (const code of units) assert.ok(committedUnits.includes(code), `${code}: sigue en el bundle comprometido`); // P1-20 / DEFAULT_SCOPE no inventa ninguna unidad
  // G.12-C4-FINAL25: Conversión (alcance candidato, fuera de DEFAULT_SCOPE) añadió PACK de forma aditiva al bundle comprometido (catálogo real, scripts/export-seed-data.mjs::CONVERSION_SECTOR).
  assert.deepEqual(committedUnits.filter((u) => !units.includes(u)), ["PACK"], "unidades añadidas solo por candidatos fuera del alcance DEFAULT");
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

// ---- M1-B2-a · declarative multi-sector scope ----------------------------------------------------------------------------------------
// The approved bundle is BOBINAS only and must not change. These tests prove the exporter is generalized (synthetic future scopes, in memory,
// never written) and that every new validation rejects what it must. Nothing here adds data to the committed bundle.

const CONVERSION_MACHINES = [
  { code: "GAMBINI", name: "Gambini", group: "Gambini", catalog: "GAMBINI" }, { code: "SINCRO_II", name: "Sincro II", group: "Sincro II", catalog: "Sincro II" },
  { code: "SINCRO_III", name: "Sincro III", group: "Sincro III", catalog: "Sincro III" }, { code: "OMET_I", name: "OMET I", group: "OMET I", catalog: "OMET I" },
  { code: "OMET_II", name: "OMET II", group: "OMET II", catalog: "OMET II" }, { code: "8_2", name: "8.2", group: "8.2", catalog: "8.2" },
  { code: "8_5", name: "8.5", group: "8.5", catalog: "8.5" }, { code: "8002", name: "8002", group: "8002", catalog: "8002" },
  { code: "SERV_4", name: "Serv 4", group: "Serv 4", catalog: "Serv 4" }, { code: "WALLY", name: "Wally", group: "Wally", catalog: "WALLY" },
  { code: "PANUELERA", name: "Pañuelera", group: "Pañuelera", catalog: "PAÑUELERA" },
];
const THREE_SHIFTS = [["MANANA", "Mañana", "06:00", "14:00"], ["TARDE", "Tarde", "14:00", "22:00"], ["NOCHE", "Noche", "22:00", "06:00"]];
const futureScope = (change = () => {}) => {
  const scope = structuredClone(DEFAULT_SCOPE);
  scope.sectors.push({ code: "CONVERSION", name: "Conversión", front: "Conversión", machines: structuredClone(CONVERSION_MACHINES), timezone: "America/La_Paz", valid_from: "2026-01-01", shifts: structuredClone(THREE_SHIFTS) });
  scope.unit_aliases = { Pack: "PACK" };
  change(scope);
  return scope;
};
const failsScope = (scope, pattern) => assert.throws(() => buildBundle(sources, scope), (error) => error instanceof SeedExportError && pattern.test(error.message));
const json = (map, name) => JSON.parse(map.get(name));
const sched = (shift, sector, start, end, from = "2026-01-01", to = null, tz = "America/La_Paz") => ({ shift, sector, starts_at: start, ends_at: end, timezone: tz, valid_from: from, valid_to: to });
const rejects = (schedules, pattern) => assert.throws(() => validateSchedules(schedules), (error) => error instanceof SeedExportError && pattern.test(error.message));

test("the default scope is the approved BOBINAS pilot and declaring it explicitly changes nothing", () => {
  assert.deepEqual(DEFAULT_SCOPE.sectors.map((s) => [s.code, s.name, s.front, s.machines.map((m) => m.code), s.timezone, s.valid_from, s.shifts]),
    [["BOBINAS", "Bobinas", "Bobinas", ["MP1", "MP3"], "America/La_Paz", "2026-01-01", [["DIA", "Día", "07:00", "19:00"], ["NOCHE", "Noche", "19:00", "07:00"]]]]);
  assert.equal(DEFAULT_SCOPE.forms_sector, "BOBINAS");
  assert.deepEqual(DEFAULT_SCOPE.unit_aliases, {});
  assert.equal(PAGE_FINGERPRINT_SCOPE, "semantic-extract:groups_bobinas,f6_override,f6_choices,q19_override,q20_override,shift_night_rule");
  assert.deepEqual([...buildBundle(sources).files], [...buildBundle(sources, structuredClone(DEFAULT_SCOPE)).files]);
  const { manifest } = buildBundle(sources);
  assert.deepEqual(manifest.scope, { sector: "Bobinas", machines: ["MP1", "MP3"], first_form: "VINTO-P1-06", forms: ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"] });
  assert.deepEqual([manifest.counts.sectors, manifest.counts.machines, manifest.counts.shifts, manifest.counts.shift_schedules], [1, 2, 2, 2]);
});

test("a synthetic multi-sector scope generates its master data without touching the published forms or the BOBINAS data", () => {
  const base = buildBundle(sources), extended = buildBundle(sources, futureScope());
  for (const name of [...base.files.keys()].filter((n) => n.startsWith("forms/") || n === "profiles.json" || n === "workflows.json")) {
    assert.equal(extended.files.get(name), base.files.get(name), name); // forms and their checksums are independent of how many sectors exist
  }
  assert.deepEqual(json(extended.files, "sectors.json").items.map((s) => s.code), ["BOBINAS", "CONVERSION"]);
  const machines = json(extended.files, "machines.json").items;
  assert.equal(machines.length, 13);
  assert.deepEqual(machines.slice(0, 2), json(base.files, "machines.json").items);
  assert.deepEqual(machines.filter((m) => m.sector === "CONVERSION").map((m) => m.code), CONVERSION_MACHINES.map((m) => m.code));
  assert.deepEqual(machines.find((m) => m.code === "SINCRO_II"), { code: "SINCRO_II", name: "Sincro II", sector: "CONVERSION" });
  const shifts = json(extended.files, "shifts.json");
  assert.deepEqual(shifts.shifts.map((s) => s.code), ["DIA", "NOCHE", "MANANA", "TARDE"]);
  assert.deepEqual(shifts.schedules.filter((s) => s.sector === "BOBINAS"), json(base.files, "shifts.json").schedules);
  assert.deepEqual(shifts.schedules.filter((s) => s.sector === "CONVERSION").map((s) => [s.shift, s.starts_at, s.ends_at]), [["MANANA", "06:00", "14:00"], ["TARDE", "14:00", "22:00"], ["NOCHE", "22:00", "06:00"]]);
  const baseArticles = json(base.files, "articles.json").items, extendedArticles = new Map(json(extended.files, "articles.json").items.map((a) => [a.code, a]));
  for (const article of baseArticles) assert.deepEqual(extendedArticles.get(article.code), article, article.code); // approved articles are untouched
  assert.ok(extendedArticles.size > baseArticles.length);
  const relations = json(extended.files, "article_machines.json").items;
  for (const r of json(base.files, "article_machines.json").items) assert.ok(relations.some((x) => x.article_code === r.article_code && x.machine_code === r.machine_code));
  const units = json(extended.files, "units.json").items.map((u) => u.code);
  assert.ok(units.includes("PACK") && !units.includes("Pack"), "the declared unit alias is applied");
  for (const code of json(base.files, "units.json").items.map((u) => u.code)) assert.ok(units.includes(code));
  assert.ok([...extendedArticles.values()].every((a) => units.includes(a.version.unit)));
  const { manifest } = extended;
  assert.deepEqual([manifest.counts.sectors, manifest.counts.machines, manifest.counts.shifts, manifest.counts.shift_schedules, manifest.counts.forms], [2, 13, 4, 5, 4]);
  assert.equal(manifest.counts.articles, extendedArticles.size);
  assert.equal(manifest.counts.article_machines, relations.length);
  assert.deepEqual(manifest.scope.sectors.map((s) => s.code), ["BOBINAS", "CONVERSION"]);
  assert.deepEqual(manifest.scope.machines, ["MP1", "MP3"]); // the scope of the FORMS does not grow
  assert.equal(manifest.generated_from.find((e) => e.path === "app/page.tsx").scope, pageFingerprintScope(futureScope()));
  assert.deepEqual(Object.keys(pageSemantics(PAGE, futureScope())).sort(), ["f6_choices", "f6_override", "groups_bobinas", "groups_conversion", "q19_override", "q20_override", "shift_night_rule"]);
  assert.notEqual(manifest.generated_from.find((e) => e.path === "app/page.tsx").sha256, base.manifest.generated_from.find((e) => e.path === "app/page.tsx").sha256);
});

test("a sector may be declared without shifts (it stays blocked until its hours are approved)", () => {
  const scope = futureScope((s) => { delete s.sectors[1].shifts; });
  const { files, manifest } = buildBundle(sources, scope);
  assert.deepEqual(json(files, "shifts.json").schedules.map((x) => x.sector), ["BOBINAS", "BOBINAS"]);
  assert.equal(manifest.counts.shift_schedules, 2);
});

test("scope declarations are validated: duplicates, invalid codes, missing machines and inconsistent shifts", () => {
  failsScope({ ...DEFAULT_SCOPE, sectors: [] }, /al menos un sector/);
  failsScope(futureScope((s) => { s.sectors[1].code = "BOBINAS"; }), /Sector duplicado en el alcance: BOBINAS/);
  for (const bad of ["conversion", "CONV ERSION", "1CONVERSION", "", "C".repeat(33)]) failsScope(futureScope((s) => { s.sectors[1].code = bad; }), /Sector con código inválido/);
  for (const bad of ["sincro ii", "SINCRO-II", "sincro_ii", "", "S".repeat(33)]) failsScope(futureScope((s) => { s.sectors[1].machines[1].code = bad; }), /Máquina con código inválido/);
  failsScope(futureScope((s) => { s.sectors[1].machines[0].code = "MP1"; }), /Máquina duplicada en el alcance: MP1/);
  failsScope(futureScope((s) => { s.sectors[1].machines[0].name = " mp1 "; }), /Nombre de máquina repetido/);
  failsScope(futureScope((s) => { s.sectors[1].machines = []; }), /sin máquinas/);
  failsScope(futureScope((s) => { s.sectors[1].name = ""; }), /sin nombre/);
  failsScope(futureScope((s) => { s.sectors[1].front = ""; }), /sin frente/);
  failsScope(futureScope((s) => { s.forms_sector = "REBOBINADO"; }), /forms_sector "REBOBINADO" no está entre los sectores declarados/);
  failsScope(futureScope((s) => { s.sectors[1].shifts[0][0] = "manana"; }), /Turno con código inválido/);
  failsScope(futureScope((s) => { s.sectors[1].shifts[2][1] = "Nocturno"; }), /Turno NOCHE declarado con nombres distintos/); // NOCHE ya existe en BOBINAS como «Noche»
  failsScope(futureScope((s) => { s.unit_aliases = { Pack: "pack" }; }), /unit_aliases/);
  failsScope(futureScope((s) => { s.unit_aliases = []; }), /unit_aliases debe ser un objeto/);
});

test("scope declarations are cross-checked against the sources (catalog and GROUPS in app/page.tsx)", () => {
  failsScope(futureScope((s) => { s.sectors[1].machines[0].catalog = "NO-EXISTE"; }), /La máquina GAMBINI no existe en PRODUCTS_BY_MACHINE/);
  failsScope(futureScope((s) => { s.sectors[1].machines[0].group = "Gambini 9"; }), /La máquina GAMBINI no pertenece a Conversión en GROUPS/);
  failsScope(futureScope((s) => { s.sectors[1].machines = s.sectors[1].machines.slice(0, 3); }), /GROUPS\.Conversión es \[/);
  failsScope(futureScope((s) => { s.sectors[1].front = "Fantasma"; }), /No se encontró GROUPS\.Fantasma/);
});

test("schedule validation: gaps, overlaps, midnight crossing, vigencias, time zones and changes of hours", () => {
  validateSchedules([sched("DIA", "BOBINAS", "07:00", "19:00"), sched("NOCHE", "BOBINAS", "19:00", "07:00")]); // the approved ones
  validateSchedules(THREE_SHIFTS.map(([c, , a, b]) => sched(c, "CONVERSION", a, b))); // 22:00–06:00 crosses midnight
  rejects([sched("DIA", "BOBINAS", "07:00", "18:00"), sched("NOCHE", "BOBINAS", "19:00", "07:00")], /BOBINAS desde 2026-01-01: minutos sin turno \(hueco\) 18:00–19:00/);
  rejects([sched("DIA", "BOBINAS", "07:00", "19:00"), sched("NOCHE", "BOBINAS", "18:00", "07:00")], /turnos solapados 18:00–19:00/);
  rejects([sched("MANANA", "C", "06:00", "14:00"), sched("TARDE", "C", "14:00", "22:00"), sched("NOCHE", "C", "22:00", "07:00")], /turnos solapados 06:00–07:00/);
  rejects([sched("MANANA", "C", "06:00", "14:00"), sched("TARDE", "C", "14:00", "22:00"), sched("NOCHE", "C", "22:00", "05:00")], /minutos sin turno \(hueco\) 05:00–06:00/);
  rejects([sched("DIA", "B", "07:00", "07:00")], /inicio y fin iguales/);
  rejects([sched("DIA", "B", "7", "19:00")], /hora inválida/);
  rejects([sched("DIA", "B", "25:00", "19:00")], /hora inválida/);
  rejects([sched("DIA", "B", "07:00", "19:00", "2026-01-01", "2025-12-31")], /valid_to anterior a valid_from/);
  rejects([sched("DIA", "B", "07:00", "19:00", "2026-02-30")], /vigencia con fecha inválida/);
  rejects([sched("DIA", "B", "07:00", "19:00"), sched("DIA", "B", "07:00", "19:00")], /shift_schedule duplicado/);
  rejects([sched("DIA", "B", "07:00", "19:00", "2026-01-01", null, "Mars/Olympus"), sched("NOCHE", "B", "19:00", "07:00", "2026-01-01", null, "Mars/Olympus")], /zona horaria inválida/);
  rejects([sched("DIA", "B", "07:00", "19:00"), sched("NOCHE", "B", "19:00", "07:00", "2026-01-01", null, "America/Lima")], /misma zona horaria/);
  const old = [sched("DIA", "B", "07:00", "19:00", "2026-01-01", "2026-10-31"), sched("NOCHE", "B", "19:00", "07:00", "2026-01-01", "2026-10-31")];
  rejects([...old, sched("DIA", "B", "07:00", "19:00", "2026-11-05"), sched("NOCHE", "B", "19:00", "07:00", "2026-11-05")], /no hay turnos vigentes entre 2026-11-01 y 2026-11-04/);
  // The M1-B1 finding: BOBINAS 07–19 → 06–18. Both regimes are fine alone, but the last old night ends at 07:00 and the new day starts at 06:00.
  rejects([...old, sched("DIA", "B", "06:00", "18:00", "2026-11-01"), sched("NOCHE", "B", "18:00", "06:00", "2026-11-01")],
    /el cambio de vigencia del 2026-11-01 deja el tiempo real sin turno o con turnos solapados \(2026-11-01 06:00–2026-11-01 07:00/);
  rejects([...old, sched("DIA", "B", "08:00", "20:00", "2026-11-01"), sched("NOCHE", "B", "20:00", "08:00", "2026-11-01")], /\(2026-11-01 07:00–2026-11-01 08:00/); // a gap
  validateSchedules([...old, sched("DIA", "B", "07:00", "19:00", "2026-11-01"), sched("NOCHE", "B", "19:00", "07:00", "2026-11-01")]); // same hours, new vigencia
  validateSchedules([...old, sched("MANANA", "B", "07:00", "15:00", "2026-11-01"), sched("TARDE", "B", "15:00", "23:00", "2026-11-01"), sched("NOCHE", "B", "23:00", "07:00", "2026-11-01")]);
});

test("validateBundle rejects inconsistent master data in the generated files", () => {
  const { files } = buildBundle(sources);
  const mutate = (name, change) => { const copy = new Map(files); const doc = JSON.parse(files.get(name)); change(doc); copy.set(name, JSON.stringify(doc)); return copy; };
  const renameMachine = (from, to) => (map) => {
    const withMachines = new Map(map); const machines = JSON.parse(map.get("machines.json")); machines.items.find((m) => m.code === from).code = to; withMachines.set("machines.json", JSON.stringify(machines));
    const relations = JSON.parse(map.get("article_machines.json")); for (const r of relations.items) if (r.machine_code === from) r.machine_code = to; withMachines.set("article_machines.json", JSON.stringify(relations));
    return withMachines;
  };
  const renameArticle = (to) => (map) => {
    const out = new Map(map); const articles = JSON.parse(map.get("articles.json")); const from = articles.items[0].code; articles.items[0].code = to; out.set("articles.json", JSON.stringify(articles));
    const relations = JSON.parse(map.get("article_machines.json")); for (const r of relations.items) if (r.article_code === from) r.article_code = to; out.set("article_machines.json", JSON.stringify(relations));
    return out;
  };
  const invalid = (map, pattern) => assert.throws(() => validateBundle({ files: map }), (error) => error instanceof SeedExportError && pattern.test(error.message));
  validateBundle({ files }); // the approved data passes every new check
  invalid(renameMachine("MP1", "mp 1")(files), /Máquina con código inválido: "mp 1"/);
  invalid(mutate("sectors.json", (d) => { d.items[0].code = "bobinas"; }), /Sector con código inválido/);
  invalid(mutate("units.json", (d) => { d.items.push({ ...d.items[0], code: "kg" }); }), /Unidad con código inválido/);
  invalid(mutate("shifts.json", (d) => { d.shifts[0].code = "dia"; }), /Turno con código inválido/);
  invalid(renameArticle("m1 1031")(files), /Artículo con código inválido: "m1 1031"/);
  invalid(mutate("machines.json", (d) => { d.items[1].name = " mp1 "; }), /Nombre de máquina repetido/);
  invalid(mutate("machines.json", (d) => { d.items[1].sector = "OTRO"; }), /Máquina MP3 sin sector válido: "OTRO"/);
  invalid(mutate("machines.json", (d) => { d.items.push({ ...d.items[0] }); }), /Máquina duplicad[ao] en el bundle: MP1/);
  invalid(mutate("article_machines.json", (d) => { d.items.push(d.items[0]); }), /Relación article-machine duplicada/);
  invalid(mutate("article_machines.json", (d) => { d.items.shift(); }), /Artículo de producto sin relación con ninguna máquina/);
  invalid(mutate("shifts.json", (d) => { d.schedules[0].ends_at = "18:00"; }), /minutos sin turno \(hueco\) 18:00–19:00/);
  invalid(mutate("shifts.json", (d) => { d.schedules[1].starts_at = "18:00"; }), /turnos solapados 18:00–19:00/);
  invalid(mutate("shifts.json", (d) => { d.schedules[1].shift = "FANTASMA"; }), /turno inexistente FANTASMA/);
  invalid(mutate("shifts.json", (d) => { d.schedules[0].sector = "FANTASMA"; }), /sector inexistente FANTASMA/);
});

// ---- M1-B2-b · candidate three-sector scope ----------------------------------------------------------------------------------------
// CANDIDATE_SCOPE is generated only on request (--scope candidate --out DIR); the committed bundle stays the approved BOBINAS one.

const REBOBINADO_CODES = ["BELOIT", "OVER", "COPASA", "PERICHUN", "TUBETERA"];
const CONVERSION_CODES = ["GAMBINI", "SINCRO_II", "SINCRO_III", "OMET_I", "OMET_II", "8_2", "8_5", "8002", "SERV_4", "WALLY", "PANUELERA"];
const candidate = buildBundle(sources, CANDIDATE_SCOPE);

test("the candidate scope is not the approved one and the approved bundle is still what is committed", () => {
  assert.notDeepEqual(CANDIDATE_SCOPE, DEFAULT_SCOPE);
  assert.deepEqual(Object.keys(SCOPES).slice(0, 2), ["approved", "candidate"]); // the partial candidate is covered by its own tests below
  assert.equal(SCOPES.approved, DEFAULT_SCOPE);
  assert.deepEqual(compareWithDisk(DEFAULT_OUT, buildBundle(sources, SCOPES.approved).files), []);
  assert.notDeepEqual(compareWithDisk(DEFAULT_OUT, candidate.files), []);
});

test("the candidate declares exactly the three sectors and their 18 technical machine codes", () => {
  const machines = json(candidate.files, "machines.json").items;
  assert.deepEqual(json(candidate.files, "sectors.json").items.map((s) => s.code), ["BOBINAS", "REBOBINADO", "CONVERSION"]);
  assert.deepEqual(machines.filter((m) => m.sector === "BOBINAS").map((m) => m.code), ["MP1", "MP3"]);
  assert.deepEqual(machines.filter((m) => m.sector === "REBOBINADO").map((m) => m.code), REBOBINADO_CODES);
  assert.deepEqual(machines.filter((m) => m.sector === "CONVERSION").map((m) => m.code), CONVERSION_CODES);
  assert.deepEqual(machines.slice(0, 2), json(buildBundle(sources).files, "machines.json").items); // MP1/MP3 untouched
  assert.deepEqual(machines.find((m) => m.code === "PANUELERA"), { code: "PANUELERA", name: "Pañuelera", sector: "CONVERSION" });
});

test("the candidate counts are the audited ones and the approved articles and relations are untouched", () => {
  const approved = buildBundle(sources);
  const { counts } = candidate.manifest;
  assert.deepEqual([counts.sectors, counts.machines, counts.articles, counts.article_machines, counts.shifts, counts.shift_schedules, counts.units, counts.material_classes], [3, 18, 315, 340, 4, 7, 4, 5]);
  const articles = new Map(json(candidate.files, "articles.json").items.map((a) => [a.code, a]));
  const base = json(approved.files, "articles.json").items;
  assert.equal(articles.size - base.length, 222);
  for (const a of base) assert.deepEqual(articles.get(a.code), a, a.code);
  const relations = json(candidate.files, "article_machines.json").items;
  const baseRelations = json(approved.files, "article_machines.json").items;
  assert.equal(relations.length - baseRelations.length, 247);
  for (const r of baseRelations) assert.ok(relations.some((x) => x.article_code === r.article_code && x.machine_code === r.machine_code));
  assert.equal(relations.filter((r) => r.machine_code === "MP1" || r.machine_code === "MP3").length, 93); // Bobinas keeps exactly its 93 relations
});

test("the candidate publishes no nominal weights or recipes and invents nothing for the new articles", () => {
  const articles = json(candidate.files, "articles.json").items;
  assert.ok(articles.every((a) => a.version.nominal_weight_kg === null));
  assert.equal(candidate.manifest.counts.articles_with_nominal_weight, 0);
  assert.ok(candidate.manifest.warnings.some((w) => w.code === "NOMINAL_WEIGHTS_DEFERRED"));
  assert.ok(buildBundle(sources, { ...CANDIDATE_SCOPE, nominal_weights: true }).manifest.counts.articles_with_nominal_weight > 0); // the switch is real, not cosmetic
  assert.ok(!candidate.files.has("recipes.json"));
});

test("PACK (label Pack) and BLANCOS come from the sources; no Bobinas article changes unit or class", () => {
  assert.deepEqual(json(candidate.files, "units.json").items, [{ code: "KG", label: "KG" }, { code: "MM", label: "MM" }, { code: "PACK", label: "Pack" }, { code: "UN", label: "UN" }]);
  assert.ok(json(candidate.files, "material_classes.json").items.some((c) => c.code === "BLANCOS" && c.name === "BLANCOS"));
  const articles = json(candidate.files, "articles.json").items;
  assert.ok(articles.every((a) => a.version.unit !== "Pack"));
  assert.ok(articles.filter((a) => a.version.unit === "PACK").length > 0);
  assert.deepEqual(articles.filter((a) => a.version.material_class === "BLANCOS").map((a) => a.code), ["10335"]); // sourced from MATERIALS
  const relations = json(candidate.files, "article_machines.json").items;
  const bobinasCodes = new Set(relations.filter((r) => r.machine_code === "MP1" || r.machine_code === "MP3").map((r) => r.article_code));
  assert.ok(articles.filter((a) => bobinasCodes.has(a.code)).every((a) => a.version.unit !== "PACK" && a.version.material_class !== "BLANCOS"));
  assert.equal(candidate.manifest.warnings.find((w) => w.code === "UNIT_LABEL_PLACEHOLDER").count, 3);
});

test("the candidate shifts keep Bobinas as is and cover each sector without gaps or overlaps", () => {
  const { schedules, shifts } = json(candidate.files, "shifts.json");
  assert.deepEqual(schedules.filter((s) => s.sector === "BOBINAS"), json(buildBundle(sources).files, "shifts.json").schedules);
  const hours = (sector) => schedules.filter((s) => s.sector === sector).map((s) => `${s.shift} ${s.starts_at}-${s.ends_at}`);
  assert.deepEqual(hours("REBOBINADO"), ["DIA 06:00-18:00", "NOCHE 18:00-06:00"]);
  assert.deepEqual(hours("CONVERSION"), ["MANANA 06:00-14:00", "TARDE 14:00-22:00", "NOCHE 22:00-06:00"]);
  assert.ok(schedules.every((s) => s.timezone === "America/La_Paz" && s.valid_from === "2026-01-01" && s.valid_to === null));
  assert.deepEqual(shifts.map((s) => [s.code, s.name]), [["DIA", "Día"], ["NOCHE", "Noche"], ["MANANA", "Mañana"], ["TARDE", "Tarde"]]);
  validateSchedules(schedules);
});

test("the four central forms are byte-identical and stay bound to MP1/MP3 only", () => {
  const approved = buildBundle(sources);
  for (const name of ["forms/VINTO-P1-03.json", "forms/VINTO-P1-06.json", "forms/VINTO-P1-19.json", "forms/VINTO-P1-20.json", "profiles.json", "workflows.json"]) {
    assert.equal(candidate.files.get(name), approved.files.get(name), name);
  }
  assert.deepEqual(candidate.manifest.scope.machines, ["MP1", "MP3"]);
  assert.deepEqual(candidate.manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
});

test("the candidate is reproducible byte for byte and passes every validation", () => {
  const again = buildBundle(sources, structuredClone(CANDIDATE_SCOPE));
  assert.deepEqual([...again.files], [...candidate.files]);
  validateBundle(candidate);
});

test("candidate declarations fail clearly when they drift from the sources", () => {
  const failsCandidate = (change, pattern) => failsScope((() => { const s = structuredClone(CANDIDATE_SCOPE); change(s); return s; })(), pattern);
  failsCandidate((s) => { s.unit_aliases = {}; s.unit_labels = {}; }, /Unidad con código inválido: "Pack"/); // without the alias the catalog "Pack" is rejected, never silently accepted
  failsCandidate((s) => { s.unit_labels = { PAQUETE: "Paquete" }; }, /unit_labels declara la unidad PAQUETE/);
  failsCandidate((s) => { s.unit_labels = { pack: "Pack" }; }, /unit_labels/);
  failsCandidate((s) => { s.nominal_weights = "no"; }, /nominal_weights debe ser booleano/);
  failsCandidate((s) => { s.sectors[2].machines.pop(); }, /GROUPS\.Conversión es \[/);
  failsCandidate((s) => { s.sectors[1].machines[0].catalog = "NO-EXISTE"; }, /no existe en PRODUCTS_BY_MACHINE/);
  failsCandidate((s) => { s.sectors[1].shifts[1][2] = "19:00"; }, /solapados|hueco/);
  failsCandidate((s) => { s.sectors[2].shifts[2][1] = "Nocturno"; }, /Turno NOCHE declarado con nombres distintos/);
});

test("NOCHE is one shift master shared by the three sectors, each with its own hours", () => {
  const { shifts, schedules } = json(candidate.files, "shifts.json");
  assert.equal(shifts.filter((s) => s.code === "NOCHE").length, 1);
  const night = schedules.filter((s) => s.shift === "NOCHE");
  assert.deepEqual(night.map((s) => [s.sector, s.starts_at, s.ends_at]), [["BOBINAS", "19:00", "07:00"], ["REBOBINADO", "18:00", "06:00"], ["CONVERSION", "22:00", "06:00"]]);
  for (const sector of ["BOBINAS", "REBOBINADO", "CONVERSION"]) validateSchedules(schedules.filter((s) => s.sector === sector)); // each sector is valid on its own
  assert.equal(new Set(schedules.map((s) => `${s.shift}|${s.sector}|${s.valid_from}`)).size, schedules.length);
});

test("articles that share an official description under different codes are published as distinct articles (documented for VINTO)", () => {
  const byDescription = new Map();
  for (const a of json(candidate.files, "articles.json").items) byDescription.set(a.version.description.toLowerCase(), [...(byDescription.get(a.version.description.toLowerCase()) ?? []), a.code]);
  const repeated = [...byDescription.values()].filter((codes) => codes.length > 1);
  assert.deepEqual(repeated, [["BC-1216-200", "BC-1216-230"], ["BC-1242-200", "BC-1242-400", "BC-1242-440"], ["RB-1216-200", "RB-1216-230", "RB-1216-580"], ["RB-1242-200", "RB-1242-400", "RB-1242-440"], ["RO-1242-200", "RO-1242-400", "RO-1242-440"]]);
});

test("a candidate bundle can only be written to a new or empty directory outside the approved bundle", () => {
  const root = mkdtempSync(join(tmpdir(), "seed-guard-"));
  try {
    const approved = join(root, "seed_data");
    mkdirSync(join(approved, "forms"), { recursive: true });
    writeFileSync(join(approved, "manifest.json"), "{}");
    const rejects = (dir, pattern) => assert.throws(() => assertSafeCandidateOut(dir, approved), (e) => e instanceof SeedExportError && pattern.test(e.message), dir);
    rejects(approved, /no puede ser el bundle aprobado/);
    rejects(`${approved}${sep}`, /no puede ser el bundle aprobado/);
    rejects(join(approved, "forms"), /no puede ser el bundle aprobado/); // inside it
    rejects(join(approved, "nuevo", "mas"), /no puede ser el bundle aprobado/); // new, but inside it
    rejects(root, /no puede ser el bundle aprobado/); // a parent that would contain it
    rejects(join(root, "seed_data", "..", "seed_data"), /no puede ser el bundle aprobado/);
    const full = join(root, "full");
    mkdirSync(full);
    writeFileSync(join(full, "x.json"), "{}");
    rejects(full, /nuevo o vacío/); // non-empty: the cleanup of stale *.json must never run on someone else's files
    assertSafeCandidateOut(join(root, "candidate"), approved); // new
    assertSafeCandidateOut(join(root, "deep", "er", "candidate"), approved); // new, parents do not exist yet
    const empty = join(root, "empty");
    mkdirSync(empty);
    assertSafeCandidateOut(empty, approved);
    assert.deepEqual(readdirSync(approved).sort(), ["forms", "manifest.json"]); // nothing was touched
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("the CLI never writes a candidate over the approved bundle and --check keeps verifying the approved one", () => {
  const run = (...args) => spawnSync(process.execPath, [join(ROOT, "scripts", "export-seed-data.mjs"), ...args], { encoding: "utf8" });
  const before = [...readdirSync(DEFAULT_OUT, { recursive: true })].sort();
  for (const args of [["--scope", "candidate"], ["--scope", "candidate", "--out", DEFAULT_OUT], ["--scope", "candidate", "--out", join(DEFAULT_OUT, "forms")], ["--scope", "candidate", "--out", join(DEFAULT_OUT, "..")],
    ["--scope", "candidate", "--check"], ["--scope", "candidate", "--check", "--out", DEFAULT_OUT], ["--scope", "nope", "--out", join(tmpdir(), "seed-never")], ["--scope", "--out", join(tmpdir(), "seed-never")]]) {
    const result = run(...args);
    assert.equal(result.status, 1, args.join(" "));
    assert.match(result.stderr, /Exportación detenida/);
  }
  assert.deepEqual([...readdirSync(DEFAULT_OUT, { recursive: true })].sort(), before);
  assert.deepEqual(compareWithDisk(DEFAULT_OUT, buildBundle(sources).files), []);
  const check = run("--check");
  assert.equal(check.status, 0);
  assert.match(check.stdout, /Bundle al día \(14 archivos\)/);
  assert.equal(run("--scope", "approved", "--check").status, 0);
  const out = mkdtempSync(join(tmpdir(), "seed-cli-"));
  try {
    assert.equal(run("--scope", "candidate", "--out", out).status, 0);
    assert.equal(readFileSync(join(out, "manifest.json"), "utf8"), candidate.files.get("manifest.json"));
    assert.equal(run("--scope", "candidate", "--out", out).status, 1); // second run into a non-empty directory
  } finally { rmSync(out, { recursive: true, force: true }); }
});

// ---- M1-B2-c2a · partial candidate scope: Bobinas + Rebobinado -------------------------------------------------------------------------
// TECHNICAL preparation only. VINTO has not approved these data; the scope cannot be promoted to backend/seed_data nor imported to DEV.

const rebobinado = buildBundle(sources, CANDIDATE_REBOBINADO_SCOPE);

test("candidate-rebobinado is composed from the existing declarations, with no manual copy of masters", () => {
  assert.deepEqual(Object.keys(SCOPES), ["approved", "candidate", "candidate-rebobinado"]);
  assert.equal(SCOPES["candidate-rebobinado"], CANDIDATE_REBOBINADO_SCOPE);
  assert.equal(CANDIDATE_REBOBINADO_SCOPE.sectors[0], DEFAULT_SCOPE.sectors[0], "Bobinas is the very same declaration as the approved one");
  assert.equal(CANDIDATE_REBOBINADO_SCOPE.sectors[1], CANDIDATE_SCOPE.sectors[1], "Rebobinado is declared once and shared with the full candidate");
  assert.deepEqual(CANDIDATE_REBOBINADO_SCOPE.sectors.map((s) => s.code), ["BOBINAS", "REBOBINADO"]);
  assert.equal(CANDIDATE_REBOBINADO_SCOPE.candidate, true);
  assert.equal(CANDIDATE_SCOPE.candidate, true);
  assert.notEqual(DEFAULT_SCOPE.candidate, true, "the approved scope is never a candidate");
  assert.equal(CANDIDATE_REBOBINADO_SCOPE.nominal_weights, false);
  assert.deepEqual(CANDIDATE_REBOBINADO_SCOPE.unit_aliases, {});
  assert.equal(CANDIDATE_REBOBINADO_SCOPE.unit_labels, undefined, "no PACK label: Conversión is the only user of PACK");
  assert.equal(CANDIDATE_REBOBINADO_SCOPE.forms_sector, "BOBINAS");
});

test("the partial candidate has exactly the expected counts and nothing from Conversión", () => {
  const { counts } = rebobinado.manifest;
  assert.deepEqual([counts.sectors, counts.machines, counts.articles, counts.article_machines, counts.shifts, counts.shift_schedules, counts.forms, counts.units, counts.material_classes],
    [2, 7, 241, 242, 2, 4, 4, 3, 4]);
  assert.deepEqual(json(rebobinado.files, "sectors.json").items.map((s) => s.code), ["BOBINAS", "REBOBINADO"]);
  assert.deepEqual(json(rebobinado.files, "machines.json").items.map((m) => m.code), ["MP1", "MP3", ...REBOBINADO_CODES]);
  const articles = json(rebobinado.files, "articles.json").items;
  assert.ok(articles.every((a) => a.version.unit !== "PACK" && a.version.unit !== "Pack" && a.version.material_class !== "BLANCOS" && a.version.nominal_weight_kg === null));
  assert.deepEqual(json(rebobinado.files, "units.json").items, [{ code: "KG", label: "KG" }, { code: "MM", label: "MM" }, { code: "UN", label: "UN" }]);
  assert.ok(!json(rebobinado.files, "material_classes.json").items.some((c) => c.code === "BLANCOS"));
  assert.ok(!articles.some((a) => a.code === "10335"), "the only BLANCOS article belongs to Conversión");
  const conversionOnly = new Set(json(candidate.files, "article_machines.json").items.filter((r) => CONVERSION_CODES.includes(r.machine_code)).map((r) => r.article_code));
  const conversionExclusive = [...conversionOnly].filter((code) => !json(candidate.files, "article_machines.json").items.some((r) => r.article_code === code && !CONVERSION_CODES.includes(r.machine_code)));
  assert.ok(conversionExclusive.length > 0 && articles.every((a) => !conversionExclusive.includes(a.code)), "no Conversión article leaks in");
  assert.ok(!rebobinado.files.has("recipes.json"));
});

test("Bobinas is byte-identical to the approved bundle inside the partial candidate", () => {
  const approved = buildBundle(sources);
  for (const name of ["forms/VINTO-P1-03.json", "forms/VINTO-P1-06.json", "forms/VINTO-P1-19.json", "forms/VINTO-P1-20.json", "profiles.json", "workflows.json"]) {
    assert.equal(rebobinado.files.get(name), approved.files.get(name), name);
  }
  const articles = new Map(json(rebobinado.files, "articles.json").items.map((a) => [a.code, a]));
  for (const a of json(approved.files, "articles.json").items) assert.deepEqual(articles.get(a.code), a, a.code);
  const relations = json(rebobinado.files, "article_machines.json").items;
  for (const r of json(approved.files, "article_machines.json").items) assert.ok(relations.some((x) => x.article_code === r.article_code && x.machine_code === r.machine_code));
  assert.equal(relations.filter((r) => r.machine_code === "MP1" || r.machine_code === "MP3").length, 93);
  assert.deepEqual(json(rebobinado.files, "shifts.json").schedules.filter((s) => s.sector === "BOBINAS"), json(approved.files, "shifts.json").schedules);
  assert.deepEqual(rebobinado.manifest.scope.machines, ["MP1", "MP3"], "the four central forms stay bound to MP1 and MP3");
  assert.deepEqual(rebobinado.manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  for (const name of ["VINTO-P1-03", "VINTO-P1-06", "VINTO-P1-19", "VINTO-P1-20"]) {
    assert.ok(!/BELOIT|OVER|COPASA|PERICHUN|TUBETERA/.test(rebobinado.files.get(`forms/${name}.json`)), name);
  }
  assert.deepEqual(compareWithDisk(DEFAULT_OUT, approved.files), [], "the committed approved bundle is untouched");
});

test("Rebobinado data in the partial candidate equals the Rebobinado data of the full candidate", () => {
  const pick = (map) => ({
    articles: json(map, "articles.json").items.filter((a) => !json(map, "article_machines.json").items.every((r) => r.article_code !== a.code || CONVERSION_CODES.includes(r.machine_code))),
    relations: json(map, "article_machines.json").items.filter((r) => REBOBINADO_CODES.includes(r.machine_code)),
    machines: json(map, "machines.json").items.filter((m) => m.sector === "REBOBINADO"),
    schedules: json(map, "shifts.json").schedules.filter((s) => s.sector === "REBOBINADO"),
  });
  assert.deepEqual(pick(rebobinado.files), pick(candidate.files));
  assert.deepEqual(json(rebobinado.files, "shifts.json").schedules.filter((s) => s.sector === "REBOBINADO").map((s) => [s.shift, s.starts_at, s.ends_at, s.timezone, s.valid_from, s.valid_to]),
    [["DIA", "06:00", "18:00", "America/La_Paz", "2026-01-01", null], ["NOCHE", "18:00", "06:00", "America/La_Paz", "2026-01-01", null]]);
  assert.deepEqual(json(rebobinado.files, "shifts.json").shifts.map((s) => s.code), ["DIA", "NOCHE"], "the shift masters are the existing ones: DIA and NOCHE are shared with Bobinas");
  validateSchedules(json(rebobinado.files, "shifts.json").schedules.filter((s) => s.sector === "REBOBINADO"));
  validateBundle(rebobinado);
});

test("every candidate keeps the provisional-data warnings and the approved bundle carries none", () => {
  for (const bundle of [rebobinado, candidate]) {
    const codes = bundle.manifest.warnings.map((w) => w.code);
    for (const code of ["SCOPE_PENDING_APPROVAL", "SHIFT_VALIDITY_PROVISIONAL", "NOMINAL_WEIGHTS_DEFERRED"]) assert.ok(codes.includes(code), code);
    assert.equal(bundle.manifest.scope.candidate, true);
    assert.match(bundle.manifest.warnings.find((w) => w.code === "SCOPE_PENDING_APPROVAL").message, /No está autorizado promoverlo a backend\/seed_data ni importarlo a DEV/);
    assert.match(bundle.manifest.warnings.find((w) => w.code === "SHIFT_VALIDITY_PROVISIONAL").message, /provisionales/);
  }
  const approved = buildBundle(sources);
  assert.ok(!approved.manifest.warnings.some((w) => w.code === "SCOPE_PENDING_APPROVAL"));
  assert.equal(approved.manifest.scope.candidate, undefined);
});

test("the partial candidate is reproducible byte for byte", () => {
  const again = buildBundle(sources, structuredClone(CANDIDATE_REBOBINADO_SCOPE));
  assert.deepEqual([...again.files], [...rebobinado.files]);
});

test("a PACK alias or label cannot be declared without Conversión and the candidate flag must be a boolean", () => {
  failsScope({ ...structuredClone(CANDIDATE_REBOBINADO_SCOPE), unit_labels: { PACK: "Pack" } }, /unit_labels declara la unidad PACK/);
  failsScope({ ...structuredClone(CANDIDATE_REBOBINADO_SCOPE), unit_aliases: { Pack: "PACK" }, unit_labels: { PACK: "Pack" } }, /unit_labels declara la unidad PACK/);
  failsScope({ ...structuredClone(CANDIDATE_REBOBINADO_SCOPE), candidate: "yes" }, /candidate debe ser booleano/);
});

test("the CLI writes candidate-rebobinado only to a new directory outside the approved bundle and never accepts --check for it", () => {
  const run = (...args) => spawnSync(process.execPath, [join(ROOT, "scripts", "export-seed-data.mjs"), ...args], { encoding: "utf8" });
  const before = [...readdirSync(DEFAULT_OUT, { recursive: true })].sort();
  for (const args of [["--scope", "candidate-rebobinado"], ["--scope", "candidate-rebobinado", "--out", DEFAULT_OUT], ["--scope", "candidate-rebobinado", "--out", join(DEFAULT_OUT, "forms")],
    ["--scope", "candidate-rebobinado", "--out", join(DEFAULT_OUT, "..")], ["--scope", "candidate-rebobinado", "--check", "--out", join(tmpdir(), "seed-never-reb")]]) {
    const result = run(...args);
    assert.equal(result.status, 1, args.join(" "));
    assert.match(result.stderr, /Exportación detenida/);
  }
  assert.deepEqual([...readdirSync(DEFAULT_OUT, { recursive: true })].sort(), before);
  const out = mkdtempSync(join(tmpdir(), "seed-reb-"));
  try {
    const first = run("--scope", "candidate-rebobinado", "--out", out);
    assert.equal(first.status, 0, first.stderr);
    assert.match(first.stdout, /articles: 241/);
    assert.equal(readFileSync(join(out, "manifest.json"), "utf8"), rebobinado.files.get("manifest.json"));
    assert.equal(run("--scope", "candidate-rebobinado", "--out", out).status, 1, "a second run into a non-empty directory is refused");
  } finally { rmSync(out, { recursive: true, force: true }); }
  assert.equal(run("--check").status, 0);
});
