// node --test scripts/mf13-02-access.test.mjs
// MF-13-02 · Frontend por permisos y concesiones. Elegibilidad (la decide el backend), frentes visibles, estados sin confirmar, revalidación y salvaguardas de código fuente.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";

import { parseAvailability } from "../lib/vinto/availability.ts";
import { accessGateCopy } from "../lib/vinto/access-copy.ts";
import { submitAttemptOf } from "../lib/vinto/capture-core.ts";
import { F3_CODE, F6_CODE, deriveAccess, effectiveFront, eligibleMachineCodes, offersForm, onlyEligible, qualityBobbinActions, visibleFronts } from "../lib/vinto/eligibility.ts";
import { failureKindFromStatus } from "../lib/vinto/orders.ts";
import { REVALIDATION_MIN_INTERVAL_MS, requestRevalidation, resetRevalidationForTests, subscribeRevalidation } from "../lib/vinto/revalidation.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");

const form = (code, eligible) => ({ code, name: code, version_number: 1, ...(eligible === undefined ? {} : { eligible }) });
const machine = (code, forms = [], bobbin_forms) => ({ code, name: code, forms, ...(bobbin_forms ? { bobbin_forms } : {}) });
const sector = (code, machines) => ({ code, name: code, machines });
const avail = (...sectors) => ({ sectors });
const ready = (data) => ({ status: "ready", data });
const idle = { status: "idle" };

// Producción tal como la devuelve el backend: Bobinas MP1/MP3 con F3 en bobbin_forms; Rebobinado y Conversión con un formulario central cada una.
const production = (flags = {}) => avail(
  sector("BOBINAS", [
    machine("MP1", [form("VINTO-P1-06", flags.mp1f6 ?? false), form("VINTO-P1-04", flags.mp1p104 ?? false)], [form(F3_CODE, flags.mp1f3 ?? false)]),
    machine("MP3", [form("VINTO-P1-06", flags.mp3f6 ?? false)], [form(F3_CODE, flags.mp3f3 ?? false)]),
  ]),
  sector("REBOBINADO", [machine("Beloit", [form("VINTO-P1-10", flags.reb ?? false)])]),
  sector("CONVERSION", [machine("Gambini", [form("VINTO-P1-11", flags.conv ?? false)])]),
);
const qualityBobbin = (humidity = false, physical = false, p121 = false) => avail(sector("BOBINAS", [machine("MP1", [form("VINTO-P1-21", p121)], [form("VINTO-P1-19", humidity), form("VINTO-P1-20", physical)])]));
const qualityMachine = (eligible = false) => avail(sector("BOBINAS", [machine("MP1", [form("VINTO-P1-22", eligible)])]));
const base = { canManage: false, canQuality: false, qualityBobbin: null, qualityMachine: null };

test("el parser conserva eligible y bobbin_forms, y rechaza tipos inválidos", () => {
  const parsed = parseAvailability(production({ mp1f3: true }));
  assert.equal(parsed.sectors[0].machines[0].bobbin_forms[0].eligible, true);
  assert.equal(parsed.sectors[0].machines[0].forms[0].eligible, false);
  assert.equal(parseAvailability({ sectors: [sector("BOBINAS", [machine("MP1", [{ ...form("VINTO-P1-06"), eligible: "yes" }])])] }), null);
  assert.equal(parseAvailability({ sectors: [sector("BOBINAS", [{ ...machine("MP1"), bobbin_forms: "x" }])] }), null);
  assert.equal(parseAvailability({ sectors: [sector("BOBINAS", [machine("MP1", [form("VINTO-P1-06")])])] }).sectors[0].machines[0].forms[0].eligible, undefined, "respuesta sin el campo: se acepta, pero no es elegible");
});

test("falla cerrado: sin el campo eligible o con false nada se muestra", () => {
  assert.deepEqual(onlyEligible(avail(sector("BOBINAS", [machine("MP1", [form("VINTO-P1-06")])]))), { sectors: [] });
  assert.deepEqual(onlyEligible(production()), { sectors: [] });
  assert.equal(offersForm(machine("MP1", [form("VINTO-P1-06")]), "VINTO-P1-06"), false);
});

test("por máquina y formulario: solo se ofrece el par que el backend marca elegible", () => {
  const only = onlyEligible(production({ mp1f6: true, mp1f3: true }));
  assert.deepEqual(eligibleMachineCodes(only, "BOBINAS"), ["MP1"]);
  const mp1 = only.sectors[0].machines[0];
  assert.equal(offersForm(mp1, F6_CODE), true);
  assert.equal(offersForm(mp1, F3_CODE), true);
  assert.equal(offersForm(mp1, "VINTO-P1-04"), false, "otro formulario de la misma máquina no elegible queda oculto");
  assert.equal(mp1.forms.length, 1);
  assert.deepEqual(eligibleMachineCodes(onlyEligible(production({ mp3f6: true })), "BOBINAS"), ["MP3"]);
  assert.deepEqual(eligibleMachineCodes(onlyEligible(production({ reb: true })), "BOBINAS"), [], "Bobinas sin elegibles: no hay máquinas");
});

test("por perfil: frentes visibles según permisos de gestión, calidad y elegibilidad", () => {
  // Operación sin concesiones: nada. Con una concesión de Rebobinado: solo Rebobinado.
  assert.deepEqual(visibleFronts({ ...base, production: production() }), []);
  assert.deepEqual(visibleFronts({ ...base, production: production({ reb: true }) }), ["Rebobinado"]);
  assert.deepEqual(visibleFronts({ ...base, production: production({ mp1f3: true, conv: true }) }), ["Bobinas", "Conversión"]);
  // Jefatura / Supervisión (gestionan): ven los sectores de su alcance aunque no tengan concesiones; un sector fuera de alcance no aparece.
  assert.deepEqual(visibleFronts({ ...base, canManage: true, production: production() }), ["Bobinas", "Rebobinado", "Conversión"]);
  assert.deepEqual(visibleFronts({ ...base, canManage: true, production: avail(sector("REBOBINADO", [machine("Beloit")])) }), ["Rebobinado"]);
  assert.deepEqual(visibleFronts({ ...base, canManage: true, production: avail(sector("BOBINAS", [])) }), [], "un sector sin máquinas operativas no es un frente");
  // Calidad: quality.capture + algún formulario elegible (por bobina o por máquina).
  const q = { ...base, canQuality: true, production: avail() };
  assert.deepEqual(visibleFronts({ ...q, qualityBobbin: qualityBobbin(), qualityMachine: qualityMachine() }), []);
  assert.deepEqual(visibleFronts({ ...q, qualityBobbin: qualityBobbin(true), qualityMachine: qualityMachine() }), ["Calidad"]);
  assert.deepEqual(visibleFronts({ ...q, qualityBobbin: qualityBobbin(), qualityMachine: qualityMachine(true) }), ["Calidad"]);
  assert.deepEqual(visibleFronts({ ...q, canQuality: false, qualityBobbin: qualityBobbin(true), qualityMachine: qualityMachine(true) }), [], "sin quality.capture no hay frente de Calidad");
  // Perfil con Producción y Calidad: ambos frentes según cada elegibilidad.
  assert.deepEqual(visibleFronts({ ...base, canQuality: true, production: production({ mp1f6: true }), qualityBobbin: qualityBobbin(false, true), qualityMachine: qualityMachine() }), ["Bobinas", "Calidad"]);
});

test("Calidad: P1-19 y P1-20 se ofrecen por máquina solo si son elegibles; P1-21 no concede las acciones", () => {
  assert.deepEqual(qualityBobbinActions(qualityBobbin(true, false), "MP1"), { humidity: true, physical: false });
  assert.deepEqual(qualityBobbinActions(qualityBobbin(false, true), "MP1"), { humidity: false, physical: true });
  assert.deepEqual(qualityBobbinActions(qualityBobbin(false, false, true), "MP1"), { humidity: false, physical: false });
  assert.deepEqual(qualityBobbinActions(qualityBobbin(true, true), "MP9"), { humidity: false, physical: false }, "máquina no listada");
  assert.deepEqual(qualityBobbinActions(null, "MP1"), { humidity: false, physical: false }, "sin disponibilidad confirmada: ninguna acción");
});

test("revocación: la misma respuesta con eligible=false retira el frente y el formulario", () => {
  const granted = production({ mp1f6: true, reb: true });
  assert.deepEqual(visibleFronts({ ...base, production: granted }), ["Bobinas", "Rebobinado"]);
  const afterRevoke = production({ mp1f6: false, reb: true });
  assert.deepEqual(visibleFronts({ ...base, production: afterRevoke }), ["Rebobinado"]);
  assert.equal(effectiveFront(["Rebobinado"], "Bobinas"), "Rebobinado", "el frente elegido ya no es visible: se pasa al primero visible");
  assert.equal(effectiveFront([], "Bobinas"), null);
  assert.equal(effectiveFront(["Bobinas", "Calidad"], "Calidad"), "Calidad");
});

test("estados: 401 es sesión, 403 denegado, 404/503/red sin confirmar; nunca se confirman accesos con un error", () => {
  const input = (production_, extra = {}) => ({ canManage: false, canQuality: false, production: production_, qualityBobbin: idle, qualityMachine: idle, ...extra });
  assert.deepEqual(deriveAccess(input({ status: "loading" })), { status: "loading" });
  assert.deepEqual(deriveAccess(input(idle)), { status: "loading" });
  for (const status of [0, 500, 502, 503, 504]) assert.deepEqual(deriveAccess(input({ status: "error", kind: failureKindFromStatus(status) })), { status: "unconfirmed" }, String(status));
  assert.equal(failureKindFromStatus(401), "session");
  assert.deepEqual(deriveAccess(input({ status: "error", kind: failureKindFromStatus(401) })), { status: "unconfirmed" }, "el 401 además cierra la sesión (onUnauthorized); aquí tampoco confirma nada");
  assert.deepEqual(deriveAccess(input({ status: "error", kind: failureKindFromStatus(403) })), { status: "denied" });
  assert.deepEqual(deriveAccess(input({ status: "error", kind: failureKindFromStatus(404) })), { status: "unconfirmed" });
  // Un fallo de Calidad (503) tampoco confirma el resto cuando la sesión necesita Calidad.
  assert.deepEqual(deriveAccess(input(ready(production({ mp1f6: true })), { canQuality: true, qualityBobbin: { status: "error", kind: "unavailable" }, qualityMachine: ready(qualityMachine()) })), { status: "unconfirmed" });
  // Sin quality.capture los listados de Calidad no se piden ni se esperan.
  assert.deepEqual(deriveAccess(input(ready(production({ mp1f6: true })))), { status: "ready", fronts: ["Bobinas"] });
  assert.deepEqual(deriveAccess(input(ready(production()), { canQuality: true, qualityBobbin: { status: "loading" }, qualityMachine: ready(qualityMachine()) })), { status: "loading" });
});

test("pantalla de accesos: sin motivos internos y con reintento solo cuando no se confirmó", () => {
  assert.equal(accessGateCopy({ status: "unconfirmed" }).retry, true);
  assert.equal(accessGateCopy({ status: "loading" }).retry, false);
  assert.equal(accessGateCopy({ status: "ready", fronts: [] }).title, "Sin accesos asignados");
  const all = [{ status: "loading" }, { status: "unconfirmed" }, { status: "denied" }, { status: "ready", fronts: [] }].map(accessGateCopy).map((c) => `${c.title} ${c.message}`).join(" ").toLowerCase();
  for (const leak of ["concesión", "concesion", "perfil", "sector", "política", "politica", "versión", "version", "grant", "permiso"]) assert.equal(all.includes(leak), false, leak);
});

test("revalidación: el bus avisa a los suscritos, limita ráfagas y se puede cancelar", () => {
  resetRevalidationForTests();
  let calls = 0;
  const off = subscribeRevalidation(() => { calls += 1; });
  assert.equal(requestRevalidation(10_000), true);
  assert.equal(requestRevalidation(10_000 + REVALIDATION_MIN_INTERVAL_MS - 1), false);
  assert.equal(requestRevalidation(10_000 + REVALIDATION_MIN_INTERVAL_MS), true);
  assert.equal(calls, 2);
  off();
  requestRevalidation(99_000);
  assert.equal(calls, 2);
  resetRevalidationForTests();
});

test("un 403 o un 404 de captura dispara la revalidación; 422, 409 y errores de red no", async () => {
  const attempt = { captureId: "c", payload: {} };
  const outcome = async (status, code) => { resetRevalidationForTests(); let n = 0; subscribeRevalidation(() => { n += 1; }); const r = await submitAttemptOf(attempt, { post: async () => ({ ok: false, kind: "x", status, code }), get: async () => ({ ok: false, kind: "x", status: 503 }) }); return [r.kind === "rejected" ? r.reason : r.kind, n]; };
  assert.deepEqual(await outcome(403), ["forbidden", 1]);
  assert.deepEqual(await outcome(404), ["not_found", 1]);
  assert.deepEqual(await outcome(422), ["invalid", 0]);
  assert.deepEqual(await outcome(409, "ASSIGNMENT_STALE"), ["stale", 0]);
  assert.equal((await outcome(503))[1], 0, "503 es incierto, no un cambio de acceso");
  resetRevalidationForTests();
});

test("salvaguardas de código fuente: la página usa la elegibilidad del backend y no listas locales para decidir qué mostrar", () => {
  const page = read("app/page.tsx"), sector = read("components/vinto/sector-central.tsx"), machines = read("components/vinto/quality-machine-controls.tsx"), inbox = read("components/vinto/quality-bobbin-inbox.tsx");
  assert.match(page, /\{fronts\.map\(x =>/, "el menú solo dibuja los frentes visibles");
  assert.equal(/\(\["Bobinas", "Rebobinado", "Conversión", "Calidad"\] as Front\[\]\)\.map/.test(page), false, "ya no hay menú estático de frentes");
  assert.match(page, /<Execution [^>]*machines=\{bobMachines\}/);
  assert.match(page, /offersForm\(bobEligibleMachine, f\.id === F3_FORM_ID \? F3_CODE : F6_CODE\)/);
  assert.match(page, /if \(access\.state\.status !== "ready" \|\| fronts\.length === 0\)\s+return <AccessGate /);
  assert.match(sector, /module === "ejecucion" \? onlyEligible\(availability\.view\.data\) : availability\.view\.data/, "solo Ejecución filtra; Programación y Seguimiento se rigen por permiso y alcance");
  assert.match(machines, /onlyEligible\(forms\.view\.data\)/);
  assert.match(inbox, /actionOffers\?\.\(i\.bobbin\.machine\.code\)\.humidity \?\? true/);
  // La gate de borradores va ANTES de la pantalla de accesos: un intento pendiente nunca se descarta por perder un acceso.
  assert.ok(page.indexOf("<F3BobbinCapture") < page.indexOf("<AccessGate "), "los borradores se tratan antes de la pantalla de accesos");
  assert.ok(page.indexOf("<QualityHumidityCapture") < page.indexOf("<AccessGate "));
  assert.equal(/localStorage|sessionStorage/.test(read("lib/vinto/use-access.ts") + read("lib/vinto/eligibility.ts") + read("lib/vinto/revalidation.ts")), false, "nada de la elegibilidad se persiste en el navegador");
});

test("Administración se conserva para user.manage aunque no haya frentes: la pantalla de accesos enlaza a /admin por permiso", () => {
  const gate = read("components/vinto/access-gate.tsx"), page = read("app/page.tsx"), technical = read("components/vinto/technical-view.tsx");
  assert.match(gate, /canAdminister\(user\)/);
  assert.match(gate, /href="\/admin"/);
  assert.match(page, /hasPermission\(user, "user\.manage"\) && <a href="\/admin"/);
  assert.match(technical, /canAdminister\(user\)/);
});
