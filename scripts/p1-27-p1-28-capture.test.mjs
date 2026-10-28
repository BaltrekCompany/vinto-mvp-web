// node --test scripts/p1-27-p1-28-capture.test.mjs
// DEV-CLOSE · candidatos de Calidad: VINTO-P1-27 (Análisis de agua para caldero, control POR MÁQUINA, 23 campos manuales con MP1 y MP3 en el MISMO contrato) y VINTO-P1-28 (Registro de bobinas rechazadas, FICHA
// DOCUMENTAL ligada a una bobina física, 7 campos manuales). Contrato frente a form-definitions.ts, tipos (sólidos / conductividad / cloruros son texto), alcalinidad no calculada, secciones visuales de una vez
// por campo, payloads de contexto «máquina» y «bobina», parsers, flujo con reconciliación, oferta según el backend por máquina y por bobina, aislamiento por sesión, y límites de alcance: P1-28 NO rechaza, no
// toca quality_release, no genera firmas ni vistos buenos. Lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { parseAvailability } from "../lib/vinto/availability.ts";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { P127, P127_CALCULATED, P127_FIELDS, P127_PENDING, P127_SECTIONS, P1_27_CODE } from "../lib/vinto/p1-27.ts";
import { P128, P128_ACTION_LABEL, P128_FIELDS, P128_OFFICIAL_STATUS_NOTE, P128_PENDING, P1_28_CODE } from "../lib/vinto/p1-28.ts";
import { bobbinScreensFor, publishedQualityScreens, qualityMachines, qualityScreensFor } from "../lib/vinto/quality-offers.ts";
import { candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", USER = "5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f", BOBBIN = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a";
const defOf = (id) => FORM_DEFINITIONS.find((f) => f.id === id);
const isManual = (f) => f.source === "manual";
const KIND = (f) => (f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : "text");
const fill = (fields) => Object.fromEntries(fields.map((f) => [f.key, f.kind === "decimal" ? "7,25" : f.key === "numero_de_bobina" ? "12" : f.kind === "textarea" ? " nota " : "texto 1,250"]));
const CASES = [
  { name: "P1-27", id: "form_27_analisis_de_agua_para_caldero", form: P127, formCode: P1_27_CODE, fields: P127_FIELDS, counts: [23, 3, 1], context: "machine", added: ["alcalinidad_total"] }, // MF-11: «alcalinidad_total» es un campo manual NUEVO de la versión 2 (la clave calculada de la definición legacy sigue sin digitarse)
  { name: "P1-28", id: "form_28_registro_de_bobinas_rechazadas", form: P128, formCode: P1_28_CODE, fields: P128_FIELDS, counts: [7, 6, 0], context: "bobbin" },
];
const base = (formCode, values, extra = {}) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", values, ...extra });
const envelope = (c, values) => c.context === "machine" ? base(c.formCode, values, { recorded_by: { id: USER, display_name: "Calidad" } })
  : base(c.formCode, values, { bobbin: { id: BOBBIN, code: "12" }, work_order: { id: UUID, number: "OT-1" }, line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } } });

test("los contratos son EXACTAMENTE los campos manuales de las definiciones legacy (23 y 7): claves, etiquetas, orden, tipos, obligatoriedad y unidades", () => {
  for (const c of CASES) {
    const legacy = defOf(c.id);
    assert.equal(legacy.area, "quality");
    assert.deepEqual(legacy.allowedMachineIds, ["mp1", "mp3"]);
    assert.deepEqual([legacy.fields.filter(isManual).length, legacy.fields.filter((f) => f.source === "automatic").length, legacy.fields.filter((f) => f.source === "calculated").length], c.counts, c.name);
    assert.equal(legacy.fields.length, c.counts[0] + c.counts[1] + c.counts[2]);
    const m = legacy.fields.filter(isManual);
    const kept = c.fields.filter((f) => !(c.added ?? []).includes(f.key)); // los añadidos por versiones posteriores se comprueban aparte
    assert.equal(kept.length, c.counts[0]);
    assert.equal(c.fields.length, c.counts[0] + (c.added ?? []).length);
    assert.deepEqual(kept.map((f) => f.key), m.map((f) => f.key), `${c.name}: claves y orden`);
    assert.deepEqual(kept.map((f) => f.label), m.map((f) => f.label), `${c.name}: etiquetas`);
    assert.deepEqual(kept.map((f) => f.required), m.map((f) => f.required ?? f.requirement), `${c.name}: obligatoriedad`);
    assert.deepEqual(kept.map((f) => f.kind), m.map(KIND), `${c.name}: tipos`);
    for (const f of kept) assert.equal(f.suffix, m.find((x) => x.key === f.key).unit ?? undefined, `${c.name}: ${f.key} unidad`);
    for (const f of legacy.fields.filter((x) => !isManual(x))) assert.equal(c.fields.some((x) => x.key === f.key), false, `${c.name}: ${f.key} no se digita`);
    assert.equal(c.form.context, c.context);
  }
  assert.deepEqual(defOf("form_27_analisis_de_agua_para_caldero").fields.filter((f) => f.source === "calculated").map((f) => f.key), ["purga_caldero_alcalinidad_total"]);
  assert.deepEqual([...P127_CALCULATED], ["Purga caldero alcalinidad total"]);
  assert.deepEqual(defOf("form_28_registro_de_bobinas_rechazadas").fields.filter((f) => f.source === "automatic").map((f) => f.key), ["fecha", "hora", "maquina", "operador", "responsable_de_calidad", "visto_bueno_produccion"]);
  assert.equal(P127_FIELDS.filter((f) => f.suffix).length, 0, "P1-27 no declara unidades: no se inventa ninguna");
  const alk = P127_FIELDS.find((f) => f.key === "alcalinidad_total"); // MF-11 (MD_Ejec 35)
  assert.deepEqual({ ...alk }, { key: "alcalinidad_total", label: "Alcalinidad total", kind: "decimal", required: false, sinceVersion: 2 }, "decimal digitado, opcional, SIN unidad");
  assert.equal(defOf("form_27_analisis_de_agua_para_caldero").fields.some((f) => f.key === "alcalinidad_total"), false, "no existe en la definición legacy: no hay colisión con el campo calculado");
  assert.deepEqual(P128_FIELDS.filter((f) => f.suffix).map((f) => [f.key, f.suffix]), [["peso_rechazado", "kg"]]);
});

test("sólidos disueltos, conductividad, cloruros y calibración son TEXTO aunque parezcan magnitudes; pH y dureza son decimales; el contrato conserva MP1 y MP3", () => {
  const kinds = Object.fromEntries(P127_FIELDS.map((f) => [f.key, f.kind]));
  for (const [key, kind] of Object.entries(kinds)) {
    if (/_ph$|_dureza$/.test(key)) assert.equal(kind, "decimal", key);
    else if (/solidos_disueltos$|conductividad$|cloruros$/.test(key) || key === "calibracion_equipo_multiparametro") assert.equal(kind, "text", key);
  }
  assert.equal(kinds.observaciones, "textarea");
  assert.equal(P127_FIELDS.find((f) => f.key === "observaciones").required, false);
  assert.deepEqual(P127_FIELDS.map((f) => f.key).filter((k) => k.startsWith("condensado_mp1_")), ["condensado_mp1_ph", "condensado_mp1_dureza", "condensado_mp1_solidos_disueltos", "condensado_mp1_conductividad"]);
  assert.deepEqual(P127_FIELDS.map((f) => f.key).filter((k) => k.startsWith("condensado_mp3_")), ["condensado_mp3_ph", "condensado_mp3_dureza", "condensado_mp3_solidos_disueltos", "condensado_mp3_conductividad"]);
  const check = P127.normalizeDraft(fill(P127_FIELDS));
  assert.equal(check.ok, true);
  assert.equal(check.values.ablandador_solidos_disueltos, "texto 1,250", "el texto conserva su coma");
  assert.equal(check.values.ablandador_ph, "7.25");
  assert.equal(Object.keys(check.values).length, 24, "los 22 obligatorios + alcalinidad total (opcional) + observaciones (llenas aquí): exactamente los 24 campos del contrato");
});

test("P1-27 conserva los 24 campos en cada captura: ni la máquina elegida ni nada los oculta o divide el contrato", () => {
  for (const machine of ["MP1", "MP3"]) {
    const { attempt } = P127.createAttempt(fill(P127_FIELDS), machine, DEVICE, () => UUID);
    assert.equal(Object.keys(attempt.payload.values).length, 24, machine);
    assert.deepEqual(Object.keys(attempt.payload.values), P127_FIELDS.map((f) => f.key), machine);
    assert.equal(attempt.payload.machine_code, machine);
  }
  const screens = code("components/vinto/candidate-form-capture.tsx") + code("lib/vinto/quality-candidates.ts") + code("components/vinto/quality-machine-controls.tsx");
  assert.equal(/condensado_mp[13]|machine\.code === "MP|filter\(.*mp1|filter\(.*mp3/i.test(screens), false, "ningún código filtra campos por máquina");
  assert.match(P127_PENDING.map((p) => p.pending).join(" "), /se conservan los 24 campos aunque elijas una máquina; no se ocultan ni se dividen/);
});

test("las secciones de P1-27 son solo visuales: cada campo manual una vez, en el orden del contrato, con los grupos pedidos", () => {
  const keys = P127_SECTIONS.flatMap((s) => s.keys);
  assert.deepEqual(keys, P127_FIELDS.map((f) => f.key));
  assert.equal(new Set(keys).size, 24);
  assert.deepEqual(P127_SECTIONS.map((s) => s.title), ["Ablandador", "Agua de alimentación", "Purga de caldero", "Condensado MP1", "Condensado MP3", "Calibración y observaciones"]);
  assert.deepEqual(P127_SECTIONS.map((s) => s.keys.length), [4, 4, 6, 4, 4, 2], "Alcalinidad total va en Purga de caldero");
  assert.deepEqual(Object.keys(P127.emptyDraft()), P127_FIELDS.map((f) => f.key), "el borrador y el payload conservan las claves individuales");
  assert.match(code("components/vinto/candidate-form-capture.tsx"), /candidate\.sections/);
  assert.equal(code("lib/vinto/quality-candidates.ts").includes("sections: P127_SECTIONS"), true);
  assert.equal(code("lib/vinto/quality-bobbin-candidates.ts").includes("sections:"), false, "P1-28 (7 campos) no necesita secciones");
});

test("el borrador valida estructuralmente y NO calcula la alcalinidad, ni genera automáticos, firmas o decisiones", () => {
  for (const c of CASES) {
    const check = c.form.normalizeDraft(fill(c.fields));
    assert.equal(check.ok, true, c.name);
    for (const key of ["purga_caldero_alcalinidad_total", "fecha", "hora", "turno", "maquina", "responsable", "operador", "responsable_de_calidad", "visto_bueno_produccion", "estado", "decision", "aprobado"]) assert.equal(key in check.values, false, `${c.name}: ${key}`);
    for (const f of c.fields.filter((x) => x.kind === "decimal")) {
      for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: bad }).errors.join(" "), /debe ser un número decimal/, `${c.name} ${f.key} ${bad}`);
      if (f.required) assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: " " }).errors.join(" "), /es obligatorio/, f.key);
      else assert.equal(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: " " }).ok, true, `${f.key}: opcional, vacío se acepta y no se guarda`);
    }
    assert.equal(c.form.normalizeDraft(c.form.emptyDraft()).errors.length, c.fields.filter((f) => f.required).length);
  }
  assert.equal(P128.normalizeDraft({ ...fill(P128_FIELDS), estado_disposicion_final: "rechazado" }).values.estado_disposicion_final, "rechazado", "es texto declarado: se guarda tal cual, sin interpretarlo");
  assert.equal(P128.normalizeDraft({ ...fill(P128_FIELDS), detalle_motivo_de_rechazo: "línea 1\nlínea 2" }).values.detalle_motivo_de_rechazo, "línea 1\nlínea 2");
});

test("los payloads son de su contexto: P1-27 «máquina» (sin bobina ni asignación), P1-28 «bobina» (UUID en el payload, sin decisión); cerrados y congelados", () => {
  const m = P127.createAttempt(fill(P127_FIELDS), "MP3", DEVICE, () => UUID).attempt;
  assert.deepEqual(Object.keys(m.payload).sort(), ["capture_id", "device_key", "form_code", "machine_code", "values"]);
  const b = P128.createAttempt(fill(P128_FIELDS), BOBBIN, DEVICE, () => UUID).attempt;
  assert.deepEqual(Object.keys(b.payload).sort(), ["bobbin_id", "capture_id", "device_key", "form_code", "values"]);
  assert.deepEqual([b.payload.form_code, b.payload.bobbin_id, b.captureId], [P1_28_CODE, BOBBIN, UUID], "el UUID de la bobina es la autoridad");
  for (const [attempt, forbidden] of [[m, ["assignment_id", "bobbin_id"]], [b, ["assignment_id", "machine_code", "status", "decision", "released", "rejected"]]]) {
    for (const key of forbidden) assert.equal(key in attempt.payload, false, key);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values));
  }
  assert.equal(P127.createAttempt(P127.emptyDraft(), "MP1", DEVICE).ok, false);
  assert.equal(P128.createAttempt(P128.emptyDraft(), BOBBIN, DEVICE).ok, false);
});

test("los parsers exigen su formulario y contexto, valores estrictos, e ignoran lo calculado o ajeno", () => {
  for (const c of CASES) {
    const values = c.form.normalizeDraft(fill(c.fields)).values;
    const parsed = c.form.parseCapture(envelope(c, values));
    assert.deepEqual(parsed?.values, values, c.name);
    for (const other of ["VINTO-P1-21", c.formCode === P1_27_CODE ? P1_28_CODE : P1_27_CODE]) assert.equal(c.form.parseCapture({ ...envelope(c, values), form: { code: other, version_number: 1, name: "x" } }), null, `${c.name}: ${other}`);
    for (const f of c.fields.filter((x) => x.required)) { const m = { ...values }; delete m[f.key]; assert.equal(c.form.parseCapture(envelope(c, m)), null, `falta ${f.key}`); }
    assert.deepEqual(c.form.parseCapture(envelope(c, { ...values, purga_caldero_alcalinidad_total: "9", estado: "aprobado", visto_bueno_produccion: "ok" }))?.values, values, "lo ajeno se ignora y nunca se presenta");
    assert.equal(c.form.parseCapture(envelope(c, { ...values, [c.fields.find((f) => f.kind === "decimal").key]: "abc" })), null);
    assert.equal(c.form.parseList([envelope(c, values)])?.length, 1);
    assert.equal(c.form.parseList([{ nope: 1 }]), null);
  }
  assert.equal(P127.parseCapture(envelope(CASES[1], P127.normalizeDraft(fill(P127_FIELDS)).values)), null, "una captura por bobina no es una captura por máquina");
  const v128 = P128.normalizeDraft(fill(P128_FIELDS)).values;
  for (const missing of ["bobbin", "work_order", "line"]) { const e = envelope(CASES[1], v128); delete e[missing]; assert.equal(P128.parseCapture(e), null, `P1-28: falta ${missing}`); }
  assert.deepEqual(P128.parseCapture(envelope(CASES[1], v128))?.bobbin, { id: BOBBIN, code: "12" });
});

const response = (status, data, errCode) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code: errCode });

test("flujo de envío: 201, 200 idempotente, rechazos definitivos, sesión y reconciliación con el MISMO capture_id", async () => {
  for (const c of CASES) {
    const created = c.form.createAttempt(fill(c.fields), c.context === "machine" ? "MP1" : BOBBIN, DEVICE, () => UUID).attempt;
    const capture = c.form.parseCapture(envelope(c, c.form.normalizeDraft(fill(c.fields)).values));
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

test("la oferta sale del backend: P1-27 por máquina (MP1 y MP3), P1-28 por la máquina de la bobina; nunca se mezclan y con la política real no se ofrece nada", () => {
  const form = (c) => ({ code: c, name: c, version_number: 1 });
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  const real = avail([{ code: "MP1", name: "MP1", forms: [] }, { code: "MP3", name: "MP3", forms: [] }]);
  assert.deepEqual([qualityMachines(real), publishedQualityScreens(real), bobbinScreensFor(real, "MP1"), bobbinScreensFor(real, "MP3")], [[], [], [], []], "configuración real: nada publicado");
  const machineSide = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-27"), form("VINTO-P1-28")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-27")] }]);
  assert.deepEqual([qualityScreensFor(machineSide, "MP1"), qualityScreensFor(machineSide, "MP3"), publishedQualityScreens(machineSide)], [["p127"], ["p127"], ["p127"]], "P1-28 no es un control por máquina");
  assert.deepEqual([bobbinScreensFor(machineSide, "MP1"), bobbinScreensFor(machineSide, "MP3")], [["p128"], []], "P1-27 no es un candidato de bobina");
  assert.deepEqual(bobbinScreensFor(avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-27"), form("VINTO-P1-19"), form("VINTO-P1-20")] }]), "MP1"), []);
  const registry = code("lib/vinto/quality-candidates.ts") + code("lib/vinto/quality-bobbin-candidates.ts");
  assert.ok(registry.includes("p127: make({ code: P1_27_CODE, form: P127,"));
  assert.ok(registry.includes("p128: make({ code: P1_28_CODE, form: P128,"));
  assert.ok(registry.includes("bobbinCodeField: P128_BOBBIN_CODE_FIELD"));
});

test("P1-28 es una ficha DOCUMENTAL: texto de acción inequívoco, estado oficial solo lectura, sin botones de rechazar / liberar / aprobar", () => {
  assert.equal(P128_ACTION_LABEL, "Registrar ficha documental P1-28 (candidato)");
  assert.match(P128_OFFICIAL_STATUS_NOTE, /DECLARA al registrar; el estado oficial de Calidad de la bobina lo controla quality_release y no cambia con esta captura/);
  const text = P128_PENDING.map((p) => `${p.label} ${p.pending}`).join(" ");
  assert.match(text, /NO rechaza, bloquea ni libera la bobina: no modifica quality_release, inventario ni disponibilidad, no hay endpoint de rechazo ni Q-LIB/);
  assert.match(text, /no es una decisión oficial ni un estado de la bobina/);
  assert.match(text, /no se generan\. El usuario autenticado solo identifica quién registra; no es firma, aprobación ni visto bueno/);
  assert.match(text, /disponibilidad histórica de bobinas rechazadas y su disposición definitiva requieren un diseño posterior con VINTO/);
  assert.match(text, /No hay hora original del rechazo/);
  const capture = code("components/vinto/candidate-form-capture.tsx"), inbox = code("components/vinto/quality-bobbin-inbox.tsx"), wrapper = code("components/vinto/quality-bobbin-candidate-capture.tsx"), cands = code("lib/vinto/quality-bobbin-candidates.ts");
  assert.match(capture, /Estado oficial de Calidad de la bobina \(solo lectura\)/);
  assert.match(capture, /qualityStatusLabel\(bobbin\.quality\.status\)/);
  assert.match(capture, /candidate\.officialStatusNote/);
  assert.match(cands, /actionLabel: P128_ACTION_LABEL/);
  assert.match(cands, /estado_disposicion_final: "Estado \/ disposición final DECLARADO en la ficha: no es el estado oficial de Calidad de la bobina\."/);
  assert.match(inbox, /actionLabel \?\?/);
  assert.equal(/Rechazar bobina|Aprobar rechazo|Confirmar disposición|Liberar bobina|Bloquear bobina|Liberar|Rechazar\b/.test(inbox + wrapper + capture + cands + code("lib/vinto/p1-28.ts")), false, "ninguna acción de decisión");
  assert.match(read("lib/vinto/p1-28.ts"), /ES UN REGISTRO DOCUMENTAL, NO UNA DECISIÓN DE RECHAZO/);
});

test("aislamiento por usuario, máquina y bobina: los historiales de otra cuenta, máquina o bobina nunca se presentan; sin localStorage", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  const keys = [candidateHistoryKey("p127-MP1", sessionScope(A), 0), candidateHistoryKey("p127-MP1", sessionScope(B), 0), candidateHistoryKey("p127-MP3", sessionScope(A), 0), candidateHistoryKey(`p128-${BOBBIN}`, sessionScope(A), 0), candidateHistoryKey("p128-otra", sessionScope(A), 0), candidateHistoryKey(`p128-${BOBBIN}`, sessionScope(B), 0)];
  assert.equal(new Set(keys).size, 6);
  const stored = { key: keys[0], attempt: 0, result: { ok: true, data: [{ id: "control-de-A" }] } };
  for (const other of keys.slice(1)) assert.equal(JSON.stringify(deriveView(other, true, 0, stored)).includes("control-de-A"), false);
  assert.match(code("components/vinto/quality-machine-controls.tsx"), /candidateHistoryKey\(`p127-\$\{code\}`, scope, refreshKey\)/);
  assert.match(code("components/vinto/quality-bobbin-candidate-capture.tsx"), /candidateHistoryKey\(`\$\{screen\}-\$\{item\.bobbin\.id\}`, scope, refreshKey\)/);
  for (const file of ["lib/vinto/p1-27.ts", "lib/vinto/p1-28.ts", "lib/vinto/quality-candidates.ts", "lib/vinto/quality-bobbin-candidates.ts", "lib/vinto/quality-offers.ts", "components/vinto/quality-machine-controls.tsx", "components/vinto/quality-bobbin-candidate-capture.tsx",
    "components/vinto/quality-bobbin-inbox.tsx", "components/vinto/candidate-form-capture.tsx"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(code(file)), false, file);
});

test("alcance: políticas vacías, producción y seed intactos, sin migraciones, sin endpoints ni pantallas nuevos, sin tocar quality_release y P1-19 / P1-20 / P1-21 / P1-24 / P1-25 sin cambios", () => {
  const machine = read("backend/app/quality/machine_capture_service.py"), bobbin = read("backend/app/quality/capture_service.py"), capture = read("backend/app/capture_service.py"), sectors = read("backend/app/sectors.py");
  const manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(machine, /^MACHINE_QUALITY_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.match(bobbin, /^ENABLED_BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.match(bobbin, /^BOBBIN_CANDIDATE_FORM_CODES: frozenset = frozenset\(\{"VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"\}\)$/m);
  assert.match(bobbin, /"VINTO-P1-28": "numero_de_bobina"\}$/m);
  assert.equal(bobbin.replace(/^"""[\s\S]*?"""/, "").split("\n").filter((l) => !/^\s*#/.test(l)).join("\n").includes("P1-27"), false, "P1-27 es de máquina: no está en ninguna política por bobina (solo se menciona en la documentación INT-01A)");
  assert.equal(/VINTO-P1-27/.test(machine), false, "la política por máquina sigue vacía: P1-27 solo se habilita en pruebas");
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.equal(readdirSync(join(root, "backend/migrations")).filter((f) => f.endsWith(".sql")).length, 6);
  assert.equal(readdirSync(join(root, "components/vinto")).some((f) => /p1-2[78]/.test(f)), false, "no hay componentes de pantalla propios");
  const routes = [...(read("backend/app/quality/router.py") + read("backend/app/quality/machine_router.py")).matchAll(/@router\.(get|post|put|patch|delete)\("([^"]*)"/g)].map((m) => `${m[1].toUpperCase()} ${m[2]}`);
  assert.equal(routes.some((r) => /reject|rechaz|release|liberar|decision|approve|aprob|disposicion/i.test(r)), false, `ningún endpoint de rechazo, liberación ni decisión: ${routes.join(", ")}`);
  assert.deepEqual(routes.filter((r) => /bobbin-forms|machine-forms/.test(r)).sort(), ["GET /bobbin-forms", "GET /machine-forms"]); // la disponibilidad ya existente: DEV-CLOSE no añade rutas
  const body = (bobbin + machine).replace(/"""[\s\S]*?"""/g, "").split("\n").filter((l) => !/^\s*#/.test(l)).join("\n");
  assert.equal(/UPDATE vinto_txn\.quality_release|INSERT INTO vinto_txn\.(bobbin|quality_release)|decided_by|decision_reason/.test(body), false);
  assert.equal(/requestJson|\/api\//.test(code("lib/vinto/p1-27.ts") + code("lib/vinto/p1-28.ts")), false);
  assert.match(read("lib/vinto/quality-history-api.ts"), /\[Q19_FORM_CODE\]: humidityViewer\(parseQualityCapture\), \[Q20_FORM_CODE\]: physicalViewer\(parsePhysicalCapture\)/);
});
