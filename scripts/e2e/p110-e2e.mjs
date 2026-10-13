// node scripts/e2e/p110-e2e.mjs <creds.json> <evidence-dir>
// M2-B2 · recorrido E2E de VINTO-P1-10 en un entorno AISLADO: Login -> OT -> asignación -> P1-10 (interfaz real en Chrome) -> envío -> PostgreSQL efímero -> GET por id -> listado
// filtrado -> logout. Requiere el backend de prueba (backend/tests/e2e_p110_server.py, puerto 8190) y el frontend de QA con el harness temporal (puerto 8796, ver
// scripts/e2e/harness-page.tsx.txt). NO es una ruta ni una prueba del producto.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787), si la base indicada no termina en `_test`, si no es `current_database()` en PostgreSQL, si el backend no
// sirve esa base (los usuarios solo existen en ella) o si el navegador intenta llamar al puerto 8000. Todas las lecturas de PostgreSQL son SELECT en transacciones de solo lectura.
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [credsPath, outDir] = process.argv.slice(2);
const API = process.env.E2E_API ?? "http://127.0.0.1:8190", WEB = process.env.E2E_WEB ?? "http://127.0.0.1:8796";
const PG_CONTAINER = process.env.E2E_PG_CONTAINER ?? "vinto-local-postgres-1";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const { database, users, machine_code: MACHINE } = JSON.parse(readFileSync(credsPath, "utf8"));
mkdirSync(outDir, { recursive: true });
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`); };
const abort = (message) => { console.error("E2E ABORTADO: " + message); process.exit(2); };

// ---------------------------------------------------------------- salvaguardas
const apiUrl = new URL(API), webUrl = new URL(WEB);
if (apiUrl.port === "8000" || webUrl.port === "8787") abort("la API o el frontend apuntan a DEV");
if (!/^127\.0\.0\.1$/.test(apiUrl.hostname) || !/^127\.0\.0\.1$/.test(webUrl.hostname)) abort("solo se admite 127.0.0.1");
if (!/_test$/.test(database) || database === "vinto") abort(`la base ${database} no es una base efímera *_test`);
const pgUser = execFileSync("docker", ["exec", PG_CONTAINER, "printenv", "POSTGRES_USER"], { encoding: "utf8" }).trim();
const psql = (db, sql) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", `BEGIN READ ONLY; ${sql}; COMMIT;`], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const q = (sql) => psql(database, sql);
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check("S0 la base del recorrido es efímera (*_test) y su identidad se verificó con current_database()", true, identity);
const devBefore = psql("vinto", "SELECT (SELECT count(*) FROM vinto_txn.capture)||'|'||(SELECT count(*) FROM vinto_audit.audit_event)||'|'||(SELECT count(*) FROM vinto_auth.session)||'|'||(SELECT count(*) FROM vinto_auth.auth_event)||'|'||(SELECT count(*) FROM vinto_master.user_sector)")[0];

// ---------------------------------------------------------------- cliente API con jar de cookies (roles de preparación y comprobaciones)
function client() {
  let cookie = "";
  const call = async (method, path, body, extraHeaders = {}) => {
    const response = await fetch(API + path, { method, headers: { "Content-Type": "application/json", Origin: WEB, ...(cookie ? { Cookie: cookie } : {}), ...extraHeaders }, body: body === undefined ? undefined : JSON.stringify(body) });
    const set = response.headers.get("set-cookie");
    if (set) cookie = set.split(";")[0];
    const text = await response.text();
    let json = null; try { json = JSON.parse(text); } catch { /* sin cuerpo */ }
    return { status: response.status, json };
  };
  return { call, login: async (u) => call("POST", "/api/auth/login", { username: users[u].username, password: users[u].password }) };
}
const orderBody = (article) => ({ machine_code: MACHINE, lines: [{ pv_reference: "PV-E2E-1", article_code: article, quantity: 10, due_date: "2026-11-01" }] });

// ---------------------------------------------------------------- Chrome (CDP)
async function browser(label, port, body) {
  const profile = mkdtempSync(join(tmpdir(), `m2b2-${label}-`));
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "--window-size=1366,900", "about:blank"], { stdio: "ignore" });
  let ws, nextId = 1; const pending = new Map(); const log = { requests: [], consoleErrors: [], exceptions: [], failedByDesign: [] };
  const byId = new Map();
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
    const setInput = (selector, value) => js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
    const clickText = (text) => js(`(() => { const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim().startsWith(${JSON.stringify(text)})); if (!b || b.disabled) return false; b.click(); return true; })()`);
    const shot = async (name) => { const h = await js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"); const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1366, height: Math.min(h, 3000), scale: 1 } }); writeFileSync(join(outDir, name), Buffer.from(r.result.data, "base64")); };
    const fields = () => js("[...document.querySelectorAll('main input, main textarea')].map((e) => e.value)");
    await body({ send, js, waitFor, goto, setInput, clickText, shot, fields, log, sleep, port });
  } finally {
    try { ws?.close(); } catch { /* ya cerrado */ }
    spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" }); await sleep(1500);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* se limpia luego */ }
  }
}
const loginUi = async (b, who) => { await b.waitFor("!!document.querySelector('#qa-user')", "formulario de ingreso"); await b.setInput("#qa-user", users[who].username); await b.setInput("#qa-pass", users[who].password); await b.js("document.querySelector('#qa-login').click()"); };
const fill = async (b, v) => {
  const inputs = ["main input:nth-of-type(1)"]; void inputs;
  const all = await b.js("[...document.querySelectorAll('main input, main textarea')].length"); if (all !== 4) throw new Error("se esperaban 4 campos y hay " + all);
  const sel = (i) => `(document.querySelectorAll('main input, main textarea'))[${i}]`;
  for (const [i, value] of [v.codigo, v.fardo, v.peso, v.obs].entries()) await b.js(`(() => { const el = ${sel(i)}; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
};
const posts = (b) => b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/captures"));
const text = (b) => b.js("document.body.innerText");
const capturePosts = (b) => b.js("window.__posts ?? []");

// ================================================================ 1. preparación por API (Login -> OT -> asignación)
const jefatura = client(), supervision = client(), operacion = client(), soloBobinas = client();
const article = JSON.parse(readFileSync(credsPath, "utf8")).article_code;
check("P1 login JEFATURA / SUPERVISION / OPERACION de prueba", (await jefatura.login("jefatura")).status === 200 && (await supervision.login("supervision")).status === 200 && (await operacion.login("operacion")).status === 200);
const me = await operacion.call("GET", "/api/auth/me");
check("P2 el backend sirve la base efímera: el id del usuario de prueba (que solo existe allí) coincide", me.status === 200 && me.json.user.id === users.operacion.user_id && q(`SELECT count(*) FROM vinto_master.user WHERE id = '${users.operacion.user_id}'`)[0] === "1");
await operacion.call("POST", "/api/auth/logout"); // la sesión de preparación se cierra: las comprobaciones de sesiones activas solo ven las del navegador
check("P3 sin sesión: POST /api/captures = 401", (await client().call("POST", "/api/captures", { x: 1 })).status === 401);
const order = await jefatura.call("POST", "/api/work-orders", orderBody(article));
check("P4 JEFATURA crea la OT en la máquina de prueba", order.status === 201, `status ${order.status}`);
const published = await jefatura.call("POST", `/api/work-orders/${order.json.id}/publish`);
const activated = await supervision.call("POST", "/api/assignments/activate", { work_order_id: published.json.id, baseline_line_id: published.json.baseline.lines[0].id });
check("P5 SUPERVISION activa la asignación (turno ficticio de prueba)", activated.status === 201 && activated.json.assignment.machine.code === MACHINE && activated.json.assignment.shift.code.startsWith("FICT_"), `status ${activated.status}, turno ${activated.json?.assignment?.shift?.code}`);
const assignment = activated.json.assignment;
await soloBobinas.login("operacion_solo_bobinas");
const outside = await soloBobinas.call("GET", `/api/assignments/active?machine_code=${MACHINE}`);
check("P6 un operador SIN concesión de Rebobinado no ve la máquina (4xx)", [404, 422].includes(outside.status), `status ${outside.status}`);

const VALUES_A = { codigo: "EJ-PROD-001", fardo: "00-0042", peso: "12,5 kg (texto)", obs: "Corrida A · dato de prueba" };
let captureA = null;

// ================================================================ 2. interfaz real: envío normal (201) + consulta posterior
await browser("a", 9371, async (b) => {
  await b.goto(`${WEB}/qa-harness?machine=${MACHINE}`);
  await loginUi(b, "operacion");
  await b.waitFor("document.body.innerText.includes('Registro de fardos') && document.querySelectorAll('main input').length === 3", "formulario P1-10", 30000);
  const plain = await text(b);
  check("A1 el formulario muestra el contexto de la asignación (OT, máquina, turno, fecha)", plain.includes(order.json.number) && plain.includes(MACHINE) && plain.includes(assignment.shift.name) && plain.includes(assignment.operating_date));
  check("A2 muestra la identificación del usuario autenticado sin llamarla firma ni responsable aprobado", plain.includes(users.operacion.username ? "Operacion (prueba E2E)" : "") && plain.includes("no es el responsable aprobado ni una firma"));
  check("A3 Responsable y Firma siguen como decisiones pendientes y la ficha figura como NO homologada", plain.includes("Ficha NO homologada") && (plain.match(/— pendiente de definición —/g) ?? []).length === 2 && plain.includes("no existe firma digital en el sistema y no se simula una"));
  await b.shot("a1-formulario-vacio.png");
  await fill(b, VALUES_A);
  const before = q("SELECT count(*) FROM vinto_txn.capture")[0];
  check("A4 clic en enviar", await b.clickText("Enviar registro trazable"));
  await b.waitFor("document.querySelector('[data-section=saved]') && document.querySelector('[data-section=saved]').innerText.includes('consulta posterior')", "confirmación", 30000);
  await b.waitFor("document.querySelector('[data-section=saved]').innerText.includes('Verificada con una consulta posterior')", "consulta posterior", 15000);
  await b.shot("a2-enviado-y-verificado.png");
  const sent = posts(b), reads = b.log.requests.filter((r) => r.method === "GET" && /\/api\/captures\/[0-9a-f-]{36}$/.test(r.url));
  check("A5 un único POST /api/captures = 201 y una consulta posterior GET /api/captures/{id} = 200", sent.length === 1 && sent[0].status === 201 && reads.length === 1 && reads[0].status === 200, `POST ${sent.map((r) => r.status)}, GET ${reads.map((r) => r.status)}`);
  const body = JSON.parse((await capturePosts(b))[0]);
  captureA = body;
  check("A6 el payload contiene solo capture_id, form_code, assignment_id, device_key y los 4 valores (sin fecha/máquina/responsable/firma)", JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["assignment_id", "capture_id", "device_key", "form_code", "values"]) && body.form_code === "VINTO-P1-10" && JSON.stringify(Object.keys(body.values).sort()) === JSON.stringify(["codigo_numero_de_producto", "numero_de_fardo", "observaciones", "peso_fardo"]));
  const rows = q(`SELECT f.key, d.value_type, d.value_text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${body.capture_id}' ORDER BY f.key`);
  check("A7 PostgreSQL guarda los valores EXACTOS como texto", JSON.stringify(rows) === JSON.stringify([`codigo_numero_de_producto|text|${VALUES_A.codigo}`, `numero_de_fardo|text|${VALUES_A.fardo}`, `observaciones|textarea|${VALUES_A.obs}`, `peso_fardo|text|${VALUES_A.peso}`]), rows.join(" ; "));
  const head = q(`SELECT c.status, c.revision, f.code, m.code, c.assignment_id, c.created_by FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id JOIN vinto_master.machine m ON m.id = c.machine_id WHERE c.id = '${body.capture_id}'`)[0];
  check("A8 la cabecera se derivó en el servidor (estado, revisión, formulario, máquina, asignación, autor)", head === `submitted|1|VINTO-P1-10|${MACHINE}|${assignment.id}|${users.operacion.user_id}`, head);
  check("A9 una captura nueva (sin duplicados) y la auditoría registró el alta", Number(q("SELECT count(*) FROM vinto_txn.capture")[0]) === Number(before) + 1 && Number(q(`SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'capture' AND entity_key::text LIKE '%${body.capture_id}%' AND actor_id = '${users.operacion.user_id}'`)[0]) >= 1, `capturas ${before} -> ${q("SELECT count(*) FROM vinto_txn.capture")[0]}`);
  const storage = JSON.parse(await b.js("JSON.stringify({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })"));
  check("A10 el navegador solo guarda la clave técnica vinto-device-key (nada de negocio en localStorage/sessionStorage)", JSON.stringify(storage.local) === JSON.stringify(["vinto-device-key"]) && storage.session.length === 0, JSON.stringify(storage));
  // lectura por id y listados desde la sesión del navegador (cookie HttpOnly)
  const read = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures/${body.capture_id}', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A11 GET por id = 200 con los mismos valores", read.status === 200 && read.body.form.code === "VINTO-P1-10" && JSON.stringify(read.body.values) === JSON.stringify(body.values));
  const filtered = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures?form_code=VINTO-P1-10', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A12 listado filtrado por form_code = solo P1-10 e incluye la captura", filtered.status === 200 && filtered.body.length >= 1 && filtered.body.every((c) => c.form.code === "VINTO-P1-10") && filtered.body.some((c) => c.id === body.capture_id));
  const historic = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A13 el listado histórico (sin filtro) sigue siendo F6 y NO incluye P1-10", historic.status === 200 && historic.body.every((c) => c.form.code === "VINTO-P1-06") && !historic.body.some((c) => c.id === body.capture_id));
  const unknown = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures?form_code=VINTO-P1-99', { credentials: 'include' }).then((r) => JSON.stringify({ status: r.status }))`));
  check("A14 un form_code no habilitado = 422 (no una lista vacía)", unknown.status === 422);
  check("A15 sin errores CORS/JS en el navegador", b.log.exceptions.length === 0 && b.log.consoleErrors.filter((e) => !/401/.test(e)).length === 0, JSON.stringify([...b.log.exceptions, ...b.log.consoleErrors]).slice(0, 300));
  // logout
  check("A16 cerrar sesión", await b.js("(() => { document.querySelector('#qa-logout').click(); return true; })()"));
  await b.waitFor("!!document.querySelector('#qa-user')", "pantalla de ingreso tras logout", 15000);
  const lo = b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/auth/logout"));
  const after = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/auth/me', { credentials: 'include' }).then((r) => JSON.stringify({ status: r.status }))`));
  const cookies = (await b.send("Network.getCookies", { urls: [API] })).result.cookies;
  check("A17 logout = 204, /api/auth/me = 401, cookie eliminada y sesión revocada en PostgreSQL", lo.length === 1 && lo[0].status === 204 && after.status === 401 && cookies.length === 0
    && q(`SELECT count(*) FROM vinto_auth.session WHERE user_id = '${users.operacion.user_id}' AND revoked_at IS NULL AND expires_at > now()`)[0] === "0");
  const afterLogout = await text(b);
  check("A18 tras el logout no quedan datos del registro en pantalla", !afterLogout.includes(VALUES_A.codigo) && !afterLogout.includes("Registro de fardos"));
});

// ================================================================ 3. idempotencia y conflicto sobre la captura A (API)
const op2 = client(); await op2.login("operacion");
const replay = await op2.call("POST", "/api/captures", captureA);
check("B1 reintento idéntico = 200 already_submitted, sin duplicados", replay.status === 200 && replay.json.already_submitted === true && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${captureA.capture_id}'`)[0] === "1");
const conflict = await op2.call("POST", "/api/captures", { ...captureA, values: { ...captureA.values, numero_de_fardo: "OTRO" } });
check("B2 mismo capture_id con contenido distinto = 409 CAPTURE_IDEMPOTENCY_CONFLICT y el dato original no cambia", conflict.status === 409 && conflict.json.code === "CAPTURE_IDEMPOTENCY_CONFLICT" && q(`SELECT d.value_text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${captureA.capture_id}' AND f.key = 'numero_de_fardo'`)[0] === VALUES_A.fardo);
const invalid = await op2.call("POST", "/api/captures", { ...captureA, capture_id: crypto.randomUUID(), values: { ...captureA.values, peso_fardo: 12.5 } });
check("B3 valores inválidos (peso como número JSON) = 422 CAPTURE_VALIDATION y no se escribe nada", invalid.status === 422 && invalid.json.code === "CAPTURE_VALIDATION" && q("SELECT count(*) FROM vinto_txn.capture")[0] === "1");
const ctxLeak = await op2.call("POST", "/api/captures", { ...captureA, capture_id: crypto.randomUUID(), values: { ...captureA.values, responsable: "x", firma: "y", fecha: "2026-01-01", maquina: "OTRA" } });
check("B4 enviar fecha/máquina/responsable/firma como valores = 422 (el contexto no lo decide el cliente)", ctxLeak.status === 422 && q("SELECT count(*) FROM vinto_txn.capture")[0] === "1");
const f6Cross = await op2.call("POST", "/api/captures", { ...captureA, form_code: "VINTO-P1-06", values: { cantidad_fardos: 1, punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "1" } });
check("B5 el mismo capture_id con otro formulario (F6) = 409", f6Cross.status === 409 && f6Cross.json.code === "CAPTURE_IDEMPOTENCY_CONFLICT");
const sbRead = await soloBobinas.call("GET", `/api/captures/${captureA.capture_id}`);
const sbList = await soloBobinas.call("GET", "/api/captures?form_code=VINTO-P1-10");
check("B6 fuera de alcance (sin concesión de Rebobinado): GET por id = 404 y listado vacío", sbRead.status === 404 && sbList.status === 200 && sbList.json.length === 0);
const jefRead = await jefatura.call("GET", `/api/captures/${captureA.capture_id}`);
check("B7 sin permiso production.capture (JEFATURA): 403", jefRead.status === 403);
const noSession = await client().call("GET", `/api/captures/${captureA.capture_id}`);
check("B8 sin sesión: GET por id = 401", noSession.status === 401);
await op2.call("POST", "/api/auth/logout");

// ================================================================ 4. reconciliación en el navegador (respuesta perdida / petición perdida) y validación local
async function faultRun(mode, label, port, values, expectRetry) {
  let result = {};
  await browser(label, port, async (b) => {
    await b.goto(`${WEB}/qa-harness?machine=${MACHINE}&mode=${mode}`);
    await loginUi(b, "operacion");
    await b.waitFor("document.querySelectorAll('main input').length === 3", "formulario", 30000);
    await fill(b, values);
    check(`${label} clic en enviar`, await b.clickText("Enviar registro trazable"));
    if (!expectRetry) {
      await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación tras respuesta perdida", 30000);
      await b.shot(`${label}-reconciliado.png`);
    } else {
      await b.waitFor("document.body.innerText.includes('El registro no se guardó')", "aviso de no guardado", 30000);
      const locked = await b.js("[...document.querySelectorAll('main input, main textarea')].every((e) => e.disabled)");
      await b.shot(`${label}-no-guardado-reintentar.png`);
      check(`${label} campos bloqueados y botón «Reintentar envío» disponible`, locked && (await text(b)).includes("Reintentar envío"));
      check(`${label} reintento`, await b.clickText("Reintentar envío"));
      await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación tras el reintento", 30000);
      await b.shot(`${label}-reintento-ok.png`);
    }
    const sent = (await capturePosts(b)).map((x) => JSON.parse(x));
    await b.js("document.querySelector('#qa-logout').click()"); // cierra la sesión del navegador (sin sesiones huérfanas)
    await b.waitFor("!!document.querySelector('#qa-user')", "ingreso tras logout", 15000);
    result = { sent, requests: [...b.log.requests] };
  });
  return result;
}
const resp = await faultRun("lose-response", "C1", 9372, { codigo: "EJ-PROD-002", fardo: "00-0043", peso: "13 kg", obs: "" }, false);
const idC = resp.sent[0].capture_id;
check("C1 respuesta perdida tras guardar: reconciliación por GET encuentra la captura (1 POST, sin duplicar) y la interfaz confirma", resp.sent.length === 1 && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${idC}'`)[0] === "1" && resp.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${idC}`) && r.status === 200), `POSTs ${resp.sent.length}`);
const lost = await faultRun("lose-request", "C2", 9373, { codigo: "EJ-PROD-003", fardo: "00-0044", peso: "14 kg", obs: "x" }, true);
const idD = lost.sent[0].capture_id;
check("C2 petición perdida antes de llegar: GET = 404 (no guardado), el reintento usa el MISMO capture_id y payload (2 envíos idénticos) y queda UNA sola captura", lost.sent.length === 2 && lost.sent[0].capture_id === lost.sent[1].capture_id && JSON.stringify(lost.sent[0]) === JSON.stringify(lost.sent[1]) && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${idD}'`)[0] === "1"
  && lost.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${idD}`) && r.status === 404), `POSTs ${lost.sent.length}`);

await browser("v", 9374, async (b) => {
  await b.goto(`${WEB}/qa-harness?machine=${MACHINE}`);
  await loginUi(b, "operacion");
  await b.waitFor("document.querySelectorAll('main input').length === 3", "formulario", 30000);
  await fill(b, { codigo: "", fardo: "   ", peso: "", obs: "solo observaciones" });
  const countBefore = q("SELECT count(*) FROM vinto_txn.capture")[0];
  await b.clickText("Enviar registro trazable");
  await b.waitFor("document.body.innerText.includes('es obligatorio')", "validación local", 10000);
  await b.shot("v1-validacion-local.png");
  check("V1 campos obligatorios vacíos: se explica el error y NO se envía ningún POST", posts(b).length === 0 && (await text(b)).includes("Código / número de producto: es obligatorio.") && q("SELECT count(*) FROM vinto_txn.capture")[0] === countBefore);
  await b.js("document.querySelector('#qa-logout').click()");
});

// ================================================================ 5. resumen y no-escritura en DEV
const total = q("SELECT count(*) FROM vinto_txn.capture WHERE form_version_id IN (SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = 'VINTO-P1-10')")[0];
check("Z1 en la base efímera hay exactamente 3 capturas P1-10 (A, C1 y C2), sin duplicados", total === "3", `total ${total}`);
check("Z2 sesiones activas de prueba tras los logouts", Number(q("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now() AND user_id = '" + users.operacion.user_id + "'")[0]) === 0);
const devAfter = psql("vinto", "SELECT (SELECT count(*) FROM vinto_txn.capture)||'|'||(SELECT count(*) FROM vinto_audit.audit_event)||'|'||(SELECT count(*) FROM vinto_auth.session)||'|'||(SELECT count(*) FROM vinto_auth.auth_event)||'|'||(SELECT count(*) FROM vinto_master.user_sector)")[0];
check("Z3 DEV intacto: capturas | auditoría | sesiones | auth_event | concesiones idénticos antes y después (solo SELECT)", devBefore === devAfter, `${devBefore} -> ${devAfter}`);
writeFileSync(join(outDir, "resultados-e2e.json"), JSON.stringify({ database, devBefore, devAfter, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
