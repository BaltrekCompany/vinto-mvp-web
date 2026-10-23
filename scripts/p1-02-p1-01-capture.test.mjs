// node --test scripts/p1-02-p1-01-capture.test.mjs
// DEV-B3 · fichas CANDIDATAS de Bobinas sobre el contexto de asignación central: VINTO-P1-02 (Parámetros de operación de máquina MP1, 48 campos manuales) y VINTO-P1-01 (Operación e inspección de máquina MP3,
// 86 campos manuales). Contrato frente a form-definitions.ts (claves, etiquetas, orden, tipos, obligatoriedad y unidades), soporte del tipo `time` del motor declarativo (tres horas manuales de P1-01), campos
// de texto que parecen numéricos, automáticos sin fuente (velocidad, firma, revisado, hora) no generados, secciones visuales que cubren cada campo una vez, payload, parser, flujo con reconciliación, oferta según
// el backend, aislamiento por sesión y límites de alcance. Lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { BOBINAS_SECTOR, parseAvailability, screenFor } from "../lib/vinto/availability.ts";
import { TIME_PATTERN, defineCandidateForm } from "../lib/vinto/candidate-form.ts";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { BOBINAS_CANDIDATE_SCREENS, candidateScreensFor, publishedCandidateScreens } from "../lib/vinto/bobinas-offers.ts";
import { P101, P101_FIELDS, P101_PENDING, P101_SECTIONS, P1_01_CODE } from "../lib/vinto/p1-01.ts";
import { P102, P102_FIELDS, P102_PENDING, P102_SECTIONS, P1_02_CODE } from "../lib/vinto/p1-02.ts";
import { candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", ASSIGNMENT = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const defOf = (id) => FORM_DEFINITIONS.find((f) => f.id === id);
const isManual = (f) => f.source === "manual";
const KIND = (f) => (f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : f.type === "time" ? "time" : "text");
const TIME_KEYS = ["hora_cambio_cuchilla_de_cambio", "hora_cambio_cuchilla_de_crepado", "hora_cambio_cuchilla_de_limpieza"];
const fill = (fields) => Object.fromEntries(fields.map((f, i) => [f.key, f.kind === "decimal" ? "1,5" : f.kind === "time" ? ["06:30", "14:45", "22:10"][i % 3] : f.kind === "textarea" ? " nota " : "texto 12,5"]));
const CASES = [
  { name: "P1-02", id: "form_2_parametros_de_operacion_de_maquina", form: P102, formCode: P1_02_CODE, fields: P102_FIELDS, sections: P102_SECTIONS, pending: P102_PENDING, counts: [48, 4], machines: ["mp1"], screen: "p102", machine: "MP1" },
  { name: "P1-01", id: "form_1_operacion_e_inspeccion_de_maquina", form: P101, formCode: P1_01_CODE, fields: P101_FIELDS, sections: P101_SECTIONS, pending: P101_PENDING, counts: [86, 7], machines: ["mp3"], screen: "p101", machine: "MP3" },
];
const envelope = (formCode, values) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "x" },
  machine: { code: "MP3", name: "MP3" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT }, work_order: { id: UUID, number: "OT-1" },
  line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });

test("los contratos son EXACTAMENTE los campos manuales de las definiciones legacy (48 y 86): claves, etiquetas, orden, tipos, obligatoriedad y unidades", () => {
  for (const c of CASES) {
    const legacy = defOf(c.id);
    assert.equal(legacy.area, "production");
    assert.equal(legacy.sector, "bobinas");
    assert.deepEqual(legacy.allowedMachineIds, c.machines);
    assert.deepEqual([legacy.fields.filter(isManual).length, legacy.fields.filter((f) => f.source === "automatic").length, legacy.fields.filter((f) => f.source === "calculated").length], [...c.counts, 0], c.name);
    assert.equal(legacy.fields.length, c.counts[0] + c.counts[1]);
    const m = legacy.fields.filter(isManual);
    assert.equal(c.fields.length, c.counts[0]);
    assert.deepEqual(c.fields.map((f) => f.key), m.map((f) => f.key), `${c.name}: claves y orden`);
    // MF-02/MF-03: textos visibles aprobados que difieren de la definición legacy; la clave consistencia_h_4 no cambia.
    const LABEL_OVERRIDES = { "P1-01": { consistencia_h_4: "Consistencia", angulo_labio: "Ángulo caja" } };
    assert.deepEqual(c.fields.map((f) => f.label), m.map((f) => LABEL_OVERRIDES[c.name]?.[f.key] ?? f.label), `${c.name}: etiquetas`);
    assert.deepEqual(c.fields.map((f) => f.required), m.map((f) => f.required ?? f.requirement), `${c.name}: obligatoriedad`);
    assert.deepEqual(c.fields.map((f) => f.kind), m.map(KIND), `${c.name}: tipos`);
    for (const f of c.fields) assert.equal(f.suffix, m.find((x) => x.key === f.key).unit ?? undefined, `${c.name}: ${f.key} unidad`);
    for (const f of legacy.fields.filter((x) => !isManual(x))) assert.equal(c.fields.some((x) => x.key === f.key), false, `${c.name}: ${f.key} no se digita`);
    assert.equal(c.form.context, "assignment");
  }
  assert.deepEqual(defOf("form_1_operacion_e_inspeccion_de_maquina").fields.filter((f) => f.source === "automatic").map((f) => f.key), ["nombre_operador", "fecha", "hora", "turno", "velocidad_maquina", "firma_operador", "revisado"]);
  assert.deepEqual(defOf("form_2_parametros_de_operacion_de_maquina").fields.filter((f) => f.source === "automatic").map((f) => f.key), ["nombre_operador", "fecha", "hora", "turno"]);
});

test("campos que parecen numéricos pero son TEXTO en la definición se conservan como texto; `opertado` conserva su ortografía; las tres horas son `time` manual obligatorio", () => {
  const k01 = Object.fromEntries(P101_FIELDS.map((f) => [f.key, f.kind])), k02 = Object.fromEntries(P102_FIELDS.map((f) => [f.key, f.kind]));
  for (const key of ["peso_balas_fibra_corta", "peso_balas_fibra_larga", "tiempo_de_pulpeo_fibra_corta", "tiempo_de_pulpeo_fibra_larga", "opertado", "produccion", "producto_gramaje_crepado"]) assert.equal(k01[key], "text", key);
  assert.ok("opertado" in k01 && !("operado" in k01) && !("operated" in k01), "se conserva la clave original `opertado`");
  for (const key of ["producto", "apertura_gas", "apertura_termocompresor", "relacion_chorro_tela", "altura_caja_entrada", "apertura_labio", "dosificacion_release", "novedades", ...Object.keys(k02).filter((k) => k.startsWith("limpieza_"))]) assert.equal(k02[key], "text", key);
  assert.equal(Object.keys(k02).filter((k) => k.startsWith("limpieza_")).length, 8);
  for (const key of TIME_KEYS) { const f = P101_FIELDS.find((x) => x.key === key), legacy = defOf("form_1_operacion_e_inspeccion_de_maquina").fields.find((x) => x.key === key); assert.deepEqual([f.kind, f.required, legacy.type, legacy.source, legacy.required], ["time", true, "time", "manual", true], key); }
  assert.deepEqual(P101_FIELDS.filter((f) => f.kind === "time").map((f) => f.key), TIME_KEYS);
  assert.equal(P102_FIELDS.some((f) => f.kind === "time"), false);
  assert.deepEqual([...new Set([...P102_FIELDS, ...P101_FIELDS].map((f) => f.kind))].sort(), ["decimal", "text", "time"]);
});

test("soporte de `time` del motor: HH:MM válido, horas imposibles y formatos inválidos rechazados, sin tocar los demás tipos", () => {
  const draft = (extra) => ({ ...fill(P101_FIELDS), ...extra });
  const ok = P101.normalizeDraft(draft({ [TIME_KEYS[0]]: " 06:05 ", [TIME_KEYS[1]]: "23:59", [TIME_KEYS[2]]: "00:00" }));
  assert.equal(ok.ok, true);
  assert.deepEqual(TIME_KEYS.map((k) => ok.values[k]), ["06:05", "23:59", "00:00"]);
  assert.equal(P101.normalizeDraft(draft({ [TIME_KEYS[0]]: "07:30:15" })).values[TIME_KEYS[0]], "07:30:15");
  for (const bad of ["24:00", "25:10", "12:60", "7:5", "7:30", "07", "0730", "T07:30", "07:30:61", "07:30:00.5", "07:30+01:00", "07:30Z", "12h30", "abc", "12,30", "1e3"]) {
    const check = P101.normalizeDraft(draft({ [TIME_KEYS[1]]: bad }));
    assert.equal(check.ok, false, bad);
    assert.match(check.errors.join(" "), /Hora cambio cuchilla de crepado: debe ser una hora válida HH:MM/, bad);
  }
  for (const key of TIME_KEYS) assert.match(P101.normalizeDraft(draft({ [key]: "  " })).errors.join(" "), /es obligatorio/, key);
  assert.equal(TIME_PATTERN.test("23:59") && TIME_PATTERN.test("00:00:59"), true);
  // el parser acepta la serialización del backend (HH:MM:SS) y rechaza una hora inválida en la respuesta
  const values = P101.normalizeDraft(draft({})).values;
  const served = { ...values, [TIME_KEYS[0]]: "06:30:00" };
  assert.equal(P101.parseCapture(envelope(P1_01_CODE, served))?.values[TIME_KEYS[0]], "06:30:00");
  assert.equal(P101.parseCapture(envelope(P1_01_CODE, { ...values, [TIME_KEYS[0]]: "25:00:00" })), null);
  assert.equal(P101.parseCapture(envelope(P1_01_CODE, { ...values, [TIME_KEYS[0]]: "06:30:00.5" })), null);
  assert.equal(P101.parseCapture(envelope(P1_01_CODE, Object.fromEntries(Object.entries(values).filter(([k]) => k !== TIME_KEYS[2])))), null, "una hora obligatoria ausente invalida la respuesta");
  // el motor no cambia para los demás tipos: un formulario sin `time` se comporta como antes
  const small = defineCandidateForm("X", [{ key: "a", label: "A", kind: "decimal", required: true }, { key: "b", label: "B", kind: "text", required: true }]);
  assert.deepEqual(small.normalizeDraft({ a: "1,5", b: " 07:99 " }).values, { a: "1.5", b: "07:99" });
  const capture = code("components/vinto/candidate-form-capture.tsx");
  assert.match(capture, /type=\{field\.kind === "time" \? "time" : "text"\}/);
});

test("las secciones visuales cubren cada campo manual EXACTAMENTE una vez, en el orden del contrato, sin grupos repetibles ni cálculos", () => {
  for (const c of CASES) {
    const keys = c.sections.flatMap((s) => s.keys);
    assert.deepEqual(keys, c.fields.map((f) => f.key), `${c.name}: mismo orden y mismos campos`);
    assert.equal(new Set(keys).size, keys.length);
    for (const f of c.fields.filter((x) => x.required)) assert.ok(keys.includes(f.key), `${c.name}: ${f.key} no desaparece`);
    assert.deepEqual(Object.keys(c.form.emptyDraft()), c.fields.map((f) => f.key), "el borrador y el payload conservan sus claves individuales");
    assert.equal(c.sections.every((s) => s.keys.length > 0), true);
    assert.equal(/_groups|repeat|total|promedio/i.test(JSON.stringify(c.sections.map((s) => s.title))), false);
  }
  assert.deepEqual(P102_SECTIONS.map((s) => s.title), ["Velocidad y corriente", "Vacíos y presiones", "Temperaturas y gramaje", "Humedad y peso seco, y ajustes de caja de entrada", "Limpieza y novedades"]);
  assert.deepEqual(P101_SECTIONS.map((s) => s.title), ["Materia prima, tanques y pulpeo", "Caudales, mezclas y consistencias", "Tela, chorro y labio", "Dosificaciones y accionamientos", "Secador, presiones y temperaturas", "Prensa, aceite, vacío y filtros", "Limpieza y cambios de cuchillas", "Novedades"]);
  assert.deepEqual(P101_SECTIONS.find((s) => s.title === "Limpieza y cambios de cuchillas").keys.slice(-3), TIME_KEYS);
  assert.match(code("components/vinto/candidate-form-capture.tsx"), /candidate\.sections/);
  assert.match(read("lib/vinto/p1-02.ts"), /SOLO VISUAL[\s\S]*representa grupos industriales aprobados/);
});

test("el borrador valida estructuralmente, no deriva ni calcula nada y no genera automáticos (hora, velocidad, firma, revisado)", () => {
  for (const c of CASES) {
    const check = c.form.normalizeDraft(fill(c.fields));
    assert.equal(check.ok, true, c.name);
    for (const f of c.fields) {
      if (f.kind === "decimal") assert.equal(check.values[f.key], "1.5", `${c.name}: ${f.key}`);
      if (f.kind === "text") assert.equal(check.values[f.key], "texto 12,5", `${c.name}: ${f.key} conserva su texto`);
    }
    for (const key of ["nombre_operador", "fecha", "hora", "turno", "velocidad_maquina", "firma_operador", "revisado", "total", "promedio"]) assert.equal(key in check.values, false, `${c.name}: ${key}`);
    for (const f of c.fields.filter((x) => x.kind === "decimal")) {
      for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: bad }).errors.join(" "), /debe ser un número decimal/, `${c.name} ${f.key} ${bad}`);
      assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: " " }).errors.join(" "), /es obligatorio/, f.key);
    }
    assert.equal(c.form.normalizeDraft(c.form.emptyDraft()).errors.length, c.fields.filter((f) => f.required).length);
  }
  assert.equal(P101.normalizeDraft({ ...fill(P101_FIELDS), peso_balas_fibra_corta: "850,5 kg" }).values.peso_balas_fibra_corta, "850,5 kg");
  assert.equal(P102.normalizeDraft({ ...fill(P102_FIELDS), producto: "Producto digitado" }).values.producto, "Producto digitado", "producto es texto digitado, no derivado del artículo");
});

test("las brechas son visibles: hora de registro ≠ hora de operación, automáticos sin fuente, sin firma ni revisión, tipos texto y producto no derivado", () => {
  const t02 = P102_PENDING_TEXT(), t01 = P101_PENDING_TEXT();
  assert.match(t02, /no se genera ni se toma de la hora de registro \(captured_at\), que no es la hora de la medición/);
  assert.match(t02, /Producto no se deriva del artículo/);
  assert.match(t02, /No hay firma, revisión ni aprobación/);
  assert.match(t02, /TEXTO en la definición legacy/);
  assert.match(t01, /Velocidad de máquina, firma del operador y revisado no tienen fuente aprobada: no se generan/);
  assert.match(t01, /No hay lectura de PLC ni sensores, firma electrónica ni revisión de supervisión/);
  assert.match(t01, /La hora de registro del servidor no es la hora de operación/);
  assert.match(t01, /se conserva la clave `opertado`/);
  for (const text of [t01, t02]) assert.match(text, /Sin rangos, límites, valores estándar, frecuencia de toma, validaciones cruzadas ni catálogos aprobados; nada se calcula/);
  const cards = read("lib/vinto/bobinas-candidates.ts");
  assert.match(cards, /unresolved: P102_UNRESOLVED_AUTOMATIC/);
  assert.match(cards, /unresolved: P101_UNRESOLVED_AUTOMATIC/);
  assert.match(read("lib/vinto/p1-01.ts"), /P101_UNRESOLVED_AUTOMATIC = \["Hora \(la del registro del servidor no es la hora de operación\)", "Velocidad de máquina", "Firma del operador", "Revisado"\]/);
  assert.match(code("components/vinto/candidate-form-capture.tsx"), /Ficha NO homologada/);
});
function P102_PENDING_TEXT() { return P102_PENDING.map((p) => `${p.label} ${p.pending}`).join(" "); }
function P101_PENDING_TEXT() { return P101_PENDING.map((p) => `${p.label} ${p.pending}`).join(" "); }

test("el payload es de contexto «asignación»: cerrado, sin máquina ni bobina, con las claves individuales de cada campo, y congelado", () => {
  for (const c of CASES) {
    const { attempt } = c.form.createAttempt(fill(c.fields), ASSIGNMENT, DEVICE, () => UUID);
    assert.deepEqual(Object.keys(attempt.payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"], c.name);
    assert.deepEqual([attempt.payload.form_code, attempt.payload.assignment_id, attempt.captureId], [c.formCode, ASSIGNMENT, UUID]);
    assert.deepEqual(Object.keys(attempt.payload.values), c.fields.map((f) => f.key).filter((k) => k !== "observaciones"));
    for (const key of ["machine_code", "bobbin_id", "hora", "turno", "fecha"]) assert.equal(key in attempt.payload || key in attempt.payload.values, false, key);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values));
    assert.equal(c.form.createAttempt(c.form.emptyDraft(), ASSIGNMENT, DEVICE).ok, false);
  }
  assert.equal(P101.createAttempt({ ...fill(P101_FIELDS), [TIME_KEYS[0]]: "24:61" }, ASSIGNMENT, DEVICE).ok, false, "una hora imposible no genera un intento");
});

test("el parser exige asignación, OT y línea, su formulario y valores estrictos; ignora lo que no es del contrato", () => {
  for (const c of CASES) {
    const values = c.form.normalizeDraft(fill(c.fields)).values;
    const parsed = c.form.parseCapture(envelope(c.formCode, values));
    assert.deepEqual(parsed?.values, values, c.name);
    assert.equal(parsed?.assignment?.id, ASSIGNMENT);
    for (const other of ["VINTO-P1-10", c.formCode === P1_02_CODE ? P1_01_CODE : P1_02_CODE]) assert.equal(c.form.parseCapture(envelope(other, values)), null, `${c.name}: ${other}`);
    for (const f of c.fields.filter((x) => x.required)) { const m = { ...values }; delete m[f.key]; assert.equal(c.form.parseCapture(envelope(c.formCode, m)), null, `falta ${f.key}`); }
    assert.deepEqual(c.form.parseCapture(envelope(c.formCode, { ...values, hora: "07:00", velocidad_maquina: "9", firma_operador: "x", total: "1" }))?.values, values, "un campo ajeno que llegara se ignora");
    assert.equal(c.form.parseCapture(envelope(c.formCode, { ...values, [c.fields.find((f) => f.kind === "decimal").key]: "abc" })), null);
    assert.equal(c.form.parseList([envelope(c.formCode, values)])?.length, 1);
    assert.equal(c.form.parseList([{ nope: 1 }]), null);
  }
});

const response = (status, data, errCode) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code: errCode });

test("flujo de envío: 201, 200 idempotente, rechazos, asignación obsoleta, sesión y reconciliación con el MISMO capture_id (intento pendiente conservado)", async () => {
  for (const c of CASES) {
    const created = c.form.createAttempt(fill(c.fields), ASSIGNMENT, DEVICE, () => UUID).attempt;
    const capture = c.form.parseCapture(envelope(c.formCode, c.form.normalizeDraft(fill(c.fields)).values));
    const ok = (made, again) => response(made ? 201 : 200, { created: made, already_submitted: again, capture });
    assert.deepEqual(((o) => [o.kind, o.created])(await c.form.submitAttempt(created, { post: async () => ok(true, false), get: async () => assert.fail() })), ["submitted", true]);
    assert.deepEqual(((o) => [o.created, o.alreadySubmitted])(await c.form.submitAttempt(created, { post: async () => ok(false, true), get: async () => assert.fail() })), [false, true]);
    for (const [status, errCode, reason] of [[409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"], [409, "ASSIGNMENT_STALE", "stale"], [409, "ASSIGNMENT_NOT_ACTIVE", "not_active"], [409, "FORM_NOT_AVAILABLE", "conflict"], [403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "UNSUPPORTED_FORM", "invalid"], [422, "CAPTURE_VALIDATION", "invalid"]]) {
      const out = await c.form.submitAttempt(created, { post: async () => response(status, null, errCode), get: async () => assert.fail("un rechazo definitivo no reconcilia") });
      assert.deepEqual([out.kind, out.reason], ["rejected", reason], `${c.name} ${status} ${errCode}`);
    }
    assert.equal((await c.form.submitAttempt(created, { post: async () => response(401), get: async () => assert.fail() })).kind, "session");
    const lost = { ok: false, kind: "network", status: 0 };
    assert.deepEqual(((o) => [o.kind, o.reconciled])(await c.form.submitAttempt(created, { post: async () => lost, get: async (id) => { assert.equal(id, UUID); return response(200, capture); } })), ["submitted", true]);
    assert.equal((await c.form.submitAttempt(created, { post: async () => lost, get: async () => response(404, null) })).kind, "not_saved");
    assert.equal((await c.form.submitAttempt(created, { post: async () => lost, get: async () => lost })).kind, "uncertain");
    const seen = [];
    for (let i = 0; i < 3; i++) await c.form.submitAttempt(created, { post: async (p) => { seen.push(JSON.stringify(p)); return lost; }, get: async () => response(404, null) });
    assert.equal(new Set(seen).size, 1, `${c.name}: mismo payload y capture_id en cada reintento`);
  }
});

test("la oferta sale del backend por máquina (P1-02 en MP1, P1-01 en MP3) y no se ofrece durante carga ni error; P1-04 / P1-05 / P1-31 no cambian", () => {
  assert.deepEqual([screenFor(BOBINAS_SECTOR, "VINTO-P1-02"), screenFor(BOBINAS_SECTOR, "VINTO-P1-01")], ["p102", "p101"]);
  assert.deepEqual([screenFor(BOBINAS_SECTOR, "VINTO-P1-04"), screenFor(BOBINAS_SECTOR, "VINTO-P1-05"), screenFor(BOBINAS_SECTOR, "VINTO-P1-31")], ["p104", "p105", "p131"]);
  for (const sector of ["REBOBINADO", "CONVERSION"]) for (const formCode of ["VINTO-P1-02", "VINTO-P1-01"]) assert.equal(screenFor(sector, formCode), null, `${sector}: ${formCode}`);
  assert.deepEqual([...BOBINAS_CANDIDATE_SCREENS], ["p104", "p105", "p131", "p102", "p101"]);
  const form = (c) => ({ code: c, name: c, version_number: 1 });
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  const real = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-06")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-06")] }]);
  assert.deepEqual([candidateScreensFor(real, "MP1"), candidateScreensFor(real, "MP3"), publishedCandidateScreens(real)], [[], [], []], "configuración real: nada publicado");
  const published = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-06"), form("VINTO-P1-02")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-06"), form("VINTO-P1-01")] }]);
  assert.deepEqual([candidateScreensFor(published, "MP1"), candidateScreensFor(published, "MP3"), candidateScreensFor(published, "MP9"), publishedCandidateScreens(published)], [["p102"], ["p101"], [], ["p102", "p101"]]);
  const cards = code("components/vinto/bobinas-candidate-cards.tsx");
  assert.match(cards, /availability\.status === "ready" \? candidateScreensFor\(availability\.data, machineCode\) : \[\]/); // sin disponibilidad cargada (carga o error) no se ofrece nada
});

test("aislamiento por usuario y formulario: los historiales de otra cuenta o de otro formulario nunca se presentan; sin localStorage", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  const kA = candidateHistoryKey("p102", sessionScope(A), 0);
  assert.equal(new Set([kA, candidateHistoryKey("p102", sessionScope(B), 0), candidateHistoryKey("p101", sessionScope(A), 0), candidateHistoryKey("p102", sessionScope(A), 1)]).size, 4);
  const stored = { key: kA, attempt: 0, result: { ok: true, data: [{ id: "control-de-A" }] } };
  assert.equal(JSON.stringify(deriveView(candidateHistoryKey("p102", sessionScope(B), 0), true, 0, stored)).includes("control-de-A"), false);
  assert.equal(JSON.stringify(deriveView(candidateHistoryKey("p101", sessionScope(A), 0), true, 0, stored)).includes("control-de-A"), false);
  const page = read("app/page.tsx");
  assert.match(page, /candidateHistoryKey\("p102", scope, candRefresh\)/);
  assert.match(page, /candidateHistoryKey\("p101", scope, candRefresh\)/);
  assert.match(page, /publishedCand\.includes\("p102"\)/);
  assert.match(page, /publishedCand\.includes\("p101"\)/);
  assert.match(page, /BOBINAS_CANDIDATES\.p102\.api\.list\(signal\)/);
  assert.equal(/captures-p10[12]:\$\{/.test(page), false, "ninguna clave sin usuario");
  for (const file of ["lib/vinto/p1-02.ts", "lib/vinto/p1-01.ts", "lib/vinto/bobinas-candidates.ts", "lib/vinto/candidate-form.ts", "components/vinto/candidate-form-capture.tsx"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(code(file)), false, file);
});

test("alcance: política, sectores y seed intactos, sin migraciones nuevas, sin pantallas ni endpoints nuevos y formularios anteriores sin tocar", () => {
  const sectors = read("backend/app/sectors.py"), capture = read("backend/app/capture_service.py"), manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.equal(readdirSync(join(root, "backend/migrations")).filter((f) => f.endsWith(".sql")).length, 6);
  assert.equal(readdirSync(join(root, "components/vinto")).some((f) => /p1-0[12]/.test(f)), false, "no hay componentes de pantalla propios");
  assert.equal(/requestJson|\/api\//.test(code("lib/vinto/p1-02.ts") + code("lib/vinto/p1-01.ts")), false);
  assert.match(code("lib/vinto/bobinas-candidates.ts"), /api: candidateApi\(P102\)/);
  assert.match(code("lib/vinto/bobinas-candidates.ts"), /api: candidateApi\(P101\)/);
  // el único cambio de backend es la validación estricta de `time` (HH:MM / HH:MM:SS): documentada en el código
  assert.match(capture, /^TIME_PATTERN = re\.compile\(r"\(\[01\]\[0-9\]\|2\[0-3\]\):\[0-5\]\[0-9\]\(:\[0-5\]\[0-9\]\)\?"\)$/m);
  assert.match(capture, /if not isinstance\(raw, str\) or not TIME_PATTERN\.fullmatch\(raw\)/);
  assert.equal(/quality_release|INSERT INTO vinto_txn\.(bobbin|quality_release)/.test(code("lib/vinto/p1-02.ts") + code("lib/vinto/p1-01.ts")), false);
});

test("MF-02: P1-01 muestra «Consistencia» con la misma clave, obligatoriedad, tipo y unidad", () => {
  const f = P101_FIELDS.find((x) => x.key === "consistencia_h_4");
  assert.deepEqual({ ...f }, { key: "consistencia_h_4", label: "Consistencia", kind: "decimal", required: true, suffix: "%" });
  assert.equal(P101_FIELDS.length, 86);
  assert.equal(P101_FIELDS.some((x) => x.label.includes("H-4")), false);
  assert.equal(P101_FIELDS.find((x) => x.key === "nivel_tanque_h_3").label, "Nivel tanque H-3");
});

test("MF-03: P1-01 muestra «Ángulo caja» con la misma clave, obligatoriedad, tipo y sección", () => {
  const f = P101_FIELDS.find((x) => x.key === "angulo_labio");
  assert.deepEqual({ ...f }, { key: "angulo_labio", label: "Ángulo caja", kind: "text", required: true });
  assert.equal(P101_FIELDS.length, 86);
  assert.equal(P101_FIELDS.some((x) => x.label === "Ángulo labio"), false);
  assert.equal(P101_FIELDS.find((x) => x.key === "apertura_labio").label, "Apertura labio");
  assert.ok(P101_SECTIONS.some((s) => s.keys.includes("angulo_labio")));
});
