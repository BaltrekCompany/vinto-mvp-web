// node --test scripts/quality-bobbin-history.test.mjs
// Q3.1 · Historial de controles de Calidad por Bobina (solo lectura): parser del historial (estructura común, identidad de la Bobina,
// formularios sin visor, P1-19 por su parser estricto de Q2), clasificación de errores HTTP, guarda contra respuestas tardías de otra
// Bobina, hora de planta, cálculo visual de humedad de Q2 y comprobaciones estructurales de la integración (sin escrituras, sin
// liberar/rechazar, sin tocar el intento pendiente de humedad). No hay entorno de renderizado React en Node: la UI se verifica por estructura.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  Q19_FORM_CODE, WEIGHT_KEYS, captureMatchesHumidityAttempt, computeHumidity, createHumidityAttempt, formatHumidity, parseQualityCapture, EMPTY_HUMIDITY_DRAFT,
} from "../lib/vinto/quality-captures.ts";
import {
  HISTORY_FAILURE_MESSAGES, HISTORY_MESSAGES, PLANT_TIME_ZONE, captureStatusLabel, formatPlantInstant, historyForBobbin, parseHistoryMeta, parseQualityBobbinHistory, qualityHistoryLoad,
} from "../lib/vinto/quality-history.ts";

// Evidencia DEV (prueba sintética de Q2): solo como fixture; aquí no se lee ni se escribe la base.
const BOBBIN_ID = "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b";
const CAPTURE_ID = "e75e35b2-de12-414d-80c9-15041cc3a9be";
const OTHER_BOBBIN_ID = "12121212-1212-4212-8212-121212121212";
const BOBBIN = { id: BOBBIN_ID, code: "1" };
const VIEWERS = { [Q19_FORM_CODE]: parseQualityCapture }; // el mismo registro que usa lib/vinto/quality-history-api.ts
const DEV_VALUES = { peso_humedo_comando: "0.100", peso_seco_comando: "0.094", peso_humedo_medio: "0.101", peso_seco_medio: "0.095", peso_humedo_transversal: "0.099", peso_seco_transversal: "0.093" };

const capture = (o = {}) => ({
  id: CAPTURE_ID, status: "submitted", revision: 1, captured_at: "2026-10-08T14:05:09.123456Z", submitted_at: "2026-10-08T14:05:09.654321Z",
  form: { code: "VINTO-P1-19", version_number: 1, name: "Control de humedad" }, bobbin: { id: BOBBIN_ID, code: "1" }, machine: { code: "MP1", name: "MP1" },
  shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-07", work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
  line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-DEV-001", article: { code: "M1-1031", description: "M1-BOBINA PH G-15.5" } },
  values: { ...DEV_VALUES }, ...o,
});
const other = (o = {}) => capture({ id: "33333333-3333-4333-8333-333333333333", form: { code: "VINTO-P1-20", version_number: 2, name: "Otro control" }, values: { gramaje: "15.5", peso_humedo_comando: "1" }, ...o });
const parse = (list, expected = BOBBIN) => parseQualityBobbinHistory(list, expected, VIEWERS);
const ready = (data, refreshing = false) => ({ status: "ready", data, refreshing });

// ---- parser: casos válidos --------------------------------------------------------------------------------------------------

test("a valid single-capture history parses with the bobbin identity and P1-19 detail", () => {
  const history = parse([capture()]);
  assert.equal(history.bobbinId, BOBBIN_ID);
  assert.equal(history.entries.length, 1);
  const [entry] = history.entries;
  assert.equal(entry.kind, "humidity");
  assert.deepEqual([entry.meta.id, entry.meta.form.code, entry.meta.form.version_number, entry.meta.status, entry.meta.bobbin.code], [CAPTURE_ID, "VINTO-P1-19", 1, "submitted", "1"]);
  assert.equal(entry.capture.id, CAPTURE_ID);
});

test("an empty list is a valid, empty history (not an error)", () => {
  assert.deepEqual(parse([]), { bobbinId: BOBBIN_ID, entries: [] });
  assert.equal(qualityHistoryLoad(BOBBIN_ID, { ok: true, status: 200, data: parse([]) }).ok, true);
  assert.match(HISTORY_MESSAGES.empty, /no tiene controles/);
});

test("multiple captures keep the backend order exactly (no re-sorting, no dedupe, no filtering)", () => {
  // Orden descendente del backend; ids deliberadamente NO ordenados alfabéticamente para detectar un re-orden de la interfaz.
  const ids = ["ffffffff-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002", "88888888-0000-4000-8000-000000000003"];
  const times = ["2026-10-08T16:00:00Z", "2026-10-08T15:00:00Z", "2026-10-08T14:00:00Z"];
  const list = [capture({ id: ids[0], captured_at: times[0] }), other({ id: ids[1], captured_at: times[1] }), capture({ id: ids[2], captured_at: times[2], status: "closed" })];
  const history = parse(list);
  assert.deepEqual(history.entries.map((e) => e.meta.id), ids);
  assert.deepEqual(history.entries.map((e) => e.kind), ["humidity", "unsupported", "humidity"]);
  assert.deepEqual(history.entries.map((e) => e.meta.status), ["submitted", "submitted", "closed"]);
  // aun si el backend entregara otro orden, se respeta tal cual
  assert.deepEqual(parse([...list].reverse()).entries.map((e) => e.meta.id), [...ids].reverse());
});

test("the six P1-19 weights stay exact decimal strings (\"0.100\" stays \"0.100\")", () => {
  const { capture: c } = parse([capture()]).entries[0];
  for (const key of WEIGHT_KEYS) { assert.equal(typeof c.values[key], "string", key); assert.equal(c.values[key], DEV_VALUES[key], key); }
  assert.equal(c.values.peso_humedo_comando, "0.100");
  const long = parse([capture({ values: { ...DEV_VALUES, peso_humedo_medio: "12345678901234567890.123456789" } })]).entries[0];
  assert.equal(long.capture.values.peso_humedo_medio, "12345678901234567890.123456789");
});

test("P1-19 humidity uses the Q2 formula: DEV evidence gives 6.00 / 5.94 / 6.06 / 6.00", () => {
  const { capture: c } = parse([capture()]).entries[0];
  const h = computeHumidity(c.values);
  assert.deepEqual([formatHumidity(h.comando), formatHumidity(h.medio), formatHumidity(h.transversal), formatHumidity(h.promedio)], ["6.00", "5.94", "6.06", "6.00"]);
  assert.equal(c.values.peso_humedo_comando, "0.100", "computing does not alter the source strings");
});

test("the average is taken over the per-position values ALREADY rounded (Q2 behaviour)", () => {
  // Caso donde el orden del redondeo cambia el resultado visible.
  const values = { peso_humedo_comando: "3", peso_seco_comando: "2.9000", peso_humedo_medio: "3", peso_seco_medio: "2.9000", peso_humedo_transversal: "3", peso_seco_transversal: "2.9006" };
  const h = computeHumidity(values);
  assert.deepEqual([h.comando, h.medio, h.transversal], [3.33, 3.33, 3.31]);
  assert.equal(formatHumidity(h.promedio), "3.32"); // (3.33+3.33+3.31)/3 = 3.3233 -> 3.32
  const unrounded = ((3 - 2.9) / 3 * 100 * 2 + (3 - 2.9006) / 3 * 100) / 3; // 3.3267 -> 3.33: NO es lo que muestra Q2
  assert.equal(unrounded.toFixed(2), "3.33");
});

test("observaciones are optional and are kept verbatim when present", () => {
  assert.equal(Object.prototype.hasOwnProperty.call(parse([capture()]).entries[0].capture.values, "observaciones"), false);
  const withNotes = parse([capture({ values: { ...DEV_VALUES, observaciones: "Muestra  tomada\nen borde" } })]).entries[0];
  assert.equal(withNotes.capture.values.observaciones, "Muestra  tomada\nen borde");
});

// ---- parser: formularios sin visor e inválidos ------------------------------------------------------------------------------

test("an unknown form is shown with metadata only: its values are never interpreted or propagated", () => {
  const history = parse([other()]);
  const [entry] = history.entries;
  assert.equal(entry.kind, "unsupported");
  assert.deepEqual([entry.meta.form.code, entry.meta.form.name, entry.meta.form.version_number], ["VINTO-P1-20", "Otro control", 2]);
  assert.equal("capture" in entry, false);
  assert.equal("values" in entry.meta, false);
  assert.equal(JSON.stringify(history).includes("gramaje"), false);
  assert.equal(HISTORY_MESSAGES.unsupported, "Detalle de este formulario todavía no disponible");
});

test("an invalid P1-19 capture is flagged as invalid: never reinterpreted as another form, never shown with measurements", () => {
  for (const bad of [{ ...DEV_VALUES, peso_seco_medio: 0.095 }, { ...DEV_VALUES, peso_humedo_comando: "abc" }, (() => { const v = { ...DEV_VALUES }; delete v.peso_seco_transversal; return v; })(), { ...DEV_VALUES, observaciones: 5 }]) {
    const history = parse([capture({ values: bad })]);
    assert.ok(history, "the history itself stays readable");
    assert.equal(history.entries[0].kind, "invalid", JSON.stringify(bad));
    assert.equal("capture" in history.entries[0], false);
  }
  assert.match(HISTORY_MESSAGES.invalidEntry, /No se muestran sus mediciones/);
});

test("the strict Q2 parser is unchanged: it still rejects any non P1-19 form", () => {
  assert.equal(parseQualityCapture(other()), null);
  assert.ok(parseQualityCapture(capture()));
});

test("a capture of ANOTHER bobbin rejects the whole response as inconsistent", () => {
  assert.equal(parse([capture(), capture({ id: "44444444-4444-4444-8444-444444444444", bobbin: { id: OTHER_BOBBIN_ID, code: "1" } })]), null);
  assert.equal(parse([capture({ bobbin: { id: BOBBIN_ID, code: "2" } })]), null, "same id, different code");
  assert.equal(parse([other({ bobbin: { id: OTHER_BOBBIN_ID, code: "9" } })]), null, "also for forms without viewer");
});

test("invalid responses are rejected as a whole (no partial history presented as complete)", () => {
  for (const notList of [null, undefined, {}, "x", 1, { items: [] }]) assert.equal(parse(notList), null, String(notList));
  assert.equal(parse([capture(), null]), null);
  const broken = capture(); delete broken.form;
  assert.equal(parse([capture({ id: "55555555-0000-4000-8000-000000000000" }), broken]), null);
  assert.equal(parse([capture(), capture()]), null, "duplicated capture id");
  for (const [field, value] of [["status", "draft"], ["status", "cancelled"], ["revision", 0], ["revision", "1"], ["captured_at", "2026-10-08T14:05:09"], ["captured_at", "ayer"],
    ["submitted_at", "x"], ["submitted_at", undefined], ["operating_date", "07/10/2026"], ["values", null], ["values", []], ["form", { code: "VINTO-P1-19", version_number: 0, name: "x" }],
    ["machine", null], ["shift", null], ["work_order", { id: "x" }], ["line", { id: "x", line_code: "L1", pv_reference: "PV" }]]) {
    assert.equal(parse([capture({ [field]: value })]), null, `${field}=${JSON.stringify(value)}`);
    assert.equal(parseHistoryMeta(capture({ [field]: value })), null, `meta ${field}`);
  }
  assert.equal(parse([capture({ submitted_at: null })]).entries[0].meta.submitted_at, null, "submitted_at null is valid");
});

// ---- clasificación de la consulta ---------------------------------------------------------------------------------------------

test("HTTP outcomes are classified: 401 session, 403, 404, network, backend down and invalid body; never demo data", () => {
  const fail = (status, kind = "unavailable") => qualityHistoryLoad(BOBBIN_ID, { ok: false, kind, status });
  assert.deepEqual(fail(401, "session"), { bobbinId: BOBBIN_ID, ok: false, failure: "session" });
  assert.equal(fail(403, "forbidden").failure, "forbidden");
  assert.equal(fail(404, "not_found").failure, "not_found");
  assert.equal(fail(0).failure, "network");
  for (const status of [500, 502, 503, 504]) assert.equal(fail(status).failure, "unavailable", String(status));
  assert.equal(fail(200).failure, "invalid_response", "requestJson returns status 2xx when the parser rejected the body");
  for (const load of [fail(403, "forbidden"), fail(404, "not_found"), fail(0), fail(503), fail(200)]) assert.equal("history" in load, false);
  for (const key of ["forbidden", "not_found", "network", "unavailable", "invalid_response", "session"]) assert.ok(HISTORY_FAILURE_MESSAGES[key], key);
  assert.match(HISTORY_FAILURE_MESSAGES.forbidden, /permisos/);
  assert.match(HISTORY_FAILURE_MESSAGES.not_found, /no existe/);
});

test("a successful result belonging to another bobbin is turned into an invalid response", () => {
  const foreign = parse([capture({ bobbin: { id: OTHER_BOBBIN_ID, code: "7" } })], { id: OTHER_BOBBIN_ID, code: "7" });
  assert.deepEqual(qualityHistoryLoad(BOBBIN_ID, { ok: true, status: 200, data: foreign }), { bobbinId: BOBBIN_ID, ok: false, failure: "invalid_response" });
});

// ---- respuestas tardías y cambios rápidos de Bobina ---------------------------------------------------------------------------

test("rapid bobbin changes: a late result of bobbin A is never shown while bobbin B is selected", () => {
  const A = { id: OTHER_BOBBIN_ID, code: "7" }, B = BOBBIN;
  const lateA = qualityHistoryLoad(A.id, { ok: true, status: 200, data: parse([capture({ bobbin: A })], A) });
  assert.equal(lateA.ok, true);
  // la vista del recurso trae el resultado tardío de A, pero la seleccionada es B -> se presenta como "cargando", sin controles de A
  assert.deepEqual(historyForBobbin(ready(lateA), B.id), { status: "loading" });
  assert.deepEqual(historyForBobbin(ready(lateA, true), B.id), { status: "loading" }, "also while refreshing");
  // y aunque A respondiera en la URL de B, el parser de B rechaza capturas de A
  assert.equal(parse([capture({ bobbin: A })], B), null);
  // cuando llega el de B, se muestra
  const loadB = qualityHistoryLoad(B.id, { ok: true, status: 200, data: parse([capture()], B) });
  assert.equal(historyForBobbin(ready(loadB), B.id).data, loadB);
  // un error tardío de A tampoco se presenta en B
  assert.deepEqual(historyForBobbin(ready(qualityHistoryLoad(A.id, { ok: false, kind: "not_found", status: 404 })), B.id), { status: "loading" });
  for (const view of [{ status: "idle" }, { status: "loading" }, { status: "error", kind: "session", refreshing: false }]) assert.equal(historyForBobbin(view, B.id), view);
});

// ---- fechas -------------------------------------------------------------------------------------------------------------------

test("test and submission instants are shown in plant time (America/La_Paz, UTC-4); operating_date is not recalculated", () => {
  assert.equal(PLANT_TIME_ZONE, "America/La_Paz");
  assert.equal(formatPlantInstant("2026-10-08T14:05:09.123456Z"), "08/10/2026 10:05:09");
  assert.equal(formatPlantInstant("2026-10-08T14:05:09+00:00"), "08/10/2026 10:05:09");
  assert.equal(formatPlantInstant("2026-10-08T10:05:09-04:00"), "08/10/2026 10:05:09");
  assert.equal(formatPlantInstant("2026-10-08T02:30:00Z"), "07/10/2026 22:30:00", "crosses midnight into the previous plant day");
  const meta = parse([capture({ captured_at: "2026-10-08T02:30:00Z", operating_date: "2026-10-08" })]).entries[0].meta;
  assert.equal(meta.operating_date, "2026-10-08", "the historical operating date is kept as received");
  assert.equal(captureStatusLabel("submitted"), "Captura enviada");
  assert.equal(captureStatusLabel("closed"), "Captura cerrada");
  assert.equal(/liberad|aprobad|conforme|rechazad/i.test(captureStatusLabel("submitted") + captureStatusLabel("closed")), false, "capture status is not a quality decision");
});

// ---- protección del intento pendiente Q2 --------------------------------------------------------------------------------------

test("reading the history does not touch a pending humidity attempt (same capture_id, payload and bobbin)", () => {
  const inboxItem = { bobbin: { id: BOBBIN_ID, code: "1", machine: { code: "MP1", name: "MP1" } }, production: { work_order: { number: "OT-2026-0001" } }, quality: { status: "pending" } };
  const made = createHumidityAttempt({ ...EMPTY_HUMIDITY_DRAFT, ...DEV_VALUES }, inboxItem, "99999999-9999-4999-8999-999999999999", () => CAPTURE_ID);
  assert.ok(made.ok);
  const before = JSON.stringify(made.attempt);
  const history = parse([capture()]);
  qualityHistoryLoad(BOBBIN_ID, { ok: true, status: 200, data: history });
  assert.equal(JSON.stringify(made.attempt), before);
  assert.ok(Object.isFrozen(made.attempt) && Object.isFrozen(made.attempt.payload.values));
  assert.equal(made.attempt.captureId, CAPTURE_ID);
  // la reconciliación de Q2 sigue reconociendo la captura del servidor como ESE intento
  assert.equal(captureMatchesHumidityAttempt(history.entries[0].capture, made.attempt), true);
});

// ---- estructura ----------------------------------------------------------------------------------------------------------------

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8").replace(/\r\n/g, "\n");
const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/ .*$/gm, "");
const page = read("../app/page.tsx");
const api = strip(read("../lib/vinto/quality-history-api.ts"));
const lib = strip(read("../lib/vinto/quality-history.ts"));
const component = strip(read("../components/vinto/quality-bobbin-history.tsx"));
const capturesLib = read("../lib/vinto/quality-captures.ts");

test("the API only GETs the existing endpoint through requestJson, with cancellation and timeout", () => {
  assert.match(api, /requestJson\(`\/api\/quality\/bobbins\/\$\{encodeURIComponent\(bobbin\.id\)\}\/captures`/);
  assert.equal(/method:|POST|PATCH|PUT|DELETE/.test(api), false);
  assert.equal(/fetch\(|Authorization|document\.cookie|localStorage|sessionStorage|indexedDB/.test(api), false);
  assert.match(api, /AbortSignal\.any\(\[signal, AbortSignal\.timeout\(GET_TIMEOUT_MS\)\]\)/);
  assert.match(api, /\[Q19_FORM_CODE\]: parseQualityCapture/, "P1-19 goes through the strict Q2 parser");
  assert.match(api, /if \(!result\.ok && result\.kind === "session"\) return result;/, "401 reaches the existing session-lost flow");
  assert.equal(/\/api\/quality\/(?!bobbins\/\$\{)/.test(api), false, "no other endpoint");
});

test("the history module is pure (type-only imports) and has no network, storage or polling", () => {
  const imports = lib.match(/^import .*$/gm) ?? [];
  assert.ok(imports.length > 0 && imports.every((line) => line.startsWith("import type ")), imports.join("\n"));
  for (const [name, text] of [["lib", lib], ["api", api], ["component", component]]) {
    assert.equal(/localStorage|sessionStorage|indexedDB|vinto-p1-records|setRecords|setInterval|setTimeout/.test(text), false, name);
  }
});

test("the history screen is read-only: only Back, Refresh and Retry; no inputs, no submit, no release/reject", () => {
  assert.equal(/Liberar|Rechazar|liberar|rechazar|quality\.release|quality_release/.test(component), false);
  const clicks = [...component.matchAll(/onClick=\{([^}]*)\}/g)].map((m) => m[1].trim()).sort();
  assert.deepEqual(clicks, ["back", "refresh", "refresh"]);
  assert.equal(/<input|<Input|<Textarea|<textarea|<select|checkbox|<form|onSubmit/.test(component), false);
  assert.equal(/submitQualityCapture|submitHumidityAttempt|createHumidityAttempt|setAttempt|getDeviceKey|useState|fetch\(/.test(component), false);
  assert.equal(/QualityHumidityCapture/.test(component), false, "the editable capture is not reused as a viewer");
});

test("the P1-19 detail reuses computeHumidity/formatHumidity and shows the original weight strings in kg (no second formula)", () => {
  assert.match(component, /computeHumidity\(values\)/);
  assert.match(component, /formatHumidity\(humidity\[p\]\)/);
  assert.match(component, /formatHumidity\(humidity\.promedio\)/);
  assert.match(component, /\{values\[`peso_humedo_\$\{p\}`\]\} kg/);
  assert.match(component, /\{values\[`peso_seco_\$\{p\}`\]\} kg/);
  assert.equal(/Number\(|parseFloat|toFixed|\* ?100|- ?dry|wet ?-/.test(component), false, "no independent humidity math or numeric coercion in the view");
  assert.equal(/Number\(|parseFloat|toFixed/.test(lib), false);
  assert.match(component, /POSITIONS\.map/);
  assert.match(component, /notes !== undefined && notes !== ""/);
  // la fórmula de Q2 sigue siendo única
  assert.equal((capturesLib.match(/\(\(wet - dry\) \/ wet\) \* 100/g) ?? []).length, 1);
});

test("the history screen renders every UI state and the header context from the selected inbox item", () => {
  assert.match(component, /Cargando historial de controles…/);
  assert.match(component, /HISTORY_MESSAGES\.empty/);
  assert.match(component, /HISTORY_MESSAGES\.unsupported/);
  assert.match(component, /HISTORY_MESSAGES\.invalidEntry/);
  assert.match(component, /HISTORY_FAILURE_MESSAGES\[failure\]/);
  assert.match(component, /Reintentando…/);
  assert.match(component, /Actualizando…/);
  assert.match(component, /historyForBobbin\(resource, bobbin\.id\)/, "late results of another bobbin are hidden");
  assert.match(component, /entries\.map\(\(e, i\) => <EntryCard key=\{e\.meta\.id\}/, "rendered in backend order, keyed by capture id");
  for (const label of ["Bobina", "Máquina", "OT", "Línea / PV", "Artículo", "Fecha operativa", "Turno", "Estado de Calidad (inbox)"]) assert.ok(component.includes(`label="${label}"`), label);
  assert.match(component, /qualityStatusLabel\(quality\.status\)/);
  for (const label of ["Ensayo (hora de planta)", "Envío (hora de planta)"]) assert.ok(component.includes(`label="${label}"`), label);
  assert.match(component, /PLANT_TIME_ZONE/);
  assert.match(component, /ID de captura: \{meta\.id\}/);
  assert.match(component, /Versión \{meta\.form\.version_number\}/);
  assert.match(component, /captureStatusLabel\(meta\.status\)/);
  assert.match(component, /production\.operating_date/);
  assert.equal(/formatPlantInstant\(production|formatPlantInstant\(meta\.operating_date/.test(component), false, "the operating date is not converted");
  // accesibilidad y responsive básicos
  assert.match(component, /role="status"/);
  assert.match(component, /role="alert"/);
  assert.match(component, /aria-live="polite"/);
  assert.match(component, /<caption className="sr-only">/);
  assert.match(component, /scope="col"/);
  assert.match(component, /<ol /);
  assert.match(component, /max-w-full overflow-x-auto/);
  assert.match(component, /Volver al inbox/);
});

test("page: independent history state, keyed per bobbin and per opening, gated by quality.capture, cleared on logout/session loss", () => {
  assert.match(page, /const \[qualityHistory, setQualityHistory\] = useState<\{ item: QualityBobbinInboxItem; seq: number \} \| null>\(null\)/);
  const declaration = page.slice(page.indexOf("const historyBobbin ="), page.indexOf("const refreshCentral"));
  assert.match(declaration, /useResource<QualityHistoryLoad>\(qualityHistory \? `quality-history:\$\{qualityHistory\.item\.bobbin\.id\}:\$\{qualityHistory\.seq\}`/);
  assert.match(declaration, /authenticated && front === "Calidad" && canReadQualityInbox && historyBobbin !== null/);
  assert.match(declaration, /getQualityBobbinHistory\(\{ id: historyBobbin\.id, code: historyBobbin\.code \}, signal\)/);
  assert.match(declaration, /, sessionLost\);/);
  assert.match(declaration, /const openQualityHistory = \(item: QualityBobbinInboxItem\) => \{ historySeq\.current \+= 1; setQualityHistory\(\{ item, seq: historySeq\.current \}\); \};/);
  // se limpia al perder la sesión y al cerrar sesión
  assert.equal((page.match(/setSelectedQualityBobbin\(null\); setHumidityAttempt\(null\); setQualityHistory\(null\);/g) ?? []).length, 2);
  // pantalla: solo con permiso; Volver solo cierra el historial (no refresca ni toca el inbox/intento)
  assert.match(page, /if \(qualityHistory && canReadQualityInbox\)\n\s+return <QualityBobbinHistory item=\{qualityHistory\.item\} resource=\{bobbinHistory\.view\} refresh=\{bobbinHistory\.refresh\} back=\{\(\) => setQualityHistory\(null\)\}\/>;/);
  assert.equal(/setInterval/.test(page), false, "no polling");
});

test("page: the history never touches the pending humidity attempt or the humidity selection", () => {
  const opener = page.slice(page.indexOf("const openQualityHistory"), page.indexOf("const refreshCentral"));
  assert.equal(/setHumidityAttempt|setSelectedQualityBobbin|humidityAttempt/.test(opener), false);
  const historyRender = page.slice(page.indexOf("if (qualityHistory && canReadQualityInbox)"), page.indexOf("// F3 tampoco usa Capture/save()"));
  assert.equal(/setHumidityAttempt|setSelectedQualityBobbin|humidityAttempt|qualityInbox\.refresh/.test(historyRender), false);
  // el formulario de humedad (con su intento pendiente) sigue teniendo prioridad y su apertura conserva la Bobina del intento
  assert.ok(page.indexOf("if (selectedQualityBobbin)") < page.indexOf("if (qualityHistory && canReadQualityInbox)"));
  assert.match(page, /onRegisterHumidity=\{item => setSelectedQualityBobbin\(humidityAttempt \? humidityAttempt\.bobbin : item\)\}/);
  assert.match(page, /<QualityHumidityCapture item=\{selectedQualityBobbin\} online=\{online\} attempt=\{humidityAttempt\} setAttempt=\{setHumidityAttempt\}/);
});
