// node --test scripts/p1-22-p1-26-capture.test.mjs
// DEV-Q1 · controles de Calidad POR MÁQUINA CANDIDATOS: VINTO-P1-22 (Grado de refinación Schopper) y VINTO-P1-26 (Medición de secos), sin bobina, asignación ni OT. Contrato frente a form-definitions.ts,
// decimales, campos automáticos y calculados ausentes (porcentaje_de_secos nunca se calcula), payload y parser de máquina, flujo con reconciliación, oferta según el backend, aislamiento por usuario y límites
// de alcance (política vacía en el backend, migraciones, seed_data y controles por bobina intactos). Lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { parseAvailability } from "../lib/vinto/availability.ts";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { P122, P122_FIELDS, P122_PENDING, P1_22_CODE } from "../lib/vinto/p1-22.ts";
import { P126, P126_CALCULATED, P126_FIELDS, P126_PENDING, P1_26_CODE } from "../lib/vinto/p1-26.ts";
import { publishedQualityScreens, qualityMachines, qualityScreensFor, QUALITY_CANDIDATE_SCREENS } from "../lib/vinto/quality-offers.ts";
import { availabilityKey, candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
const pyCode = (file) => read(file).replace(/^"""[\s\S]*?"""/, "").split("\n").filter((l) => !/^\s*#/.test(l)).join("\n"); // sin docstrings ni comentarios
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d", USER = "5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f";
const D122 = { numero_de_cuba: " C-1 ", masa_humeda: "20,5", volumen_desplazado: "630", grado_de_refinacion_sr: " 28,5 ", amperaje: "45.25", observacion: "" };
const D126 = { punto_de_muestreo: "punto", masa_humeda: "100,50", masa_seca: "3.25", observaciones: " nota " };
const CASES = [["P1-22", P122, P1_22_CODE, D122, P122_FIELDS], ["P1-26", P126, P1_26_CODE, D126, P126_FIELDS]];
const defOf = (id) => FORM_DEFINITIONS.find((f) => f.id === id);
const isManual = (f) => f.source === "manual";

const machineEnvelope = (formCode, values, extra = {}) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", recorded_by: { id: USER, display_name: "Calidad" }, values, ...extra });

test("los contratos son EXACTAMENTE los campos manuales de las definiciones legacy; los automáticos y el calculado no se digitan", () => {
  for (const [id, fields, manual, automatic, calculated] of [["form_22_grado_de_refinacion_schopper", P122_FIELDS, 6, 4, 0], ["form_26_medicion_de_secos", P126_FIELDS, 4, 4, 1]]) {
    const legacy = defOf(id);
    assert.equal(legacy.area, "quality");
    assert.deepEqual([legacy.fields.filter(isManual).length, legacy.fields.filter((f) => f.source === "automatic").length, legacy.fields.filter((f) => f.source === "calculated").length], [manual, automatic, calculated], id);
    assert.equal(legacy.fields.length, manual + automatic + calculated);
    const m = legacy.fields.filter(isManual);
    assert.deepEqual(fields.map((f) => f.key), m.map((f) => f.key), `${id}: claves y orden`);
    assert.deepEqual(fields.map((f) => f.label), m.map((f) => f.label), `${id}: etiquetas`);
    assert.deepEqual(fields.map((f) => f.required), m.map((f) => f.required ?? f.requirement), `${id}: obligatoriedad`);
    assert.deepEqual(fields.map((f) => f.kind), m.map((f) => (f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : "text")), `${id}: tipos`);
    for (const f of legacy.fields.filter((x) => !isManual(x))) assert.equal(fields.some((x) => x.key === f.key), false, `${id}: ${f.key} no se digita`);
  }
  assert.deepEqual(P122_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key), ["masa_humeda", "volumen_desplazado", "grado_de_refinacion_sr", "amperaje"]);
  assert.deepEqual(P126_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key), ["masa_humeda", "masa_seca"]);
  assert.equal(defOf("form_22_grado_de_refinacion_schopper").fields.find((f) => f.key === "amperaje").unit, "A"); // única unidad declarada: se conserva como sufijo, no se añade ninguna
  assert.equal(P122_FIELDS.find((f) => f.key === "amperaje").suffix, "A");
  assert.equal(P122_FIELDS.filter((f) => f.suffix).length + P126_FIELDS.filter((f) => f.suffix).length, 1, "ninguna otra unidad inventada");
  assert.deepEqual(defOf("form_26_medicion_de_secos").allowedMachineIds, ["por_definir"]); // brecha de alcance de máquinas documentada abajo
  assert.deepEqual([...P126_CALCULATED], ["Porcentaje de secos"]);
});

test("las brechas se documentan: hora de registro frente a hora del ensayo, porcentaje de secos sin fórmula y alcance de máquinas de P1-26", () => {
  const t122 = P122_PENDING.map((p) => `${p.label} ${p.pending}`).join(" "), t126 = P126_PENDING.map((p) => `${p.label} ${p.pending}`).join(" ");
  assert.match(t122, /Hora del ensayo/);
  assert.match(t122, /es la de registro \(servidor\): no es la hora real de la prueba/);
  assert.match(t122, /no libera ni rechaza ninguna bobina/);
  assert.match(t126, /Porcentaje de secos/);
  assert.match(t126, /no se calcula, no se guarda ni se muestra/);
  assert.match(t126, /por definir/);
  assert.match(read("lib/vinto/p1-26.ts"), /NO se calcula `porcentaje_de_secos`/);
  assert.match(read("components/vinto/candidate-form-capture.tsx"), /candidate\.calculated/);
});

test("el borrador valida los decimales estructuralmente y NO calcula porcentajes ni genera horas", () => {
  const a = P122.normalizeDraft(D122), b = P126.normalizeDraft(D126);
  assert.deepEqual(a.values, { numero_de_cuba: "C-1", masa_humeda: "20.5", volumen_desplazado: "630", grado_de_refinacion_sr: "28.5", amperaje: "45.25" });
  assert.deepEqual(b.values, { punto_de_muestreo: "punto", masa_humeda: "100.50", masa_seca: "3.25", observaciones: "nota" });
  for (const key of ["porcentaje_de_secos", "hora", "fecha", "maquina", "responsable", "total"]) assert.equal(key in a.values || key in b.values, false, key);
  assert.equal(b.values.masa_seca, "3.25"); // las masas se guardan tal cual: nada derivado de ellas
  for (const [, form, , draft, fields] of CASES) for (const key of fields.filter((f) => f.kind === "decimal").map((f) => f.key)) {
    for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(form.normalizeDraft({ ...draft, [key]: bad }).errors.join(" "), /debe ser un número decimal/, `${key} ${bad}`);
    assert.match(form.normalizeDraft({ ...draft, [key]: " " }).errors.join(" "), /es obligatorio/, key);
    assert.equal(form.normalizeDraft({ ...draft, [key]: "-1,5" }).values[key], "-1.5", "sin rangos inventados");
  }
  assert.equal(P122.normalizeDraft(P122.emptyDraft()).errors.length, 5);
  assert.equal(P126.normalizeDraft(P126.emptyDraft()).errors.length, 3);
});

test("el payload es de contexto «máquina»: sin assignment_id ni bobina, cerrado y congelado; el backend recibe la máquina por la ruta", () => {
  for (const [name, form, formCode, draft] of CASES) {
    assert.equal(form.context, "machine", name);
    const { attempt } = form.createAttempt(draft, "MP3", DEVICE, () => UUID);
    assert.deepEqual(Object.keys(attempt.payload).sort(), ["capture_id", "device_key", "form_code", "machine_code", "values"], name);
    assert.deepEqual([attempt.payload.form_code, attempt.payload.machine_code, attempt.payload.device_key, attempt.captureId], [formCode, "MP3", DEVICE, UUID]);
    for (const key of ["assignment_id", "bobbin_id", "work_order_id"]) assert.equal(key in attempt.payload, false, `${name}: ${key}`);
    for (const key of ["fecha", "hora", "maquina", "responsable", "porcentaje_de_secos"]) assert.equal(key in attempt.payload.values, false, `${name}: ${key}`);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values));
    assert.equal(form.createAttempt(form.emptyDraft(), "MP1", DEVICE).ok, false);
  }
});

test("el parser de máquina acepta la respuesta sin asignación ni OT, exige el formulario esperado y valores estrictos, e ignora lo calculado", () => {
  for (const [name, form, formCode, draft] of CASES) {
    const values = form.normalizeDraft(draft).values;
    const parsed = form.parseCapture(machineEnvelope(formCode, values));
    assert.deepEqual(parsed?.values, values, name);
    assert.deepEqual(parsed?.recorded_by, { id: USER, display_name: "Calidad" });
    assert.equal(parsed?.assignment, undefined);
    assert.equal(form.parseCapture(machineEnvelope("VINTO-P1-99", values)), null, `${name}: otro formulario`);
    assert.equal(form.parseCapture(machineEnvelope(formCode, values, { recorded_by: { id: 5 } })), null);
    assert.ok(form.parseCapture(machineEnvelope(formCode, values, { recorded_by: null })), `${name}: recorded_by puede ser nulo`);
    for (const field of form.fields.filter((f) => f.required)) { const m = { ...values }; delete m[field.key]; assert.equal(form.parseCapture(machineEnvelope(formCode, m)), null, `${name}: falta ${field.key}`); }
    assert.equal(form.parseCapture(machineEnvelope(formCode, { ...values, masa_humeda: "12,5" })), null, `${name}: decimal inválido`);
    assert.deepEqual(form.parseCapture(machineEnvelope(formCode, { ...values, porcentaje_de_secos: "9" }))?.values, values, `${name}: un calculado que llegara se ignora y nunca se presenta`);
    assert.equal(form.parseCapture(null), null);
    assert.equal(form.parseSubmission({ created: true, already_submitted: false, capture: machineEnvelope(formCode, values) })?.created, true);
    assert.equal(form.parseList([machineEnvelope(formCode, values)])?.length, 1);
    assert.equal(form.parseList([{ nope: 1 }]), null);
  }
});

const response = (status, data, errCode) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code: errCode });

test("flujo de envío: 201, 200 idempotente, rechazos definitivos, sesión y reconciliación con el MISMO capture_id", async () => {
  for (const [name, form, formCode, draft] of CASES) {
    const created = form.createAttempt(draft, "MP1", DEVICE, () => UUID).attempt;
    const capture = form.parseCapture(machineEnvelope(formCode, form.normalizeDraft(draft).values));
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
    assert.equal(JSON.parse(seen[0]).machine_code, "MP1");
  }
});

test("los controles se ofrecen solo si el backend los publica para la máquina; con la política real no se ofrece nada", () => {
  const form = (c) => ({ code: c, name: c, version_number: 1 });
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  assert.deepEqual([...QUALITY_CANDIDATE_SCREENS], ["p118", "p122", "p126", "p127"]); // p118 (DEV-Q2) y p127 (DEV-CLOSE) se añadieron después
  const real = avail([{ code: "MP1", name: "MP1", forms: [] }, { code: "MP3", name: "MP3", forms: [] }]);
  assert.deepEqual([qualityMachines(real), qualityScreensFor(real, "MP1"), publishedQualityScreens(real)], [[], [], []], "configuración real: el backend no publica ningún control por máquina");
  const published = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-22"), form("VINTO-P1-26")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-22")] }]);
  assert.deepEqual(qualityMachines(published).map((m) => m.code), ["MP1", "MP3"]);
  assert.deepEqual([qualityScreensFor(published, "MP1"), qualityScreensFor(published, "MP3"), qualityScreensFor(published, "MP9")], [["p122", "p126"], ["p122"], []]);
  assert.deepEqual(publishedQualityScreens(published), ["p122", "p126"]);
  assert.deepEqual(qualityScreensFor(avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-19"), form("VINTO-P1-20"), form("VINTO-P1-06")] }]), "MP1"), [], "otros formularios no son controles por máquina");
});

test("aislamiento por usuario: disponibilidad e historial por máquina de la cuenta anterior nunca se presentan a otra", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  const kA = candidateHistoryKey("p122-MP1", sessionScope(A), 0), kB = candidateHistoryKey("p122-MP1", sessionScope(B), 0);
  assert.notEqual(kA, kB);
  assert.notEqual(candidateHistoryKey("p122-MP1", sessionScope(A), 0), candidateHistoryKey("p122-MP3", sessionScope(A), 0));
  const stored = { key: kA, attempt: 0, result: { ok: true, data: [{ id: "control-de-A" }] } };
  assert.equal(deriveView(kA, true, 0, stored).status, "ready");
  const viewB = deriveView(kB, true, 0, stored);
  assert.equal(viewB.status, "loading");
  assert.equal(JSON.stringify(viewB).includes("control-de-A"), false);
  assert.equal(deriveView(kB, false, 0, stored).status, "idle");
  const component = code("components/vinto/quality-machine-controls.tsx");
  assert.match(component, /`quality-machine-forms:\$\{scope\}`/);
  assert.match(component, /candidateHistoryKey\(`p122-\$\{code\}`, scope, refreshKey\)/);
  assert.match(component, /candidateHistoryKey\(`p126-\$\{code\}`, scope, refreshKey\)/);
  assert.match(read("app/page.tsx"), /<QualityMachineControls scope=\{scope\} canCapture=\{canReadQualityInbox\} mode="execution"/);
  assert.notEqual(availabilityKey(false, sessionScope(A)), availabilityKey(false, sessionScope(B)));
});

test("el cliente HTTP usa las rutas de Calidad por máquina (máquina en la ruta, sin assignment_id) y nunca almacenamiento local", () => {
  const api = code("lib/vinto/candidate-form-api.ts");
  assert.match(api, /const \{ machine_code: machine, \.\.\.body \} = payload;/);
  assert.match(api, /`\/api\/quality\/machines\/\$\{encodeURIComponent\(machine \?\? ""\)\}\/captures`, \{ method: "POST", body,/);
  assert.match(api, /`\/api\/quality\/machine-captures\/\$\{encodeURIComponent\(captureId\)\}`/);
  assert.match(api, /\/api\/quality\/machines\/\$\{encodeURIComponent\(machineCode\)\}\/captures\?form_code=\$\{encodeURIComponent\(form\.code\)\}&limit=\$\{limit\}/);
  assert.match(api, /requestJson\("\/api\/quality\/machine-forms"/);
  assert.equal(/\/api\/captures`|"\/api\/captures"/.test(api.split("export const machineCandidateApi")[1]), false, "no reutiliza el endpoint de Producción");
  for (const file of ["lib/vinto/p1-22.ts", "lib/vinto/p1-26.ts", "lib/vinto/quality-offers.ts", "lib/vinto/quality-candidates.ts", "lib/vinto/candidate-form-api.ts", "components/vinto/quality-machine-controls.tsx"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(code(file)), false, file);
});

test("alcance: política de Calidad por máquina vacía, producción y seed_data intactos, sin migraciones nuevas y controles por bobina sin tocar", () => {
  const service = read("backend/app/quality/machine_capture_service.py"), capture = read("backend/app/capture_service.py"), sectors = read("backend/app/sectors.py"), manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(service, /^MACHINE_QUALITY_FORM_CODES: frozenset = frozenset\(\)$/m);
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.deepEqual(readdirSync(join(root, "backend/migrations")).filter((f) => f.endsWith(".sql")), ["0001_initial_schema.sql", "0002_auth.sql", "0003_capture_revision_semantics.sql", "0004_bobbin_production.sql", "0005_quality_capture_bobbin.sql", "0006_user_sector_grants.sql"]);
  // el servicio por máquina nunca toca bobinas, liberaciones ni asignaciones y no reutiliza el endpoint de Producción
  const body = pyCode("backend/app/quality/machine_capture_service.py");
  assert.equal(/quality_release|INSERT INTO vinto_txn\.(bobbin|assignment|work_order)|submit_production_capture/.test(body), false);
  assert.match(body, /bobbin_id IS NULL AND c\.assignment_id IS NULL/);
  // los controles por bobina P1-19 / P1-20 no importan ni conocen el servicio nuevo
  assert.equal(/machine_capture|MACHINE_QUALITY/.test(read("backend/app/quality/capture_service.py") + read("backend/app/quality/router.py") + read("backend/app/quality/service.py")), false);
  const page = read("app/page.tsx");
  assert.match(page, /if \(qualCapture && front === "Calidad"\)/);
  assert.match(page, /machine=\{pending \? pending\.machine : qualCapture\.machine\}/);
  assert.equal(/localStorage\.(removeItem|clear)/.test(page), false);
  assert.match(page, /function Fiber\(/); // los formularios legacy y sus registros no se tocan
  assert.match(page, /setQualCapture\(null\); setQualAttempts\(\{\}\)/); // la sesión perdida descarta los intentos
});
