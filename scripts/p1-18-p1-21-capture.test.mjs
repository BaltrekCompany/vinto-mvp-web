// node --test scripts/p1-18-p1-21-capture.test.mjs
// DEV-Q2 · candidatos de Calidad: VINTO-P1-18 (Porcentaje de consistencia, control POR MÁQUINA) y VINTO-P1-21 (Perfil de gramaje y humedad, ligado a UNA BOBINA física). Contrato frente a form-definitions.ts, tipos
// (los pesos de papel de P1-18 siguen siendo texto), campos automáticos y calculados ausentes (consistencia, humedad y promedios nunca se calculan), payloads de contexto «máquina» y «bobina», parsers estrictos,
// flujo con reconciliación, oferta según el backend por máquina y por bobina, aislamiento por sesión y límites de alcance (políticas vacías en el backend, migraciones, seed_data y controles P1-19 / P1-20 intactos).
// Lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { parseAvailability } from "../lib/vinto/availability.ts";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { P118, P118_CALCULATED, P118_FIELDS, P118_PENDING, P1_18_CODE } from "../lib/vinto/p1-18.ts";
import { P121, P121_BOBBIN_CODE_FIELD, P121_CALCULATED, P121_FIELDS, P121_PENDING, P1_21_CODE } from "../lib/vinto/p1-21.ts";
import { BOBBIN_SCREEN_BY_FORM, QUALITY_BOBBIN_SCREENS, bobbinScreensFor, publishedQualityScreens, qualityMachines, qualityScreensFor } from "../lib/vinto/quality-offers.ts";
import { availabilityKey, candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
const pyCode = (file) => read(file).replace(/^"""[\s\S]*?"""/, "").split("\n").filter((l) => !/^\s*#/.test(l)).join("\n"); // sin docstrings ni comentarios
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", USER = "5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f", BOBBIN = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a";
const D118 = { producto: " producto ", numero_de_cuba: "C-2", punto_de_muestreo: "p", masa_humeda_g: "100,50", masa_seca_g: "3.25", papel_filtro_g: " 1,10 ", papel_muestra_g: "4.35 g", peso_muestra_g: "0,0032", observaciones: "" };
const D121 = { numero_de_bobina: "12", posicion_de_perfil: " centro ", gramaje: "85,5", peso_seco: "0.250", observaciones: " nota " };
const defOf = (id) => FORM_DEFINITIONS.find((f) => f.id === id);
const isManual = (f) => f.source === "manual";
const KIND = (f) => (f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : "text");

const base = (formCode, values, extra = {}) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", values, ...extra });
const machineEnvelope = (formCode, values, extra = {}) => base(formCode, values, { recorded_by: { id: USER, display_name: "Calidad" }, ...extra });
const bobbinEnvelope = (values, extra = {}) => base(P1_21_CODE, values, { bobbin: { id: BOBBIN, code: "12" }, work_order: { id: UUID, number: "OT-1" },
  line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, ...extra });

test("los contratos son EXACTAMENTE los campos manuales de las definiciones legacy; los automáticos y los calculados no se digitan", () => {
  for (const [id, fields, manual, automatic, calculated] of [["form_18_porcentaje_de_consistencia", P118_FIELDS, 9, 4, 1], ["form_21_perfil_de_gramaje_y_humedad", P121_FIELDS, 5, 4, 3]]) {
    const legacy = defOf(id);
    assert.equal(legacy.area, "quality");
    assert.deepEqual([legacy.fields.filter(isManual).length, legacy.fields.filter((f) => f.source === "automatic").length, legacy.fields.filter((f) => f.source === "calculated").length], [manual, automatic, calculated], id);
    assert.equal(legacy.fields.length, manual + automatic + calculated);
    const m = legacy.fields.filter(isManual);
    assert.deepEqual(fields.map((f) => f.key), m.map((f) => f.key), `${id}: claves y orden`);
    assert.deepEqual(fields.map((f) => f.label), m.map((f) => f.label), `${id}: etiquetas`);
    assert.deepEqual(fields.map((f) => f.required), m.map((f) => f.required ?? f.requirement), `${id}: obligatoriedad`);
    assert.deepEqual(fields.map((f) => f.kind), m.map(KIND), `${id}: tipos`);
    for (const f of legacy.fields.filter((x) => !isManual(x))) assert.equal(fields.some((x) => x.key === f.key), false, `${id}: ${f.key} no se digita`);
  }
  assert.deepEqual(P118_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key), ["masa_humeda_g", "masa_seca_g", "peso_muestra_g"]);
  assert.deepEqual(P118_FIELDS.filter((f) => f.kind === "text").map((f) => f.key), ["producto", "numero_de_cuba", "punto_de_muestreo", "papel_filtro_g", "papel_muestra_g"], "los pesos de papel son TEXTO, no decimal por su nombre");
  assert.deepEqual(P121_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key), ["gramaje", "peso_seco"]);
  assert.deepEqual([...P118_CALCULATED], ["Consistencia %"]);
  assert.deepEqual([...P121_CALCULATED], ["Humedad %", "Promedio gramaje", "Promedio humedad"]);
  assert.deepEqual(defOf("form_18_porcentaje_de_consistencia").allowedMachineIds, ["mp1", "mp3"]);
  assert.deepEqual(defOf("form_21_perfil_de_gramaje_y_humedad").allowedMachineIds, ["mp1", "mp3"]);
});

test("las unidades solo se muestran donde la definición no es contradictoria: P1-21 conserva g/m² y kg; P1-18 no muestra ninguna", () => {
  const u21 = defOf("form_21_perfil_de_gramaje_y_humedad").fields;
  assert.equal(u21.find((f) => f.key === "gramaje").unit, "g/m²");
  assert.equal(u21.find((f) => f.key === "peso_seco").unit, "kg");
  assert.deepEqual(P121_FIELDS.filter((f) => f.suffix).map((f) => [f.key, f.suffix]), [["gramaje", "g/m²"], ["peso_seco", "kg"]]);
  const peso = defOf("form_18_porcentaje_de_consistencia").fields.find((f) => f.key === "peso_muestra_g");
  assert.deepEqual([peso.label, peso.unit], ["Peso muestra g", "kg"]); // la etiqueta dice «g» y la unidad «kg»: contradicción de la definición legacy
  assert.equal(P118_FIELDS.filter((f) => f.suffix).length, 0, "no se inventa ni se elige una unidad para P1-18");
  assert.match(P118_PENDING.map((p) => `${p.label} ${p.pending}`).join(" "), /contradicción pendiente de VINTO y no se muestra ninguna unidad/);
});

test("las brechas se documentan: consistencia y promedios sin fórmula, hora de registro, cardinalidad del perfil, número de bobina y efecto sobre la bobina", () => {
  const t118 = P118_PENDING.map((p) => `${p.label} ${p.pending}`).join(" "), t121 = P121_PENDING.map((p) => `${p.label} ${p.pending}`).join(" ");
  assert.match(t118, /Consistencia %/);
  assert.match(t118, /no se calcula, no se guarda ni se muestra/);
  assert.match(t118, /Hora del ensayo/);
  assert.match(t118, /son texto en la definición legacy: se guardan tal como se digitan, sin convertirlos a número/);
  assert.match(t121, /promedio de gramaje y promedio de humedad son calculados/);
  assert.match(t121, /no se calculan, no se guardan ni se muestran/);
  assert.match(t121, /UNA posición declarada de la bobina/);
  assert.match(t121, /Perfil multiposición, series de ensayo y promedios siguen pendientes de VINTO/);
  assert.match(t121, /debe coincidir con la bobina seleccionada/i);
  assert.match(t121, /no libera ni rechaza la bobina/);
  assert.match(read("lib/vinto/p1-18.ts"), /NO se calcula `consistencia`/);
  assert.match(read("lib/vinto/p1-21.ts"), /NO se calculan `humedad`, `promedio_gramaje` ni `promedio_humedad`/);
  assert.match(read("components/vinto/candidate-form-capture.tsx"), /candidate\.calculated/);
});

test("el borrador valida estructuralmente, deja los textos como se digitaron y NO calcula consistencia, humedad ni promedios", () => {
  const a = P118.normalizeDraft(D118), b = P121.normalizeDraft(D121);
  assert.deepEqual(a.values, { producto: "producto", numero_de_cuba: "C-2", punto_de_muestreo: "p", masa_humeda_g: "100.50", masa_seca_g: "3.25", papel_filtro_g: "1,10", papel_muestra_g: "4.35 g", peso_muestra_g: "0.0032" });
  assert.deepEqual(b.values, { numero_de_bobina: "12", posicion_de_perfil: "centro", gramaje: "85.5", peso_seco: "0.250", observaciones: "nota" });
  assert.equal(a.values.papel_filtro_g, "1,10", "un campo de TEXTO conserva su coma: no se convierte a decimal por su nombre");
  assert.equal(a.values.papel_muestra_g, "4.35 g", "ni se rechaza por tener una unidad");
  for (const key of ["consistencia", "humedad", "promedio_gramaje", "promedio_humedad", "hora", "fecha", "maquina", "responsable", "total"]) assert.equal(key in a.values || key in b.values, false, key);
  for (const [form, draft, keys] of [[P118, D118, ["masa_humeda_g", "masa_seca_g", "peso_muestra_g"]], [P121, D121, ["gramaje", "peso_seco"]]]) for (const key of keys) {
    for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(form.normalizeDraft({ ...draft, [key]: bad }).errors.join(" "), /debe ser un número decimal/, `${key} ${bad}`);
    assert.match(form.normalizeDraft({ ...draft, [key]: " " }).errors.join(" "), /es obligatorio/, key);
    assert.equal(form.normalizeDraft({ ...draft, [key]: "-1,5" }).values[key], "-1.5", "sin rangos inventados");
  }
  assert.equal(P118.normalizeDraft(P118.emptyDraft()).errors.length, 8);
  assert.equal(P121.normalizeDraft(P121.emptyDraft()).errors.length, 4);
});

test("P1-18 usa el contexto «máquina» y P1-21 el contexto «bobina»: payloads cerrados, sin asignación, y congelados", () => {
  assert.equal(P118.context, "machine");
  assert.equal(P121.context, "bobbin");
  const m = P118.createAttempt(D118, "MP3", DEVICE, () => UUID).attempt;
  assert.deepEqual(Object.keys(m.payload).sort(), ["capture_id", "device_key", "form_code", "machine_code", "values"]);
  assert.deepEqual([m.payload.form_code, m.payload.machine_code], [P1_18_CODE, "MP3"]);
  const b = P121.createAttempt(D121, BOBBIN, DEVICE, () => UUID).attempt;
  assert.deepEqual(Object.keys(b.payload).sort(), ["bobbin_id", "capture_id", "device_key", "form_code", "values"]);
  assert.deepEqual([b.payload.form_code, b.payload.bobbin_id, b.payload.device_key, b.captureId], [P1_21_CODE, BOBBIN, DEVICE, UUID]);
  for (const [attempt, forbidden] of [[m, ["assignment_id", "bobbin_id", "work_order_id"]], [b, ["assignment_id", "machine_code", "work_order_id"]]]) {
    for (const key of forbidden) assert.equal(key in attempt.payload, false, key);
    for (const key of ["fecha", "hora", "maquina", "responsable", "consistencia", "humedad", "promedio_gramaje", "promedio_humedad"]) assert.equal(key in attempt.payload.values, false, key);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values));
  }
  assert.equal(P118.createAttempt(P118.emptyDraft(), "MP1", DEVICE).ok, false);
  assert.equal(P121.createAttempt(P121.emptyDraft(), BOBBIN, DEVICE).ok, false);
});

test("el parser de P1-18 acepta la respuesta por máquina y el de P1-21 exige la bobina, OT y línea; ambos exigen su formulario y valores estrictos e ignoran lo calculado", () => {
  const v118 = P118.normalizeDraft(D118).values, v121 = P121.normalizeDraft(D121).values;
  const p118 = P118.parseCapture(machineEnvelope(P1_18_CODE, v118));
  assert.deepEqual(p118?.values, v118);
  assert.equal(p118?.assignment, undefined);
  assert.equal(P118.parseCapture(machineEnvelope(P1_21_CODE, v118)), null, "P1-18 no acepta una captura de P1-21");
  assert.equal(P118.parseCapture(bobbinEnvelope(v118)), null, "ni una respuesta con otro formulario");
  const p121 = P121.parseCapture(bobbinEnvelope(v121));
  assert.deepEqual(p121?.values, v121);
  assert.deepEqual([p121?.bobbin, p121?.work_order?.number, p121?.line?.line_code, p121?.assignment], [{ id: BOBBIN, code: "12" }, "OT-1", "L1", undefined]);
  assert.equal(P121.parseCapture(bobbinEnvelope(v121, { form: { code: P1_18_CODE, version_number: 1, name: "x" } })), null, "P1-21 no acepta una captura de P1-18");
  assert.equal(P121.parseCapture(machineEnvelope(P1_21_CODE, v121)), null, "una captura por máquina (sin bobina) no es una captura de bobina");
  for (const missing of ["bobbin", "work_order", "line"]) { const e = bobbinEnvelope(v121); delete e[missing]; assert.equal(P121.parseCapture(e), null, `falta ${missing}`); }
  assert.equal(P121.parseCapture(bobbinEnvelope(v121, { bobbin: { id: BOBBIN } })), null);
  for (const [form, values, build] of [[P118, v118, (v) => machineEnvelope(P1_18_CODE, v)], [P121, v121, bobbinEnvelope]]) {
    for (const field of form.fields.filter((f) => f.required)) { const m = { ...values }; delete m[field.key]; assert.equal(form.parseCapture(build(m)), null, `falta ${field.key}`); }
    for (const key of ["consistencia", "humedad", "promedio_gramaje", "promedio_humedad"]) assert.deepEqual(form.parseCapture(build({ ...values, [key]: "9" }))?.values, values, `${key}: un calculado que llegara se ignora y nunca se presenta`);
    assert.equal(form.parseCapture(null), null);
    assert.equal(form.parseList([{ nope: 1 }]), null);
    assert.equal(form.parseList([build(values)])?.length, 1);
    assert.equal(form.parseSubmission({ created: true, already_submitted: false, capture: build(values) })?.created, true);
  }
  assert.equal(P118.parseCapture(machineEnvelope(P1_18_CODE, { ...v118, masa_humeda_g: "12,5" })), null, "decimal inválido");
  assert.equal(P121.parseCapture(bobbinEnvelope({ ...v121, gramaje: "abc" })), null);
});

const response = (status, data, errCode) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code: errCode });

test("flujo de envío (P1-18 y P1-21): 201, 200 idempotente, rechazos definitivos, sesión y reconciliación con el MISMO capture_id", async () => {
  for (const [name, form, context, draft, build, formCode] of [["P1-18", P118, "MP1", D118, (v) => machineEnvelope(P1_18_CODE, v), P1_18_CODE], ["P1-21", P121, BOBBIN, D121, bobbinEnvelope, P1_21_CODE]]) {
    const created = form.createAttempt(draft, context, DEVICE, () => UUID).attempt;
    const capture = form.parseCapture(build(form.normalizeDraft(draft).values));
    assert.equal(capture?.form.code, formCode);
    const ok = (c, a) => response(c ? 201 : 200, { created: c, already_submitted: a, capture });
    const first = await form.submitAttempt(created, { post: async () => ok(true, false), get: async () => assert.fail() });
    assert.deepEqual([first.kind, first.created, first.reconciled], ["submitted", true, false], name);
    const again = await form.submitAttempt(created, { post: async () => ok(false, true), get: async () => assert.fail() });
    assert.deepEqual([again.created, again.alreadySubmitted], [false, true], name);
    for (const [status, errCode, reason] of [[409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"], [409, "FORM_NOT_AVAILABLE", "conflict"], [403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "UNSUPPORTED_FORM", "invalid"], [422, "CAPTURE_VALIDATION", "invalid"]]) {
      const out = await form.submitAttempt(created, { post: async () => response(status, null, errCode), get: async () => assert.fail("un rechazo definitivo no reconcilia") });
      assert.deepEqual([out.kind, out.reason], ["rejected", reason], `${name} ${status} ${errCode}`);
    }
    assert.equal((await form.submitAttempt(created, { post: async () => response(401), get: async () => assert.fail() })).kind, "session");
    const lost = { ok: false, kind: "network", status: 0 };
    const reconciled = await form.submitAttempt(created, { post: async () => lost, get: async (id) => { assert.equal(id, UUID); return response(200, capture); } });
    assert.deepEqual([reconciled.kind, reconciled.reconciled], ["submitted", true], name);
    assert.equal((await form.submitAttempt(created, { post: async () => lost, get: async () => response(404, null) })).kind, "not_saved");
    assert.equal((await form.submitAttempt(created, { post: async () => lost, get: async () => lost })).kind, "uncertain");
    const seen = [];
    for (let i = 0; i < 3; i++) await form.submitAttempt(created, { post: async (p) => { seen.push(JSON.stringify(p)); return lost; }, get: async () => response(404, null) });
    assert.equal(new Set(seen).size, 1, `${name}: mismo payload en cada reintento`);
  }
});

test("la oferta sale del backend: P1-18 por máquina, P1-21 por la máquina de la bobina; nunca se mezclan y con la política real no se ofrece nada", () => {
  const form = (c) => ({ code: c, name: c, version_number: 1 });
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  assert.deepEqual([...QUALITY_BOBBIN_SCREENS], ["p121", "p124", "p125", "p128"]); // p124 / p125 (DEV-Q3) y p128 (DEV-CLOSE) se añadieron después
  assert.deepEqual(BOBBIN_SCREEN_BY_FORM, { "VINTO-P1-21": "p121", "VINTO-P1-24": "p124", "VINTO-P1-25": "p125", "VINTO-P1-28": "p128" });
  const real = avail([{ code: "MP1", name: "MP1", forms: [] }, { code: "MP3", name: "MP3", forms: [] }]);
  assert.deepEqual([qualityMachines(real), publishedQualityScreens(real), bobbinScreensFor(real, "MP1"), bobbinScreensFor(real, "MP3")], [[], [], [], []], "configuración real: el backend no publica ningún candidato");
  const machineSide = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-18"), form("VINTO-P1-22")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-18")] }]);
  assert.deepEqual([qualityScreensFor(machineSide, "MP1"), qualityScreensFor(machineSide, "MP3"), publishedQualityScreens(machineSide)], [["p118", "p122"], ["p118"], ["p118", "p122"]]);
  assert.deepEqual([bobbinScreensFor(machineSide, "MP1"), bobbinScreensFor(machineSide, "MP3")], [[], []], "P1-18 no se ofrece como candidato de bobina");
  const bobbinSide = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-21")] }, { code: "MP3", name: "MP3", forms: [] }]);
  assert.deepEqual([bobbinScreensFor(bobbinSide, "MP1"), bobbinScreensFor(bobbinSide, "MP3"), bobbinScreensFor(bobbinSide, "MP9")], [["p121"], [], []]);
  assert.deepEqual([qualityMachines(bobbinSide), qualityScreensFor(bobbinSide, "MP1")], [[], []], "P1-21 no se ofrece como control por máquina");
  assert.deepEqual(bobbinScreensFor(avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-19"), form("VINTO-P1-20"), form("VINTO-P1-22")] }]), "MP1"), [], "otros formularios no son candidatos de bobina");
});

test("aislamiento por usuario y por bobina: disponibilidad e historiales de la cuenta o la bobina anterior nunca se presentan a otra", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  const kA = candidateHistoryKey(`p121-${BOBBIN}`, sessionScope(A), 0), kB = candidateHistoryKey(`p121-${BOBBIN}`, sessionScope(B), 0);
  assert.notEqual(kA, kB);
  assert.notEqual(kA, candidateHistoryKey("p121-otra-bobina", sessionScope(A), 0));
  assert.notEqual(kA, candidateHistoryKey(`p121-${BOBBIN}`, sessionScope(A), 1));
  const stored = { key: kA, attempt: 0, result: { ok: true, data: [{ id: "control-de-A" }] } };
  assert.equal(deriveView(kA, true, 0, stored).status, "ready");
  const viewB = deriveView(kB, true, 0, stored);
  assert.equal(viewB.status, "loading");
  assert.equal(JSON.stringify(viewB).includes("control-de-A"), false);
  const machine = code("components/vinto/quality-machine-controls.tsx"), bobbin = code("components/vinto/quality-bobbin-candidate-capture.tsx"), page = read("app/page.tsx");
  assert.match(machine, /candidateHistoryKey\(`p118-\$\{code\}`, scope, refreshKey\)/);
  assert.match(bobbin, /candidateHistoryKey\(`\$\{screen\}-\$\{item\.bobbin\.id\}`, scope, refreshKey\)/);
  assert.match(page, /useResource\(`quality-bobbin-forms:\$\{scope\}`, authenticated && front === "Calidad" && canReadQualityInbox && activeModule === "ejecucion", signal => getQualityBobbinForms\(signal\), sessionLost\)/);
  assert.notEqual(availabilityKey(false, sessionScope(A)), availabilityKey(false, sessionScope(B)));
  assert.match(page, /setBobbinCand\(null\); setBobbinCandAttempts\(\{\}\)/); // la sesión perdida (y el cierre de sesión) descartan la bobina y los intentos pendientes
  assert.equal((page.match(/setBobbinCand\(null\); setBobbinCandAttempts\(\{\}\);/g) ?? []).length, 2);
});

test("el cliente HTTP de P1-21 reutiliza las rutas de Calidad por bobina (bobina en la ruta, historial filtrado) y P1-18 las de por máquina; nunca almacenamiento local", () => {
  const api = code("lib/vinto/candidate-form-api.ts");
  assert.match(api, /const \{ bobbin_id: bobbin, \.\.\.body \} = payload;/);
  assert.match(api, /`\/api\/quality\/bobbins\/\$\{encodeURIComponent\(bobbin \?\? ""\)\}\/captures`, \{ method: "POST", body,/);
  assert.match(api, /`\/api\/quality\/captures\/\$\{encodeURIComponent\(captureId\)\}`/);
  assert.match(api, /\/api\/quality\/bobbins\/\$\{encodeURIComponent\(bobbinId\)\}\/captures\?form_code=\$\{encodeURIComponent\(form\.code\)\}/);
  assert.match(api, /requestJson\("\/api\/quality\/bobbin-forms"/);
  const bobbinPart = api.split("export const bobbinCandidateApi")[1].split("export function getQualityBobbinForms")[0];
  assert.equal(/\/api\/quality\/machine|\/api\/captures`|"\/api\/captures"/.test(bobbinPart), false, "P1-21 no usa la API de Calidad por máquina ni la de Producción");
  assert.equal(/\/api\/quality\/bobbins/.test(api.split("export const machineCandidateApi")[1].split("export const bobbinCandidateApi")[0]), false, "P1-18 no usa la API por bobina");
  for (const file of ["lib/vinto/p1-18.ts", "lib/vinto/p1-21.ts", "lib/vinto/quality-offers.ts", "lib/vinto/quality-candidates.ts", "lib/vinto/quality-bobbin-candidates.ts", "lib/vinto/candidate-form-api.ts", "components/vinto/quality-machine-controls.tsx",
    "components/vinto/quality-bobbin-candidate-capture.tsx", "components/vinto/quality-bobbin-inbox.tsx"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(code(file)), false, file);
});

test("la pantalla de P1-21 precarga y bloquea el número de bobina, muestra el identificador y código de la bobina y su historial central; el backend sigue siendo la autoridad", () => {
  assert.equal(P121_BOBBIN_CODE_FIELD, "numero_de_bobina");
  const capture = code("components/vinto/candidate-form-capture.tsx"), wrapper = code("components/vinto/quality-bobbin-candidate-capture.tsx"), history = code("components/vinto/candidate-history.tsx"), candidates = code("lib/vinto/quality-bobbin-candidates.ts");
  assert.match(candidates, /bobbinCodeField: P121_BOBBIN_CODE_FIELD/);
  assert.match(capture, /draft\[codeField\] = bobbin\.bobbin\.code/);
  assert.match(capture, /disabled=\{locked \|\| field\.key === codeField\}/);
  assert.match(capture, /bobbin \? `\$\{bobbin\.bobbin\.code\} · \$\{bobbin\.bobbin\.id\}`/);
  assert.match(capture, /contextId = form\.context === "machine" \? machine\?\.code : form\.context === "bobbin" \? bobbin\?\.bobbin\.id : context\?\.assignmentId/);
  assert.match(capture, /sameBobbin/);
  assert.match(wrapper, /candidate\.bobbinApi\.list\(item\.bobbin\.id, signal\)/);
  assert.match(wrapper, /<CandidateHistory candidate=\{candidate\}/);
  assert.match(history, /bobbinLevel/);
  assert.match(history, /"Bobina", "OT"/);
  const page = read("app/page.tsx");
  assert.match(page, /if \(bobbinCand && front === "Calidad" && canReadQualityInbox\)/);
  assert.match(page, /item=\{pending \? pending\.item : bobbinCand\.item\}/);
  const inbox = code("components/vinto/quality-bobbin-inbox.tsx");
  assert.match(inbox, /candidateOffers\?\.\(i\.bobbin\.machine\.code\)/);
  assert.match(inbox, /\(candidato\)/);
  assert.equal(/Liberar|Rechazar|liberar|rechazar/.test(inbox + wrapper), false, "ninguna acción libera ni rechaza");
});

test("alcance: políticas vacías en el backend, producción y seed_data intactos, sin migraciones nuevas, P1-19 / P1-20 y su historial sin tocar", () => {
  const machine = read("backend/app/quality/machine_capture_service.py"), bobbin = read("backend/app/quality/capture_service.py"), capture = read("backend/app/capture_service.py"), sectors = read("backend/app/sectors.py");
  const manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(machine, /^MACHINE_QUALITY_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.match(bobbin, /^ENABLED_BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.match(bobbin, /^BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset\(\{"VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"\}\)$/m);
  assert.match(bobbin, /^BOBBIN_CODE_FIELDS: dict = \{"VINTO-P1-21": "numero_de_bobina", "VINTO-P1-24": "numero_de_bobina", "VINTO-P1-25": "numero_de_bobina", "VINTO-P1-28": "numero_de_bobina"\}$/m);
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.deepEqual(readdirSync(join(root, "backend/migrations")).filter((f) => f.endsWith(".sql")), ["0001_initial_schema.sql", "0002_auth.sql", "0003_capture_revision_semantics.sql", "0004_bobbin_production.sql", "0005_quality_capture_bobbin.sql", "0006_user_sector_grants.sql"]);
  // ningún servicio de Calidad libera, rechaza ni crea bobinas / asignaciones / OT
  const body = pyCode("backend/app/quality/capture_service.py") + pyCode("backend/app/quality/machine_capture_service.py") + pyCode("backend/app/quality/form_availability.py");
  assert.equal(/UPDATE vinto_txn\.quality_release|INSERT INTO vinto_txn\.(bobbin|assignment|work_order|quality_release)|decided_by|decision_reason/.test(body), false);
  // el servicio por bobina no importa el servicio por máquina (separación de rutas) y el de máquina no conoce la política por bobina
  assert.equal(/machine_capture|MACHINE_QUALITY/.test(bobbin + read("backend/app/quality/router.py") + read("backend/app/quality/service.py")), false);
  assert.equal(/BOBBIN_CANDIDATE|capture_service as bobbin/.test(machine), false);
  // la política por bobina solo afecta al candidato: P1-19 / P1-20 no se mencionan ni se condicionan
  assert.equal(/VINTO-P1-19|VINTO-P1-20/.test(bobbin), false);
  const history = read("lib/vinto/quality-history-api.ts");
  assert.match(history, /\[Q19_FORM_CODE\]: humidityViewer\(parseQualityCapture\), \[Q20_FORM_CODE\]: physicalViewer\(parsePhysicalCapture\)/); // el historial de la bobina de P1-19 / P1-20 no cambia
  const page = read("app/page.tsx");
  assert.match(page, /function Fiber\(/); // los formularios legacy y sus registros no se tocan
  assert.equal(/localStorage\.(removeItem|clear)/.test(page), false);
});
