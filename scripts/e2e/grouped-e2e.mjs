// node scripts/e2e/grouped-e2e.mjs <creds.json> <evidence-dir>
// M3-A · recorrido E2E de un formulario SINTÉTICO con grupos repetibles en un entorno AISLADO: Asignación válida -> captura con varias filas (interfaz real: agregar/eliminar filas en React) ->
// API -> PostgreSQL efímero -> GET -> reconstrucción de filas -> idempotencia -> reconciliación -> logout. Requiere el backend de prueba (backend/tests/e2e_p110_server.py, puerto 8190, que
// instala también el formulario sintético agrupado) y el frontend de QA con el harness temporal scripts/e2e/harness-grouped-page.tsx.txt (puerto 8796). NO es una ruta ni una prueba del producto.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787), si la base no termina en `_test`, si no es `current_database()`, si el backend no sirve esa base o si el navegador
// llama al puerto 8000. Las lecturas de PostgreSQL son SELECT en transacciones de solo lectura (también sobre DEV, solo para comprobar que no cambió).
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [credsPath, outDir] = process.argv.slice(2);
const API = process.env.E2E_API ?? "http://127.0.0.1:8190", WEB = process.env.E2E_WEB ?? "http://127.0.0.1:8796";
const PG_CONTAINER = process.env.E2E_PG_CONTAINER ?? "vinto-local-postgres-1";
const CODE = "VINTO-TEST-GRP-1";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const creds = JSON.parse(readFileSync(credsPath, "utf8"));
const { database, users, machine_code: MACHINE } = creds;
mkdirSync(outDir, { recursive: true });
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };
const abort = (message) => { console.error("E2E ABORTADO: " + message); process.exit(2); };

// ---------------------------------------------------------------- salvaguardas
const apiUrl = new URL(API), webUrl = new URL(WEB);
if (apiUrl.port === "8000" || webUrl.port === "8787") abort("la API o el frontend apuntan a DEV");
if (apiUrl.hostname !== "127.0.0.1" || webUrl.hostname !== "127.0.0.1") abort("solo se admite 127.0.0.1");
if (!/_test$/.test(database) || database === "vinto") abort(`la base ${database} no es una base efímera *_test`);
const pgUser = execFileSync("docker", ["exec", PG_CONTAINER, "printenv", "POSTGRES_USER"], { encoding: "utf8" }).trim();
const psql = (db, sql) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", `BEGIN READ ONLY; ${sql}; COMMIT;`], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const q = (sql) => psql(database, sql);
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check("S0 la base del recorrido es efímera (*_test) y su identidad se verificó con current_database()", true, identity);
const DEV_SQL = "SELECT (SELECT count(*) FROM vinto_txn.capture)||'|'||(SELECT count(*) FROM vinto_txn.capture_group_row)||'|'||(SELECT count(*) FROM vinto_audit.audit_event)||'|'||(SELECT count(*) FROM vinto_auth.session)||'|'||(SELECT count(*) FROM vinto_auth.auth_event)||'|'||(SELECT count(*) FROM vinto_master.user_sector)";
const devBefore = psql("vinto", DEV_SQL)[0];

function client() {
  let cookie = "";
  const call = async (method, path, body) => {
    const response = await fetch(API + path, { method, headers: { "Content-Type": "application/json", Origin: WEB, ...(cookie ? { Cookie: cookie } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
    const set = response.headers.get("set-cookie"); if (set) cookie = set.split(";")[0];
    const text = await response.text(); let json = null; try { json = JSON.parse(text); } catch { /* sin cuerpo */ }
    return { status: response.status, json, text };
  };
  return { call, login: (u) => call("POST", "/api/auth/login", { username: users[u].username, password: users[u].password }) };
}

// ---------------------------------------------------------------- Chrome (CDP)
async function browser(label, port, body) {
  const profile = mkdtempSync(join(tmpdir(), `m3a-${label}-`));
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "--window-size=1366,900", "about:blank"], { stdio: "ignore" });
  let ws, nextId = 1; const pending = new Map(); const log = { requests: [], consoleErrors: [], exceptions: [] }; const byId = new Map();
  const send = (method, params = {}) => new Promise((res) => { const id = nextId++; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
  try {
    for (let i = 0; i < 60; i++) { try { const t = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); const p = t.find((x) => x.type === "page"); if (p) { ws = new WebSocket(p.webSocketDebuggerUrl); await new Promise((a, b) => { ws.onopen = a; ws.onerror = b; }); break; } } catch { /* arrancando */ } await sleep(300); }
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
      const p = msg.params;
      if (msg.method === "Network.requestWillBeSent") { const r = { method: p.request.method, url: p.request.url, status: null }; byId.set(p.requestId, r); log.requests.push(r); if (new URL(p.request.url).port === "8000") { console.error("E2E ABORTADO: el navegador llamó al puerto 8000 (DEV): " + p.request.url); process.exit(2); } }
      if (msg.method === "Network.responseReceived") { const r = byId.get(p.requestId); if (r) r.status = p.response.status; }
      if (msg.method === "Runtime.exceptionThrown") log.exceptions.push(p.exceptionDetails.text + " " + (p.exceptionDetails.exception?.description ?? "").slice(0, 120));
      if (msg.method === "Runtime.consoleAPICalled" && p.type === "error") log.consoleErrors.push(p.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 160));
    };
    await send("Page.enable"); await send("Network.enable"); await send("Runtime.enable");
    const js = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 200)); return r.result?.result?.value; };
    const waitFor = async (expr, what, ms = 25000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await js(expr)) return true; } catch { /* navegando */ } await sleep(200); } throw new Error("tiempo agotado esperando: " + what); };
    const goto = async (url) => { await send("Page.navigate", { url }); await sleep(700); await waitFor("document.readyState === 'complete'", "carga " + url); };
    const setValue = (selector, value) => js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); return true; })()`);
    const click = (selector) => js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el || el.disabled) return false; el.click(); return true; })()`);
    const clickText = (text) => js(`(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim().startsWith(${JSON.stringify(text)})); if (!b || b.disabled) return false; b.click(); return true; })()`);
    const shot = async (name) => { const h = await js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"); const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1366, height: Math.min(h, 4500), scale: 1 } }); writeFileSync(join(outDir, name), Buffer.from(r.result.data, "base64")); };
    await body({ send, js, waitFor, goto, setValue, click, clickText, shot, log, sleep });
  } finally {
    try { ws?.close(); } catch { /* ya cerrado */ }
    spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" }); await sleep(1500);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* se limpia luego */ }
  }
}
const loginUi = async (b, who) => { await b.waitFor("!!document.querySelector('#qa-user')", "formulario de ingreso"); await b.setValue("#qa-user", users[who].username); await b.setValue("#qa-pass", users[who].password); await b.js("document.querySelector('#qa-login').click()"); };
// selectores de la interfaz de grupos
const G = { detalle: '[data-group="Detalle"]', extras: '[data-group="Extras"]', unico: '[data-group="Único"]' };
const cellAt = (group, row, i) => `(document.querySelectorAll('${G[group]} li[data-row="${row}"] input, ${G[group]} li[data-row="${row}"] select'))[${i}]`;
const setCell = (b, group, row, i, value) => b.js(`(() => { const el = ${cellAt(group, row, i)}; if (!el) return false; const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); return true; })()`);
const addRowBtn = (group) => `${G[group]} button`; // el primer botón del grupo es «Agregar fila»
const counter = (b, group) => b.js(`document.querySelector('${G[group]} [data-testid="group-count"]').innerText`);
const rowCount = (b, group) => b.js(`document.querySelectorAll('${G[group]} li[data-row]').length`);
const isDisabled = (b, selector) => b.js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); return !!el && el.disabled; })()`);
const removeBtn = (group, title, row) => `${G[group]} button[aria-label="Eliminar fila ${row} de ${title}"]`;
const capturePosts = (b) => b.js("window.__posts ?? []");
const posts = (b) => b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/captures"));
const text = (b) => b.js("document.body.innerText");
const dbRows = (id) => q(`SELECT g.code||'|'||r.row_number||'|'||coalesce((SELECT string_agg(f.key||'='||coalesce(d.value_text, d.value_decimal::text, d.value_integer::text), ',' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.group_row_id = r.id), '') FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = '${id}' ORDER BY g.display_order, r.row_number`);

// ================================================================ 1. preparación por API (asignación válida)
const jefatura = client(), supervision = client(), operacion = client();
const article = creds.article_code;
check("P1 login JEFATURA / SUPERVISION de prueba", (await jefatura.login("jefatura")).status === 200 && (await supervision.login("supervision")).status === 200);
const me = await operacion.login("operacion");
check("P2 el backend sirve la base efímera (el usuario de prueba solo existe allí)", me.status === 200 && me.json.user.id === users.operacion.user_id && q(`SELECT count(*) FROM vinto_master.user WHERE id = '${users.operacion.user_id}'`)[0] === "1");
await operacion.call("POST", "/api/auth/logout");
const order = await jefatura.call("POST", "/api/work-orders", { machine_code: MACHINE, lines: [{ pv_reference: "PV-E2E-G", article_code: article, quantity: 10, due_date: "2026-11-01" }] });
const published = await jefatura.call("POST", `/api/work-orders/${order.json.id}/publish`);
const activated = await supervision.call("POST", "/api/assignments/activate", { work_order_id: published.json.id, baseline_line_id: published.json.baseline.lines[0].id });
check("P3 asignación válida: OT creada y activada en la máquina de prueba", order.status === 201 && activated.status === 201 && activated.json.assignment.machine.code === MACHINE, `OT ${order.status}, asignación ${activated.status}`);
const assignment = activated.json.assignment;

// ================================================================ 2. interfaz real: varias filas, agregar/eliminar, envío y persistencia
const EXPECTED = {
  detalle: [{ item: "A", cantidad: 2, peso: "1.50", tipo: "a" }, { item: "C", cantidad: 7, peso: "3.25", tipo: "b" }],
  extras: [{ etiqueta: "x", valor: "0.10" }, { etiqueta: "y" }],
  unico: [{ ref: "r" }],
};
let sent = null;
await browser("a", 9381, async (b) => {
  await b.goto(`${WEB}/qa-harness`);
  await loginUi(b, "operacion");
  await b.waitFor("document.body.innerText.includes('Captura con grupos repetibles')", "formulario agrupado", 30000);
  check("A1 estado inicial: Detalle con 1 fila (mínimo 1), Extras 0 filas, Único 0 filas; no se puede eliminar por debajo del mínimo",
    (await counter(b, "detalle")) === "1 fila · mínimo 1, máximo 3" && (await counter(b, "extras")) === "0 filas · sin mínimo" && (await counter(b, "unico")).startsWith("0 filas") && await isDisabled(b, removeBtn("detalle", "Detalle", 1)));
  await b.shot("a1-estado-inicial.png");
  check("A2 agregar filas en Detalle hasta el máximo declarado (3): el botón queda deshabilitado", await b.click(addRowBtn("detalle")) && await b.click(addRowBtn("detalle")) && (await rowCount(b, "detalle")) === 3 && await isDisabled(b, addRowBtn("detalle")));
  const detalle = [["A", "2", "1,50", "a"], ["B", "5", "", ""], ["C", "7", "3.25", "b"]];
  for (const [r, cells] of detalle.entries()) for (const [i, v] of cells.entries()) await setCell(b, "detalle", r + 1, i, v);
  check("A3 eliminar la fila 2: las filas se renumeran y el contenido restante conserva su orden", await b.click(removeBtn("detalle", "Detalle", 2)) && (await rowCount(b, "detalle")) === 2
    && (await b.js(`${cellAt("detalle", 2, 0)}.value`)) === "C" && (await b.js(`${cellAt("detalle", 1, 0)}.value`)) === "A" && !(await isDisabled(b, addRowBtn("detalle"))));
  check("A4 Extras (sin máximo): dos filas; Único (no repetible): una fila y el botón queda deshabilitado", await b.click(addRowBtn("extras")) && await b.click(addRowBtn("extras")) && await b.click(addRowBtn("unico")) && (await rowCount(b, "extras")) === 2 && await isDisabled(b, addRowBtn("unico")));
  for (const [r, cells] of [["x", "0,10"], ["y", ""]].entries()) for (const [i, v] of cells.entries()) await setCell(b, "extras", r + 1, i, v);
  await setCell(b, "unico", 1, 0, "r");
  await b.setValue('main input', "L-E2E");
  await b.js("(() => { const t = document.querySelector('main textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, 'nota E2E'); t.dispatchEvent(new Event('input', { bubbles: true })); })()");
  await b.shot("a2-formulario-lleno.png");
  check("A5 enviar", await b.clickText("Enviar registro trazable"));
  await b.waitFor("document.querySelector('[data-section=saved]') && document.querySelector('[data-readback]')?.dataset.readback === 'ok'", "captura guardada y verificada", 30000);
  await b.shot("a3-guardado-y-verificado.png");
  const sentPosts = posts(b);
  check("A6 un único POST /api/captures = 201 y GET por id = 200", sentPosts.length === 1 && sentPosts[0].status === 201 && b.log.requests.some((r) => r.method === "GET" && /\/api\/captures\/[0-9a-f-]{36}$/.test(r.url) && r.status === 200));
  sent = JSON.parse((await capturePosts(b))[0]);
  check("A7 el payload lleva los grupos en values._groups con las filas en orden y sin ids, row_number ni rowKey", JSON.stringify(sent.values._groups) === JSON.stringify(EXPECTED) && sent.values.lote === "L-E2E" && !JSON.stringify(sent).match(/rowKey|row_number|group_row|field_group/));
  const stored = dbRows(sent.capture_id);
  check("A8 PostgreSQL: filas por grupo en su orden (row_number 1..n) con los valores tipados", JSON.stringify(stored) === JSON.stringify(["detalle|1|item=A,cantidad=2,peso=1.50,tipo=a", "detalle|2|item=C,cantidad=7,peso=3.25,tipo=b", "extras|1|etiqueta=x,valor=0.10", "extras|2|etiqueta=y", "unico|1|ref=r"]), stored.join(" ; "));
  const head = q(`SELECT c.status||'|'||c.revision||'|'||m.code||'|'||c.assignment_id||'|'||c.created_by FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id WHERE c.id = '${sent.capture_id}'`)[0];
  check("A9 capture: submitted, revision = 1, contexto derivado de la asignación y autor", head === `submitted|1|${MACHINE}|${assignment.id}|${users.operacion.user_id}`, head);
  check("A10 detalles: 2 simples + 12 de filas (8 de Detalle, 3 de Extras, 1 de Único; todos ligados a su fila y grupo)", q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent.capture_id}' AND group_row_id IS NULL`)[0] === "2" && q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent.capture_id}' AND group_row_id IS NOT NULL AND field_group_id IS NOT NULL`)[0] === "12");
  const read = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures/${sent.capture_id}', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A11 GET por id reconstruye campos simples, grupos y filas en el orden original", read.status === 200 && JSON.stringify(read.body.values._groups.detalle) === JSON.stringify(EXPECTED.detalle) && JSON.stringify(read.body.values._groups.extras) === JSON.stringify(EXPECTED.extras) && read.body.values.lote === "L-E2E");
  const listed = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures?form_code=${CODE}', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A12 listado filtrado por form_code incluye la captura con sus filas", listed.status === 200 && listed.body.some((c) => c.id === sent.capture_id && JSON.stringify(c.values._groups.unico) === JSON.stringify(EXPECTED.unico)));
  const historic = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A13 el listado histórico (F6) no incluye la captura agrupada", historic.status === 200 && !historic.body.some((c) => c.id === sent.capture_id));
  const storage = JSON.parse(await b.js("JSON.stringify({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })"));
  check("A14 el navegador solo guarda vinto-device-key (las filas no se guardan en el navegador)", JSON.stringify(storage.local) === JSON.stringify(["vinto-device-key"]) && storage.session.length === 0);
  check("A15 sin errores de JavaScript/CORS en el navegador", b.log.exceptions.length === 0 && b.log.consoleErrors.filter((e) => !/401/.test(e)).length === 0, JSON.stringify([...b.log.exceptions, ...b.log.consoleErrors]).slice(0, 300));
  await b.js("document.querySelector('#qa-logout').click()"); await b.waitFor("!!document.querySelector('#qa-user')", "ingreso tras logout", 15000);
});

// ================================================================ 3. idempotencia y conflictos sobre la captura A (API, con el contenido completo de las filas)
const op = client(); await op.login("operacion");
const countsA = () => `${q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${sent.capture_id}'`)[0]}|${q(`SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = '${sent.capture_id}'`)[0]}|${q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent.capture_id}'`)[0]}`;
const before = countsA();
const replay = await op.call("POST", "/api/captures", sent);
check("B1 reintento idéntico = 200 already_submitted, sin crear filas ni detalles", replay.status === 200 && replay.json.already_submitted === true && countsA() === before, `${before} -> ${countsA()}`);
const variants = {
  "una celda de una fila": (v) => { v.values._groups.detalle[1].cantidad = 8; },
  "una fila de más": (v) => { v.values._groups.extras.push({ etiqueta: "z" }); },
  "una fila de menos": (v) => { v.values._groups.detalle.pop(); },
  "el orden de las filas": (v) => { v.values._groups.detalle.reverse(); },
};
for (const [name, mutate] of Object.entries(variants)) {
  const body = structuredClone(sent); mutate(body);
  const r = await op.call("POST", "/api/captures", body);
  check(`B2 mismo capture_id con ${name} distinto = 409 CAPTURE_IDEMPOTENCY_CONFLICT`, r.status === 409 && r.json.code === "CAPTURE_IDEMPOTENCY_CONFLICT" && countsA() === before);
}
check("B3 el contenido original no cambió tras los conflictos", JSON.stringify(dbRows(sent.capture_id)) === JSON.stringify(["detalle|1|item=A,cantidad=2,peso=1.50,tipo=a", "detalle|2|item=C,cantidad=7,peso=3.25,tipo=b", "extras|1|etiqueta=x,valor=0.10", "extras|2|etiqueta=y", "unico|1|ref=r"]));
const bad = structuredClone(sent); bad.capture_id = crypto.randomUUID(); bad.values._groups.detalle[0].cantidad = "doce"; bad.values._groups.detalle[1].id = "x"; bad.values._groups.inventado = [{}];
const rejected = await op.call("POST", "/api/captures", bad);
check("B4 filas mal formadas / claves internas / grupo no declarado = 422 seguro (nombra filas, no valores ni SQL) y no se escribe nada", rejected.status === 422 && rejected.json.code === "CAPTURE_VALIDATION" && /_groups\.detalle\[1\]\.cantidad/.test(rejected.text) && !rejected.text.includes("doce") && !/SELECT/.test(rejected.text) && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${bad.capture_id}'`)[0] === "0");
const sinGrupo = structuredClone(sent); sinGrupo.capture_id = crypto.randomUUID(); delete sinGrupo.values._groups;
check("B5 sin el grupo con mínimo 1 = 422 (la definición manda)", (await op.call("POST", "/api/captures", sinGrupo)).status === 422);
const noGroups = await op.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-10", assignment_id: assignment.id, device_key: sent.device_key, values: { codigo_numero_de_producto: "A", numero_de_fardo: "B", peso_fardo: "C", _groups: {} } });
check("B6 un formulario sin grupos (P1-10) rechaza `_groups` (campo desconocido): su contrato no cambia", noGroups.status === 422 && /_groups: campo desconocido/.test(noGroups.text), `status ${noGroups.status}`);
await op.call("POST", "/api/auth/logout");

// ================================================================ 4. validación local, reconciliación y filas bloqueadas durante un intento pendiente
await browser("v", 9382, async (b) => {
  await b.goto(`${WEB}/qa-harness`); await loginUi(b, "operacion");
  await b.waitFor("document.body.innerText.includes('Captura con grupos repetibles')", "formulario", 30000);
  await setCell(b, "detalle", 1, 0, "solo ítem");
  const countBefore = q("SELECT count(*) FROM vinto_txn.capture")[0];
  await b.clickText("Enviar registro trazable");
  await b.waitFor("document.body.innerText.includes('Cantidad: es obligatorio.')", "errores de fila", 10000);
  await b.shot("v1-errores-por-fila.png");
  const t = await text(b);
  check("V1 errores asociados a la fila y al campo (Detalle fila 1: Cantidad; y Lote), sin ningún POST", t.includes("Cantidad: es obligatorio.") && t.includes("Lote: es obligatorio.") && posts(b).length === 0 && q("SELECT count(*) FROM vinto_txn.capture")[0] === countBefore);
  await b.js("document.querySelector('#qa-logout').click()"); await b.waitFor("!!document.querySelector('#qa-user')", "ingreso tras logout", 15000);
});

async function faultRun(mode, label, port, lote, expectRetry) {
  let result = {};
  await browser(label, port, async (b) => {
    await b.goto(`${WEB}/qa-harness?mode=${mode}`); await loginUi(b, "operacion");
    await b.waitFor("document.body.innerText.includes('Captura con grupos repetibles')", "formulario", 30000);
    await b.click(addRowBtn("detalle")); await b.click(addRowBtn("extras"));
    for (const [i, v] of ["P", "3", "", ""].entries()) await setCell(b, "detalle", 1, i, v);
    for (const [i, v] of ["Q", "9", "", ""].entries()) await setCell(b, "detalle", 2, i, v);
    for (const [i, v] of ["e1", "1.5"].entries()) await setCell(b, "extras", 1, i, v);
    await b.setValue('main input', lote);
    await b.clickText("Enviar registro trazable");
    if (!expectRetry) await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación tras respuesta perdida", 30000);
    else {
      await b.waitFor("document.body.innerText.includes('El registro no se guardó')", "aviso de no guardado", 30000);
      const locked = (await isDisabled(b, addRowBtn("detalle"))) && (await isDisabled(b, removeBtn("detalle", "Detalle", 1))) && (await isDisabled(b, addRowBtn("extras"))) && await b.js("[...document.querySelectorAll('main input, main select, main textarea')].every((e) => e.disabled)");
      await b.shot(`${label}-no-guardado-filas-bloqueadas.png`);
      check(`${label} con el intento pendiente no se pueden agregar/eliminar filas ni editar campos (el intento no cambia)`, locked);
      await b.clickText("Reintentar envío");
      await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación tras el reintento", 30000);
    }
    await b.shot(`${label}-final.png`);
    result = { sent: (await capturePosts(b)).map((x) => JSON.parse(x)), requests: [...b.log.requests] };
    await b.js("document.querySelector('#qa-logout').click()"); await b.waitFor("!!document.querySelector('#qa-user')", "ingreso tras logout", 15000);
  });
  return result;
}
const lostResponse = await faultRun("lose-response", "C1", 9383, "L-C1", false);
const idC = lostResponse.sent[0].capture_id;
check("C1 respuesta perdida tras guardar: el GET por el mismo id encuentra la captura con TODAS sus filas (1 POST, sin duplicar)", lostResponse.sent.length === 1 && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${idC}'`)[0] === "1" && dbRows(idC).length === 3 && lostResponse.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${idC}`) && r.status === 200), dbRows(idC).join(" ; "));
const lostRequest = await faultRun("lose-request", "C2", 9384, "L-C2", true);
const idD = lostRequest.sent[0].capture_id;
check("C2 petición perdida antes de llegar: GET 404 -> reintento con el MISMO capture_id y las MISMAS filas (2 envíos idénticos) -> una sola captura con sus 3 filas", lostRequest.sent.length === 2 && JSON.stringify(lostRequest.sent[0]) === JSON.stringify(lostRequest.sent[1]) && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${idD}'`)[0] === "1" && dbRows(idD).length === 3
  && lostRequest.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${idD}`) && r.status === 404));

// ================================================================ 5. resumen y no-escritura en DEV
check("Z1 en la base efímera hay exactamente 3 capturas agrupadas (A, C1 y C2), sin duplicados", q(`SELECT count(*) FROM vinto_txn.capture WHERE form_version_id IN (SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = '${CODE}')`)[0] === "3");
check("Z2 sin sesiones activas de prueba tras los logouts", q(`SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now() AND user_id = '${users.operacion.user_id}'`)[0] === "0");
const devAfter = psql("vinto", DEV_SQL)[0];
check("Z3 DEV intacto: capturas | filas de grupo | auditoría | sesiones | auth_event | concesiones idénticos antes y después (solo SELECT)", devBefore === devAfter, `${devBefore} -> ${devAfter}`);
writeFileSync(join(outDir, "resultados-e2e-grupos.json"), JSON.stringify({ database, devBefore, devAfter, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
