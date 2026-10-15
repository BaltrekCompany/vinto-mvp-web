// node --test scripts/p1-05-p1-31-capture.test.mjs
// DEV-B1 · captura CENTRAL CANDIDATA de VINTO-P1-05 (Registro de tubetes) y VINTO-P1-31 (Consumo de químicos): contrato, parser estricto, borrador, payload, intento pendiente, flujo de envío con
// reconciliación, oferta de las pantallas según la disponibilidad que publica el backend y límites de alcance (política real, seed_data y almacenamiento local). Es lógica PURA: no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { FORM_DEFINITIONS } from "../lib/vinto/form-definitions.ts";
import { parseAvailability, screenFor, offeredForms } from "../lib/vinto/availability.ts";
import { candidateScreensFor, publishedCandidateScreens } from "../lib/vinto/bobinas-offers.ts";
import { defineCandidateForm, MAX_TEXT_LENGTH } from "../lib/vinto/candidate-form.ts";
import { P105, P105_FIELDS, P1_05_CODE } from "../lib/vinto/p1-05.ts";
import { P131, P131_FIELDS, P1_31_CODE } from "../lib/vinto/p1-31.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const UUID = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", ASSIGNMENT = "7a1d9c0e-2b3f-4a5c-9d6e-8f7a6b5c4d3e", DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const P105_DRAFT = { numero_de_bobina: " B-1 ", numero_codigo_de_tubete: "TUB-9", tipo_de_tubete: "tipo", cantidad_utilizada: "12 (texto)", cantidad_recuperada: "2", cantidad_devuelta: "0", estado_del_tubete: "estado", procedencia: "proc", destino: "dest", observaciones: " nota " };
const P131_DRAFT = { codigo_de_insumo: "INS-1", seccion: "sec", insumo_quimico: "quim", caudal_mp1_ml_min: " 125,5 ", caudal_mp3_ml_min: "98", consumo_dia_mp1_kg: "15,5 (texto)", consumo_dia_mp3_kg: "12", consumo_total_kg: "no es la suma", observaciones: "" };
const CASES = [["P1-05", P105, P1_05_CODE, P105_DRAFT], ["P1-31", P131, P1_31_CODE, P131_DRAFT]];

const envelope = (code, values) => ({ id: UUID, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code, version_number: 1, name: "x" }, machine: { code: "MP1", name: "MP1" },
  shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", assignment: { id: ASSIGNMENT }, work_order: { id: UUID, number: "OT-2026-0001" }, line: { id: UUID, line_code: "L1", pv_reference: "PV-1", article: { code: "A", description: "d" } }, values });

test("los contratos candidatos son EXACTAMENTE los campos manuales de las definiciones legacy (no se inventan ni se omiten campos)", () => {
  for (const [id, fields, manual, automatic] of [["form_5_registro_de_tubetes", P105_FIELDS, 10, 4], ["form_31_consumo_de_quimicos", P131_FIELDS, 9, 3]]) {
    const legacy = FORM_DEFINITIONS.find((f) => f.id === id);
    assert.equal(legacy.fields.length, manual + automatic, id);
    const legacyManual = legacy.fields.filter((f) => f.origin === "manual" || f.source === "manual");
    assert.equal(legacyManual.length, manual, id);
    assert.deepEqual(fields.map((f) => f.key), legacyManual.map((f) => f.key), `${id}: mismas claves y orden`);
    assert.deepEqual(fields.map((f) => f.label.split(" ").slice(0, 2).join(" ")), legacyManual.map((f) => f.label.split(" ").slice(0, 2).join(" ")), `${id}: mismas etiquetas (salvo la unidad)`);
    assert.deepEqual(fields.map((f) => f.required), legacyManual.map((f) => f.required ?? f.requirement), `${id}: misma obligatoriedad`);
    // tipos: el legacy declara decimal solo para los caudales de P1-31; todo lo demás es texto
    for (const f of fields) { const l = legacyManual.find((x) => x.key === f.key); assert.equal(f.kind === "decimal", l.type === "decimal", `${id}.${f.key}`); assert.equal(f.kind === "textarea", l.type === "textarea", `${id}.${f.key}`); }
    for (const a of legacy.fields.filter((f) => !(f.origin === "manual" || f.source === "manual"))) assert.equal(fields.some((f) => f.key === a.key), false, `${id}: ${a.key} es automático y no se digita`);
  }
  assert.equal(P131_FIELDS.filter((f) => f.kind === "decimal").map((f) => f.key).join(), "caudal_mp1_ml_min,caudal_mp3_ml_min");
});

test("la definición declarativa rechaza claves duplicadas y la reservada de grupos", () => {
  assert.throws(() => defineCandidateForm("X", [{ key: "a", label: "A", kind: "text", required: true }, { key: "a", label: "A", kind: "text", required: true }]));
  assert.throws(() => defineCandidateForm("X", [{ key: "_groups", label: "G", kind: "text", required: true }]));
});

test("parser estricto: obligatorios presentes y no vacíos, decimales con formato decimal, opcionales ausentes o texto; el código del formulario se exige", () => {
  for (const [name, form, code] of CASES) {
    const good = form.normalizeDraft(CASES.find((c) => c[0] === name)[3]);
    assert.equal(good.ok, true, name);
    assert.deepEqual(form.parseCapture(envelope(code, good.values))?.values, good.values, name);
    assert.equal(form.parseCapture(envelope("VINTO-P1-99", good.values)), null, `${name}: código distinto`);
    for (const f of form.fields.filter((x) => x.required)) {
      const missing = { ...good.values }; delete missing[f.key];
      assert.equal(form.parseCapture(envelope(code, missing)), null, `${name}: falta ${f.key}`);
      assert.equal(form.parseCapture(envelope(code, { ...good.values, [f.key]: "" })), null, `${name}: ${f.key} vacío`);
      assert.equal(form.parseCapture(envelope(code, { ...good.values, [f.key]: 5 })), null, `${name}: ${f.key} no es texto`);
    }
    const noNotes = { ...good.values }; delete noNotes.observaciones;
    assert.ok(form.parseCapture(envelope(code, noNotes)), `${name}: observaciones es opcional`);
    assert.deepEqual(form.parseCapture(envelope(code, { ...good.values, extra: "x" }))?.values, good.values, `${name}: lo desconocido se ignora`);
    assert.equal(form.parseCapture(null), null);
  }
  const v = P131.normalizeDraft(P131_DRAFT).values;
  for (const bad of ["12,5", "abc", "1e3", " 1", "-"]) assert.equal(P131.parseCapture(envelope(P1_31_CODE, { ...v, caudal_mp3_ml_min: bad })), null, `decimal inválido ${bad}`);
  assert.ok(P131.parseCapture(envelope(P1_31_CODE, { ...v, caudal_mp3_ml_min: "-3.50" })), "un decimal con signo y escala se conserva como texto");
  const submission = P105.parseSubmission({ created: true, already_submitted: false, capture: envelope(P1_05_CODE, P105.normalizeDraft(P105_DRAFT).values) });
  assert.equal(submission?.created, true);
  assert.equal(P105.parseSubmission({ created: true, already_submitted: false, capture: envelope(P1_31_CODE, {}) }), null);
  assert.equal(P105.parseList([envelope(P1_05_CODE, P105.normalizeDraft(P105_DRAFT).values)])?.length, 1);
  assert.equal(P105.parseList([{ nope: 1 }]), null);
});

test("el borrador se valida estructuralmente: recorta el texto, solo normaliza la coma decimal de los caudales y NO calcula ni convierte nada", () => {
  const a = P105.normalizeDraft(P105_DRAFT);
  assert.deepEqual(a.values, { numero_de_bobina: "B-1", numero_codigo_de_tubete: "TUB-9", tipo_de_tubete: "tipo", cantidad_utilizada: "12 (texto)", cantidad_recuperada: "2", cantidad_devuelta: "0", estado_del_tubete: "estado", procedencia: "proc", destino: "dest", observaciones: "nota" });
  const b = P131.normalizeDraft(P131_DRAFT);
  assert.equal(b.values.caudal_mp1_ml_min, "125.5"); // única normalización: coma -> punto en un decimal
  assert.equal(b.values.consumo_dia_mp1_kg, "15,5 (texto)"); // los consumos son texto: se conservan tal cual (con su coma)
  assert.equal(b.values.consumo_total_kg, "no es la suma"); // ningún total ni consumo se calcula desde los caudales
  assert.equal("observaciones" in b.values, false, "la observación vacía no se envía");
  assert.deepEqual(Object.keys(b.values).sort(), P131_FIELDS.map((f) => f.key).filter((k) => k !== "observaciones").sort());
  for (const [, form] of CASES.map((c) => [c[0], c[1]])) {
    const empty = form.normalizeDraft(form.emptyDraft());
    assert.equal(empty.ok, false);
    assert.equal(empty.errors.length, form.fields.filter((f) => f.required).length);
    assert.ok(empty.errors.every((e) => e.endsWith("es obligatorio.")));
    assert.equal(form.normalizeDraft({ ...form.emptyDraft(), ...Object.fromEntries(form.fields.filter((f) => f.required).map((f) => [f.key, "   "])) }).ok, false, "solo espacios = vacío");
  }
  assert.equal(P131.normalizeDraft({ ...P131_DRAFT, caudal_mp1_ml_min: "abc" }).ok, false);
  assert.match(P131.normalizeDraft({ ...P131_DRAFT, caudal_mp1_ml_min: "1e3" }).errors[0], /Caudal MP1: debe ser un número decimal/);
  assert.match(P105.normalizeDraft({ ...P105_DRAFT, destino: "x".repeat(MAX_TEXT_LENGTH + 1) }).errors[0], /Destino: supera 10000 caracteres/);
  assert.equal(P105.normalizeDraft({ ...P105_DRAFT, destino: "x".repeat(MAX_TEXT_LENGTH) }).ok, true);
});

test("el intento pendiente congela payload y borrador; el payload es cerrado y solo lleva los valores manuales", () => {
  for (const [name, form, code, draft] of CASES) {
    const created = form.createAttempt(draft, ASSIGNMENT, DEVICE, () => UUID);
    assert.equal(created.ok, true, name);
    const { attempt } = created;
    assert.equal(attempt.captureId, UUID);
    assert.deepEqual(Object.keys(attempt.payload).sort(), ["assignment_id", "capture_id", "device_key", "form_code", "values"]);
    assert.deepEqual([attempt.payload.form_code, attempt.payload.assignment_id, attempt.payload.device_key], [code, ASSIGNMENT, DEVICE]);
    for (const automatic of ["fecha", "turno", "maquina", "responsable", "responsable_mp1", "responsable_mp3", "operating_date", "shift_code", "machine_code"]) assert.equal(automatic in attempt.payload.values || automatic in attempt.payload, false, `${name}: ${automatic}`);
    assert.ok(Object.isFrozen(attempt) && Object.isFrozen(attempt.payload) && Object.isFrozen(attempt.payload.values) && Object.isFrozen(attempt.draft));
    draft.observaciones = "cambiado después"; // modificar el borrador de la pantalla no altera un intento pendiente
    assert.notEqual(attempt.draft.observaciones, "cambiado después");
    assert.equal(form.createAttempt(form.emptyDraft(), ASSIGNMENT, DEVICE).ok, false);
  }
  const first = P105.createAttempt(P105_DRAFT, ASSIGNMENT, DEVICE), second = P105.createAttempt(P105_DRAFT, ASSIGNMENT, DEVICE);
  assert.notEqual(first.attempt.captureId, second.attempt.captureId, "cada envío nuevo genera su propio capture_id");
});

const response = (status, data, code) => (status >= 200 && status < 300 ? { ok: true, status, data } : { ok: false, kind: "http", status, code });

test("flujo de envío: 201, 200 idempotente, rechazos definitivos, sesión perdida y reconciliación ante una respuesta incierta con el MISMO capture_id", async () => {
  for (const [name, form, code, draft] of CASES) {
    const values = form.normalizeDraft(draft).values;
    const created = form.createAttempt(draft, ASSIGNMENT, DEVICE, () => UUID).attempt;
    const capture = form.parseCapture(envelope(code, values));
    const ok = (created_, already) => response(created_ ? 201 : 200, { created: created_, already_submitted: already, capture });
    const submitted = await form.submitAttempt(created, { post: async () => ok(true, false), get: async () => assert.fail("no se consulta") });
    assert.deepEqual([submitted.kind, submitted.created, submitted.alreadySubmitted, submitted.reconciled], ["submitted", true, false, false], name);
    const again = await form.submitAttempt(created, { post: async () => ok(false, true), get: async () => assert.fail() });
    assert.deepEqual([again.kind, again.created, again.alreadySubmitted], ["submitted", false, true], name);
    const calls = [];
    for (const [status, errCode, reason] of [[409, "ASSIGNMENT_STALE", "stale"], [409, "ASSIGNMENT_NOT_ACTIVE", "not_active"], [409, "CAPTURE_IDEMPOTENCY_CONFLICT", "idempotency"], [403, undefined, "forbidden"], [404, undefined, "not_found"], [422, "CAPTURE_VALIDATION", "invalid"]]) {
      const out = await form.submitAttempt(created, { post: async (p) => { calls.push(p.capture_id); return response(status, null, errCode); }, get: async () => assert.fail("un rechazo definitivo no reconcilia") });
      assert.deepEqual([out.kind, out.reason], ["rejected", reason], `${name} ${status}`);
    }
    assert.equal((await form.submitAttempt(created, { post: async () => response(401), get: async () => assert.fail() })).kind, "session");
    // respuesta incierta: se consulta por id; 200 -> éxito reconciliado; 404 -> no se guardó (reintento con el mismo id); otro -> incierto
    const lost = { ok: false, kind: "network", status: 0 };
    const reconciled = await form.submitAttempt(created, { post: async () => lost, get: async (id) => { assert.equal(id, UUID); return response(200, capture); } });
    assert.deepEqual([reconciled.kind, reconciled.reconciled], ["submitted", true], name);
    assert.equal((await form.submitAttempt(created, { post: async () => lost, get: async () => response(404, null) })).kind, "not_saved", name);
    assert.equal((await form.submitAttempt(created, { post: async () => lost, get: async () => ({ ok: false, kind: "network", status: 0 }) })).kind, "uncertain", name);
    assert.equal((await form.submitAttempt(created, { post: async () => response(500), get: async () => response(200, capture) })).kind, "submitted", `${name}: un 5xx reconcilia`);
    // el reintento reutiliza exactamente el mismo payload (mismo capture_id, mismos valores)
    const seen = [];
    for (let i = 0; i < 3; i++) await form.submitAttempt(created, { post: async (p) => { seen.push(JSON.stringify(p)); return lost; }, get: async () => response(404, null) });
    assert.equal(new Set(seen).size, 1, `${name}: mismo payload en cada reintento`);
    assert.equal(JSON.parse(seen[0]).capture_id, UUID);
    assert.deepEqual(calls.every((id) => id === UUID), true);
  }
});

test("las pantallas solo se ofrecen si el backend publica el formulario para la máquina; sin disponibilidad o con la política real no se ofrece nada", () => {
  const avail = (machines) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines }] });
  const form = (code) => ({ code, name: code, version_number: 1 });
  const real = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-06")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-06")] }]);
  assert.deepEqual(candidateScreensFor(real, "MP1"), [], "configuración real: solo F6, ninguna ficha candidata");
  assert.deepEqual(publishedCandidateScreens(real), []);
  const both = avail([{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-05"), form("VINTO-P1-06"), form("VINTO-P1-31")] }, { code: "MP3", name: "MP3", forms: [form("VINTO-P1-06"), form("VINTO-P1-31")] }]);
  assert.deepEqual(candidateScreensFor(both, "MP1"), ["p105", "p131"]);
  assert.deepEqual(candidateScreensFor(both, "MP3"), ["p131"]);
  assert.deepEqual(candidateScreensFor(both, "MP9"), [], "máquina desconocida");
  assert.deepEqual(publishedCandidateScreens(both), ["p105", "p131"]);
  const machine = both.sectors[0].machines[0];
  assert.deepEqual(offeredForms("BOBINAS", machine).map((o) => [o.form.code, o.screen]), [["VINTO-P1-05", "p105"], ["VINTO-P1-06", null], ["VINTO-P1-31", "p131"]]); // F6 no usa estas pantallas
  assert.equal(screenFor("BOBINAS", "VINTO-P1-05"), "p105");
  assert.equal(screenFor("BOBINAS", "VINTO-P1-31"), "p131");
  assert.equal(screenFor("REBOBINADO", "VINTO-P1-05"), null, "las pantallas son solo de Bobinas");
  assert.equal(screenFor("CONVERSION", "VINTO-P1-31"), null);
  // un sector distinto que publique estos códigos no los habilita en Bobinas
  const other = parseAvailability({ sectors: [{ code: "REBOBINADO", name: "R", machines: [{ code: "MP1", name: "MP1", forms: [form("VINTO-P1-05")] }] }] });
  assert.deepEqual(candidateScreensFor(other, "MP1"), []);
});

test("alcance: la política real y los datos de referencia no incluyen P1-05 ni P1-31; las pantallas no usan almacenamiento local", () => {
  const capture = read("backend/app/capture_service.py"), sectors = read("backend/app/sectors.py");
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
  assert.match(capture, /^FORM_CODE = "VINTO-P1-06"/m);
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  const manifest = JSON.parse(read("backend/seed_data/manifest.json"));
  assert.deepEqual(manifest.scope.forms, ["VINTO-P1-06", "VINTO-P1-03", "VINTO-P1-19", "VINTO-P1-20"], "seed_data no incorpora contratos no homologados");
  for (const file of ["lib/vinto/candidate-form.ts", "lib/vinto/candidate-form-api.ts", "lib/vinto/bobinas-offers.ts", "lib/vinto/bobinas-candidates.ts", "lib/vinto/p1-05.ts", "lib/vinto/p1-31.ts", "components/vinto/candidate-form-capture.tsx", "components/vinto/candidate-history.tsx", "components/vinto/bobinas-candidate-cards.tsx"]) {
    const text = read(file);
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie/.test(text.split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n")), false, `${file} no usa almacenamiento local`);
  }
  const page = read("app/page.tsx");
  assert.match(page, /bobAvailability = useAvailability\(false, authenticated && bobinasFront/); // la oferta depende de la disponibilidad del backend
  assert.match(page, /candidates=\{bobinasFront \? <BobinasCandidateCards offered=\{offeredCandidates\(bobAvailability\.view, machine\)\}/);
  assert.match(page, /if \(bobCandidate && front === "Bobinas"\)/);
  assert.match(page, /<CandidateHistory candidate=\{BOBINAS_CANDIDATES\[screen\]\} resource=\{candHistory\[screen\]\.view\}/);
  // Rebobinado y Conversión no cambian: sus shells siguen siendo los mismos
  assert.match(page, /front === "Conversión" \? <ConversionCentral /);
  assert.match(page, /front === "Rebobinado" \? <RebobinadoCentral /);
  assert.match(page, /function resetSessionState\(\) \{\n[^\n]*setBobCandidate\(null\); setCandAttempts\(\{\}\)/); // la sesión perdida descarta intentos y pantallas candidatas
});
