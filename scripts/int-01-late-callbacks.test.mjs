// node --test scripts/int-01-late-callbacks.test.mjs
// INT-01B (corrección de auditoría) · respuestas TARDÍAS de operaciones asíncronas tras un cambio de sesión. deriveView ya aísla los recursos de lectura; aquí se ejercita el control de VIGENCIA de las
// devoluciones de las capturas POST: A inicia un envío, sale, B inicia sesión y la respuesta de A llega después. La respuesta de A NO debe ejecutar setAttempt(null), onSessionLost(), onSubmitted() ni
// onAssignmentChanged() sobre el estado de B; una respuesta tardía de la MISMA sesión sigue funcionando.
//
// El banco de pruebas ejecuta el protocolo REAL de los componentes de captura (beginSessionOperation al empezar, `if (!live()) return` tras cada await) sobre el motor real de las fichas (createAttempt /
// submitAttempt / reconciliación, con promesas pendientes que se resuelven a mano) y un «padre» que descarta el estado exactamente como resetSessionState(). Además se verifica en el código de los 11 componentes de
// captura que cada await de send() va seguido de la guarda. Lógica PURA: sin DOM ni red.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { P122 } from "../lib/vinto/p1-22.ts";
import { beginSessionOperation, bumpSessionEpoch, currentSessionEpoch } from "../lib/vinto/session-epoch.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const DEVICE = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";
const ID_A = "3f2b8a9e-1c4d-4e5f-8a6b-7c8d9e0f1a2b", ID_B = "5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f";
const VALUES = { numero_de_cuba: "C-1", masa_humeda: "20.5", volumen_desplazado: "630", grado_de_refinacion_sr: "28.5", amperaje: "45.25", observacion: "" };

const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const envelope = (id) => ({ id, status: "submitted", revision: 1, captured_at: "2026-10-06T16:00:00Z", submitted_at: "2026-10-06T16:00:01Z", form: { code: "VINTO-P1-22", version_number: 1, name: "x" },
  machine: { code: "MP1", name: "MP1" }, shift: { code: "DIA", name: "Día" }, operating_date: "2026-10-06", recorded_by: null, values: { numero_de_cuba: "C-1", masa_humeda: "20.5", volumen_desplazado: "630", grado_de_refinacion_sr: "28.5", amperaje: "45.25" } });
const posted = (id) => ({ ok: true, status: 201, data: { created: true, already_submitted: false, capture: P122.parseCapture(envelope(id)) } });

// «Padre» (page.tsx): estado compartido que las devoluciones de los componentes pueden alterar, y el descarte único de la sesión.
function makePage() {
  const page = {
    user: null, attempt: null, saved: null, refreshes: 0, sessionLostCalls: 0, assignmentChangedCalls: 0, notices: [],
    // mismo orden que resetSessionState(): primero se invalida la generación, luego se limpia el estado de pantalla
    reset() { bumpSessionEpoch(); page.attempt = null; page.saved = null; },
    login(user) { page.reset(); page.user = user; },
    logout() { page.user = null; page.reset(); },
    // props que recibe un componente de captura
    props: () => ({
      setAttempt: (a) => { page.attempt = a; }, onSubmitted: (capture) => { page.refreshes += 1; page.saved = capture; },
      onSessionLost: () => { page.sessionLostCalls += 1; page.user = null; page.reset(); }, onAssignmentChanged: () => { page.assignmentChangedCalls += 1; }, notice: (m) => page.notices.push(m),
    }),
  };
  return page;
}

// Protocolo de CandidateFormCapture.send() (y de los demás componentes): guarda al empezar, `live()` tras CADA await, y solo entonces las devoluciones.
async function send(attempt, deps, props) {
  const live = beginSessionOperation();
  props.setAttempt(attempt); // se conserva desde el primer POST
  const outcome = await P122.submitAttempt(attempt, deps);
  if (!live()) return "descartada";
  if (outcome.kind === "submitted") {
    props.setAttempt(null); props.onSubmitted(outcome.capture);
    const read = await deps.get(outcome.capture.id);
    if (!live()) return "descartada (lectura)";
    return read.ok ? "verificada" : "sin verificar";
  }
  if (outcome.kind === "session") { props.setAttempt(null); props.onSessionLost(); return "sesión"; }
  if (outcome.kind === "rejected") {
    props.setAttempt(null);
    if (outcome.reason === "stale" || outcome.reason === "not_active") { props.onAssignmentChanged(); return "asignación"; }
    props.notice(outcome.message); return "rechazada";
  }
  props.notice(outcome.message); return "incierta";
}

const attemptOf = (id) => P122.createAttempt(VALUES, "MP1", DEVICE, () => id).attempt;

test("A → envío pendiente → cierre de sesión → B inicia sesión → respuesta tardía de A (éxito): B conserva su sesión y su intento y no se ejecuta ninguna devolución de A", async () => {
  const page = makePage();
  page.login("A");
  const post = deferred(), attemptA = attemptOf(ID_A);
  const lateA = send(attemptA, { post: () => post.promise, get: async () => assert.fail("la lectura posterior de A no debe ocurrir") }, page.props());
  assert.equal(page.attempt?.captureId, ID_A, "A tiene su intento pendiente mientras la respuesta no llega");
  page.logout();            // A sale (el estado de A se descarta)
  page.login("B");          // B inicia sesión en el mismo navegador
  const attemptB = attemptOf(ID_B);
  page.attempt = attemptB;  // B prepara su propio intento pendiente (resultado incierto de B)
  const before = { ...page, props: undefined };
  post.resolve(posted(ID_A)); // llega TARDE la respuesta de A
  assert.equal(await lateA, "descartada");
  assert.equal(page.user, "B", "1. B sigue autenticado");
  assert.equal(page.attempt, attemptB, "2. B no pierde su intento pendiente (setAttempt(null) de A no se ejecutó)");
  assert.equal(page.saved, null, "3. no aparecen resultados de A en la pantalla de B");
  assert.deepEqual([page.refreshes, page.sessionLostCalls, page.assignmentChangedCalls, page.notices.length], [0, 0, 0, 0], "4. no se ejecutó ninguna devolución de mutación de A");
  assert.deepEqual({ ...page, props: undefined }, before);
});

test("la respuesta tardía de A con sesión perdida (401) NO cierra la sesión de B", async () => {
  const page = makePage();
  page.login("A");
  const post = deferred(), lateA = send(attemptOf(ID_A), { post: () => post.promise, get: async () => assert.fail() }, page.props());
  page.logout(); page.login("B");
  const attemptB = attemptOf(ID_B); page.attempt = attemptB;
  post.resolve({ ok: false, kind: "http", status: 401 });
  assert.equal(await lateA, "descartada");
  assert.deepEqual([page.user, page.attempt === attemptB, page.sessionLostCalls], ["B", true, 0], "onSessionLost() de A no se ejecutó");
});

test("la respuesta tardía de A con asignación obsoleta o rechazo definitivo NO cierra el formulario ni muestra avisos en B", async () => {
  for (const [status, code] of [[409, "ASSIGNMENT_STALE"], [409, "ASSIGNMENT_NOT_ACTIVE"], [422, "CAPTURE_VALIDATION"], [403, undefined]]) {
    const page = makePage();
    page.login("A");
    const post = deferred(), lateA = send(attemptOf(ID_A), { post: () => post.promise, get: async () => assert.fail() }, page.props());
    page.logout(); page.login("B");
    const attemptB = attemptOf(ID_B); page.attempt = attemptB;
    post.resolve({ ok: false, kind: "http", status, code });
    assert.equal(await lateA, "descartada", `${status} ${code}`);
    assert.deepEqual([page.user, page.attempt === attemptB, page.assignmentChangedCalls, page.notices.length], ["B", true, 0, 0], `${status} ${code}`);
  }
});

test("una respuesta incierta de A que se reconcilia después del cambio de sesión tampoco modifica el estado de B", async () => {
  const page = makePage();
  page.login("A");
  const post = deferred(), get = deferred();
  const lateA = send(attemptOf(ID_A), { post: () => post.promise, get: () => get.promise }, page.props());
  page.logout(); page.login("B");
  const attemptB = attemptOf(ID_B); page.attempt = attemptB;
  post.resolve({ ok: false, kind: "network", status: 0 }); // el POST de A queda incierto: se reconcilia con GET por el mismo capture_id
  await new Promise((r) => setImmediate(r));
  get.resolve({ ok: true, status: 200, data: P122.parseCapture(envelope(ID_A)) }); // la reconciliación de A llega tarde
  assert.equal(await lateA, "descartada");
  assert.deepEqual([page.user, page.attempt === attemptB, page.refreshes, page.saved], ["B", true, 0, null]);
});

test("la lectura posterior de A (read-back tras un éxito de la misma sesión) que llega después del cambio se descarta sin efectos", async () => {
  const page = makePage();
  page.login("A");
  const get = deferred();
  const lateA = send(attemptOf(ID_A), { post: async () => posted(ID_A), get: () => get.promise }, page.props());
  await new Promise((r) => setImmediate(r)); // el POST ya resolvió dentro de la sesión de A: onSubmitted ya corrió (legítimo)
  assert.equal(page.refreshes, 1);
  page.logout(); page.login("B");
  const attemptB = attemptOf(ID_B); page.attempt = attemptB;
  get.resolve({ ok: true, status: 200, data: P122.parseCapture(envelope(ID_A)) });
  assert.equal(await lateA, "descartada (lectura)");
  assert.deepEqual([page.user, page.attempt === attemptB, page.refreshes, page.saved], ["B", true, 1, page.saved], "nada nuevo se aplicó tras el cambio de sesión");
  assert.equal(page.saved, null, "el estado de la pantalla de B (descartado en el reset) no recupera lo de A");
});

test("las respuestas tardías de la MISMA sesión siguen funcionando con normalidad: éxito, sesión perdida, asignación obsoleta y rechazo", async () => {
  const run = async (resolveWith) => {
    const page = makePage();
    page.login("A");
    const post = deferred(), lateA = send(attemptOf(ID_A), { post: () => post.promise, get: async () => ({ ok: true, status: 200, data: P122.parseCapture(envelope(ID_A)) }) }, page.props());
    await new Promise((r) => setTimeout(r, 5)); // la respuesta tarda, pero la sesión no cambia
    post.resolve(resolveWith);
    return { page, result: await lateA };
  };
  let { page, result } = await run(posted(ID_A));
  assert.deepEqual([result, page.refreshes, page.attempt, page.saved?.id, page.user], ["verificada", 1, null, ID_A, "A"]);
  ({ page, result } = await run({ ok: false, kind: "http", status: 401 }));
  assert.deepEqual([result, page.sessionLostCalls, page.user], ["sesión", 1, null], "una sesión realmente perdida en la sesión vigente sí se procesa");
  ({ page, result } = await run({ ok: false, kind: "http", status: 409, code: "ASSIGNMENT_STALE" }));
  assert.deepEqual([result, page.assignmentChangedCalls, page.attempt, page.user], ["asignación", 1, null, "A"]);
  ({ page, result } = await run({ ok: false, kind: "http", status: 422, code: "CAPTURE_VALIDATION" }));
  assert.deepEqual([result, page.notices.length, page.attempt, page.user], ["rechazada", 1, null, "A"]);
});

test("el capture_id, la idempotencia y la reconciliación no cambian: el intento pendiente conserva su id mientras la sesión sea la misma y el reintento reenvía el mismo payload", async () => {
  const page = makePage();
  page.login("A");
  const attempt = attemptOf(ID_A), seen = [];
  const lost = { ok: false, kind: "network", status: 0 };
  for (let i = 0; i < 3; i++) {
    const result = await send(attempt, { post: async (p) => { seen.push(JSON.stringify(p)); return lost; }, get: async () => ({ ok: false, kind: "http", status: 404 }) }, page.props());
    assert.equal(result, "incierta");
    assert.equal(page.attempt, attempt, "el intento (y su capture_id) se conserva tras un resultado no confirmado");
  }
  assert.equal(new Set(seen).size, 1, "mismo payload en cada reintento");
  const done = await send(attempt, { post: async () => posted(ID_A), get: async () => ({ ok: true, status: 200, data: P122.parseCapture(envelope(ID_A)) }) }, page.props());
  assert.equal(done, "verificada");
  assert.equal(page.saved.id, ID_A);
});

test("un cambio de sesión invalida TODAS las operaciones en vuelo de la cuenta anterior, también las de otro formulario, y no las de la nueva", async () => {
  const page = makePage();
  page.login("A");
  const slow = [deferred(), deferred(), deferred()];
  const lateA = slow.map((d, i) => send(attemptOf(`${ID_A.slice(0, -1)}${i}`), { post: () => d.promise, get: async () => ({ ok: true, status: 200, data: null }) }, makePage().props()));
  page.login("B");
  const postB = deferred(), mineB = send(attemptOf(ID_B), { post: () => postB.promise, get: async () => ({ ok: true, status: 200, data: P122.parseCapture(envelope(ID_B)) }) }, page.props());
  slow.forEach((d, i) => d.resolve(posted(`${ID_A.slice(0, -1)}${i}`)));
  assert.deepEqual(await Promise.all(lateA), ["descartada", "descartada", "descartada"]);
  postB.resolve(posted(ID_B));
  assert.equal(await mineB, "verificada", "la operación iniciada DESPUÉS del cambio pertenece a B y sí se procesa");
  assert.equal(page.saved.id, ID_B);
  // y re-iniciar sesión con la MISMA cuenta también es otra generación
  const epoch = currentSessionEpoch();
  page.logout(); page.login("A");
  assert.ok(currentSessionEpoch() > epoch);
});

// ---- verificación del código real de los componentes ---------------------------------------------------------------------------------------------------------

const CAPTURE_COMPONENTS = ["candidate-form-capture", "f6-capture", "f3-bobbin-capture", "quality-humidity-capture", "quality-physical-capture", "p1-10-capture", "p1-29-capture", "p1-11-capture", "p1-12-capture", "p1-13-capture", "p1-16-capture"];

test("los 11 componentes de captura toman la guarda al empezar send() y comprueban live() tras CADA await antes de tocar el estado compartido", () => {
  for (const name of CAPTURE_COMPONENTS) {
    const source = read(`components/vinto/${name}.tsx`);
    assert.match(source, /import \{ beginSessionOperation \} from "@\/lib\/vinto\/session-epoch";/, name);
    const start = source.indexOf("    async function send() {"), end = source.indexOf("\n    }\n", start);
    assert.ok(start > 0 && end > start, `${name}: send() encontrado`);
    const body = source.slice(start, end).split("\n");
    assert.match(body[1], /const live = beginSessionOperation\(\);/, `${name}: la guarda se toma antes del primer await`);
    const awaits = body.map((line, i) => [line, i]).filter(([line]) => /\bawait\b/.test(line));
    assert.ok(awaits.length >= 1, `${name}: tiene al menos un await`);
    for (const [line, i] of awaits) {
      assert.match(body[i + 1], /if \(!live\(\)\) return;/, `${name}: «${line.trim().slice(0, 70)}» no va seguido de la guarda`);
      // antes de la guarda ninguna devolución del padre ni cambio de estado compartido
      assert.equal(/setAttempt\(|onSubmitted|onSessionLost|onAssignmentChanged|setSaved|toast\./.test(line), false, `${name}: efecto en la misma línea del await`);
    }
    // el primer efecto compartido posterior al await solo aparece DESPUÉS de la guarda
    const firstAwait = awaits[0][1], firstGuard = body.findIndex((l, i) => i > firstAwait && /if \(!live\(\)\) return;/.test(l));
    const earlyEffect = body.slice(firstAwait + 1, firstGuard).some((l) => /setAttempt\(|onSubmitted|onSessionLost|onAssignmentChanged/.test(l));
    assert.equal(earlyEffect, false, `${name}: ningún efecto entre el await y la guarda`);
    assert.match(source, /\} finally \{ busy\.current = false; setSending\(false\); \}/, `${name}: el finally sigue igual`);
  }
});

test("el padre invalida la generación en el descarte único de la sesión (cierre de sesión, sesión perdida y cambio de identidad)", () => {
  const page = read("app/page.tsx");
  assert.match(page, /import \{ bumpSessionEpoch \} from "@\/lib\/vinto\/session-epoch";/);
  assert.match(page, /function resetSessionState\(\) \{\n\s*bumpSessionEpoch\(\);/);
  assert.match(page, /function sessionLost\(\) \{\n\s*resetSessionState\(\);/);
  assert.match(page, /async function endSession\(\) \{[\s\S]*?const result = await logout\(\);\n\s*resetSessionState\(\);/);
  assert.match(page, /if \(user && stateOwner !== user\.id\) \{ setStateOwner\(user\.id\); if \(stateOwner !== null\) resetSessionState\(\); \}/);
  assert.equal((page.match(/bumpSessionEpoch\(\)/g) ?? []).length, 1, "un único punto invalida la generación");
  const epoch = read("lib/vinto/session-epoch.ts").split("\n").filter((l) => !/^\s*\/\//.test(l)).join("\n");
  assert.equal(/cookie|token|localStorage|sessionStorage|fetch\(/i.test(epoch), false, "la generación es solo un contador en memoria");
  // todos los componentes de captura del repositorio con un envío asíncrono hacia el padre están cubiertos
  const withSend = readdirSync(join(root, "components/vinto")).filter((f) => f.endsWith(".tsx") && /async function send\(\)/.test(read(`components/vinto/${f}`))).map((f) => f.replace(".tsx", ""));
  assert.deepEqual(withSend.sort(), [...CAPTURE_COMPONENTS].sort(), "ningún componente con send() asíncrono queda sin guarda");
});
