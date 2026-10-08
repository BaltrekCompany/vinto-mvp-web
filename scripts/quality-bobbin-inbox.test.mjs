// node --test scripts/quality-bobbin-inbox.test.mjs
// Inbox central de Calidad (solo lectura): parser defensivo del contrato de GET /api/quality/bobbins y comprobaciones estructurales
// de que Calidad ya no usa los `releases` demo ni acciones locales de liberar/rechazar.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { NO_GRAMMAGE_LABEL, grammageLabel, parseQualityBobbinInbox, parseQualityBobbinInboxItem, qualityStatusLabel } from "../lib/vinto/quality-bobbins.ts";

const item = (o = {}) => ({
  bobbin: {
    id: "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b", code: "1", machine: { code: "MP1", name: "MP1" }, management_start_year: 2026, sequence_number: 1,
    start_time: "12:00:00", end_time: "13:00:00", diameter_mm: "1200", weight_kg: "845.25", grammage_g_m2: "15.5", number_of_cuts: "3", notes: "ok", ...o.bobbin,
  },
  production: {
    capture_id: "40b936c3-387f-4399-a394-33642813ffbd", captured_at: "2026-10-07T16:00:00Z", operating_date: "2026-10-07", shift: { code: "DIA", name: "Día" },
    work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-2026-0001" },
    line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1", pv_reference: "PV-DEV-001", article: { code: "M1-1031", description: "M1-BOBINA PH G-15.5" } }, ...o.production,
  },
  quality: { status: "pending", ...o.quality },
});
const without = (path, base = item()) => { const copy = structuredClone(base); const keys = path.split("."); const last = keys.pop(); let node = copy; for (const k of keys) node = node[k]; delete node[last]; return copy; };

// ---- parser ----------------------------------------------------------------------------------------------------------------

test("a valid pending response parses into a clean list", () => {
  const list = parseQualityBobbinInbox([item(), item({ bobbin: { id: "b2", code: "2", sequence_number: 2 } })]);
  assert.equal(list.length, 2);
  assert.deepEqual([list[0].bobbin.code, list[0].quality.status, list[0].production.work_order.number, list[0].production.line.article.code], ["1", "pending", "OT-2026-0001", "M1-1031"]);
  assert.deepEqual(parseQualityBobbinInbox([]), []);
});

test("released and rejected are valid statuses of the endpoint contract", () => {
  for (const status of ["pending", "released", "rejected"]) assert.equal(parseQualityBobbinInboxItem(item({ quality: { status } })).quality.status, status);
  assert.equal(qualityStatusLabel("pending"), "Pendiente");
});

test("grammage null is valid and is not an error", () => {
  const parsed = parseQualityBobbinInboxItem(item({ bobbin: { grammage_g_m2: null } }));
  assert.equal(parsed.bobbin.grammage_g_m2, null);
  assert.equal(grammageLabel(null), NO_GRAMMAGE_LABEL);
  assert.doesNotMatch(grammageLabel(null), /error|falta|inválid/i);
  assert.equal(grammageLabel("15.5"), "15.5 g/m²");
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { grammage_g_m2: "x" } })), null);
});

test("decimals are preserved exactly as text (no Number conversion)", () => {
  const parsed = parseQualityBobbinInboxItem(item({ bobbin: { diameter_mm: "1200.10", weight_kg: "0.10", grammage_g_m2: "14.50" } }));
  assert.deepEqual([parsed.bobbin.diameter_mm, parsed.bobbin.weight_kg, parsed.bobbin.grammage_g_m2], ["1200.10", "0.10", "14.50"]);
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { weight_kg: "12345678901234567890.123456789" } })).bobbin.weight_kg, "12345678901234567890.123456789");
  for (const key of ["diameter_mm", "weight_kg"]) assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { [key]: 12.5 } })), null, `${key} must be text`);
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { diameter_mm: "abc" } })), null);
});

test("weight cannot be negative; diameter has no functional range", () => {
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { weight_kg: "-0.5" } })), null);
  assert.ok(parseQualityBobbinInboxItem(item({ bobbin: { weight_kg: "0" } })));
  assert.ok(parseQualityBobbinInboxItem(item({ bobbin: { weight_kg: "-0" } })));
  assert.ok(parseQualityBobbinInboxItem(item({ bobbin: { diameter_mm: "0" } }))); // sin rango funcional confirmado
});

test("code must equal String(sequence_number)", () => {
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { code: "2" } })), null);
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { code: "01" } })), null);
  assert.ok(parseQualityBobbinInboxItem(item({ bobbin: { code: "12", sequence_number: 12 } })));
});

test("sequence_number and management_start_year must be positive integers", () => {
  for (const bad of [0, -1, 1.5, "1", null]) {
    assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { sequence_number: bad, code: String(bad) } })), null, `sequence ${bad}`);
    assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { management_start_year: bad } })), null, `management ${bad}`);
  }
});

test("an unknown quality status is invalid", () => {
  for (const bad of ["foo", "PENDING", "", null, undefined, 1]) assert.equal(parseQualityBobbinInboxItem(item({ quality: { status: bad } })), null, String(bad));
  assert.equal(parseQualityBobbinInboxItem(without("quality.status")), null);
});

test("a missing work order, line or article makes the item invalid", () => {
  for (const path of ["production.work_order", "production.work_order.number", "production.work_order.id", "production.line", "production.line.line_code", "production.line.pv_reference",
    "production.line.article", "production.line.article.code", "production.line.article.description", "production.shift", "production.capture_id", "production.captured_at", "production.operating_date"]) {
    assert.equal(parseQualityBobbinInboxItem(without(path)), null, path);
  }
});

test("every mandatory bobbin field is required", () => {
  for (const path of ["bobbin.id", "bobbin.code", "bobbin.machine", "bobbin.management_start_year", "bobbin.sequence_number", "bobbin.start_time", "bobbin.end_time",
    "bobbin.diameter_mm", "bobbin.weight_kg", "bobbin.grammage_g_m2", "bobbin.number_of_cuts", "bobbin.notes"]) {
    assert.equal(parseQualityBobbinInboxItem(without(path)), null, path);
  }
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { number_of_cuts: "" } })), null);
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { notes: 5 } })), null);
  assert.equal(parseQualityBobbinInboxItem(item({ bobbin: { notes: null } })).bobbin.notes, null);
});

test("one malformed item rejects the WHOLE list (no silent hiding)", () => {
  const bad = item(); delete bad.production.work_order;
  assert.equal(parseQualityBobbinInbox([item(), bad, item({ bobbin: { id: "b3", code: "3", sequence_number: 3 } })]), null);
  for (const notList of [null, undefined, {}, "x", 1, { items: [] }]) assert.equal(parseQualityBobbinInbox(notList), null);
  assert.equal(parseQualityBobbinInbox([item(), null]), null);
});

test("unknown fields (audit, device, internals) are not propagated", () => {
  const dirty = item();
  dirty.created_by = "u"; dirty.bobbin.created_by = "u"; dirty.bobbin.device = "d"; dirty.production.updated_by = "u"; dirty.production.line.audit = {}; dirty.quality.decided_by = "u";
  const clean = parseQualityBobbinInboxItem(dirty);
  const text = JSON.stringify(clean);
  for (const forbidden of ["created_by", "updated_by", "device", "audit", "decided_by"]) assert.equal(text.includes(forbidden), false, forbidden);
  assert.deepEqual(Object.keys(clean).sort(), ["bobbin", "production", "quality"]);
});

// ---- estructura ------------------------------------------------------------------------------------------------------------

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const page = read("../app/page.tsx");
const api = strip(read("../lib/vinto/quality-api.ts"));
const lib = strip(read("../lib/vinto/quality-bobbins.ts"));
const component = strip(read("../components/vinto/quality-bobbin-inbox.tsx"));
const executionBody = page.slice(page.indexOf("function Execution("), page.indexOf("function Cards("));
const programmingBody = page.slice(page.indexOf("function Programming("), page.indexOf("function Execution("));
const trackingBody = page.slice(page.indexOf("function Tracking("), page.indexOf("function ReleaseCards("));

test("the API consumes GET /api/quality/bobbins and nothing else", () => {
  assert.match(api, /"\/api\/quality\/bobbins"/);
  assert.equal(/POST|PATCH|PUT|DELETE|method:/.test(api), false);
  assert.equal(/Authorization|document\.cookie|localStorage|sessionStorage/.test(api), false);
  assert.match(api, /requestJson/);
  assert.equal(/status=/.test(api), false, "the backend default (pending) is used");
});

test("the inbox code never touches browser storage or local records", () => {
  for (const [name, text] of [["api", api], ["lib", lib], ["component", component]]) {
    assert.equal(/localStorage|sessionStorage|vinto-p1-records|vinto-ot|vinto-asg|setRecords/.test(text), false, name);
  }
});

test("the component is read-only: no release/reject, no actions or selection", () => {
  assert.equal(/Liberar|Rechazar|liberar|rechazar/.test(component), false);
  assert.equal(/onClick=\{(?!refresh)/.test(component), false, "the only click is the refresh");
  assert.equal(/<input|checkbox|<select|<textarea|<Textarea|<Input/.test(component), false);
  assert.equal(/setReleases|useState|fetch\(/.test(component), false);
  assert.match(component, /Bobinas pendientes de Calidad/);
  assert.match(component, /no depende de la asignación actualmente activa/);
});

test("the component has loading/error, empty and counter states", () => {
  assert.match(component, /CentralStatus/);
  assert.match(component, /No hay bobinas pendientes de Calidad\./);
  assert.match(component, /Pendientes: \{items\.length\}/);
  for (const header of ["Bobina", "Máquina", "OT", "Línea / PV", "Artículo", "Fecha operativa", "Turno", "Hora inicio", "Hora fin", "Gramaje", "Diámetro", "Peso", "Cortes", "Observaciones", "Estado"]) {
    assert.ok(component.includes(`"${header}`), header);
  }
  assert.match(component, /overflow-x-auto/);
  assert.match(component, /grammageLabel\(/); // gramaje null: texto neutro, no un error
});

test("Calidad Execution renders the central inbox and no longer the demo ReleaseCards gate", () => {
  const quality = executionBody.slice(executionBody.indexOf('if (front === "Calidad")'), executionBody.indexOf("return <><Panel"));
  assert.match(quality, /\{qualityInbox\}/);
  assert.equal(/ReleaseCards|releases|setReleases|Compuerta de liberación/.test(quality), false);
  assert.match(page, /<QualityBobbinInbox resource=\{qualityInbox\.view\} refresh=\{qualityInbox\.refresh\}\/>/);
  assert.equal(/Execution\(\{[^}]*\b(releases|setReleases|canRelease)\b/.test(executionBody), false);
  assert.equal(/<Execution [^>]*(releases=|setReleases=|canRelease=)/.test(page), false);
});

test("no local state setter decides anything for Calidad", () => {
  assert.equal(/setReleases/.test(page), false);
  assert.equal(/"quality\.release"/.test(page), false);
  assert.equal(/Liberar|Rechazar/.test(strip(executionBody)), false);
});

test("Programming and Tracking do not present demo releases as Calidad state", () => {
  assert.equal(/ReleaseCards/.test(programmingBody), false);
  assert.match(programmingBody, /se gestionan desde Ejecución/);
  assert.match(trackingBody, /front !== "Calidad" && <Metric label="Bobinas liberadas"/);
  assert.match(trackingBody, /front === "Calidad" \? <Panel title="Bobinas de Calidad"[\s\S]*?: <Panel title="Genealogía y calidad"/);
});

test("the resource is enabled only for Calidad + quality.capture in Ejecución, with sessionLost, and ignores the active assignment", () => {
  const declaration = page.slice(page.indexOf("const qualityInbox = useResource"), page.indexOf("const refreshCentral"));
  assert.match(declaration, /useResource<QualityBobbinInboxItem\[\]>\("quality-bobbin-inbox"/);
  assert.match(declaration, /front === "Calidad" && canReadQualityInbox && activeModule === "ejecucion"/);
  assert.match(declaration, /listQualityBobbins\(signal\)/);
  assert.match(declaration, /sessionLost\)/);
  assert.match(page, /canReadQualityInbox = hasPermission\(user, "quality\.capture"\)/);
  assert.equal(/activeAssignment|useActiveAssignment/.test(declaration), false);
  assert.match(page, /usesCentralAssignment\(front, activeModule\)/); // Calidad sigue sin consultar la asignación activa
});
