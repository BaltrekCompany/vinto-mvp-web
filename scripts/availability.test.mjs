// node --test scripts/availability.test.mjs
// M4-A · disponibilidad de Rebobinado verificada por el backend: parser estricto, vista habilitada/deshabilitada, formularios ofrecidos por máquina, y salvaguardas de código fuente
// (sin localStorage ni respaldo demo en la ruta central, sin habilitar Rebobinado ni P1-10/P1-29 en la configuración productiva).
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";

import { CONVERSION_DISABLED_TITLE, DISABLED_TITLE, articlesOf, conversionView, offeredForms, parseAvailability, rebobinadoView, screenFor, sectorView } from "../lib/vinto/availability.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const code = (file) => read(file).replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");

const FORM10 = { code: "VINTO-P1-10", name: "Registro de fardos", version_number: 1 };
const FORM29 = { code: "VINTO-P1-29", name: "Producción Tubetera", version_number: 2 };
const payload = (sectors) => ({ sectors });
const REB = { code: "REBOBINADO", name: "Rebobinado", machines: [{ code: "COPASA", name: "Copasa", forms: [FORM10], articles: [{ code: "ART-1", description: "Artículo ficticio" }] }, { code: "TUBETERA", name: "Tubetera", forms: [FORM29] }] };

test("parseAvailability acepta la respuesta bien formada y conserva el orden", () => {
  const parsed = parseAvailability(payload([REB]));
  assert.deepEqual(parsed.sectors[0].machines.map((m) => m.code), ["COPASA", "TUBETERA"]);
  assert.deepEqual(articlesOf(parsed.sectors[0].machines[0]).map((a) => a.code), ["ART-1"]);
  assert.deepEqual(articlesOf(parsed.sectors[0].machines[1]), []);
});

test("parseAvailability es estricto: un elemento mal formado invalida toda la respuesta", () => {
  for (const bad of [null, [], {}, { sectors: "x" }, payload([{ code: "R", name: "R" }]), payload([{ ...REB, machines: [{ code: "C", name: "C" }] }]),
    payload([{ ...REB, machines: [{ code: "C", name: "C", forms: [{ code: "F", name: "n", version_number: 1.5 }] }] }]),
    payload([{ ...REB, machines: [{ code: "C", name: "C", forms: [], articles: [{ code: "A" }] }] }])]) assert.equal(parseAvailability(bad), null);
});

test("rebobinadoView: sin sector o sin máquinas = deshabilitado; con máquinas = listo", () => {
  assert.deepEqual(rebobinadoView(parseAvailability(payload([]))), { kind: "disabled" });
  assert.deepEqual(rebobinadoView(parseAvailability(payload([{ code: "BOBINAS", name: "Bobinas", machines: [{ code: "MP1", name: "MP1", forms: [] }] }]))), { kind: "disabled" });
  assert.deepEqual(rebobinadoView(parseAvailability(payload([{ ...REB, machines: [] }]))), { kind: "disabled" });
  assert.equal(rebobinadoView(parseAvailability(payload([REB]))).kind, "ready");
  assert.ok(DISABLED_TITLE.includes("no está habilitado"));
});

test("los formularios ofrecidos son solo los que el backend publica para la máquina; sin pantalla no se abren", () => {
  const view = rebobinadoView(parseAvailability(payload([REB])));
  assert.deepEqual(offeredForms(view.sector.machines[0]).map((o) => [o.form.code, o.screen]), [["VINTO-P1-10", "p110"]]);
  assert.deepEqual(offeredForms(view.sector.machines[1]).map((o) => [o.form.code, o.screen]), [["VINTO-P1-29", "p129"]]);
  assert.equal(screenFor("VINTO-P1-99"), null);
  assert.deepEqual(offeredForms({ code: "X", name: "X", forms: [{ code: "VINTO-P1-99", name: "n", version_number: 1 }] }).map((o) => o.screen), [null]);
});

test("la ruta central de Rebobinado no usa almacenamiento del navegador ni datos demo/legacy", () => {
  for (const file of ["components/vinto/sector-central.tsx", "components/vinto/rebobinado-central.tsx", "components/vinto/conversion-central.tsx", "components/vinto/central-form-history.tsx", "lib/vinto/availability.ts", "lib/vinto/production-api.ts"]) {
    assert.equal(/localStorage|sessionStorage|document\.cookie|vinto-ot|vinto-asg|vinto-p1-records|form-definitions|GROUPS\b/.test(code(file)), false, file);
  }
});

test("Home: Rebobinado se renderiza con RebobinadoCentral y el legacy queda en la rama alterna, no como respaldo", () => {
  const page = read("app/page.tsx");
  assert.match(page, /front === "Rebobinado" \? <RebobinadoCentral/);
  assert.ok(page.includes("<RebobinadoCentral module={activeModule}") && page.includes("onSessionLost={sessionLost}/> : <>"));
  assert.match(page, /P110CaptureForm/);
  assert.match(page, /P129CaptureForm/);
});

test("BobbinasProgramming: las props genéricas son opcionales, así Bobinas no cambia", () => {
  const source = read("components/vinto/bobinas-programming.tsx");
  assert.match(source, /catalog\?:/);
  assert.match(source, /sectorLabel\?:/);
});

test("la configuración productiva no habilita Rebobinado ni P1-10/P1-29 y no hay banderas de entorno", () => {
  assert.match(read("backend/app/sectors.py"), /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
  const service = read("backend/app/capture_service.py");
  assert.match(service, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  assert.equal(/CENTRAL_FORM_CODES[^\n]*P1-(10|29)/.test(service), false);
  const access = read("backend/app/production_access.py");
  assert.equal(/os\.environ|getenv/.test(access), false);
  assert.match(access, /SET TRANSACTION READ ONLY/);
  assert.equal(/INSERT|UPDATE |DELETE/.test(access.replace(/--[^\n]*/g, "")), false);
});

// ---- M6-A: el mismo shell para Conversión (candidato), sin tocar Rebobinado ----------------------------------------------------------------

const FORM16 = { code: "VINTO-P1-16", name: "Registro de control de merma", version_number: 1 };
const CONV = { code: "CONVERSION", name: "Conversión", machines: [{ code: "GAMBINI", name: "Gambini", forms: [FORM16] }, { code: "WALLY", name: "Wally", forms: [] }] };

test("M6-A: conversionView depende solo de lo que el backend devuelve; Rebobinado y Conversión no se confunden", () => {
  assert.deepEqual(conversionView(parseAvailability(payload([]))), { kind: "disabled" });
  assert.deepEqual(conversionView(parseAvailability(payload([REB]))), { kind: "disabled" }); // Rebobinado listo no habilita Conversión
  assert.deepEqual(rebobinadoView(parseAvailability(payload([CONV]))), { kind: "disabled" }); // ni al revés
  assert.deepEqual(conversionView(parseAvailability(payload([{ ...CONV, machines: [] }]))), { kind: "disabled" });
  const both = parseAvailability(payload([REB, CONV]));
  assert.equal(conversionView(both).kind, "ready");
  assert.equal(conversionView(both).sector.code, "CONVERSION");
  assert.equal(rebobinadoView(both).sector.code, "REBOBINADO");
  assert.deepEqual(sectorView(both, "BOBINAS"), { kind: "disabled" });
  assert.ok(CONVERSION_DISABLED_TITLE.includes("Conversión no está habilitado"));
});

test("M6-A: P1-16 tiene pantalla central solo si el backend lo publica para la máquina; P1-10 y P1-29 no cambian", () => {
  const view = conversionView(parseAvailability(payload([CONV])));
  assert.deepEqual(offeredForms(view.sector.machines[0]).map((o) => [o.form.code, o.screen]), [["VINTO-P1-16", "p116"]]);
  assert.deepEqual(offeredForms(view.sector.machines[1]), []); // WALLY: sin relación formulario-máquina no se ofrece nada
  assert.equal(screenFor("VINTO-P1-10"), "p110");
  assert.equal(screenFor("VINTO-P1-29"), "p129");
});

test("M6-A: Home enruta Conversión al shell central y deja Rebobinado y Bobinas tal cual; los registros locales no se leen ni se borran", () => {
  const page = read("app/page.tsx");
  assert.match(page, /front === "Conversión" \? <ConversionCentral module=\{activeModule\}/);
  assert.match(page, /: front === "Rebobinado" \? <RebobinadoCentral module=\{activeModule\}/);
  assert.ok(page.includes("onSessionLost={sessionLost}/> : <>")); // la rama de Bobinas / Calidad sigue después de Rebobinado
  assert.match(page, /convCapture && front === "Conversión" && convCapture\.screen === "p116"/);
  assert.match(page, /setConvCapture\(null\); setP116Attempt\(null\); setP116Context\(null\)/); // sesión perdida y logout limpian el intento de Conversión
  assert.equal((page.match(/setP116Attempt\(null\); setP116Context\(null\)/g) ?? []).length, 2);
  // el código de la ruta central no escribe ni borra las claves legacy (se conservan intactas en el navegador)
  for (const file of ["components/vinto/sector-central.tsx", "components/vinto/conversion-central.tsx", "components/vinto/p1-16-capture.tsx"]) assert.equal(/removeItem|localStorage|vinto-ot|vinto-asg|vinto-p1-records/.test(code(file)), false, file);
});

test("M6-A: la configuración productiva no cambia (Conversión sigue sin habilitar y P1-16 fuera de la política)", () => {
  const sectors = read("backend/app/sectors.py"), policy = read("backend/app/capture_service.py");
  assert.match(sectors, /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
  assert.match(policy, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  assert.equal(/P1-16/.test(code("backend/app/capture_service.py")), false);
  assert.equal(existsSync(join(root, "backend/seed_data/forms/VINTO-P1-16.json")), false); // el formulario candidato no está en el bundle oficial
});
