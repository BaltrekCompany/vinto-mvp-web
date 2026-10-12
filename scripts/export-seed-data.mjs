#!/usr/bin/env node
// Deterministic exporter of the VINTO reference-data bundle (pilot: sector Bobinas, MP1 + MP3).
//
//   node scripts/export-seed-data.mjs            write backend/seed_data/
//   node scripts/export-seed-data.mjs --check    fail if the committed bundle is stale
//   node scripts/export-seed-data.mjs --out DIR  write somewhere else
//
// Reads the existing TypeScript sources (nothing is copied by hand) and writes canonical JSON.
// It never touches PostgreSQL. Requires Node with TypeScript type stripping enabled by default
// (>= 22.18, >= 23.6 or 24); the repository already requires Node >= 22.18.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const DEFAULT_OUT = join(ROOT, "backend", "seed_data");
export const SCHEMA_VERSION = 1;

const SOURCE_FILES = {
  catalogs: "lib/vinto/catalogs.ts",
  forms: "lib/vinto/form-definitions.ts",
  weights: "lib/vinto/product-weights.ts",
  recipes: "lib/vinto/recipes.ts",
  page: "app/page.tsx",
};

// Pilot scope (project decision). Everything below is validated against the sources.
// The master-data scope (sectors, machines, shifts, unit aliases) is DECLARATIVE: see DEFAULT_SCOPE below.
const PILOT_FORM = { legacyNumber: 6, legacyKey: "form_6_registro_de_control_de_fardos", code: "VINTO-P1-06" };
const QUALITY_FORM = { legacyNumber: 19, legacyKey: "form_19_control_de_humedad", code: "VINTO-P1-19" };
const PROPERTIES_FORM = { legacyNumber: 20, legacyKey: "form_20_propiedades_fisicas_de_bobina", code: "VINTO-P1-20" };
const NEXT_FORM = { legacyNumber: 3, legacyKey: "form_3_registro_de_produccion_de_bobinas", code: "VINTO-P1-03" };
const PROFILES = [
  ["JEFATURA", "Jefatura"],
  ["SUPERVISION", "Supervisión"],
  ["OPERACION", "Operación"],
  ["CALIDAD", "Calidad"],
  ["DATA_BALTREK", "Data Baltrek"],
];

// ---- declarative master-data scope -----------------------------------------------------------------------------------------
// ONLY approved data belongs here. Adding a sector, machine or shift is a reviewed change to this table plus the approval from VINTO; the rest
// of the exporter is derived from it. M1-B2-a keeps the approved BOBINAS pilot exactly as it was (the generated bundle is byte-identical).
//   sector:   { code, name, front (key of GROUPS in app/page.tsx), machines, timezone, valid_from, shifts }
//   machine:  { code, name?, group?, catalog? }   name defaults to code (warning MACHINE_NAME_FROM_CODE); group = name shown in GROUPS (defaults to code);
//             catalog = key of PRODUCTS_BY_MACHINE (defaults to code)
//   shift:    [code, name, starts_at "HH:MM", ends_at "HH:MM", valid_from?, valid_to?]  (a night shift crosses midnight: ends_at < starts_at; its
//             operating date is the day it STARTS). valid_from defaults to the sector's.
//   unit_aliases: { "<unit as written in the catalog>": "<unit code>" } (none today). Material classes are derived from MATERIALS.
//   unit_labels: { "<unit code>": "<label>" } declared labels (the rest keep the code as a placeholder label, warning UNIT_LABEL_PLACEHOLDER).
//   nominal_weights: false keeps product-weights.ts out of the bundle (nominal_weight_kg null); omitted/true exports them as before.
//   forms_sector: the sector whose machines the published forms (F3, F6, P1-19, P1-20) are enabled for. Adding sectors never changes the forms.
// Shifts are declarative reference data requested for the pilot. Not read from the sources: the only source is the ctx() function in
// app/page.tsx, which is cross-checked below.
export const DEFAULT_SCOPE = {
  forms_sector: "BOBINAS",
  unit_aliases: {},
  sectors: [
    {
      code: "BOBINAS", name: "Bobinas", front: "Bobinas",
      machines: [{ code: "MP1" }, { code: "MP3" }],
      timezone: "America/La_Paz", valid_from: "2026-01-01",
      shifts: [["DIA", "Día", "07:00", "19:00"], ["NOCHE", "Noche", "19:00", "07:00"]],
    },
  ],
};
// M1-B2-b CANDIDATE scope: the three-sector master data (Bobinas + Rebobinado + Conversión). It is NOT the approved bundle: it is only reachable
// through `--scope candidate --out DIR` and is never written over backend/seed_data. Machine codes are technical candidates derived from the
// catalog (pending the final agreement from VINTO); the visible names are the ones shown in GROUPS (app/page.tsx). Shifts of Rebobinado are
// candidates (exact hours pending confirmation). Nominal weights and recipes are NOT part of this increment (nominal_weights: false).
const named = (list) => list.map(([code, group, catalog = group]) => ({ code, name: group, group, catalog }));
export const CANDIDATE_SCOPE = {
  forms_sector: "BOBINAS",
  unit_aliases: { Pack: "PACK" },
  unit_labels: { PACK: "Pack" },
  nominal_weights: false,
  sectors: [
    DEFAULT_SCOPE.sectors[0],
    {
      code: "REBOBINADO", name: "Rebobinado", front: "Rebobinado",
      machines: named([["BELOIT", "Beloit", "BELOIT"], ["OVER", "Over", "OVER"], ["COPASA", "Copasa", "COPASA"], ["PERICHUN", "Perichun", "PERICHUN"], ["TUBETERA", "Tubetera", "TUBETERA"]]),
      timezone: "America/La_Paz", valid_from: "2026-01-01",
      shifts: [["DIA", "Día", "06:00", "18:00"], ["NOCHE", "Noche", "18:00", "06:00"]],
    },
    {
      code: "CONVERSION", name: "Conversión", front: "Conversión",
      machines: named([["GAMBINI", "Gambini", "GAMBINI"], ["SINCRO_II", "Sincro II"], ["SINCRO_III", "Sincro III"], ["OMET_I", "OMET I"], ["OMET_II", "OMET II"], ["8_2", "8.2"], ["8_5", "8.5"],
        ["8002", "8002"], ["SERV_4", "Serv 4"], ["WALLY", "Wally", "WALLY"], ["PANUELERA", "Pañuelera", "PAÑUELERA"]]),
      timezone: "America/La_Paz", valid_from: "2026-01-01",
      shifts: [["MANANA", "Mañana", "06:00", "14:00"], ["TARDE", "Tarde", "14:00", "22:00"], ["NOCHE", "Noche", "22:00", "06:00"]],
    },
  ],
};
export const SCOPES = { approved: DEFAULT_SCOPE, candidate: CANDIDATE_SCOPE };
// Code formats of the master data (the backend loader enforces the same ones).
const CODE_PATTERNS = {
  sector: /^[A-Z][A-Z0-9_]{0,31}$/, machine: /^[A-Z0-9][A-Z0-9_]{0,31}$/, unit: /^[A-Z][A-Z0-9_]{0,15}$/,
  shift: /^[A-Z][A-Z0-9_]{0,31}$/, article: /^[A-Z0-9][A-Z0-9._-]{0,63}$/,
};
// Canonical F6 contract (project decision). Labels, units and option labels are read from app/page.tsx.
const F6_FIELDS = [
  { key: "cantidad_fardos", value_type: "integer", required: true },
  { key: "punto_merma", value_type: "text", required: true, options: ["bobina_rechazada", "recorte_maquina"] },
  { key: "tipo_producto", value_type: "text", required: true, options: ["servilleta", "hoja_doble", "hoja_simple"] },
  { key: "peso_kg", value_type: "decimal", required: true, unit: "KG" },
  { key: "observaciones", value_type: "textarea", required: false },
];

// Canonical F3 contract (project decision, confirmed with VINTO): ONLY what Operación types. Date, shift, machine, operator,
// bobbin code, article data, grammage and OT/PV/line are derived by the backend and never become fields. The source
// definition (form-definitions.ts) supplies label, type, required and unit, which are cross-checked here. Its "source"
// column is NOT checked: it still lists hora_inicio/hora_fin as automatic, and the confirmed contract makes both manual.
const F3_FIELDS = [
  { key: "hora_inicio", value_type: "time", required: true },
  { key: "hora_fin", value_type: "time", required: true },
  { key: "diametro", value_type: "decimal", required: true, unit: "MM" },
  { key: "peso_kg", value_type: "decimal", required: true, unit: "KG" },
  { key: "numero_de_cortes", value_type: "text", required: true },
  { key: "observaciones", value_type: "textarea", required: false },
];

// Canonical VINTO-P1-19 (Control de humedad, Calidad): ONLY the manual SOURCE data. The derived values (humedad por posición y
// promedio_humedad) and the automatic ones (fecha, hora, máquina, número de bobina, responsable) are central context or are
// recomputed from these weights, so they are NOT fields. Labels/units are read from the override in app/page.tsx.
const Q19_POSITIONS = ["comando", "medio", "transversal"];
const Q19_FIELDS = [
  ...Q19_POSITIONS.flatMap((position) => [
    { key: `peso_humedo_${position}`, value_type: "decimal", required: true, unit: "KG" },
    { key: `peso_seco_${position}`, value_type: "decimal", required: true, unit: "KG" },
  ]),
  { key: "observaciones", value_type: "textarea", required: false },
];

// Canonical VINTO-P1-20 (Propiedades físicas de bobina, Calidad) — PROVISIONAL contract (project decision): ONLY the eleven manual
// measurements plus optional observaciones. Type and requirement come from FORM_DEFINITIONS and are cross-checked here; the label is the
// source label after the visible relabelling of the effectiveForms override in app/page.tsx ("centro" -> "comando", provisional until
// VINTO validates it), reproduced by q20Label().
// Units are provisional (current MVP representation, not a laboratory homologation): `unit` is the catalog code that is published,
// `sourceUnit` is what FORM_DEFINITIONS declares today. espesor_* declares "kg" in the source and the effectiveForms override in
// app/page.tsx corrects it to "mm" (cross-checked and fingerprinted); gramaje declares "g/m²", which has no catalog code yet, so it is
// published with unit null (none is invented). The technical *_centro keys are never renamed: only their visible label changes.
const Q20_POSITIONS = ["centro", "medio", "extremo"];
const Q20_FIELDS = [
  { key: "crepado", value_type: "decimal", required: true, unit: null, sourceUnit: null },
  { key: "gramaje", value_type: "decimal", required: true, unit: null, sourceUnit: "g/m²" },
  ...Q20_POSITIONS.map((p) => ({ key: `resistencia_longitudinal_${p}`, value_type: "decimal", required: true, unit: null, sourceUnit: null })),
  ...Q20_POSITIONS.map((p) => ({ key: `resistencia_transversal_${p}`, value_type: "decimal", required: true, unit: null, sourceUnit: null })),
  ...Q20_POSITIONS.map((p) => ({ key: `espesor_${p}`, value_type: "decimal", required: true, unit: "MM", sourceUnit: "kg", pageUnit: "mm" })),
  { key: "observaciones", value_type: "textarea", required: false, unit: null, sourceUnit: null },
];
// Every other field of the legacy definition is deliberately NOT a field: central context derived from the F3 bobbin and the session,
// or a derived average (recomputed for display only, never stored). The list must match the source exactly, so a new legacy field
// stops the export instead of being silently dropped or published.
const Q20_EXCLUDED = {
  fecha: "automatic", hora: "automatic", maquina: "automatic", responsable: "automatic",
  numero_de_bobina: "bobbin context", producto: "bobbin context", numero_de_cortes: "F3 production data",
  promedio_resistencia_longitudinal: "calculated", promedio_resistencia_transversal: "calculated", promedio_espesor: "calculated",
};

export class SeedExportError extends Error {}

// Grammage of a bobbin is encoded in the official description ("... G-17 ...", "G-15.5", "G-14,5"). Deliberately narrow:
// only G-<number>, "." or "," as decimal separator, not glued to a preceding letter/digit. No match -> null (e.g. SEGUNDA).
const GRAMMAGE = /(?<![A-Za-z0-9])G-(\d+(?:[.,]\d+)?)(?!\d)/;
export function grammageFromDescription(description) {
  const match = GRAMMAGE.exec(description);
  if (!match) return null;
  const value = Number(match[1].replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

const fail = (message) => { throw new SeedExportError(message); };
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const sha256 = (text) => createHash("sha256").update(text, "utf8").digest("hex");
const slug = (text) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const json = (value) => JSON.stringify(value, null, 2) + "\n";

function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export async function loadSources(root = ROOT) {
  const texts = {};
  for (const [name, rel] of Object.entries(SOURCE_FILES)) {
    const path = join(root, rel);
    if (!existsSync(path)) fail(`Fuente ausente: ${rel}`);
    texts[name] = readFileSync(path, "utf8").replace(/\r\n/g, "\n"); // CRLF checkouts hash the same
  }
  const load = async (rel) => {
    try { return await import(pathToFileURL(join(root, rel)).href); }
    catch (error) {
      fail(`No se pudo importar ${rel} (${error.code ?? error.name}). Usa Node >= 22.18 / 24, con type stripping.`);
    }
  };
  const catalogs = await load(SOURCE_FILES.catalogs);
  const forms = await load(SOURCE_FILES.forms);
  const weights = await load(SOURCE_FILES.weights);
  const recipes = await load(SOURCE_FILES.recipes);
  return {
    texts,
    productsByMachine: catalogs.PRODUCTS_BY_MACHINE,
    materials: catalogs.MATERIALS,
    formDefinitions: forms.FORM_DEFINITIONS,
    nominalWeights: weights.NOMINAL_WEIGHT_BY_PRODUCT,
    recipes: recipes.RECIPES_BY_PRODUCT,
  };
}

// ---- extraction from app/page.tsx (fails loudly if the layout changes) -------------------------

function groupMachines(page, sector) {
  const match = page.match(new RegExp(`const GROUPS\\b[^=]*=\\s*\\{[^;]*?\\b${sector}:\\s*\\[([^\\]]*)\\]`));
  if (!match) fail(`No se encontró GROUPS.${sector} en app/page.tsx`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function functionBody(page, name) {
  const start = page.indexOf(`function ${name}(`);
  if (start < 0) fail(`No se encontró la función ${name} en app/page.tsx`);
  const next = page.indexOf("\nfunction ", start + 1);
  return page.slice(start, next < 0 ? undefined : next);
}

function formOverride(page, legacyKey, label) {
  const start = page.indexOf(`f.id === "${legacyKey}"`);
  if (start < 0) fail(`${label}: no se encontró su override en effectiveForms() de app/page.tsx`);
  const next = page.indexOf("if (f.id", start + 10);
  const block = page.slice(start, next < 0 ? undefined : next);
  const fields = {};
  for (const m of block.matchAll(/fld\("(\w+)",\s*"([^"]+)",\s*"(\w+)"(?:,\s*(true|false))?(?:,\s*"([^"]*)")?\)/g)) {
    fields[m[1]] = { label: m[2], type: m[3], required: m[4] !== "false", unit: m[5] ?? null };
  }
  return fields;
}

const f6Override = (page) => formOverride(page, PILOT_FORM.legacyKey, "F6");
const q19Override = (page) => formOverride(page, QUALITY_FORM.legacyKey, "P1-19");

// The P1-20 override is a transformation of the legacy fields (not fld() calls). The exporter consumes what it forces: the unit of espesor_*
// and the visible relabelling label.replace(from, to), applied to espesor_* and to every label containing `from`. Keys are never renamed.
function q20Override(page) {
  const start = page.indexOf(`f.id === "${PROPERTIES_FORM.legacyKey}"`);
  if (start < 0) fail("P1-20: no se encontró su override en effectiveForms() de app/page.tsx");
  const next = page.indexOf("if (f.id", start + 10);
  const block = page.slice(start, next < 0 ? undefined : next);
  const unit = block.match(/x\.key\.includes\("espesor"\)\s*\?\s*\{\s*\.\.\.x,\s*unit:\s*"([^"]*)"/);
  if (!unit) fail("P1-20: el override de app/page.tsx ya no fija la unidad de espesor");
  const espesor = block.match(/x\.key\.includes\("espesor"\)\s*\?\s*\{([^}]*)\}/)?.[1].match(/label:\s*x\.label\.replace\("([^"]*)",\s*"([^"]*)"\)/);
  const others = block.match(/x\.label\.toLowerCase\(\)\.includes\("([^"]*)"\)\s*\?\s*\{\s*\.\.\.x,\s*label:\s*x\.label\.replace\("([^"]*)",\s*"([^"]*)"\)\s*\}/);
  if (!espesor || !others) fail("P1-20: el override de app/page.tsx ya no reetiqueta las posiciones de espesor y del resto de campos");
  if (others[1] !== others[2] || espesor[1] !== others[2] || espesor[2] !== others[3]) fail("P1-20: el override de app/page.tsx reetiqueta espesor y el resto de campos de forma distinta");
  return { espesor_unit: unit[1], relabel: { from: others[2], to: others[3] } };
}

// Same rule as the override: espesor_* -> label.replace(from, to); any other label containing `from` (case-insensitive) -> idem.
export function q20Label(key, label, { from, to }) {
  return key.includes("espesor") || label.toLowerCase().includes(from) ? label.replace(from, to) : label;
}

function f6Choices(page) {
  const body = functionBody(page, "BobbinBales");
  const choices = {};
  for (const key of ["punto_merma", "tipo_producto"]) {
    const m = body.match(new RegExp(`<Choice label="([^"]+)" value=\\{v\\.${key}\\}\\s+set=\\{[^}]*\\}\\s+options=\\{\\[([^\\]]*)\\]\\}`));
    if (!m) fail(`F6: BobbinBales ya no define el selector ${key}`);
    choices[key] = { label: m[1], options: [...m[2].matchAll(/"([^"]+)"/g)].map((o) => o[1]) };
  }
  for (const key of ["cantidad_fardos", "peso_kg"]) {
    if (!body.includes(`v.${key}`)) fail(`F6: BobbinBales ya no escribe ${key}`);
  }
  return choices;
}

// Fingerprint of app/page.tsx: SHA-256 of a canonical object with only the SEMANTIC values the exporter consumes
// (already extracted and normalised), never of the raw file. Visual/authentication edits, whitespace or
// formatting changes elsewhere in the page do not alter it; changing GROUPS.Bobinas, the F6 override or the
// BobbinBales selectors/options does.
export const pageFingerprintScope = (scope = DEFAULT_SCOPE) =>
  `semantic-extract:${scope.sectors.map((s) => `groups_${s.code.toLowerCase()}`).join(",")},f6_override,f6_choices,q19_override,q20_override,shift_night_rule`;
export const PAGE_FINGERPRINT_SCOPE = pageFingerprintScope(DEFAULT_SCOPE); // "semantic-extract:groups_bobinas,f6_override,f6_choices,q19_override,q20_override,shift_night_rule"
const NIGHT_RULE = /else if \(h < 7 \|\| h >= 19\)/;

export function pageSemantics(page, scope = DEFAULT_SCOPE) {
  return {
    ...Object.fromEntries(scope.sectors.map((s) => [`groups_${s.code.toLowerCase()}`, groupMachines(page, s.front)])),
    f6_override: f6Override(page),
    q19_override: q19Override(page),
    q20_override: q20Override(page),
    f6_choices: f6Choices(page),
    shift_night_rule: NIGHT_RULE.test(page),
  };
}

export function pageFingerprint(page, scope = DEFAULT_SCOPE) {
  return sha256(canonical(pageSemantics(page, scope)));
}

// ---- scope preparation and master-data validation (pure) ------------------------------------------------------------------------

const MINUTES_PER_DAY = 1440;
const isIsoDate = (value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const dayNumber = (iso) => Math.floor(Date.parse(`${iso}T00:00:00Z`) / 86400000);
const dayIso = (n) => new Date(n * 86400000).toISOString().slice(0, 10);
const hhmm = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
function clock(value, what) {
  const match = typeof value === "string" ? /^(\d{2}):(\d{2})(?::\d{2})?$/.exec(value) : null;
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) fail(`${what}: hora inválida ${JSON.stringify(value)} (se espera HH:MM)`);
  return Number(match[1]) * 60 + Number(match[2]);
}
function validZone(zone) {
  try { new Intl.DateTimeFormat("en-US", { timeZone: zone }); return typeof zone === "string" && zone.length > 0; } catch { return false; }
}
function ranges(minutes, label) { // sorted absolute minutes -> "from–to" runs
  const runs = [];
  for (const m of minutes) {
    const last = runs[runs.length - 1];
    if (last && m === last.to + 1) last.to = m; else runs.push({ from: m, to: m });
  }
  return runs.slice(0, 3).map((r) => `${label(r.from)}–${label(r.to + 1)}`).join(", ") + (runs.length > 3 ? ` (+${runs.length - 3})` : "");
}
const localLabel = (absolute) => `${dayIso(Math.floor(absolute / MINUTES_PER_DAY))} ${hhmm(absolute % MINUTES_PER_DAY)}`;

// Which schedules cover a LOCAL wall-clock minute, with the same rule as app/shifts.py: [starts_at, ends_at) with a night shift crossing midnight; the
// operating date is the day the shift STARTED; validity is evaluated against the operating date. Assumes a zone without DST jumps (America/La_Paz).
function matchesAt(rows, absolute) {
  const day = Math.floor(absolute / MINUTES_PER_DAY), minute = absolute % MINUTES_PER_DAY;
  return rows.filter((r) => {
    let operating = null;
    if (r.start < r.end) operating = minute >= r.start && minute < r.end ? day : null;
    else if (minute >= r.start) operating = day;
    else if (minute < r.end) operating = day - 1;
    return operating !== null && operating >= r.from && (r.to === null || operating <= r.to);
  }).length;
}

// Schedules of ONE sector: well-formed, one timezone, no gaps between vigencias, every minute of the day covered exactly once inside each vigencia
// and exactly once across each change of vigencia (a change of hours can overlap or leave a gap in real time even if both regimes are fine alone).
export function validateSchedules(schedules) {
  const keys = new Set(), bySector = new Map();
  for (const s of schedules) {
    const tag = `shift_schedule ${s.sector}/${s.shift}`;
    const start = clock(s.starts_at, tag), end = clock(s.ends_at, tag);
    if (start === end) fail(`${tag}: inicio y fin iguales`);
    if (!isIsoDate(s.valid_from) || !(s.valid_to === null || isIsoDate(s.valid_to))) fail(`${tag}: vigencia con fecha inválida`);
    if (s.valid_to !== null && s.valid_to < s.valid_from) fail(`${tag}: valid_to anterior a valid_from`);
    if (!validZone(s.timezone)) fail(`${tag}: zona horaria inválida ${JSON.stringify(s.timezone)}`);
    const key = `${s.shift}|${s.sector}|${s.valid_from}`;
    if (keys.has(key)) fail(`${tag}: shift_schedule duplicado`);
    keys.add(key);
    if (!bySector.has(s.sector)) bySector.set(s.sector, []);
    bySector.get(s.sector).push({ shift: s.shift, zone: s.timezone, start, end, from: dayNumber(s.valid_from), to: s.valid_to === null ? null : dayNumber(s.valid_to) });
  }
  for (const [sector, rows] of bySector) {
    if (new Set(rows.map((r) => r.zone)).size !== 1) fail(`Horarios del sector ${sector}: todas las vigencias deben usar la misma zona horaria`);
    const bounds = [...new Set(rows.flatMap((r) => (r.to === null ? [r.from] : [r.from, r.to + 1])))].sort((a, b) => a - b);
    let previous = null;
    bounds.forEach((b, i) => {
      const next = i + 1 < bounds.length ? bounds[i + 1] : null;
      const active = rows.filter((r) => r.from <= b && (r.to === null || r.to >= b));
      if (active.length === 0) {
        if (next !== null) fail(`Horarios del sector ${sector}: no hay turnos vigentes entre ${dayIso(b)} y ${dayIso(next - 1)}`);
        previous = null; return; // every vigencia ended: nothing is configured afterwards
      }
      const cover = new Array(MINUTES_PER_DAY).fill(0);
      for (const r of active) for (let m = r.start; m !== r.end; m = (m + 1) % MINUTES_PER_DAY) cover[m] += 1;
      const hole = cover.flatMap((n, m) => (n === 0 ? [m] : [])), overlap = cover.flatMap((n, m) => (n > 1 ? [m] : []));
      if (hole.length) fail(`Horarios del sector ${sector} desde ${dayIso(b)}: minutos sin turno (hueco) ${ranges(hole, hhmm)}`);
      if (overlap.length) fail(`Horarios del sector ${sector} desde ${dayIso(b)}: turnos solapados ${ranges(overlap, hhmm)}`);
      if (previous) { // change of vigencia: simulate real time from one day before to one day after
        const bad = [];
        for (let absolute = (b - 1) * MINUTES_PER_DAY; absolute < (b + 1) * MINUTES_PER_DAY; absolute += 1) if (matchesAt(rows, absolute) !== 1) bad.push(absolute);
        if (bad.length) fail(`Horarios del sector ${sector}: el cambio de vigencia del ${dayIso(b)} deja el tiempo real sin turno o con turnos solapados (${ranges(bad, localLabel)})`);
      }
      previous = active;
    });
  }
}

// Declaration -> normalized model. Fails (SeedExportError) on duplicated/invalid codes, machines without sector, inconsistent shifts or bad schedules.
export function prepareScope(scope = DEFAULT_SCOPE) {
  if (!scope || !Array.isArray(scope.sectors) || scope.sectors.length === 0) fail("El alcance debe declarar al menos un sector");
  const sectorCodes = new Set(), machineCodes = new Set(), machineNames = new Set(), shiftNames = new Map();
  const sectors = [], machines = [], shifts = [], schedules = [];
  for (const raw of scope.sectors) {
    if (!CODE_PATTERNS.sector.test(raw?.code ?? "")) fail(`Sector con código inválido: ${JSON.stringify(raw?.code)}`);
    if (sectorCodes.has(raw.code)) fail(`Sector duplicado en el alcance: ${raw.code}`);
    sectorCodes.add(raw.code);
    if (typeof raw.name !== "string" || !raw.name.trim()) fail(`Sector ${raw.code} sin nombre`);
    if (typeof raw.front !== "string" || !raw.front.trim()) fail(`Sector ${raw.code} sin frente (clave de GROUPS en app/page.tsx)`);
    if (!Array.isArray(raw.machines) || raw.machines.length === 0) fail(`Sector ${raw.code} sin máquinas`);
    const list = raw.machines.map((m) => ({ code: m?.code, name: m?.name ?? m?.code, nameFromCode: m?.name === undefined, group: m?.group ?? m?.code, catalog: m?.catalog ?? m?.code, sector: raw.code }));
    for (const m of list) {
      if (!CODE_PATTERNS.machine.test(m.code ?? "")) fail(`Máquina con código inválido: ${JSON.stringify(m.code)}`);
      if (machineCodes.has(m.code)) fail(`Máquina duplicada en el alcance: ${m.code}`);
      machineCodes.add(m.code);
      if (typeof m.name !== "string" || !m.name.trim()) fail(`Máquina ${m.code} sin nombre`);
      const lower = m.name.trim().toLowerCase();
      if (machineNames.has(lower)) fail(`Nombre de máquina repetido: ${m.name}`);
      machineNames.add(lower);
    }
    sectors.push({ code: raw.code, name: raw.name, front: raw.front, machines: list });
    machines.push(...list);
    if (raw.shifts !== undefined && !Array.isArray(raw.shifts)) fail(`Sector ${raw.code}: shifts debe ser una lista`);
    for (const [code, name, starts_at, ends_at, valid_from, valid_to] of raw.shifts ?? []) {
      if (!CODE_PATTERNS.shift.test(code ?? "")) fail(`Turno con código inválido: ${JSON.stringify(code)}`);
      if (typeof name !== "string" || !name.trim()) fail(`Turno ${code} sin nombre`);
      if (shiftNames.has(code) && shiftNames.get(code) !== name) fail(`Turno ${code} declarado con nombres distintos: «${shiftNames.get(code)}» y «${name}»`);
      if (!shiftNames.has(code)) { shiftNames.set(code, name); shifts.push({ code, name }); }
      schedules.push({ shift: code, sector: raw.code, starts_at, ends_at, timezone: raw.timezone, valid_from: valid_from ?? raw.valid_from, valid_to: valid_to ?? null });
    }
  }
  const formsSector = sectors.find((s) => s.code === scope.forms_sector);
  if (!formsSector) fail(`forms_sector ${JSON.stringify(scope.forms_sector)} no está entre los sectores declarados`);
  const unitAliases = scope.unit_aliases ?? {};
  if (typeof unitAliases !== "object" || unitAliases === null || Array.isArray(unitAliases)) fail("unit_aliases debe ser un objeto");
  for (const [from, to] of Object.entries(unitAliases)) if (!from.trim() || !CODE_PATTERNS.unit.test(to ?? "")) fail(`unit_aliases: ${JSON.stringify(from)} → ${JSON.stringify(to)} no es un código de unidad válido`);
  const unitLabels = scope.unit_labels ?? {};
  if (typeof unitLabels !== "object" || unitLabels === null || Array.isArray(unitLabels)) fail("unit_labels debe ser un objeto");
  for (const [code, label] of Object.entries(unitLabels)) if (!CODE_PATTERNS.unit.test(code) || typeof label !== "string" || !label.trim()) fail(`unit_labels: ${JSON.stringify(code)} → ${JSON.stringify(label)} no es válido`);
  if (scope.nominal_weights !== undefined && typeof scope.nominal_weights !== "boolean") fail("nominal_weights debe ser booleano");
  validateSchedules(schedules);
  return {
    sectors, machines, shifts, schedules, unitAliases, unitLabels, nominalWeights: scope.nominal_weights !== false, formsSector, formMachines: formsSector.machines.map((m) => m.code),
    timezones: [...new Set(schedules.map((s) => s.timezone))], validFromValues: [...new Set(schedules.map((s) => s.valid_from))],
  };
}

// Master data of a generated bundle: code formats, references and schedules. Runs after the older structural checks.
function validateMasterData(read) {
  const sectors = read("sectors.json").items, machines = read("machines.json").items, articles = read("articles.json").items;
  const relations = read("article_machines.json").items, units = read("units.json").items, shiftsDoc = read("shifts.json");
  const check = (kind, items, label) => {
    const seen = new Set();
    for (const item of items) {
      if (!CODE_PATTERNS[kind].test(item.code ?? "")) fail(`${label} con código inválido: ${JSON.stringify(item.code)}`);
      if (seen.has(item.code)) fail(`${label} duplicado en el bundle: ${item.code}`);
      seen.add(item.code);
    }
  };
  check("sector", sectors, "Sector");
  check("machine", machines, "Máquina");
  check("unit", units, "Unidad");
  check("shift", shiftsDoc.shifts, "Turno");
  check("article", articles, "Artículo");
  const sectorCodes = new Set(sectors.map((s) => s.code));
  for (const m of machines) if (!sectorCodes.has(m.sector)) fail(`Máquina ${m.code} sin sector válido: ${JSON.stringify(m.sector)}`);
  const names = new Set();
  for (const m of machines) {
    if (typeof m.name !== "string" || !m.name.trim()) fail(`Máquina ${m.code} sin nombre`);
    if (names.has(m.name.trim().toLowerCase())) fail(`Nombre de máquina repetido: ${m.name}`);
    names.add(m.name.trim().toLowerCase());
  }
  const related = new Set(relations.map((r) => r.article_code));
  const seenPairs = new Set();
  for (const r of relations) {
    const pair = `${r.article_code}|${r.machine_code}`;
    if (seenPairs.has(pair)) fail(`Relación article-machine duplicada: ${r.article_code} / ${r.machine_code}`);
    seenPairs.add(pair);
  }
  for (const a of articles) if (a.is_product && !related.has(a.code)) fail(`Artículo de producto sin relación con ninguna máquina: ${a.code}`);
  const shiftCodes = new Set(shiftsDoc.shifts.map((s) => s.code));
  for (const s of shiftsDoc.schedules) {
    if (!shiftCodes.has(s.shift)) fail(`shift_schedule: turno inexistente ${s.shift}`);
    if (!sectorCodes.has(s.sector)) fail(`shift_schedule: sector inexistente ${s.sector}`);
  }
  validateSchedules(shiftsDoc.schedules);
}

// ---- bundle construction ------------------------------------------------------------------------

export function buildBundle(sources, scope = DEFAULT_SCOPE) {
  const { texts, productsByMachine, materials, formDefinitions, nominalWeights, recipes } = sources;
  const model = prepareScope(scope); // validates the declaration (codes, uniqueness, schedules) before reading anything else
  const FORM_MACHINES = model.formMachines; // the published forms keep their machines no matter how many sectors are declared
  const unitOf = (raw) => model.unitAliases[raw] ?? raw;
  const warnings = [];
  const warn = (code, severity, message, count) =>
    warnings.push(count === undefined ? { code, severity, message } : { code, severity, message, count });

  // Sectors and machines: each declared sector must match its GROUPS entry in app/page.tsx and exist in the catalog
  for (const sector of model.sectors) {
    const group = groupMachines(texts.page, sector.front);
    for (const machine of sector.machines) {
      if (!productsByMachine || !(machine.catalog in productsByMachine)) fail(`La máquina ${machine.code} no existe en PRODUCTS_BY_MACHINE`);
      if (!group.includes(machine.group)) fail(`La máquina ${machine.code} no pertenece a ${sector.name} en GROUPS de app/page.tsx`);
    }
    if (group.length !== sector.machines.length || group.some((m, i) => m !== sector.machines[i].group)) {
      fail(`GROUPS.${sector.front} es [${group}] y el alcance del piloto es [${sector.machines.map((m) => m.group)}]`);
    }
  }

  // Materials index (authoritative for material class and for "is also a material")
  const materialByCode = new Map();
  for (const item of materials) {
    const known = materialByCode.get(item.code);
    if (known && (known.name !== item.name || known.unit !== item.unit || known.className !== item.className)) {
      fail(`MATERIALS tiene el código ${item.code} duplicado con datos distintos`);
    }
    materialByCode.set(item.code, item);
  }

  // Articles (authoritative for description and unit: PRODUCTS_BY_MACHINE)
  const articles = new Map();
  const relations = [];
  for (const { code: machine, catalog } of model.machines) {
    const seenInMachine = new Set();
    for (const product of productsByMachine[catalog]) {
      const { code, name, unit } = product;
      if (typeof code !== "string" || !code.trim()) fail(`${machine}: producto sin código`);
      if (typeof name !== "string" || !name.trim()) fail(`${machine}/${code}: producto sin nombre`);
      if (typeof unit !== "string" || !unit.trim()) fail(`${machine}/${code}: artículo sin unidad (obligatoria)`);
      const known = articles.get(code);
      if (known && (known.name !== name || known.unit !== unit)) {
        fail(`Código de artículo ${code} duplicado con datos incompatibles (${known.machines[0]}: "${known.name}"/${known.unit} frente a ${machine}: "${name}"/${unit})`);
      }
      if (seenInMachine.has(code)) { warn("DUPLICATE_PRODUCT_IN_MACHINE", "warning", `${machine} repite el producto ${code} con datos idénticos; se deduplica`); continue; }
      seenInMachine.add(code);
      if (known) known.machines.push(machine);
      else articles.set(code, { code, name, unit, machines: [machine] });
      relations.push({ article_code: code, machine_code: machine });
    }
  }

  const unitCodes = [...new Set([...[...articles.values()].map((a) => unitOf(a.unit)), ...F3_FIELDS.flatMap((f) => (f.unit ? [f.unit] : []))])].sort(cmp);
  const classNames = new Map(); // slug -> className
  let alsoMaterial = 0, withoutMaterial = 0, withWeight = 0, withGrammage = 0;
  const articleItems = [...articles.values()].sort((a, b) => cmp(a.code, b.code)).map((a) => {
    const material = materialByCode.get(a.code) ?? null;
    if (material) {
      alsoMaterial++;
      if (material.name !== a.name || material.unit !== a.unit) {
        warn("MATERIAL_CONFLICT", "warning", `${a.code}: PRODUCTS_BY_MACHINE ("${a.name}"/${a.unit}) difiere de MATERIALS ("${material.name}"/${material.unit}); se conserva PRODUCTS_BY_MACHINE`);
      }
    } else withoutMaterial++;
    let classCode = null;
    if (material?.className) {
      classCode = slug(material.className);
      if (!classCode) fail(`${a.code}: className de MATERIALS no produce un código válido`);
      if (classNames.has(classCode) && classNames.get(classCode) !== material.className) {
        fail(`Las clases "${classNames.get(classCode)}" y "${material.className}" producen el mismo código ${classCode}`);
      }
      classNames.set(classCode, material.className);
    }
    const weight = model.nominalWeights ? nominalWeights?.[a.code] : undefined;
    if (weight !== undefined && !(typeof weight === "number" && weight >= 0)) fail(`${a.code}: peso nominal inválido`);
    if (weight !== undefined) withWeight++;
    const grammage = grammageFromDescription(a.name);
    if (grammage !== null) withGrammage++;
    return {
      code: a.code,
      is_product: true,
      is_material: material !== null,
      version: {
        version_number: 1,
        description: a.name,
        unit: unitOf(a.unit),
        material_class: classCode,
        nominal_weight_kg: weight ?? null,
        grammage_g_m2: grammage,
      },
    };
  });
  const articleCodes = new Set(articleItems.map((a) => a.code));
  for (const r of relations) if (!articleCodes.has(r.article_code)) fail(`Relación article-machine hacia un artículo inexistente: ${r.article_code}`);
  relations.sort((a, b) => cmp(a.article_code, b.article_code) || cmp(a.machine_code, b.machine_code));

  // Forms
  const find = (spec) => {
    const form = (formDefinitions ?? []).find((f) => f.legacyNumber === spec.legacyNumber);
    if (!form) fail(`No se encontró el formulario ${spec.legacyKey} en FORM_DEFINITIONS`);
    if (form.id !== spec.legacyKey || form.code !== spec.code) fail(`El formulario ${spec.legacyNumber} es ${form.id}/${form.code}, se esperaba ${spec.legacyKey}/${spec.code}`);
    return form;
  };
  const f6 = find(PILOT_FORM), f3 = find(NEXT_FORM);
  if (f6.area !== "production") fail(`F6 debe tener area production y tiene ${f6.area}`);
  const allowed = new Set(f6.allowedMachineIds.map((m) => m.toLowerCase()));
  for (const machine of FORM_MACHINES) if (!allowed.has(machine.toLowerCase())) fail(`F6 no admite la máquina ${machine} en allowedMachineIds`);

  const override = f6Override(texts.page);
  const choices = f6Choices(texts.page);
  const unitFromSource = (override.peso_kg?.unit ?? "").toUpperCase();
  const fields = F6_FIELDS.map((spec, index) => {
    const fromOverride = override[spec.key];
    const fromChoice = choices[spec.key];
    const label = fromOverride?.label ?? fromChoice?.label;
    if (!label) fail(`F6: no se encontró la etiqueta de ${spec.key} en app/page.tsx`);
    if (fromOverride && fromOverride.required !== spec.required) fail(`F6: ${spec.key} cambió su obligatoriedad en app/page.tsx`);
    const field = { key: spec.key, label, value_type: spec.value_type, source: "manual", required: spec.required, unit: spec.unit ?? null, display_order: index + 1 };
    if (spec.key === "peso_kg" && unitFromSource !== spec.unit) fail(`F6: la unidad de peso_kg en app/page.tsx es "${unitFromSource}", se esperaba ${spec.unit}`);
    if (spec.unit && !unitCodes.includes(spec.unit)) fail(`F6: la unidad ${spec.unit} no está entre las unidades del alcance (${unitCodes})`);
    if (spec.options) {
      if (new Set(spec.options).size !== spec.options.length) fail(`F6: opciones duplicadas en ${spec.key}`);
      if (fromChoice.options.length !== spec.options.length || new Set(fromChoice.options).size !== fromChoice.options.length) {
        fail(`F6: ${spec.key} tiene ${fromChoice.options.length} opciones en app/page.tsx y el contrato canónico espera ${spec.options.length} distintas`);
      }
      field.options = spec.options.map((option_key, i) => ({ option_key, label: fromChoice.options[i], display_order: i + 1 }));
    }
    return field;
  });
  for (const key of ["cantidad_fardos", "peso_kg", "observaciones"]) if (!override[key]) fail(`F6: el override de app/page.tsx ya no define ${key}`);
  const extra = Object.keys(override).filter((k) => !F6_FIELDS.some((f) => f.key === k));
  if (extra.length) fail(`F6: app/page.tsx define campos fuera del contrato canónico: ${extra}`);
  if (fields.length !== 5 || fields.reduce((n, f) => n + (f.options?.length ?? 0), 0) !== 5) fail("F6 debe tener exactamente 5 campos y 5 opciones");

  const definition = {
    legacy_key: f6.id,
    code: f6.code,
    legacy_number: f6.legacyNumber,
    name: f6.name,
    area: "production",
    workflow: f6.workflowId,
    version_number: 1,
    machines: [...FORM_MACHINES],
    groups: [],
    fields,
  };
  const form = { schema_version: SCHEMA_VERSION, ...definition, definition_checksum: sha256(canonical(definition)) };

  // F3 (VINTO-P1-03): only the six manual fields Operación types.
  if (f3.area !== "production") fail(`F3 debe tener area production y tiene ${f3.area}`);
  const f3Allowed = new Set(f3.allowedMachineIds.map((m) => m.toLowerCase()));
  for (const machine of FORM_MACHINES) if (!f3Allowed.has(machine.toLowerCase())) fail(`F3 no admite la máquina ${machine} en allowedMachineIds`);
  const f3Fields = F3_FIELDS.map((spec, index) => {
    const source = f3.fields.find((f) => f.key === spec.key);
    if (!source) fail(`F3: FORM_DEFINITIONS ya no define ${spec.key}`);
    if (source.type !== spec.value_type) fail(`F3: ${spec.key} es ${source.type} en FORM_DEFINITIONS y el contrato canónico espera ${spec.value_type}`);
    if (source.required !== spec.required) fail(`F3: ${spec.key} cambió su obligatoriedad en FORM_DEFINITIONS`);
    if ((source.unit ? source.unit.toUpperCase() : null) !== (spec.unit ?? null)) fail(`F3: la unidad de ${spec.key} en FORM_DEFINITIONS es ${JSON.stringify(source.unit)}, se esperaba ${spec.unit ?? null}`);
    if (!source.label) fail(`F3: ${spec.key} no tiene etiqueta en FORM_DEFINITIONS`);
    return { key: spec.key, label: source.label, value_type: spec.value_type, source: "manual", required: spec.required, unit: spec.unit ?? null, display_order: index + 1 };
  });
  const f3Definition = {
    legacy_key: f3.id,
    code: f3.code,
    legacy_number: f3.legacyNumber,
    name: f3.name,
    area: "production",
    workflow: f3.workflowId,
    version_number: 1,
    machines: [...FORM_MACHINES],
    groups: [],
    fields: f3Fields,
  };
  const f3Form = { schema_version: SCHEMA_VERSION, ...f3Definition, definition_checksum: sha256(canonical(f3Definition)) };

  // VINTO-P1-19 (Calidad · Control de humedad): only the seven manual source fields.
  const q19 = find(QUALITY_FORM);
  if (q19.area !== "quality") fail(`P1-19 debe tener area quality y tiene ${q19.area}`);
  const q19Allowed = new Set(q19.allowedMachineIds.map((m) => m.toLowerCase()));
  for (const machine of FORM_MACHINES) if (!q19Allowed.has(machine.toLowerCase())) fail(`P1-19 no admite la máquina ${machine} en allowedMachineIds`);
  const q19Source = q19Override(texts.page);
  const q19Extra = Object.keys(q19Source).filter((k) => !Q19_FIELDS.some((f) => f.key === k));
  if (q19Extra.length) fail(`P1-19: app/page.tsx define campos fuera del contrato canónico: ${q19Extra}`);
  const q19Fields = Q19_FIELDS.map((spec, index) => {
    const source = q19Source[spec.key];
    if (!source) fail(`P1-19: el override de app/page.tsx ya no define ${spec.key}`);
    if (source.type !== spec.value_type) fail(`P1-19: ${spec.key} es ${source.type} en app/page.tsx y el contrato canónico espera ${spec.value_type}`);
    if (source.required !== spec.required) fail(`P1-19: ${spec.key} cambió su obligatoriedad en app/page.tsx`);
    if ((source.unit ? source.unit.toUpperCase() : null) !== (spec.unit ?? null)) fail(`P1-19: la unidad de ${spec.key} en app/page.tsx es ${JSON.stringify(source.unit)}, se esperaba ${spec.unit ?? null}`);
    if (spec.unit && !unitCodes.includes(spec.unit)) fail(`P1-19: la unidad ${spec.unit} no está entre las unidades del alcance (${unitCodes})`);
    return { key: spec.key, label: source.label, value_type: spec.value_type, source: "manual", required: spec.required, unit: spec.unit ?? null, display_order: index + 1 };
  });
  if (q19Fields.length !== 7) fail("P1-19 debe tener exactamente 7 campos manuales");
  const q19Definition = {
    legacy_key: q19.id, code: q19.code, legacy_number: q19.legacyNumber, name: q19.name, area: "quality", workflow: q19.workflowId, version_number: 1,
    machines: [...FORM_MACHINES], groups: [], fields: q19Fields,
  };
  const q19Form = { schema_version: SCHEMA_VERSION, ...q19Definition, definition_checksum: sha256(canonical(q19Definition)) };

  // VINTO-P1-20 (Calidad · Propiedades físicas de bobina): eleven manual measurements + observaciones (provisional units).
  const q20 = find(PROPERTIES_FORM);
  if (q20.area !== "quality") fail(`P1-20 debe tener area quality y tiene ${q20.area}`);
  const q20Allowed = new Set(q20.allowedMachineIds.map((m) => m.toLowerCase()));
  for (const machine of FORM_MACHINES) if (!q20Allowed.has(machine.toLowerCase())) fail(`P1-20 no admite la máquina ${machine} en allowedMachineIds`);
  const q20SourceKeys = q20.fields.map((f) => f.key);
  const q20Unexpected = q20SourceKeys.filter((k) => !Q20_FIELDS.some((f) => f.key === k) && !(k in Q20_EXCLUDED));
  if (q20Unexpected.length) fail(`P1-20: FORM_DEFINITIONS define campos fuera del contrato canónico: ${q20Unexpected}`);
  const q20Missing = Object.keys(Q20_EXCLUDED).filter((k) => !q20SourceKeys.includes(k));
  if (q20Missing.length) fail(`P1-20: FORM_DEFINITIONS ya no define los campos excluidos ${q20Missing}; revisar el contrato`);
  const q20Page = q20Override(texts.page);
  const q20Fields = Q20_FIELDS.map((spec, index) => {
    const source = q20.fields.find((f) => f.key === spec.key);
    if (!source) fail(`P1-20: FORM_DEFINITIONS ya no define ${spec.key}`);
    if (source.source !== "manual") fail(`P1-20: ${spec.key} es ${source.source} en FORM_DEFINITIONS y el contrato canónico espera manual`);
    if (source.type !== spec.value_type) fail(`P1-20: ${spec.key} es ${source.type} en FORM_DEFINITIONS y el contrato canónico espera ${spec.value_type}`);
    if (source.required !== spec.required) fail(`P1-20: ${spec.key} cambió su obligatoriedad en FORM_DEFINITIONS`);
    if ((source.unit ?? null) !== spec.sourceUnit) fail(`P1-20: la unidad de ${spec.key} en FORM_DEFINITIONS es ${JSON.stringify(source.unit)}, se esperaba ${JSON.stringify(spec.sourceUnit)}`);
    if (spec.pageUnit !== undefined && q20Page.espesor_unit !== spec.pageUnit) fail(`P1-20: el override de app/page.tsx fija espesor en "${q20Page.espesor_unit}", se esperaba "${spec.pageUnit}"`);
    if (spec.unit && !unitCodes.includes(spec.unit)) fail(`P1-20: la unidad ${spec.unit} no está entre las unidades del alcance (${unitCodes})`);
    if (!source.label) fail(`P1-20: ${spec.key} no tiene etiqueta en FORM_DEFINITIONS`);
    return { key: spec.key, label: q20Label(spec.key, source.label, q20Page.relabel), value_type: spec.value_type, source: "manual", required: spec.required, unit: spec.unit, display_order: index + 1 };
  });
  if (q20Fields.length !== 12 || q20Fields.filter((f) => f.value_type === "decimal").length !== 11) fail("P1-20 debe tener exactamente 12 campos (11 decimales y observaciones)");
  const q20Definition = {
    legacy_key: q20.id, code: q20.code, legacy_number: q20.legacyNumber, name: q20.name, area: "quality", workflow: q20.workflowId, version_number: 1,
    machines: [...FORM_MACHINES], groups: [], fields: q20Fields,
  };
  const q20Form = { schema_version: SCHEMA_VERSION, ...q20Definition, definition_checksum: sha256(canonical(q20Definition)) };

  // Workflows used by F6/F3/P1-19/P1-20 only
  const workflowCodes = [...new Set([f6.workflowId, f3.workflowId, q19.workflowId, q20.workflowId])].sort(cmp);
  if (workflowCodes.some((c) => typeof c !== "string" || !c)) fail("Workflow sin código en F6/F3/P1-19/P1-20");

  // Shifts: declarative, cross-checked against ctx() in app/page.tsx
  if (!NIGHT_RULE.test(texts.page)) {
    warn("SHIFT_SOURCE_CHANGED", "warning", "ctx() en app/page.tsx ya no define Noche como h<7 || h>=19; revisar los horarios declarativos de Bobinas");
  }

  // ---- entity files ----
  const wrap = (entity, items) => ({ schema_version: SCHEMA_VERSION, entity, items });
  const files = new Map();
  for (const code of Object.keys(model.unitLabels)) if (!unitCodes.includes(code)) fail(`unit_labels declara la unidad ${code}, que ningún artículo ni campo usa`);
  files.set("units.json", json(wrap("unit", unitCodes.map((code) => ({ code, label: model.unitLabels[code] ?? code })))));
  files.set("material_classes.json", json(wrap("material_class", [...classNames].sort((a, b) => cmp(a[0], b[0])).map(([code, name]) => ({ code, name })))));
  files.set("sectors.json", json(wrap("sector", model.sectors.map((s) => ({ code: s.code, name: s.name })))));
  files.set("machines.json", json(wrap("machine", model.machines.map((m) => ({ code: m.code, name: m.name, sector: m.sector })))));
  files.set("articles.json", json(wrap("article", articleItems)));
  files.set("article_machines.json", json(wrap("article_machine", relations)));
  files.set("profiles.json", json(wrap("profile", PROFILES.map(([code, name]) => ({ code, name })))));
  files.set("workflows.json", json(wrap("workflow_definition", workflowCodes.map((code) => ({ code, name: code })))));
  files.set("shifts.json", json({
    schema_version: SCHEMA_VERSION,
    entity: "shift",
    note: "Vigencia valid_from provisional (fecha técnica). La vigencia funcional real debe recibirse antes de producción. No se define valid_to.",
    shifts: model.shifts,
    schedules: model.schedules,
  }));
  files.set(`forms/${PILOT_FORM.code}.json`, json(form));
  files.set(`forms/${NEXT_FORM.code}.json`, json(f3Form));
  files.set(`forms/${QUALITY_FORM.code}.json`, json(q19Form));
  files.set(`forms/${PROPERTIES_FORM.code}.json`, json(q20Form));

  // ---- warnings and out-of-scope information ----
  if (alsoMaterial) warn("ARTICLE_ALSO_MATERIAL", "info", "Artículos del alcance que también figuran en MATERIALS (is_product e is_material)", alsoMaterial);
  if (withoutMaterial) warn("ARTICLE_NOT_IN_MATERIALS", "info", "Artículos del alcance ausentes de MATERIALS: sin clase de material", withoutMaterial);
  if (articleItems.length - withWeight) warn("NOMINAL_WEIGHT_MISSING", "info", "Artículos sin peso nominal en product-weights.ts; nominal_weight_kg queda null (no se inventa)", articleItems.length - withWeight);
  if (articleItems.length - withGrammage) warn("GRAMMAGE_MISSING", "info", "Artículos sin gramaje en la descripción oficial (sin G-<número>, p. ej. tubetes o SEGUNDA); grammage_g_m2 queda null y no bloquea F3", articleItems.length - withGrammage);
  warn("UNIT_LABEL_PLACEHOLDER", "warning", "unit.label usa el código de la fuente (no existe etiqueta real); Data Baltrek debe proveerla", unitCodes.filter((c) => model.unitLabels[c] === undefined).length);
  if (!model.nominalWeights) warn("NOMINAL_WEIGHTS_DEFERRED", "info", "Los pesos nominales de product-weights.ts quedan fuera de este alcance; nominal_weight_kg es null en todos los artículos");
  warn("MACHINE_NAME_FROM_CODE", "warning", "machine.name usa el código de la fuente (no existe otro nombre)", model.machines.filter((m) => m.nameFromCode).length);
  warn("WORKFLOW_NAME_PLACEHOLDER", "warning", "workflow_definition.name usa el código de la fuente (no existe nombre real)", workflowCodes.length);
  warn("SHIFT_VALIDITY_PROVISIONAL", "warning", `valid_from=${model.validFromValues.join(", ")} y timezone=${model.timezones.join(", ")} son datos técnicos provisionales; producción debe recibir la vigencia funcional real`);
  const otherMachines = Object.keys(productsByMachine).filter((m) => !model.machines.some((x) => x.catalog === m));
  warn("OUT_OF_SCOPE_MACHINES", "info", "Máquinas de PRODUCTS_BY_MACHINE fuera del piloto (otros frentes)", otherMachines.length);
  warn("OUT_OF_SCOPE_FORMS", "info", `Definiciones de FORM_DEFINITIONS fuera del piloto (F6, F3, P1-19 y P1-20 sí se exportan)`, formDefinitions.length - 4);
  warn("P1_20_PROVISIONAL_CONTRACT", "warning", "VINTO-P1-20: unidades provisionales del MVP (espesor_* en MM; gramaje medido sin código de catálogo para g/m², unit null; crepado y resistencias sin unidad); etiquetas visibles «comando» de las claves *_centro provisionales hasta validarlas con VINTO; sin rangos ni reglas de conformidad. Requiere homologación de laboratorio");
  warn("OUT_OF_SCOPE_RECIPES", "info", "Artículos del alcance con receta en recipes.ts; las recetas no se exportan en este piloto", articleItems.filter((a) => recipes?.[a.code]).length);
  warn("OUT_OF_SCOPE_MATERIALS", "info", "Entradas de MATERIALS que no son artículos del alcance", materials.length - alsoMaterial);
  warnings.sort((a, b) => cmp(a.code, b.code) || cmp(a.message, b.message));

  const counts = {
    units: unitCodes.length,
    material_classes: classNames.size,
    sectors: model.sectors.length,
    machines: model.machines.length,
    articles: articleItems.length,
    article_machines: relations.length,
    articles_also_material: alsoMaterial,
    articles_with_nominal_weight: withWeight,
    articles_with_grammage: withGrammage,
    profiles: PROFILES.length,
    workflows: workflowCodes.length,
    shifts: model.shifts.length,
    shift_schedules: model.schedules.length,
    forms: 4,
    form_fields: fields.length + f3Fields.length + q19Fields.length + q20Fields.length,
    form_options: [...fields, ...f3Fields, ...q19Fields, ...q20Fields].reduce((n, f) => n + (f.options?.length ?? 0), 0),
  };
  const manifest = {
    schema_version: SCHEMA_VERSION,
    bundle: "vinto-reference-bobinas-pilot",
    scope: {
      sector: model.formsSector.name, machines: [...FORM_MACHINES], first_form: PILOT_FORM.code, forms: [PILOT_FORM.code, NEXT_FORM.code, QUALITY_FORM.code, PROPERTIES_FORM.code],
      // Only when more than one sector is declared (never in the current bundle): the sectors of the master data, so the scope above stays about the forms.
      ...(model.sectors.length > 1 ? { sectors: model.sectors.map((s) => ({ code: s.code, machines: s.machines.map((m) => m.code) })) } : {}),
    },
    generated_from: Object.entries(SOURCE_FILES).map(([name, path]) => (
      name === "page" ? { path, sha256: pageFingerprint(texts.page, scope), scope: pageFingerprintScope(scope) } : { path, sha256: sha256(texts[name]) }
    )).sort((a, b) => cmp(a.path, b.path)),
    files: [...files].sort((a, b) => cmp(a[0], b[0])).map(([path, text]) => ({ path, sha256: sha256(text), bytes: Buffer.byteLength(text, "utf8") })),
    counts,
    authority_rules: {
      article_description_and_unit: "PRODUCTS_BY_MACHINE",
      article_is_material_and_material_class: "MATERIALS",
      nominal_weight_kg: "product-weights.ts (null when absent)",
      sector_and_machines: "GROUPS in app/page.tsx",
      f6_labels_units_and_options: "app/page.tsx (effectiveForms override and BobbinBales)",
      f3_labels_units: "form-definitions.ts (F3 fields; the six manual fields are the canonical contract)",
      p1_19_labels_units: "app/page.tsx (effectiveForms override of form_19_control_de_humedad); only the 7 manual source fields, derived humidity is recomputed",
      p1_20_labels_units: "form-definitions.ts (labels, types, requirement); visible relabelling centro -> comando and espesor unit (mm -> MM) from the app/page.tsx override, *_centro keys unchanged; provisional units, gramaje without catalog unit; only the 12 manual fields, averages are recomputed for display",
      grammage_g_m2: "official article description (PRODUCTS_BY_MACHINE): G-<number>, '.' or ',' decimal; null when absent",
    },
    warnings,
  };
  const bundle = { files, manifest };
  validateBundle(bundle);
  files.set("manifest.json", json(manifest));
  return { files, manifest };
}

// Structural checks over the generated data (also used by tests against mutated bundles).
export function validateBundle({ files, manifest }) {
  const read = (name) => JSON.parse(files.get(name));
  const machines = read("machines.json").items.map((m) => m.code);
  const articles = read("articles.json").items;
  const codes = new Set();
  for (const a of articles) {
    if (codes.has(a.code)) fail(`Código de artículo duplicado en el bundle: ${a.code}`);
    codes.add(a.code);
    if (!a.version.unit) fail(`Artículo sin unidad: ${a.code}`);
  }
  for (const r of read("article_machines.json").items) {
    if (!codes.has(r.article_code)) fail(`Relación article-machine hacia un artículo inexistente: ${r.article_code}`);
    if (!machines.includes(r.machine_code)) fail(`Relación article-machine hacia una máquina inexistente: ${r.machine_code}`);
  }
  const unitCodes = new Set(read("units.json").items.map((u) => u.code));
  for (const a of articles) if (!unitCodes.has(a.version.unit)) fail(`Unidad no declarada: ${a.version.unit}`);
  for (const a of articles) {
    const g = a.version.grammage_g_m2;
    if (g === undefined || (g !== null && !(typeof g === "number" && g > 0))) fail(`Gramaje inválido en ${a.code}`);
  }
  for (const spec of [PILOT_FORM, NEXT_FORM, QUALITY_FORM, PROPERTIES_FORM]) {
    const form = JSON.parse(files.get(`forms/${spec.code}.json`));
    for (const f of form.fields) {
      const keys = (f.options ?? []).map((o) => o.option_key);
      if (new Set(keys).size !== keys.length) fail(`Opciones duplicadas en ${f.key}`);
      if (f.unit !== null && !unitCodes.has(f.unit)) fail(`Unidad no declarada: ${f.unit}`);
    }
  }
  validateMasterData(read);
  if (manifest) {
    for (const f of manifest.files) if (sha256(files.get(f.path)) !== f.sha256) fail(`Checksum inconsistente en el manifest: ${f.path}`);
  }
}

// ---- IO ---------------------------------------------------------------------------------------

// A non-approved scope (candidate) may only be written to a NEW or EMPTY directory that is neither inside nor above the approved bundle
// (backend/seed_data): that rules out overwriting it, writing into its forms/ folder or the cleanup of stale *.json in a parent directory.
// Paths are resolved through symlinks/junctions (nearest existing ancestor) and compared case-insensitively on Windows.
export function assertSafeCandidateOut(outDir, approvedDir = DEFAULT_OUT) {
  const real = (p) => {
    let current = resolve(p); const rest = [];
    while (!existsSync(current)) { const parent = dirname(current); if (parent === current) break; rest.unshift(current.slice(parent.length).replace(/^[\\/]+/, "")); current = parent; }
    return join(realpathSync.native(current), ...rest);
  };
  const norm = (p) => (process.platform === "win32" ? p.toLowerCase() : p);
  const out = norm(real(outDir)), approved = norm(real(approvedDir));
  const inside = (child, parent) => { const rel = relative(parent, child); return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel)); };
  if (inside(out, approved) || inside(approved, out)) fail(`--out no puede ser el bundle aprobado, estar dentro de él ni contenerlo: ${outDir}`);
  if (existsSync(outDir) && readdirSync(outDir).length > 0) fail(`--out debe ser un directorio nuevo o vacío para un alcance candidato: ${outDir}`);
}

export function writeBundle(outDir, files) {
  mkdirSync(join(outDir, "forms"), { recursive: true });
  for (const [path, text] of files) writeFileSync(join(outDir, path), text, { encoding: "utf8" });
  for (const dir of [outDir, join(outDir, "forms")]) { // drop stale generated files
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const rel = relative(outDir, join(dir, entry.name)).replaceAll("\\", "/");
      if (entry.isFile() && entry.name.endsWith(".json") && !files.has(rel)) rmSync(join(dir, entry.name));
    }
  }
}

export function compareWithDisk(outDir, files) {
  const stale = [];
  for (const [path, text] of files) {
    const target = join(outDir, path);
    if (!existsSync(target) || readFileSync(target, "utf8").replace(/\r\n/g, "\n") !== text) stale.push(path);
  }
  return stale;
}

async function main(argv) {
  const outIndex = argv.indexOf("--out");
  const outDir = outIndex >= 0 ? resolve(argv[outIndex + 1] ?? fail("--out requiere un directorio")) : DEFAULT_OUT;
  const scopeIndex = argv.indexOf("--scope");
  const scopeName = scopeIndex >= 0 ? (argv[scopeIndex + 1] ?? fail("--scope requiere un nombre (approved|candidate)")) : "approved";
  if (!Object.hasOwn(SCOPES, scopeName)) fail(`Alcance desconocido: ${scopeName}. Opciones: ${Object.keys(SCOPES).join(", ")}`);
  if (scopeName !== "approved") {
    if (outIndex < 0) fail(`El alcance ${scopeName} es un candidato: indica --out con un directorio nuevo fuera de backend/seed_data`);
    if (argv.includes("--check")) fail(`--check solo verifica el bundle aprobado, no el alcance ${scopeName}`);
    assertSafeCandidateOut(outDir);
  }
  const { files, manifest } = buildBundle(await loadSources(), SCOPES[scopeName]);
  if (argv.includes("--check")) {
    const stale = compareWithDisk(outDir, files);
    if (stale.length) { console.error(`Bundle desactualizado: ${stale.join(", ")}. Ejecuta node scripts/export-seed-data.mjs`); return 1; }
    console.log(`Bundle al día (${files.size} archivos).`);
    return 0;
  }
  writeBundle(outDir, files);
  console.log(`Bundle escrito: ${files.size} archivos en ${relative(ROOT, outDir) || "."}`);
  for (const [name, value] of Object.entries(manifest.counts)) console.log(`  ${name}: ${value}`);
  for (const w of manifest.warnings) console.log(`  [${w.severity}] ${w.code}${w.count === undefined ? "" : ` (${w.count})`}: ${w.message}`);
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (error) => {
    if (error instanceof SeedExportError) { console.error(`Exportación detenida: ${error.message}`); process.exitCode = 1; }
    else throw error;
  });
}
