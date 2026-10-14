// node --test scripts/p1-30-p1-07-capture.test.mjs
// DEV-R2 · fichas CANDIDATAS de Rebobinado sobre el contexto de asignación central: VINTO-P1-30 (Producción Perichun) y VINTO-P1-07 (Registro de producción de bobinas refiladas). Contrato frente a form-definitions.ts
// (incluidas las 21 crías 1-11 y 13-22, sin la 12), tipos (peso_de_bobina es TEXTO), horas de inicio / término sin fuente (no se generan), payload de asignación, parser estricto, flujo con reconciliación, oferta
// según el backend, aislamiento por sesión y límites de alcance (Rebobinado no operativo, política y seed intactos, sin genealogía). Lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { REBOBINADO_SECTOR, SECTOR_SCREENS, parseAvailability, rebobinadoView, screenFor } from "../lib/vinto/availability.ts";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { P107, P107_CRIA_NUMBERS, P107_FIELDS, P107_PENDING, P107_SECTIONS, P1_07_CODE } from "../lib/vinto/p1-07.ts";
import { P130, P130_FIELDS, P130_PENDING, P1_30_CODE } from "../lib/vinto/p1-30.ts";
import { candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", ASSIGNMENT = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const defOf = (id) => FORM_DEFINITIONS.find((f) => f.id === id);
const isManual = (f) => f.source === "manual";
const KIND = (f) => (f.type === "decimal" ? "decimal" : f.type === "textarea" ? "textarea" : "text");
const fill = (fields) => Object.fromEntries(fields.map((f) => [f.key, f.kind === "decimal" ? "1,5" : f.key === "observaciones" ? " nota " : "texto 12,5"]));
const CASES = [
  { name: "P1-30", id: "form_30_produccion_perichun", form: P130, formCode: P1_30_CODE, fields: P130_FIELDS, pending: P130_PENDING, counts: [10, 5], machines: ["perichun"], hours: ["hora_inicio", "hora_termino"] },
  { name: "P1-07", id: "form_7_registro_de_productos_rebobinados", form: P107, formCode: P1_07_CODE, fields: P107_FIELDS, pending: P107_PENDING, counts: [36, 5], machines: ["copasa", "beloit", "over"], hours: ["hora_inicio", "hora_final"] },
];
const envelope = (formCode, values) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: formCode, version_number: 1, name: "x" },
  machine: { code: "COPASA", name: "Copasa" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT }, work_order: { id: UUID, number: "OT-1" },
  line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A1", description: "d" } }, values });

test("los contratos son EXACTAMENTE los campos manuales de las definiciones legacy; automáticos no se digitan", () => {
  for (const c of CASES) {
    const legacy = defOf(c.id);
    assert.equal(legacy.area, "production");
    assert.equal(legacy.sector, "rebobinado");
    assert.deepEqual([legacy.fields.filter(isManual).length, legacy.fields.filter((f) => f.source === "automatic").length, legacy.fields.filter((f) => f.source === "calculated").length], [...c.counts, 0], c.name);
    assert.equal(legacy.fields.length, c.counts[0] + c.counts[1]);
    assert.deepEqual(legacy.allowedMachineIds, c.machines, `${c.name}: máquinas legacy`);
    const m = legacy.fields.filter(isManual);
    assert.deepEqual(c.fields.map((f) => f.key), m.map((f) => f.key), `${c.name}: claves y orden`);
    assert.deepEqual(c.fields.map((f) => f.label), m.map((f) => f.label), `${c.name}: etiquetas`);
    assert.deepEqual(c.fields.map((f) => f.required), m.map((f) => f.required ?? f.requirement), `${c.name}: obligatoriedad`);
    assert.deepEqual(c.fields.map((f) => f.kind), m.map(KIND), `${c.name}: tipos`);
    for (const f of legacy.fields.filter((x) => !isManual(x))) assert.equal(c.fields.some((x) => x.key === f.key), false, `${c.name}: ${f.key} no se digita`);
    for (const hour of c.hours) assert.equal(legacy.fields.find((f) => f.key === hour).source, "automatic", `${c.name}: ${hour} es automático en la definición`);
    assert.equal(c.form.context, "assignment");
    // las unidades solo salen de la definición: sufijo == unidad declarada, ninguna inventada
    for (const f of c.fields) assert.equal(f.suffix, m.find((x) => x.key === f.key).unit ?? undefined, `${c.name}: ${f.key}`);
  }
  assert.equal(P130_FIELDS.find((f) => f.key === "peso_de_bobina").kind, "text", "peso_de_bobina es TEXTO");
  assert.equal(P130_FIELDS.find((f) => f.key === "numero_mrp").kind, "text");
});

test("P1-07 tiene EXACTAMENTE 21 crías individuales (1-11 y 13-22) y la cría 12 no existe", () => {
  const legacy = defOf("form_7_registro_de_productos_rebobinados").fields.filter((f) => f.key.startsWith("peso_cria_")).map((f) => f.key);
  const ours = P107_FIELDS.filter((f) => f.key.startsWith("peso_cria_")).map((f) => f.key);
  assert.equal(ours.length, 21);
  assert.deepEqual(ours, legacy);
  assert.deepEqual(ours, [...Array.from({ length: 11 }, (_, i) => `peso_cria_${i + 1}`), ...Array.from({ length: 10 }, (_, i) => `peso_cria_${i + 13}`)]);
  assert.equal(ours.includes("peso_cria_12"), false);
  assert.equal(P107_CRIA_NUMBERS.includes(12), false);
  assert.ok(P107_FIELDS.filter((f) => f.key.startsWith("peso_cria_")).every((f) => f.kind === "decimal" && f.required), "obligatoriedad legacy conservada (la condicionalidad queda pendiente)");
  assert.equal(P107.normalizeDraft({ ...fill(P107_FIELDS), peso_cria_12: "1" }).values.peso_cria_12, undefined, "una cría 12 enviada nunca llega al payload");
});

test("la agrupación visual cubre cada campo exactamente una vez y no cambia la estructura guardada", () => {
  const keys = P107_SECTIONS.flatMap((s) => s.keys);
  assert.deepEqual([...keys].sort(), P107_FIELDS.map((f) => f.key).sort());
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(P107_SECTIONS.some((s) => s.title === "Pesos de crías" && s.keys.length === 21), true);
  assert.deepEqual(Object.keys(P107.emptyDraft()), P107_FIELDS.map((f) => f.key), "el borrador y el payload conservan el orden y las claves del contrato, sin grupos repetibles");
  const capture = code("components/vinto/candidate-form-capture.tsx");
  assert.match(capture, /candidate\.sections/);
  assert.equal(/Repeatable|repeat|_groups/i.test(read("lib/vinto/p1-07.ts").split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n")), false, "no se introducen grupos repetibles");
});

test("las brechas son visibles: horas sin fuente, bobina como texto, sector no operativo, cría 12 y, en P1-07, que NO es genealogía", () => {
  const t30 = P130_PENDING.map((p) => `${p.label} ${p.pending}`).join(" "), t07 = P107_PENDING.map((p) => `${p.label} ${p.pending}`).join(" ");
  assert.match(t30, /Horas de inicio y término[\s\S]*no se generan ni se toman de la hora de registro/);
  assert.match(t30, /no crea ni busca una bobina física/);
  assert.match(t30, /Número MRP/);
  assert.match(t30, /peso de bobina es TEXTO/);
  assert.match(t30, /PERICHUN y los turnos oficiales siguen pendientes/);
  assert.match(t07, /NO equivale a una genealogía funcional/);
  assert.match(t07, /no crea bobinas hijas, no consume bobinas madre, no crea relaciones madre-hija ni correlativos, no calcula balances de masa ni mueve inventario/i);
  assert.match(t07, /NO identifica una bobina madre/);
  assert.match(t07, /no existe la cría 12/);
  assert.match(t07, /cardinalidad y la condicionalidad/);
  assert.match(t07, /Horas de inicio y final[\s\S]*no se generan/);
  assert.match(t07, /COPASA, BELOIT, OVER y los turnos oficiales siguen pendientes/);
  assert.match(read("lib/vinto/p1-07.ts"), /NO UNA GENEALOGÍA \(docs\/M5-A-p107-genealogia\.md\)/);
  assert.match(read("lib/vinto/rebobinado-candidates.ts"), /unresolved: P130_UNRESOLVED_AUTOMATIC/);
  assert.match(read("lib/vinto/rebobinado-candidates.ts"), /unresolved: P107_UNRESOLVED_AUTOMATIC/);
  assert.match(code("components/vinto/candidate-form-capture.tsx"), /Automáticos sin fuente confirmada \(no se generan ni se sustituyen por la hora de envío\)/);
});

test("el borrador valida estructuralmente, deja los textos tal cual y NO genera horas ni calcula totales", () => {
  for (const c of CASES) {
    const check = c.form.normalizeDraft(fill(c.fields));
    assert.equal(check.ok, true, c.name);
    for (const f of c.fields) {
      if (f.kind === "decimal") assert.equal(check.values[f.key], "1.5", `${c.name}: ${f.key}`);
      if (f.kind === "text") assert.equal(check.values[f.key], "texto 12,5", `${c.name}: ${f.key} conserva su coma`);
    }
    for (const key of [...c.hours, "fecha", "turno", "operador", "total", "balance", "merma", "peso_cria_12"]) assert.equal(key in check.values, false, `${c.name}: ${key}`);
    for (const f of c.fields.filter((x) => x.kind === "decimal")) {
      for (const bad of ["abc", "1e3", "12.5.1", "12 kg"]) assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: bad }).errors.join(" "), /debe ser un número decimal/, `${c.name} ${f.key} ${bad}`);
      assert.match(c.form.normalizeDraft({ ...fill(c.fields), [f.key]: " " }).errors.join(" "), /es obligatorio/, f.key);
    }
    assert.equal(c.form.normalizeDraft(c.form.emptyDraft()).errors.length, c.fields.filter((f) => f.required).length);
  }
  assert.equal(P130.normalizeDraft({ ...fill(P130_FIELDS), peso_de_bobina: "850,5 kg" }).values.peso_de_bobina, "850,5 kg", "el peso es texto: no se convierte");
});

test("el payload es de contexto «asignación»: cerrado, sin máquina ni bobina, sin horas, y congelado", () => {
  for (const c of CASES) {
    const { attempt } = c.form.createAttempt(fill(c.fields), ASSIGNMENT, DEVICE, () => UUID);
    assert.deepEqual(Object.keys(attempt.payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"], c.name);
    assert.deepEqual([attempt.payload.form_code, attempt.payload.assignment_id, attempt.captureId], [c.formCode, ASSIGNMENT, UUID]);
    for (const key of ["machine_code", "bobbin_id", "hora_inicio", ...c.hours]) assert.equal(key in attempt.payload || key in attempt.payload.values, false, key);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values));
    assert.equal(c.form.createAttempt(c.form.emptyDraft(), ASSIGNMENT, DEVICE).ok, false);
  }
});

test("el parser exige asignación, OT y línea, su formulario y valores estrictos; ignora lo que no es del contrato", () => {
  for (const c of CASES) {
    const values = c.form.normalizeDraft(fill(c.fields)).values;
    const parsed = c.form.parseCapture(envelope(c.formCode, values));
    assert.deepEqual(parsed?.values, values, c.name);
    assert.equal(parsed?.assignment?.id, ASSIGNMENT);
    for (const other of ["VINTO-P1-10", c.formCode === P1_30_CODE ? P1_07_CODE : P1_30_CODE]) assert.equal(c.form.parseCapture(envelope(other, values)), null, `${c.name}: ${other}`);
    for (const f of c.fields.filter((x) => x.required)) { const m = { ...values }; delete m[f.key]; assert.equal(c.form.parseCapture(envelope(c.formCode, m)), null, `falta ${f.key}`); }
    assert.deepEqual(c.form.parseCapture(envelope(c.formCode, { ...values, hora_inicio: "07:00", total: "9", peso_cria_12: "1" }))?.values, values, "un campo ajeno que llegara se ignora y no se presenta");
    assert.equal(c.form.parseCapture(envelope(c.formCode, { ...values, [c.fields.find((f) => f.kind === "decimal").key]: "abc" })), null);
    assert.equal(c.form.parseList([envelope(c.formCode, values)])?.length, 1);
    assert.equal(c.form.parseList([{ nope: 1 }]), null);
  }
});

const response = (status, data, errCode) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code: errCode });

test("flujo de envío: 201, 200 idempotente, rechazos, asignación obsoleta, sesión y reconciliación con el MISMO capture_id", async () => {
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
  }
});

test("la oferta sale del backend por máquina: las pantallas se registran solo para Rebobinado y P1-10 / P1-29 / otros sectores no cambian", () => {
  assert.deepEqual([screenFor(REBOBINADO_SECTOR, "VINTO-P1-30"), screenFor(REBOBINADO_SECTOR, "VINTO-P1-07")], ["p130", "p107"]);
  assert.deepEqual([screenFor(REBOBINADO_SECTOR, "VINTO-P1-10"), screenFor(REBOBINADO_SECTOR, "VINTO-P1-29")], ["p110", "p129"]);
  for (const sector of ["CONVERSION", "BOBINAS"]) for (const formCode of ["VINTO-P1-30", "VINTO-P1-07"]) assert.equal(screenFor(sector, formCode), null, `${sector}: ${formCode} no tiene pantalla`);
  assert.deepEqual(SECTOR_SCREENS.CONVERSION, { "VINTO-P1-11": "p111", "VINTO-P1-12": "p112", "VINTO-P1-13": "p113", "VINTO-P1-16": "p116" });
  assert.deepEqual(SECTOR_SCREENS.BOBINAS, { "VINTO-P1-04": "p104", "VINTO-P1-05": "p105", "VINTO-P1-31": "p131" });
  // con la configuración real el backend no expone Rebobinado: la vista queda deshabilitada y no se ofrece nada
  assert.deepEqual(rebobinadoView(parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines: [{ code: "MP1", name: "MP1", forms: [] }, { code: "MP3", name: "MP3", forms: [] }] }] })), { kind: "disabled" });
  const published = parseAvailability({ sectors: [{ code: "REBOBINADO", name: "Rebobinado", machines: [{ code: "PERICHUN", name: "Perichun", forms: [{ code: "VINTO-P1-30", name: "x", version_number: 1 }] }, { code: "COPASA", name: "Copasa", forms: [{ code: "VINTO-P1-07", name: "y", version_number: 1 }, { code: "VINTO-P1-99", name: "z", version_number: 1 }] }] }] });
  assert.equal(rebobinadoView(published).kind, "ready");
  const sector = rebobinadoView(published).sector;
  assert.deepEqual(sector.machines.map((m) => m.forms.map((f) => screenFor(REBOBINADO_SECTOR, f.code))), [["p130"], ["p107", null]], "un formulario sin pantalla se informa como tal y no se abre");
  const central = code("components/vinto/sector-central.tsx");
  assert.match(central, /offeredForms\(code, machine\)/); // las tarjetas salen de lo que el backend publica para la máquina elegida
});

test("aislamiento por usuario y formulario: disponibilidad e historiales de otra cuenta nunca se presentan; sin localStorage", () => {
  const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
  const kA = candidateHistoryKey("reb-p130", sessionScope(A), 0);
  assert.equal(new Set([kA, candidateHistoryKey("reb-p130", sessionScope(B), 0), candidateHistoryKey("reb-p107", sessionScope(A), 0), candidateHistoryKey("reb-p130", sessionScope(A), 1)]).size, 4);
  const stored = { key: kA, attempt: 0, result: { ok: true, data: [{ id: "control-de-A" }] } };
  assert.equal(JSON.stringify(deriveView(candidateHistoryKey("reb-p130", sessionScope(B), 0), true, 0, stored)).includes("control-de-A"), false);
  assert.equal(JSON.stringify(deriveView(candidateHistoryKey("reb-p107", sessionScope(A), 0), true, 0, stored)).includes("control-de-A"), false);
  const central = code("components/vinto/sector-central.tsx"), page = read("app/page.tsx");
  assert.match(central, /useAvailability\(canManageOrders && module === "programacion", true, onSessionLost, scope\)/);
  assert.match(central, /candidateHistoryKey\("reb-p130", scope \?\? "", refreshKey\)/);
  assert.match(central, /candidateHistoryKey\("reb-p107", scope \?\? "", refreshKey\)/);
  assert.match(central, /scope !== undefined/);
  assert.match(page, /<RebobinadoCentral [^>]*refreshKey=\{rebRefresh\} scope=\{scope\}/);
  assert.match(page, /<ConversionCentral|ConversionCentral/);
  assert.equal((page.match(/setRebCandAttempts\(\{\}\);/g) ?? []).length, 2, "la sesión perdida y el cierre de sesión descartan los intentos pendientes");
  for (const file of ["lib/vinto/p1-30.ts", "lib/vinto/p1-07.ts", "lib/vinto/rebobinado-candidates.ts", "components/vinto/sector-central.tsx", "components/vinto/candidate-form-capture.tsx"]) assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(code(file)), false, file);
});

test("la pantalla reutiliza el motor: la ficha se abre con SU contexto y el intento pendiente conserva el original; sin pantallas ni endpoints nuevos", () => {
  const page = read("app/page.tsx");
  assert.match(page, /if \(rebCapture && front === "Rebobinado" && isRebobinadoCandidate\(rebCapture\.screen\)\)/);
  assert.match(page, /context=\{pending \? pending\.context : rebCapture\.context\}/);
  assert.match(page, /candidate=\{REBOBINADO_CANDIDATES\[screen\]\}/);
  assert.equal(readdirSync(join(root, "components/vinto")).some((f) => /p1-30|p1-07/.test(f)), false, "no hay componentes de pantalla propios");
  assert.equal(/requestJson|\/api\//.test(code("lib/vinto/p1-30.ts") + code("lib/vinto/p1-07.ts")), false);
  assert.match(code("lib/vinto/rebobinado-candidates.ts"), /candidateApi\(P130\)/);
  assert.match(code("lib/vinto/rebobinado-candidates.ts"), /candidateApi\(P107\)/);
  assert.match(code("components/vinto/candidate-form-capture.tsx"), /Ficha NO homologada/);
});

test("alcance: Rebobinado sigue NO operativo, política y seed intactos, sin migraciones nuevas y P1-07 no toca genealogía, bobinas ni calidad", () => {
  const sectors = read("backend/app/sectors.py"), capture = read("backend/app/capture_service.py"), manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"]);
  assert.equal(JSON.stringify(manifest).includes("PERICHUN") || JSON.stringify(manifest).includes("COPASA"), false, "el seed aprobado no contiene máquinas de Rebobinado");
  assert.equal(readdirSync(join(root, "backend/migrations")).filter((f) => f.endsWith(".sql")).length, 6);
  for (const file of ["lib/vinto/p1-30.ts", "lib/vinto/p1-07.ts", "lib/vinto/rebobinado-candidates.ts"]) assert.equal(/quality_release|bobbins?-api|\/api\/bobbins|from "[^"]*(bobbin|genealog)[^"]*"/i.test(code(file)), false, file);
  assert.match(read("docs/DEV-R2-rebobinado-candidatos.md"), /NO equivale a una genealogía funcional/);
  assert.match(read("docs/DEV-R2-rebobinado-candidatos.md"), /peso_cria_12/);
});
