// node --test scripts/int-01-session-scope.test.mjs
// INT-01B · aislamiento multiusuario de TODOS los recursos centrales: ninguna clave es constante, todas llevan la identidad de la sesión (sessionScope), y el estado de pantalla de una cuenta (intentos pendientes,
// selecciones) se descarta al cerrar sesión, perderla o cambiar de usuario. Lógica PURA sobre las claves y deriveView, más comprobaciones estructurales del código: no hay DOM ni red.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import {
  activeAssignmentKey, assignmentsKey, availabilityKey, candidateHistoryKey, deriveView, qualityHistoryKey, qualityInboxKey, sessionScope, workOrdersKey,
} from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };
const BOBBIN_1 = "7d6e5f4a-3b2c-4d1e-8f0a-9b8c7d6e5f4a", BOBBIN_2 = "8e7f6a5b-4c3d-4e2f-9a1b-0c9d8e7f6a5b";

// Todas las claves de recursos sensibles para una cuenta (y su refresco), para comprobarlas de una vez.
const keysFor = (user, refresh = 0) => {
  const scope = sessionScope(user);
  return {
    workOrders: workOrdersKey(scope), assignments: assignmentsKey(scope), activeMP1: activeAssignmentKey("MP1", scope), activeMP3: activeAssignmentKey("MP3", scope),
    availBase: availabilityKey(false, scope), availArticles: availabilityKey(true, scope), f6: candidateHistoryKey("f6", scope, refresh), inbox: qualityInboxKey(scope),
    historyB1: qualityHistoryKey(scope, BOBBIN_1, 1), historyB2: qualityHistoryKey(scope, BOBBIN_2, 1), historyNone: qualityHistoryKey(scope, null, 0),
    p110: candidateHistoryKey("p110", scope, refresh), p129: candidateHistoryKey("p129", scope, refresh), p111: candidateHistoryKey("p111", scope, refresh), p112: candidateHistoryKey("p112", scope, refresh),
    p113: candidateHistoryKey("p113", scope, refresh), p116: candidateHistoryKey("p116", scope, refresh), p130: candidateHistoryKey("reb-p130", scope, refresh), p107: candidateHistoryKey("reb-p107", scope, refresh),
    machineP122MP1: candidateHistoryKey("p122-MP1", scope, refresh), machineP122MP3: candidateHistoryKey("p122-MP3", scope, refresh), bobbinP121B1: candidateHistoryKey(`p121-${BOBBIN_1}`, scope, refresh),
    bobbinP121B2: candidateHistoryKey(`p121-${BOBBIN_2}`, scope, refresh),
  };
};

test("las claves de todos los recursos sensibles incluyen la identidad de la sesión: ninguna coincide entre dos cuentas y ninguna es constante", () => {
  const a = keysFor(A), b = keysFor(B), anon = keysFor(null);
  for (const name of Object.keys(a)) {
    assert.ok(a[name].includes(A.id), `${name}: lleva el id de A`);
    assert.ok(b[name].includes(B.id), `${name}: lleva el id de B`);
    assert.notEqual(a[name], b[name], name);
    assert.notEqual(a[name], anon[name], `${name}: sin sesión nunca coincide con una cuenta`);
    assert.equal(a[name].includes(B.id), false, name);
  }
  assert.equal(new Set(Object.values(a)).size, Object.keys(a).length, "las claves de recursos distintos no colisionan entre sí");
  assert.equal(Object.values(a).includes("work-orders") || Object.values(a).includes("assignments") || Object.values(a).includes("captures-f6") || Object.values(a).includes("quality-bobbin-inbox"), false);
});

test("las claves distinguen máquina, bobina, apertura del historial y refresco dentro de una misma sesión", () => {
  const k = keysFor(A);
  assert.notEqual(k.activeMP1, k.activeMP3);
  assert.notEqual(k.historyB1, k.historyB2);
  assert.notEqual(k.historyB1, qualityHistoryKey(sessionScope(A), BOBBIN_1, 2), "reabrir el historial usa otra clave");
  assert.notEqual(k.machineP122MP1, k.machineP122MP3);
  assert.notEqual(k.bobbinP121B1, k.bobbinP121B2);
  assert.notEqual(k.f6, keysFor(A, 1).f6, "tras un envío se recarga");
  assert.notEqual(k.availBase, k.availArticles);
  for (const value of Object.values(k)) assert.equal(/token|cookie|secret|password|session_id|bearer/i.test(value), false, "las claves no contienen secretos");
});

test("invariante A -> cierre de sesión -> B: ninguna vista de A se presenta a B, ni durante la carga, para cada recurso", () => {
  const a = keysFor(A), b = keysFor(B);
  for (const name of Object.keys(a)) {
    const stored = { key: a[name], attempt: 0, result: { ok: true, data: [{ id: `dato-de-A-${name}` }] } };
    assert.equal(deriveView(a[name], true, 0, stored).status, "ready", `${name}: A ve lo suyo`);
    const loadingForB = deriveView(b[name], true, 0, stored);
    assert.equal(loadingForB.status, "loading", `${name}: B sin resultado propio está «cargando»`);
    assert.equal(JSON.stringify(loadingForB).includes("dato-de-A"), false, name);
    assert.equal(deriveView(b[name], false, 0, stored).status, "idle", `${name}: deshabilitado no muestra nada`);
    const errored = { key: a[name], attempt: 0, result: { ok: false, kind: "unavailable" } };
    assert.equal(deriveView(b[name], true, 0, errored).status, "loading", `${name}: el error de A tampoco se presenta a B`);
    const refreshingForB = deriveView(b[name], true, 1, stored);
    assert.equal(refreshingForB.status, "loading", `${name}: un reintento de B no reutiliza datos de A`);
  }
});

test("una solicitud de A que termina DESPUÉS de que B inició sesión no se presenta a B y B recibe solo su propio resultado", () => {
  const a = keysFor(A), b = keysFor(B);
  for (const name of ["workOrders", "assignments", "f6", "inbox", "p110", "historyB1", "availBase"]) {
    // la solicitud de A resuelve tarde: se guarda con la clave de A mientras la vista ya es la de B
    let stored = { key: a[name], attempt: 0, result: { ok: true, data: ["tardío-de-A"] } };
    assert.equal(deriveView(b[name], true, 0, stored).status, "loading", `${name}: el resultado tardío de A no es de B`);
    assert.equal(JSON.stringify(deriveView(b[name], true, 0, stored)).includes("tardío-de-A"), false);
    // después llega el resultado de B
    stored = { key: b[name], attempt: 0, result: { ok: true, data: ["de-B"] } };
    const view = deriveView(b[name], true, 0, stored);
    assert.deepEqual([view.status, view.data], ["ready", ["de-B"]]);
    // y si luego aún llegara otro resultado tardío de A, B tampoco lo ve (la vista de A seguiría siendo de A)
    assert.equal(deriveView(a[name], true, 0, stored).status, "loading");
  }
  // recarga y errores: el estado de error de B es de B
  const errB = { key: b.inbox, attempt: 0, result: { ok: false, kind: "forbidden" } };
  assert.deepEqual([deriveView(b.inbox, true, 0, errB).status, deriveView(a.inbox, true, 0, errB).status], ["error", "loading"]);
});

test("TODOS los recursos centrales del código usan una clave con sesión: no queda ninguna clave constante ni sin `scope`", () => {
  const useCentral = read("lib/vinto/use-central.ts");
  assert.match(useCentral, /export const useWorkOrders = \(enabled: boolean, onUnauthorized: \(\) => void, scope: string\)/);
  assert.match(useCentral, /export const useAssignments = \(enabled: boolean, onUnauthorized: \(\) => void, scope: string\)/);
  assert.match(useCentral, /export const useActiveAssignment = \(machineCode: string, enabled: boolean, onUnauthorized: \(\) => void, scope: string\)/);
  assert.match(useCentral, /export const useAvailability = \(withArticles: boolean, enabled: boolean, onUnauthorized: \(\) => void, scope: string\)/);
  assert.match(useCentral, /useResource<WorkOrder\[\]>\(workOrdersKey\(scope\)/);
  assert.match(useCentral, /useResource<Assignment\[\]>\(assignmentsKey\(scope\)/);
  assert.match(useCentral, /useResource<ActiveAssignment>\(activeAssignmentKey\(machineCode, scope\)/);
  assert.match(useCentral, /availabilityKey\(withArticles, scope\)/);
  assert.equal(/useResource<[^>]*>\("[^"]*"|useResource\("[^"]*"|`work-orders`|"work-orders"|"assignments"|`active:\$\{machineCode\}`/.test(useCentral), false, "ninguna clave literal en los wrappers");
  const files = ["app/page.tsx", ...readdirSync(join(root, "components/vinto")).filter((f) => f.endsWith(".tsx")).map((f) => `components/vinto/${f}`)];
  let calls = 0;
  for (const file of files) for (const line of read(file).split("\n")) {
    if (/^\s*(import|\/\/)/.test(line)) continue;
    if (/\buseResource\b[<(]/.test(line) && !/^export /.test(line)) { calls++; assert.ok(/scope/i.test(line) || /Key\(/.test(line), `${file}: useResource sin clave de sesión → ${line.trim().slice(0, 140)}`); assert.equal(/useResource(<[^(]*>)?\(\s*["'`][^"'`]*["'`]\s*,/.test(line) && !/\$\{scope\}|scope/.test(line), false, `${file}: clave literal`); }
    if (/\buse(WorkOrders|Assignments|ActiveAssignment|Availability)\(/.test(line)) { calls++; assert.ok(/scope\)/.test(line) || /scope\)\s*;?\s*(\/\/.*)?$/.test(line.replace(/\/\/.*$/, "").trim()), `${file}: hook sin scope → ${line.trim().slice(0, 140)}`); }
  }
  assert.ok(calls >= 30, `se revisaron ${calls} llamadas`);
});

test("el scope llega a TODOS los fronts: Bobinas, Rebobinado y Conversión (ConversionCentral ya lo recibe) y SectorCentral lo exige", () => {
  const page = read("app/page.tsx"), sector = read("components/vinto/sector-central.tsx");
  for (const front of ["RebobinadoCentral", "ConversionCentral"]) assert.match(page, new RegExp(`<${front} [^>]*scope=\\{scope\\}`), front);
  assert.match(sector, /^    scope: string;/m, "scope es obligatorio en SectorCentralProps");
  assert.equal(/scope\?\s*:/.test(sector), false);
  assert.match(sector, /useAvailability\(canManageOrders && module === "programacion", true, onSessionLost, scope\)/);
  assert.match(sector, /useActiveAssignment\(machine\.code, canReadAssignments, onSessionLost, scope\)/);
  assert.equal((sector.match(/useWorkOrders\(canReadOrders, onSessionLost, scope\)/g) ?? []).length, 2);
  assert.match(sector, /useAssignments\(canReadAssignments, onSessionLost, scope\)/);
  for (const p of ["p110", "p111", "p112", "p113", "p116", "p129"]) assert.match(sector, new RegExp(`candidateHistoryKey\\("${p}", scope, refreshKey\\)`), p);
  assert.match(page, /useResource<CentralCapture\[\]>\(candidateHistoryKey\("f6", scope, 0\)/);
  assert.match(page, /useResource<QualityBobbinInboxItem\[\]>\(qualityInboxKey\(scope\)/);
  assert.match(page, /useResource<QualityHistoryLoad>\(qualityHistoryKey\(scope, /);
  assert.match(read("components/vinto/rebobinado-central.tsx"), /<SectorCentral \{\.\.\.props\} code="REBOBINADO"\/>/);
  assert.match(read("components/vinto/conversion-central.tsx"), /<SectorCentral \{\.\.\.props\} code="CONVERSION"\/>/);
});

test("los intentos pendientes y las selecciones de una cuenta se descartan al cerrar sesión, perderla o cambiar de usuario y nunca reaparecen en otra", () => {
  const page = read("app/page.tsx");
  const reset = page.slice(page.indexOf("function resetSessionState()"), page.indexOf("// Cambio de identidad sin pasar"));
  assert.ok(reset.length > 200, "resetSessionState existe");
  assert.match(page, /function sessionLost\(\) \{\n\s*resetSessionState\(\);/);
  assert.match(page, /async function endSession\(\) \{[\s\S]*?const result = await logout\(\);\n\s*resetSessionState\(\);/);
  assert.match(page, /const \[stateOwner, setStateOwner\] = useState<string \| null>\(null\);/);
  assert.match(page, /if \(user && stateOwner !== user\.id\) \{ setStateOwner\(user\.id\); if \(stateOwner !== null\) resetSessionState\(\); \}/);
  // cada estado de intento / contexto / selección con identidad de cuenta se limpia en el descarte único
  const setters = [...page.matchAll(/\[(\w+), (set\w+)\] = useState/g)].map((m) => m[2]);
  const mustReset = setters.filter((name) => /Attempt|Context$|Candidate$|Capture$|Selected\w*Bobbin|^setQualityHistory$|^setSelected$|^setCaptureContext$/.test(name) && name !== "setSession");
  assert.ok(mustReset.length >= 20, `se revisaron ${mustReset.length} estados`);
  for (const name of mustReset) assert.ok(reset.includes(`${name}(`), `${name} no se descarta en resetSessionState`);
  // no se borra el almacenamiento local (funciones legacy lo siguen usando) ni se guardan sesiones en él
  assert.equal(/localStorage\.(removeItem|clear)|sessionStorage\.(removeItem|clear)/.test(page), false);
});

test("la cancelación de solicitudes (AbortController) y el manejo de la sesión perdida se conservan; los resultados tardíos abortados no se guardan", () => {
  const central = read("lib/vinto/use-central.ts");
  assert.match(central, /const controller = new AbortController\(\);/);
  assert.match(central, /return \(\) => controller\.abort\(\);/);
  assert.match(central, /if \(controller\.signal\.aborted\) return;/);
  assert.match(central, /if \(!result\.ok && result\.kind === "session"\) latest\.current\.onUnauthorized\(\);/);
  assert.match(central, /setStored\(\{ key, attempt, result:/);
  assert.match(central, /const view: Resource<T> = deriveView\(key, enabled, attempt, stored\);/);
  assert.equal(/cookie|token|localStorage|sessionStorage/i.test(central.replace(/\/\/.*$/gm, "")), false, "el mecanismo HttpOnly no se toca: nada de cookies ni tokens en el cliente");
});

test("sin regresión: los componentes y claves de Bobinas, Calidad, Rebobinado y Conversión conservan sus claves por sesión ya existentes", () => {
  const machine = read("components/vinto/quality-machine-controls.tsx"), bobbin = read("components/vinto/quality-bobbin-candidate-capture.tsx"), page = read("app/page.tsx");
  assert.match(machine, /`quality-machine-forms:\$\{scope\}`/);
  assert.match(machine, /candidateHistoryKey\(`p122-\$\{code\}`, scope, refreshKey\)/);
  assert.match(bobbin, /candidateHistoryKey\(`\$\{screen\}-\$\{item\.bobbin\.id\}`, scope, refreshKey\)/);
  assert.match(page, /`quality-bobbin-forms:\$\{scope\}`/);
  for (const p of ["p104", "p105", "p131", "p102", "p101"]) assert.match(page, new RegExp(`candidateHistoryKey\\("${p}", scope, candRefresh\\)`), p);
  assert.match(read("components/vinto/sector-central.tsx"), /candidateHistoryKey\("reb-p130", scope, refreshKey\)/);
  assert.match(page, /const scope = sessionScope\(user\);/);
});
