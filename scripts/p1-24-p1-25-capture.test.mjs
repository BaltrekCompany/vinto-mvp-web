// node --test scripts/p1-24-p1-25-capture.test.mjs
// DEV-Q3 · candidatos de Calidad ligados a UNA BOBINA física F3 de MP1 / MP3: VINTO-P1-24 (Propiedades físicas en húmedo) y VINTO-P1-25 (Resistencia en húmedo-curado). Contrato frente a form-definitions.ts, tipos
// (curado_min es TEXTO), automáticos y calculados ausentes (ningún promedio ni porcentaje se calcula), payload de contexto «bobina», parser estricto, flujo con reconciliación, oferta según el backend, aislamiento
// por sesión y por bobina y límites de alcance (política vacía, rebobinadoras no cubiertas, P1-19 / P1-20 / P1-21 sin tocar). Lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { parseAvailability } from "../lib/vinto/availability.ts";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { labelFor } from "../lib/vinto/candidate-form.ts";
import { P124, P124_CALCULATED_FIELDS, P124_FIELDS, P124_MEANS, P124_PENDING, P1_24_CODE } from "../lib/vinto/p1-24.ts";
import { P125, P125_CALCULATED_FIELDS, P125_FIELDS, P125_MEANS, P125_PENDING, P1_25_CODE } from "../lib/vinto/p1-25.ts";
import { meanTwoDecimals, previewMeans } from "../lib/vinto/quality-averages.ts";
import { bobbinScreensFor, publishedQualityScreens, qualityScreensFor } from "../lib/vinto/quality-offers.ts";
import { candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", BOBBIN = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a";
const defOf = (id) => FORM_DEFINITIONS.find((f) => f.id === id);
const isManual = (f) => f.source === "manual";
const KIND = (f) => (f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : "text");
const NEW_KINDS = { n_cortes: "integer" }; // MF-06: no existe en la definición legacy
const fill = (fields, textValue = "texto") => Object.fromEntries(fields.map((f) => [f.key, f.kind === "decimal" ? "1,5" : f.kind === "integer" ? "3" : f.key === "numero_de_bobina" ? "12" : f.key === "observaciones" ? " nota " : textValue]));
const CASES = [
  { name: "P1-24", id: "form_24_propiedades_fisicas_en_humedo", form: P124, formCode: P1_24_CODE, fields: P124_FIELDS, calculated: P124_CALCULATED_FIELDS, pending: P124_PENDING, counts: [12, 4, 2], removed: ["numero_de_bobina", "producto"], added: [], screen: "p124", machines: ["mp1", "mp3", "todas_las_rebobinadoras"] },
  { name: "P1-25", id: "form_25_resistencia_en_humedo_curado", form: P125, formCode: P1_25_CODE, fields: P125_FIELDS, calculated: P125_CALCULATED_FIELDS, pending: P125_PENDING, counts: [14, 3, 3], removed: ["numero_de_bobina", "producto", "gramaje_laboratorio_g_m2"], added: ["caudal_rh_ml_min", "n_cortes"], screen: "p125", machines: ["por_definir"] },
];

const envelope = (formCode, values, extra = {}) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", bobbin: { id: BOBBIN, code: "12" }, work_order: { id: UUID, number: "OT-1" },
  line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values, ...extra });

test("los contratos son EXACTAMENTE los campos manuales de las definiciones legacy; automáticos y calculados no se digitan", () => {
  for (const c of CASES) {
    const legacy = defOf(c.id);
    assert.equal(legacy.area, "quality");
    assert.deepEqual([legacy.fields.filter(isManual).length, legacy.fields.filter((f) => f.source === "automatic").length, legacy.fields.filter((f) => f.source === "calculated").length], c.counts, c.name);
    assert.equal(legacy.fields.length, c.counts[0] + c.counts[1] + c.counts[2]);
    const m = legacy.fields.filter(isManual).filter((f) => !c.removed.includes(f.key)); // MF-06: versión 2 = definición legacy menos los campos retirados (más los añadidos, comprobados aparte)
    const kept = c.fields.filter((f) => !c.added.includes(f.key));
    assert.deepEqual(c.removed.filter((k) => c.fields.some((f) => f.key === k)), [], `${c.name}: los retirados ya no existen`);
    assert.deepEqual(kept.map((f) => f.key), m.map((f) => f.key), `${c.name}: claves y orden`);
    assert.deepEqual(kept.map((f) => labelFor(f, 2)), m.map((f) => f.label), `${c.name}: etiquetas de la versión anterior (MF-07 solo renombra posiciones; la versión 2 conserva las suyas)`);
    assert.deepEqual(kept.map((f) => f.required), m.map((f) => f.required ?? f.requirement), `${c.name}: obligatoriedad`);
    assert.deepEqual(kept.map((f) => f.kind), m.map(KIND), `${c.name}: tipos`);
    for (const f of legacy.fields.filter((x) => !isManual(x))) assert.equal(c.fields.some((x) => x.key === f.key), false, `${c.name}: ${f.key} no se digita`);
    assert.deepEqual(legacy.allowedMachineIds, c.machines, `${c.name}: alcance legacy documentado`);
    // MF-07: solo se calculan los promedios aprobados; todos existen como calculados en la definición legacy (el porcentaje de resistencia húmeda de P1-25 no se pidió y no se calcula)
    assert.ok(c.calculated.every((f) => legacy.fields.some((x) => x.key === f.key && x.source === "calculated")), `${c.name}: calculados`);
    assert.equal(c.calculated.some((f) => f.key === "porcentaje_de_resistencia_humeda"), false);
    assert.equal(c.form.context, "bobbin");
  }
  assert.equal(P125_FIELDS.find((f) => f.key === "curado_min").kind, "text", "curado_min es TEXTO: no se convierte por su nombre");
  assert.equal(defOf("form_24_propiedades_fisicas_en_humedo").fields.find((f) => f.key === "promedio_transversal_humedo").type, "text"); // tipo legacy del calculado: se documenta, no se corrige
  assert.match(P124_PENDING.map((p) => p.pending).join(" "), /los calcula el sistema al guardar; no se digitan/);
  assert.equal(P125_FIELDS.filter((f) => f.suffix).length, 0, "las unidades de P1-25 ya están en sus etiquetas: no se duplican ni se inventan");
  // MF-06 · P1-25 v2: «Caudal RH [ml/min]» abre el formulario (decimal, opcional) y «# Cortes» (entero, obligatorio desde la v2) va inmediatamente antes de «Observaciones»
  assert.deepEqual(P125_FIELDS[0], { key: "caudal_rh_ml_min", label: "Caudal RH [ml/min]", kind: "decimal", required: false });
  assert.deepEqual(P125_FIELDS.at(-2), { key: "n_cortes", label: "# Cortes", kind: "integer", required: true, sinceVersion: 2 });
  assert.equal(P125_FIELDS.at(-1).key, "observaciones");
  assert.equal(P125_FIELDS.length, 13);
  assert.equal(P124_FIELDS.length, 10);
  const u24 = defOf("form_24_propiedades_fisicas_en_humedo").fields;
  assert.deepEqual(P124_FIELDS.filter((f) => f.suffix).map((f) => [f.key, f.suffix]), [["crepado", "%"], ["gramaje", u24.find((f) => f.key === "gramaje").unit], ["tiempo_de_curado_condicion", u24.find((f) => f.key === "tiempo_de_curado_condicion").unit]]);
});

test("MF-07 · posiciones Comando / Medio / Transversal, claves técnicas sin cambios y promedios aprobados", () => {
  const cmd = (dir, wet, kgf) => ["centro", "medio", "extremo"].map((pos) => `resistencia_${dir}_${wet ? "humeda_" : ""}${pos}${kgf ? "_kgf" : ""}`);
  const names = { centro: "Comando", medio: "Medio", extremo: "Transversal" };
  for (const [fields, keys, kgf] of [[P124_FIELDS, [...cmd("longitudinal", true, false), ...cmd("transversal", true, false)], false], [P125_FIELDS, [...cmd("longitudinal", false, true), ...cmd("longitudinal", true, true)], true]]) {
    for (const key of keys) {
      const f = fields.find((x) => x.key === key);
      assert.ok(f, key);
      const position = names[key.match(/(centro|medio|extremo)/)[1]];
      assert.ok(f.label.endsWith(kgf ? ` – ${position} kgf` : ` – ${position}`), `${key}: ${f.label}`);
      assert.equal(f.label.includes("Transmisión"), false);
      assert.ok(f.renamedAt.version === 3 && !f.renamedAt.previous.includes("–"), `${key}: las versiones 1 y 2 conservan su etiqueta`);
      assert.equal(labelFor(f, 2), f.renamedAt.previous);
      assert.equal(labelFor(f, 3), f.label);
      assert.equal(labelFor(f), f.label);
    }
  }
  assert.deepEqual(P124_FIELDS.filter((f) => f.renamedAt).map((f) => f.label), ["Crepado (%)", "Resistencia longitudinal húmeda – Comando", "Resistencia longitudinal húmeda – Medio", "Resistencia longitudinal húmeda – Transversal", "Resistencia transversal húmeda – Comando", "Resistencia transversal húmeda – Medio", "Resistencia transversal húmeda – Transversal"]);
  assert.deepEqual(P125_FIELDS.filter((f) => f.renamedAt).map((f) => f.label), ["Resistencia longitudinal – Comando kgf", "Resistencia longitudinal – Medio kgf", "Resistencia longitudinal – Transversal kgf", "Resistencia longitudinal húmeda – Comando kgf", "Resistencia longitudinal húmeda – Medio kgf", "Resistencia longitudinal húmeda – Transversal kgf"]);
  assert.deepEqual(P124_CALCULATED_FIELDS.map((f) => f.key), ["promedio_longitudinal_humedo", "promedio_transversal_humedo"]);
  assert.deepEqual(P125_CALCULATED_FIELDS.map((f) => f.key), ["promedio_resistencia_longitudinal_kgf", "promedio_resistencia_longitudinal_humeda_kgf"]);
  assert.deepEqual(P124_MEANS.promedio_longitudinal_humedo, cmd("longitudinal", true, false));
  assert.deepEqual(P124_MEANS.promedio_transversal_humedo, cmd("transversal", true, false));
  assert.deepEqual(P125_MEANS.promedio_resistencia_longitudinal_kgf, cmd("longitudinal", false, true));
  assert.deepEqual(P125_MEANS.promedio_resistencia_longitudinal_humeda_kgf, cmd("longitudinal", true, true));
  // las elongaciones de P1-25 se conservan (una vez) y no entran en ningún promedio; ni campos nuevos digitables
  assert.equal(P125_FIELDS.filter((f) => /elongacion/.test(f.key)).length, 2);
  assert.equal(Object.values(P125_MEANS).flat().some((k) => /elongacion/.test(k)), false);
  assert.equal(P124_FIELDS.length, 10);
  assert.equal(P125_FIELDS.length, 13);
  // promedios mostrados: media exacta con dos decimales y solo con las tres posiciones digitadas
  const draft = Object.fromEntries(P124_MEANS.promedio_longitudinal_humedo.map((k, i) => [k, ["1,00", "2", "2"][i]]));
  assert.deepEqual(previewMeans(P124_MEANS, draft), { promedio_longitudinal_humedo: "1.67", promedio_transversal_humedo: null });
  assert.equal(previewMeans(P124_MEANS, { ...draft, [P124_MEANS.promedio_longitudinal_humedo[0]]: "" }).promedio_longitudinal_humedo, null, "con una posición vacía no hay promedio");
  assert.equal(previewMeans(P125_MEANS, {}).promedio_resistencia_longitudinal_kgf, null);
  assert.deepEqual(["0.005", "-0.005", "0", "1", "2.5", "10.0025"].map((v) => meanTwoDecimals([v])), ["0.01", "-0.01", "0.00", "1.00", "2.50", "10.00"]);
  assert.equal(meanTwoDecimals([]), null);
  assert.equal(meanTwoDecimals(["0.01", "0", "0"]), "0.00");
  assert.equal(meanTwoDecimals(["0", "0", "0"]), "0.00", "un promedio de ceros es 0.00, no vacío");
});

test("las brechas son visibles: sin fórmulas, rebobinadoras no cubiertas, alcance de P1-25 por definir, producto sin equivalencia, hora de registro y sin efecto sobre la bobina", () => {
  for (const c of CASES) {
    const text = c.pending.map((p) => `${p.label} ${p.pending}`).join(" ");
    assert.match(text, /los calcula el sistema al guardar; no se digitan/, c.name);
    assert.match(text, /rebobinadoras NO están cubiertas/, c.name);
    assert.match(text, /no es la hora real del ensayo/, c.name);
    assert.match(text, /no libera, rechaza ni aprueba la bobina/, c.name);
    assert.match(text, /Ya no se digitan \(MF-06\)/, c.name);
  }
  assert.match(P124_PENDING.map((p) => p.pending).join(" "), /MP1, MP3 y todas las rebobinadoras\. Solo se cubren bobinas F3 de MP1 \/ MP3/);
  assert.match(P125_PENDING.map((p) => p.pending).join(" "), /«por definir»/);
  assert.match(P125_PENDING.map((p) => p.pending).join(" "), /«Curado min» es TEXTO/);
  assert.match(read("lib/vinto/p1-24.ts"), /NO hay bobinas de rebobinadoras\s+\/\/ y no se fabrican|NO hay bobinas de rebobinadoras/);
  assert.match(read("lib/vinto/p1-25.ts"), /`por_definir`/);
});

test("el borrador valida estructuralmente, conserva el texto tal cual y NO calcula promedios ni porcentajes ni genera automáticos", () => {
  for (const c of CASES) {
    const check = c.form.normalizeDraft(fill(c.fields, " 30 min (texto) "));
    assert.equal(check.ok, true, c.name);
    for (const f of c.fields.filter((x) => x.kind === "decimal")) assert.equal(check.values[f.key], "1.5", `${c.name}: ${f.key} coma → punto`);
    assert.equal(check.values.observaciones, "nota");
    const forbidden = ["fecha", "hora", "maquina", "responsable", ...c.calculated.map((x) => x.key)];
    for (const key of ["fecha", "hora", "maquina", "responsable", "promedio_longitudinal_humedo", "promedio_transversal_humedo", "promedio_resistencia_longitudinal_kgf", "promedio_resistencia_longitudinal_humeda_kgf", "porcentaje_de_resistencia_humeda"]) assert.equal(key in check.values, false, `${c.name}: ${key}`);
    assert.ok(forbidden.length > 0);
    for (const f of c.fields.filter((x) => x.kind === "decimal")) {
      for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: bad }).errors.join(" "), /debe ser un número decimal/, `${c.name} ${f.key} ${bad}`);
      if (f.required) assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: " " }).errors.join(" "), /es obligatorio/, f.key);
      else assert.equal(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: " " }).ok, true, `${c.name}: ${f.key} es opcional`);
    }
    assert.equal(c.form.normalizeDraft(c.form.emptyDraft()).errors.length, c.fields.filter((f) => f.required).length);
  }
  assert.equal(P125.normalizeDraft(fill(P125_FIELDS, "no numérico")).values.curado_min, "no numérico");
  assert.equal(P125.normalizeDraft({ ...fill(P125_FIELDS), curado_min: "30,5" }).values.curado_min, "30,5", "un texto con coma no se normaliza como decimal");
});

test("el payload es de contexto «bobina»: cerrado, sin asignación ni máquina, y congelado", () => {
  for (const c of CASES) {
    const { attempt } = c.form.createAttempt(fill(c.fields), BOBBIN, DEVICE, () => UUID);
    assert.deepEqual(Object.keys(attempt.payload).sort(), ["bobbin_id", "capture_id", "device_key", "form_code", "values"], c.name);
    assert.deepEqual([attempt.payload.form_code, attempt.payload.bobbin_id, attempt.captureId], [c.formCode, BOBBIN, UUID]);
    for (const key of ["assignment_id", "machine_code", "work_order_id"]) assert.equal(key in attempt.payload, false, key);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values));
    assert.equal(c.form.createAttempt(c.form.emptyDraft(), BOBBIN, DEVICE).ok, false);
  }
});

test("el parser exige bobina, OT y línea, su formulario y valores estrictos; ignora lo calculado y rechaza el formulario de otra pantalla", () => {
  for (const c of CASES) {
    const values = c.form.normalizeDraft(fill(c.fields)).values;
    const parsed = c.form.parseCapture(envelope(c.formCode, values));
    assert.deepEqual(parsed?.values, values, c.name);
    assert.deepEqual([parsed?.bobbin, parsed?.work_order?.number, parsed?.assignment], [{ id: BOBBIN, code: "12" }, "OT-1", undefined]);
    for (const other of ["VINTO-P1-21", c.formCode === P1_24_CODE ? P1_25_CODE : P1_24_CODE, "VINTO-P1-19"]) assert.equal(c.form.parseCapture(envelope(other, values)), null, `${c.name}: ${other}`);
    for (const missing of ["bobbin", "work_order", "line"]) { const e = envelope(c.formCode, values); delete e[missing]; assert.equal(c.form.parseCapture(e), null, `falta ${missing}`); }
    for (const f of c.fields.filter((x) => x.required)) { const m = { ...values }; delete m[f.key]; const version = Math.max(1, f.sinceVersion ?? 1); assert.equal(c.form.parseCapture(envelope(c.formCode, m, { form: { code: c.formCode, version_number: version, name: "x" } })), null, `falta ${f.key}`); } // un campo posterior se exige desde su versión
    assert.deepEqual(c.form.parseCapture(envelope(c.formCode, { ...values, porcentaje_de_resistencia_humeda: "9" }))?.values, values, `${c.name}: lo que no se calcula ni se declara se ignora`);
    // MF-07: los promedios que guarda el backend (versión 3) se leen; una captura anterior no los trae y se lee igual; un promedio inválido invalida la lectura
    const averages = Object.fromEntries(c.calculated.map((f) => [f.key, "12.35"]));
    const v3 = (v) => envelope(c.formCode, v, { form: { code: c.formCode, version_number: 3, name: "x" } });
    assert.deepEqual(c.form.parseCapture(v3({ ...values, ...averages }))?.values, { ...values, ...averages }, c.name);
    assert.deepEqual(c.form.parseCapture(envelope(c.formCode, values, { form: { code: c.formCode, version_number: 2, name: "x" } }))?.values, values, `${c.name}: la versión 2 no tiene promedios y se lee tal cual`);
    assert.equal(c.form.parseCapture(v3({ ...values, [c.calculated[0].key]: "abc" })), null);
    assert.equal(c.form.parseCapture(v3({ ...values, [c.calculated[0].key]: 12.35 })), null, "los decimales llegan como texto exacto");
    assert.equal(c.form.parseCapture(envelope(c.formCode, { ...values, [c.fields.find((f) => f.kind === "decimal").key]: "abc" })), null);
    assert.equal(c.form.parseList([envelope(c.formCode, values)])?.length, 1);
    assert.equal(c.form.parseList([{ nope: 1 }]), null);
  }
});

test("MF-06 · «# Cortes»: entero no negativo OBLIGATORIO; «Caudal RH» decimal OPCIONAL", () => {
  const base = fill(P125_FIELDS);
  const check = (extra) => P125.normalizeDraft({ ...base, ...extra });
  for (const ok of ["0", "1", "12", " 7 ", "000"]) assert.equal(check({ n_cortes: ok }).ok, true, `acepta «${ok}»`);
  assert.equal(check({ n_cortes: " 7 " }).values.n_cortes, "7");
  for (const bad of ["-1", "1.5", "1,5", "2.0", "abc", "1e3", "+3", "3 cortes", "", "   "]) {
    const out = check({ n_cortes: bad });
    assert.equal(out.ok, false, `rechaza «${bad}»`);
    assert.match(out.errors.join(" "), bad.trim() === "" ? /# Cortes: es obligatorio/ : /# Cortes: debe ser un número entero no negativo/, bad);
  }
  assert.equal(P125.normalizeDraft(P125.emptyDraft()).errors.some((e) => e.startsWith("# Cortes")), true);
  // Caudal RH: decimal válido o vacío; texto o separador raro se rechaza
  assert.equal(check({ caudal_rh_ml_min: "" }).ok, true);
  assert.equal(check({ caudal_rh_ml_min: "12,5" }).values.caudal_rh_ml_min, "12.5");
  assert.equal(check({ caudal_rh_ml_min: "abc" }).ok, false);
  const { attempt } = P125.createAttempt({ ...base, n_cortes: "4", caudal_rh_ml_min: "9.5" }, BOBBIN, DEVICE, () => UUID);
  assert.deepEqual([attempt.payload.values.n_cortes, attempt.payload.values.caudal_rh_ml_min], ["4", "9.5"]);
  assert.equal("n_cortes" in P124.emptyDraft(), false, "P1-24 no cambia");
});

test("MF-06 · compatibilidad: las capturas v1 se leen sin «# Cortes»; las v2 lo exigen; el backend lo entrega como número", () => {
  const v1 = {
    [P1_24_CODE]: { numero_de_bobina: "12", producto: "ficticio", crepado: "18.5", gramaje: "21.3", resistencia_longitudinal_humeda_centro: "1", resistencia_longitudinal_humeda_medio: "1", resistencia_longitudinal_humeda_extremo: "1",
      resistencia_transversal_humeda_centro: "1", resistencia_transversal_humeda_medio: "1", resistencia_transversal_humeda_extremo: "1", tiempo_de_curado_condicion: "30" },
    [P1_25_CODE]: { numero_de_bobina: "12", producto: "ficticio", crepado: "17", gramaje_laboratorio_g_m2: "20.5", curado_min: "30 min", resistencia_longitudinal_centro_kgf: "1", resistencia_longitudinal_medio_kgf: "1", resistencia_longitudinal_extremo_kgf: "1",
      elongacion_media_longitudinal: "2", resistencia_longitudinal_humeda_centro_kgf: "1", resistencia_longitudinal_humeda_medio_kgf: "1", resistencia_longitudinal_humeda_extremo_kgf: "1", elongacion_media_transversal: "3" },
  };
  for (const c of CASES) {
    const old = c.form.parseCapture(envelope(c.formCode, v1[c.formCode], { form: { code: c.formCode, version_number: 1, name: "x" } }));
    assert.notEqual(old, null, `${c.name}: la captura v1 se lee`);
    for (const key of c.removed) assert.equal(old.values[key], v1[c.formCode][key], `${c.name}: ${key} (campo retirado) se conserva al LEER la captura antigua`);
    for (const key of c.added) assert.equal(key in old.values, false, `${c.name}: ${key} no existe en la v1`);
    assert.equal(old.form.version_number, 1);
  }
  // la MISMA captura marcada como v2 sin «# Cortes» NO es válida (es obligatorio desde la v2)
  const asV2 = (values) => P125.parseCapture(envelope(P1_25_CODE, values, { form: { code: P1_25_CODE, version_number: 2, name: "x" } }));
  const v2Values = { ...P125.normalizeDraft({ ...fill(P125_FIELDS), n_cortes: "3" }).values };
  assert.equal(asV2(v2Values)?.values.n_cortes, "3");
  const { n_cortes: _omit, ...withoutCortes } = v2Values;
  assert.equal(asV2(withoutCortes), null, "v2 sin # Cortes: inválida");
  assert.equal(asV2({ ...v2Values, n_cortes: 3 })?.values.n_cortes, "3", "el backend devuelve el entero como número JSON");
  for (const bad of [-1, 1.5, "1.5", "-2", "x", true, null]) assert.equal(asV2({ ...v2Values, n_cortes: bad }), null, `v2 con n_cortes=${String(bad)}`);
  assert.deepEqual([asV2({ ...v2Values, n_cortes: 0 })?.values.n_cortes, asV2({ ...v2Values, n_cortes: "0" })?.values.n_cortes], ["0", "0"]);
  const fresh = asV2({ ...v2Values, caudal_rh_ml_min: "12.5" });
  assert.equal(fresh?.values.caudal_rh_ml_min, "12.5");
  const { caudal_rh_ml_min: _c, ...noCaudal } = v2Values;
  assert.equal(asV2(noCaudal)?.values.caudal_rh_ml_min, undefined, "Caudal RH puede faltar");
});

const response = (status, data, errCode) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code: errCode });

test("flujo de envío: 201, 200 idempotente, rechazos definitivos, sesión y reconciliación con el MISMO capture_id", async () => {
  for (const c of CASES) {
    const created = c.form.createAttempt(fill(c.fields), BOBBIN, DEVICE, () => UUID).attempt;
    const capture = c.form.parseCapture(envelope(c.formCode, c.form.normalizeDraft(fill(c.fields)).values));
    const ok = (made, again) => response(made ? 201 : 200, { created: made, already_submitted: again, capture });
    assert.deepEqual(((o) => [o.kind, o.created])(await c.form.submitAttempt(created, { post: async () => ok(true, false), get: async () => assert.fail() })), ["submitted", true]);
    assert.deepEqual(((o) => [o.created, o.alreadySubmitted])(await c.form.submitAttempt(created, { post: async () => ok(false, true), get: async () => assert.fail() })), [false, true]);
    for (const [status, errCode, reason] of [[409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"], [409, "FORM_NOT_AVAILABLE", "conflict"], [403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "UNSUPPORTED_FORM", "invalid"], [422, "CAPTURE_VALIDATION", "invalid"]]) {
      const out = await c.form.submitAttempt(created, { post: async () => response(status, null, errCode), get: async () => assert.fail("un rechazo definitivo no reconcilia") });
      assert.deepEqual([out.kind, out.reason], ["rejected", reason], `${c.name} ${status} ${errCode}`);
    }
    assert.equal((await c.form.submitAttempt(created, { post: async () => response(401), get: async () => assert.fail() })).kind, "session");
    const lost = { ok: false, kind: "network", status: 0 };
    assert.deepEqual(((o) => [o.kind, o.reconciled])(await c.form.submitAttempt(created, { post: async () => lost, get: async (id) => { assert.equal(id, UUID); return response(200, capture); } })), ["submitted", true]);
    assert.equal((await c.form.submitAttempt(created, { post: async () => lost, get: async () => response(404, null) })).kind, "not_saved");
    assert.equal((await c.form.submitAttempt(created, { post: async () => lost, get: async () => lost })).kind, "uncertain");
  }
});

test("la oferta sale del backend y es por la MÁQUINA de la bobina: sin disponibilidad no se ofrece nada y no se mezcla con los controles por máquina", () => {
  const form = (c) => ({ code: c, name: c, version_number: 1 });
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  assert.deepEqual(bobbinScreensFor(avail([{ code: "MP1", name: "MP1", forms: [] }, { code: "MP3", name: "MP3", forms: [] }]), "MP1"), [], "configuración real: nada publicado");
  const published = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-21"), form("VINTO-P1-24"), form("VINTO-P1-25")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-25")] }]);
  assert.deepEqual([bobbinScreensFor(published, "MP1"), bobbinScreensFor(published, "MP3"), bobbinScreensFor(published, "MP9")], [["p121", "p124", "p125"], ["p125"], []]);
  assert.deepEqual([qualityScreensFor(published, "MP1"), publishedQualityScreens(published)], [[], []], "no son controles por máquina");
  assert.deepEqual(bobbinScreensFor(avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-18"), form("VINTO-P1-19"), form("VINTO-P1-20")] }]), "MP1"), []);
  const registry = code("lib/vinto/quality-bobbin-candidates.ts"); // (usa alias «@/», no importable desde Node): se verifica el registro por su texto
  for (const c of CASES) {
    const [codeConst, formConst] = c.formCode === P1_24_CODE ? ["P1_24_CODE", "P124"] : ["P1_25_CODE", "P125"];
    assert.ok(registry.includes(`${c.screen}: make({ code: ${codeConst}, form: ${formConst},`), c.name);
    assert.equal(registry.includes(`${formConst}_BOBBIN_CODE_FIELD`), false, `${c.name}: ya no hay campo de número de bobina que precargar`);
  }
});

test("aislamiento por usuario, bobina y formulario: el historial de otra cuenta, bobina o formulario nunca se presenta", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  const keys = new Set([["p124", A, BOBBIN], ["p125", A, BOBBIN], ["p124", B, BOBBIN], ["p124", A, "otra"]].map(([s, u, b]) => candidateHistoryKey(`${s}-${b}`, sessionScope(u), 0)));
  assert.equal(keys.size, 4);
  const kA = candidateHistoryKey(`p124-${BOBBIN}`, sessionScope(A), 0);
  const stored = { key: kA, attempt: 0, result: { ok: true, data: [{ id: "control-de-A" }] } };
  assert.equal(JSON.stringify(deriveView(candidateHistoryKey(`p125-${BOBBIN}`, sessionScope(A), 0), true, 0, stored)).includes("control-de-A"), false);
  assert.equal(JSON.stringify(deriveView(candidateHistoryKey(`p124-${BOBBIN}`, sessionScope(B), 0), true, 0, stored)).includes("control-de-A"), false);
  assert.match(code("components/vinto/quality-bobbin-candidate-capture.tsx"), /candidateHistoryKey\(`\$\{screen\}-\$\{item\.bobbin\.id\}`, scope, refreshKey\)/);
  assert.match(code("components/vinto/quality-bobbin-candidate-capture.tsx"), /candidate\.bobbinApi\.list\(item\.bobbin\.id, signal\)/); // lista filtrada por formulario en el backend
});

test("se reutiliza la pantalla compartida: ni pantallas ni endpoints nuevos, sin almacenamiento local y sin acciones de liberar o rechazar", () => {
  const files = ["lib/vinto/p1-24.ts", "lib/vinto/p1-25.ts", "lib/vinto/quality-bobbin-candidates.ts", "lib/vinto/quality-offers.ts", "components/vinto/quality-bobbin-candidate-capture.tsx", "components/vinto/quality-bobbin-inbox.tsx", "components/vinto/candidate-form-capture.tsx"];
  for (const f of files) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(code(f)), false, f);
  assert.equal(readdirSync(join(root, "components/vinto")).some((f) => /p1-2[45]/.test(f)), false, "no hay componentes de pantalla propios de P1-24 / P1-25");
  assert.equal(/\/api\/quality|requestJson/.test(code("lib/vinto/p1-24.ts") + code("lib/vinto/p1-25.ts")), false, "los contratos no declaran endpoints");
  const inbox = code("components/vinto/quality-bobbin-inbox.tsx");
  assert.match(inbox, /candidateOffers\?\.\(i\.bobbin\.machine\.code\)/);
  assert.equal(/Liberar|Rechazar|liberar|rechazar|Aprobar/.test(inbox + code("components/vinto/quality-bobbin-candidate-capture.tsx")), false);
  const cap = code("components/vinto/candidate-form-capture.tsx");
  assert.match(cap, /disabled=\{locked \|\| field\.key === codeField\}/);
  assert.match(cap, /draft\[codeField\] = bobbin\.bobbin\.code/);
  assert.match(cap, /Ficha NO homologada/);
  assert.match(cap, /Artículo/); // el artículo real de la bobina es contexto informativo
});

test("alcance: política vacía, producción y seed_data intactos, sin migraciones nuevas, P1-19 / P1-20 / P1-21 sin tocar", () => {
  const bobbin = read("backend/app/quality/capture_service.py"), manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(bobbin, /^ENABLED_BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.match(bobbin, /^BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset\(\{"VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"\}\)$/m);
  assert.match(bobbin, /"VINTO-P1-24": "numero_de_bobina", "VINTO-P1-25": "numero_de_bobina"/);
  assert.match(read("backend/app/quality/machine_capture_service.py"), /^MACHINE_QUALITY_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.equal(readdirSync(join(root, "backend/migrations")).filter((f) => f.endsWith(".sql")).length, 6);
  assert.equal(/VINTO-P1-19|VINTO-P1-20/.test(bobbin.replace(/^CENTRAL_BOBBIN_FORM_CODES: frozenset = frozenset\(\{"VINTO-P1-19", "VINTO-P1-20"\}\)$/m, "").replace(/^"""[\s\S]*?"""/, "")), false); // INT-01A: solo en la política positiva
  assert.equal(/UPDATE vinto_txn\.quality_release|INSERT INTO vinto_txn\.(bobbin|assignment|work_order|quality_release)|decided_by|decision_reason/.test(bobbin.replace(/^"""[\s\S]*?"""/, "")), false);
  assert.match(read("lib/vinto/quality-history-api.ts"), /\[Q19_FORM_CODE\]: humidityViewer\(parseQualityCapture\), \[Q20_FORM_CODE\]: physicalViewer\(parsePhysicalCapture\)/);
});
