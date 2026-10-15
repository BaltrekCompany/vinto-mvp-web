// node --test scripts/candidate-session-scope.test.mjs
// DEV-B1 · aislamiento por sesión de los recursos candidatos (disponibilidad e historiales de P1-05 / P1-31): una cuenta que inicia sesión en el mismo navegador NUNCA ve, ni siquiera mientras carga, el
// resultado guardado para la cuenta anterior. El entorno de pruebas no renderiza React, así que se prueba la lógica pura que usa useResource (deriveView + claves) con un simulador mínimo del hook,
// y se verifica estáticamente que la página y useAvailability usan esas claves. Limitación: no es una prueba del montaje real de React (eso requiere un E2E de navegador).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { parseAvailability } from "../lib/vinto/availability.ts";
import { publishedCandidateScreens } from "../lib/vinto/bobinas-offers.ts";
import { availabilityKey, candidateHistoryKey, deriveView, sessionScope } from "../lib/vinto/resource-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const A = { id: "11111111-1111-4111-8111-111111111111" }, B = { id: "22222222-2222-4222-8222-222222222222" };

// Simulador de useResource: conserva el ÚLTIMO resultado guardado (como el hook) y deriva la vista con deriveView; `respond` entrega el resultado de la consulta en curso.
function hook() {
    let stored = null, attempt = 0;
    return {
        view: (key, enabled) => deriveView(key, enabled, attempt, stored),
        respond: (key, result) => { stored = { key, attempt, result }; },
        refresh: () => { attempt += 1; },
    };
}
const form = (code) => ({ code, name: code, version_number: 1 });
const availOf = (codes) => parseAvailability({ sectors: [{ code: "BOBINAS", name: "Bobinas", machines: [{ code: "MP1", name: "MP1", forms: codes.map(form) }] }] });
const historyOf = (id) => [{ id, form: { code: "VINTO-P1-05" } }];

test("las claves incluyen al usuario: distintas cuentas, distintas claves; sin sesión, una clave que no coincide con la de ningún usuario", () => {
  assert.notEqual(sessionScope(A), sessionScope(B));
  assert.equal(sessionScope(null), "anonymous");
  assert.notEqual(sessionScope(null), sessionScope(A));
  assert.notEqual(availabilityKey(false, sessionScope(A)), availabilityKey(false, sessionScope(B)));
  assert.notEqual(candidateHistoryKey("p105", sessionScope(A), 0), candidateHistoryKey("p105", sessionScope(B), 0));
  assert.notEqual(candidateHistoryKey("p105", sessionScope(A), 0), candidateHistoryKey("p131", sessionScope(A), 0));
  assert.notEqual(candidateHistoryKey("p105", sessionScope(A), 0), candidateHistoryKey("p105", sessionScope(A), 1)); // tras un envío se recarga
  // INT-01B: el scope es obligatorio y siempre forma parte de la clave (ya no existe una clave de disponibilidad sin sesión)
  assert.equal(availabilityKey(false, sessionScope(A)), `availability:base:user:${A.id}`);
  assert.equal(availabilityKey(true, sessionScope(A)), `availability:articles:user:${A.id}`);
});

test("usuario A carga disponibilidad e historial, la sesión pasa a anónima y B inicia sesión: B no ve nada de A ni mientras carga", () => {
  const avail = hook(), history = hook();
  const kA = availabilityKey(false, sessionScope(A)), hA = candidateHistoryKey("p105", sessionScope(A), 0);
  assert.equal(avail.view(kA, true).status, "loading");
  avail.respond(kA, { ok: true, data: availOf(["VINTO-P1-05", "VINTO-P1-06"]) });
  history.respond(hA, { ok: true, data: historyOf("captura-de-A") });
  assert.equal(avail.view(kA, true).status, "ready");
  assert.equal(history.view(hA, true).data[0].id, "captura-de-A");
  // la sesión pasa a anónima: los recursos se deshabilitan (el resultado de A sigue guardado, pero no se presenta)
  assert.equal(avail.view(availabilityKey(false, sessionScope(null)), false).status, "idle");
  assert.equal(history.view(candidateHistoryKey("p105", sessionScope(null), 0), false).status, "idle");
  // B inicia sesión en el MISMO montaje: antes de recibir cualquier respuesta, la vista es «cargando» y no contiene datos de A
  const kB = availabilityKey(false, sessionScope(B)), hB = candidateHistoryKey("p105", sessionScope(B), 0);
  const availB = avail.view(kB, true), historyB = history.view(hB, true);
  assert.deepEqual([availB.status, historyB.status], ["loading", "loading"]);
  assert.equal(JSON.stringify([availB, historyB]).includes("captura-de-A"), false);
  assert.equal("data" in availB || "data" in historyB, false);
  // llega la respuesta válida de B: solo sus recursos
  avail.respond(kB, { ok: true, data: availOf(["VINTO-P1-06"]) });
  history.respond(hB, { ok: true, data: historyOf("captura-de-B") });
  assert.equal(avail.view(kB, true).status, "ready");
  assert.deepEqual(publishedCandidateScreens(avail.view(kB, true).data), []);
  assert.equal(history.view(hB, true).data[0].id, "captura-de-B");
  // si A vuelve a entrar, el último resultado guardado es el de B: A tampoco ve lo de B
  assert.equal(history.view(hA, true).status, "loading");
});

test("con la clave constante de antes, B vería la disponibilidad y el historial de A: la clave por sesión elimina esa fuga", () => {
  const history = hook();
  const old = "captures-p105:0"; // clave anterior (sin usuario)
  history.respond(old, { ok: true, data: historyOf("captura-de-A") });
  assert.equal(history.view(old, true).data[0].id, "captura-de-A", "con la clave constante el resultado de A se presentaría a cualquier usuario");
  assert.equal(history.view(candidateHistoryKey("p105", sessionScope(B), 0), true).status, "loading");
});

test("un usuario sin concesión de BOBINAS no recibe historial anterior aunque tenga permiso general de captura", () => {
  const avail = hook(), history = hook();
  const kA = availabilityKey(false, sessionScope(A)), hA = candidateHistoryKey("p105", sessionScope(A), 0);
  avail.respond(kA, { ok: true, data: availOf(["VINTO-P1-05"]) });
  history.respond(hA, { ok: true, data: historyOf("captura-de-A") });
  // B tiene production.capture pero ninguna concesión: el backend devuelve sectores vacíos
  const kB = availabilityKey(false, sessionScope(B));
  assert.equal(avail.view(kB, true).status, "loading"); // antes de la respuesta: nada de A
  avail.respond(kB, { ok: true, data: parseAvailability({ sectors: [] }) });
  const published = publishedCandidateScreens(avail.view(kB, true).data);
  assert.deepEqual(published, []);
  const enabled = true && published.includes("p105"); // el historial se habilita solo si el backend publica la ficha (como en page.tsx)
  assert.equal(enabled, false);
  assert.equal(history.view(candidateHistoryKey("p105", sessionScope(B), 0), enabled).status, "idle");
  assert.equal(JSON.stringify(history.view(candidateHistoryKey("p105", sessionScope(B), 0), true)).includes("captura-de-A"), false);
});

test("recarga y reintentos siguen funcionando: refrescar conserva la vista mientras recarga, un error se reintenta y un envío nuevo recarga el historial", () => {
  const history = hook();
  const key = candidateHistoryKey("p105", sessionScope(B), 0);
  history.respond(key, { ok: false, kind: "unavailable" });
  assert.deepEqual(history.view(key, true), { status: "error", kind: "unavailable", refreshing: false });
  history.refresh(); // «Reintentar» / «Actualizar»
  assert.deepEqual(history.view(key, true), { status: "error", kind: "unavailable", refreshing: true }); // mantiene el estado mientras reconsulta
  history.respond(key, { ok: true, data: historyOf("c1") });
  assert.deepEqual(history.view(key, true), { status: "ready", data: historyOf("c1"), refreshing: false });
  history.refresh();
  assert.equal(history.view(key, true).refreshing, true);
  assert.equal(history.view(key, true).data[0].id, "c1");
  history.respond(key, { ok: true, data: historyOf("c2") });
  assert.equal(history.view(key, true).data[0].id, "c2");
  // tras un envío el contador cambia la clave: la vista pasa a «cargando» y luego trae el registro nuevo
  const afterSubmit = candidateHistoryKey("p105", sessionScope(B), 1);
  assert.equal(history.view(afterSubmit, true).status, "loading");
  history.respond(afterSubmit, { ok: true, data: [...historyOf("c3"), ...historyOf("c2")] });
  assert.deepEqual(history.view(afterSubmit, true).data.map((c) => c.id), ["c3", "c2"]);
  // una sesión caducada (401) llega como error de sesión y el hook la informa; la vista queda en error, nunca con datos
  history.respond(afterSubmit, { ok: false, kind: "session" });
  assert.equal(history.view(afterSubmit, true).status, "error");
});

test("la página y useAvailability usan las claves por sesión y los demás llamadores conservan las suyas", () => {
  const page = read("app/page.tsx"), central = read("lib/vinto/use-central.ts"), sector = read("components/vinto/sector-central.tsx");
  assert.match(page, /const scope = sessionScope\(user\);/);
  assert.match(page, /useAvailability\(false, authenticated && bobinasFront && \(activeModule === "ejecucion" \|\| activeModule === "seguimiento"\), sessionLost, scope\)/);
  assert.match(page, /candidateHistoryKey\("p105", scope, candRefresh\)/);
  assert.match(page, /candidateHistoryKey\("p131", scope, candRefresh\)/);
  assert.equal(/captures-p105:\$\{|captures-p131:\$\{/.test(page), false, "ya no quedan claves sin usuario");
  assert.match(central, /export const useAvailability = \(withArticles: boolean, enabled: boolean, onUnauthorized: \(\) => void, scope: string\)/);
  assert.match(central, /availabilityKey\(withArticles, scope\)/);
  assert.match(central, /const view: Resource<T> = deriveView\(key, enabled, attempt, stored\);/);
  assert.match(sector, /useAvailability\(canManageOrders && module === "programacion", true, onSessionLost, scope\)/); // DEV-R2: la disponibilidad de Rebobinado / Conversión también va ligada a la sesión
  assert.match(sector, /candidateHistoryKey\("p110", scope, refreshKey\)/); // INT-01B: ya no hay claves constantes
  assert.equal(/localStorage\.(removeItem|clear)/.test(page), false, "no se borra el almacenamiento local");
});
