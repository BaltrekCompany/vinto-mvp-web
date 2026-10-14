// node scripts/e2e/b0-e2e.mjs <creds.json> <evidence-dir>
// E2E-B0 · validación integral de Bobinas MP1/MP3 y Calidad desde la NAVEGACIÓN NORMAL de VINTO (la aplicación real en `/`, sin harness de formulario ni ruta de QA):
// Jefatura crea y publica la OT -> Supervisión activa la asignación -> Operación captura F3 (bobina) y P1-06 -> Calidad ve la bobina en la bandeja, registra P1-19 y P1-20 y consulta el historial.
// Más seguridad y permisos, Seguimiento saneado (PB-CLEAN), un recorrido en MP3 con reintento idempotente y la comprobación de que Rebobinado y Conversión siguen sin disponibilidad operativa.
// Backend REAL (backend/tests/e2e_b0_server.py) con la configuración real del producto: solo BOBINAS operativo y política central solo F6 (VINTO-P1-06); F3 y Calidad usan sus rutas existentes.
// TODOS los datos son FICTICIOS y los maestros son CANDIDATOS (no homologados). Esta prueba demuestra el circuito TÉCNICO; no aprueba ninguna regla industrial ni autoriza el piloto.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787) o no son 127.0.0.1, si la base no termina en `_test`, si no es `current_database()`, si el contenedor de PostgreSQL
// no es el exclusivo de E2E-B0 o si el navegador llama al puerto 8000. Las lecturas SQL son SELECT en transacciones de solo lectura; la única escritura SQL posible es sobre la base EFÍMERA y solo
// para comprobaciones explícitas (ninguna en este recorrido).
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [credsPath, outDir] = process.argv.slice(2);
const API = process.env.E2E_API ?? "http://127.0.0.1:8190", WEB = process.env.E2E_WEB ?? "http://127.0.0.1:8796";
const PG_CONTAINER = process.env.E2E_PG_CONTAINER ?? "vinto-e2eb0-pg";
const CHROME = process.env.E2E_CHROME ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const creds = JSON.parse(readFileSync(credsPath, "utf8"));
const { database, users, articles } = creds;
mkdirSync(outDir, { recursive: true });
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// kind: "browser" = navegador real; "http" = verificación HTTP complementaria; "sql" = comprobación SQL de solo lectura
const check = (name, ok, detail = "", kind = "browser") => { results.push({ name, ok: !!ok, kind, detail }); console.log(`${ok ? "PASS" : "FAIL"}  [${kind}] ${name}${detail ? "  — " + String(detail).slice(0, 400) : ""}`); };
const abort = (message) => { console.error("E2E ABORTADO: " + message); process.exit(2); };

// ---------------------------------------------------------------- salvaguardas
const apiUrl = new URL(API), webUrl = new URL(WEB);
if (apiUrl.port === "8000" || webUrl.port === "8787" || apiUrl.port === "5432") abort("la API o el frontend apuntan a puertos de DEV");
if (apiUrl.hostname !== "127.0.0.1" || webUrl.hostname !== "127.0.0.1") abort("solo se admite 127.0.0.1");
if (!/^vinto-e2eb0-/.test(PG_CONTAINER)) abort(`el contenedor ${PG_CONTAINER} no es el PostgreSQL exclusivo de E2E-B0`);
if (!/_test$/.test(database) || ["vinto", "vinto_test", "postgres"].includes(database)) abort(`la base ${database} no es una base efímera *_test exclusiva`);
const pgUser = execFileSync("docker", ["exec", PG_CONTAINER, "printenv", "POSTGRES_USER"], { encoding: "utf8" }).trim();
const q = (sql, db = database) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", `BEGIN READ ONLY; ${sql}; COMMIT;`], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check("S0 la base del recorrido es efímera (*_test) y su identidad se verificó con current_database() dentro del PostgreSQL exclusivo de E2E-B0", true, identity, "sql");
const health = await fetch(`${API}/api/health`);
check("S0b la API real responde y su health consulta la base (200)", health.status === 200, String(health.status), "http");

function client() {
  let cookie = "";
  const call = async (method, path, body, extraHeaders = {}) => {
    const response = await fetch(API + path, { method, headers: { "Content-Type": "application/json", Origin: WEB, ...(cookie ? { Cookie: cookie } : {}), ...extraHeaders }, body: body === undefined ? undefined : JSON.stringify(body) });
    const set = response.headers.get("set-cookie"); if (set) cookie = set.split(";")[0];
    const text = await response.text(); let json = null; try { json = JSON.parse(text); } catch { /* sin cuerpo */ }
    return { status: response.status, json, text, headers: response.headers };
  };
  return { call, login: (u) => call("POST", "/api/auth/login", { username: users[u].username, password: users[u].password }), anonymous: () => { cookie = ""; } };
}

// ---------------------------------------------------------------- Chrome (CDP) sobre la aplicación real
// Registra TODA petición POST de escritura a /api/ (salvo auth) y permite fallos simulados: «lose-request» (la petición no llega) o «lose-response» (el servidor procesa y la respuesta se pierde)
// una sola vez para la primera petición de captura de bobina (F3 o Calidad). `window.__block` lista subcadenas de URL que fallan siempre (estado central no disponible).
const FAULT_SCRIPT = (mode) => `(() => { const w = window; if (w.__fault) return; w.__fault = true; w.__posts = []; w.__block = []; const real = w.fetch.bind(w); let armed = ${JSON.stringify(mode)} !== "none";
  const target = (url) => /\\/api\\/bobbins$|\\/api\\/quality\\/bobbins\\/[^/]+\\/captures$/.test(String(url));
  w.fetch = async (input, init) => { const url = String(input && input.url ? input.url : input); const post = (init && init.method === "POST") && /\\/api\\//.test(url) && !/\\/api\\/auth\\//.test(url); if (post) w.__posts.push({ url, body: String(init.body ?? "") });
    if (w.__block.some((p) => url.includes(p))) throw new TypeError("simulated: central source unavailable");
    if (post && armed && ${JSON.stringify(mode)} === "lose-request" && target(url)) { armed = false; throw new TypeError("simulated: request never reached the server"); }
    const response = await real(input, init); if (post && armed && ${JSON.stringify(mode)} === "lose-response" && target(url)) { armed = false; throw new TypeError("simulated: response lost after the server processed the request"); } return response; }; })()`;

async function browser(label, port, opts, body) {
  const { mobile = false, fault = "none" } = opts;
  const width = mobile ? 390 : 1366, height = mobile ? 844 : 900;
  const profile = mkdtempSync(join(tmpdir(), `m4a-${label}-`));
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", `--window-size=${width},${height}`, "about:blank"], { stdio: "ignore" });
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
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
    if (fault !== "none") await send("Page.addScriptToEvaluateOnNewDocument", { source: FAULT_SCRIPT(fault) });
    else await send("Page.addScriptToEvaluateOnNewDocument", { source: FAULT_SCRIPT("none") }); // solo registra los POST /api/captures
    const js = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails).slice(0, 300)); return r.result?.result?.value; };
    const waitFor = async (expr, what, ms = 25000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await js(`!!(${expr})`)) return true; } catch { /* navegando */ } await sleep(200); } throw new Error("tiempo agotado esperando: " + what); };
    const goto = async (url) => { await send("Page.navigate", { url }); await sleep(700); await waitFor("document.readyState === 'complete'", "carga " + url); };
    const text = () => js("document.body.innerText");
    const setField = (labelText, value) => js(`(() => { const l = [...document.querySelectorAll('label')].find((x) => x.innerText.trim().replace(/ \\*$/, '') === ${JSON.stringify(labelText)} && x.offsetParent !== null); const el = l && l.parentElement.querySelector('select, input, textarea'); if (!el) return false; const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); return true; })()`);
    const clickText = (t, scope = "document") => js(`(() => { const b = [...${scope}.querySelectorAll('button')].filter((x) => x.offsetParent !== null).find((x) => x.innerText.trim().startsWith(${JSON.stringify(t)})); if (!b || b.disabled) return false; b.click(); return true; })()`);
    const click = (selector) => js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el || el.disabled) return false; el.click(); return true; })()`);
    const shot = async (name) => { const h = await js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"); const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(h, 5000), scale: 1 } }); writeFileSync(join(outDir, name), Buffer.from(r.result.data, "base64")); };
    const overflow = () => js("document.documentElement.scrollWidth - window.innerWidth");
    const api = { send, js, waitFor, goto, text, setField, clickText, click, shot, overflow, log, sleep };
    try { await body(api); } catch (error) { try { await shot(`fallo-${label}.png`); console.error("TEXTO AL FALLAR:", (await text()).replace(/\s+/g, " ").slice(0, 600)); console.error("HTTP:", JSON.stringify(log.requests.filter((r) => r.status >= 400 || r.status === null).slice(0, 8).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`))); } catch { /* sin captura */ } throw error; }
  } finally {
    try { ws?.close(); } catch { /* ya cerrado */ }
    spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" }); await sleep(1500);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* se limpia luego */ }
  }
}
// navegación NORMAL de la aplicación
const loginApp = async (b, who) => {
  await b.goto(`${WEB}/`);
  await b.waitFor("!!document.getElementById('vinto-username')", "formulario de ingreso");
  await b.js(`(() => { const set = (id, v) => { const el = document.getElementById(id); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); }; set('vinto-username', ${JSON.stringify(users[who].username)}); set('vinto-password', ${JSON.stringify(users[who].password)}); })()`);
  await b.clickText("Ingresar");
  await b.waitFor(`!!document.querySelector('button[aria-label="Cerrar sesión"]')`, "aplicación tras el login", 30000);
};
const nav = (b, label) => b.clickText(label); // botones visibles (barra lateral en escritorio; barra superior en móvil)
const logoutApp = async (b) => { await b.click('button[aria-label="Cerrar sesión"]'); await b.waitFor("!!document.getElementById('vinto-username')", "ingreso tras logout", 20000); };

const cap = (b) => b.js("window.__posts ?? []");
const storageDump = (b) => b.js("JSON.stringify(Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])))");
const setNth = (b, selector, i, value) => b.js(`(() => { const el = document.querySelectorAll(${JSON.stringify(selector)})[${i}]; if (!el) return false; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const setById = (b, id, value) => b.js(`(() => { const el = document.getElementById(${JSON.stringify(id)}); if (!el) return false; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const clickCard = (b, title) => b.js(`(() => { const c = [...document.querySelectorAll('button')].filter((x) => x.offsetParent !== null).find((x) => x.querySelector('h3')?.innerText.trim() === ${JSON.stringify(title)}); if (!c) return false; c.click(); return true; })()`);
const clickAria = (b, prefix, contains) => b.js(`(() => { const c = [...document.querySelectorAll('button[aria-label]')].filter((x) => x.offsetParent !== null).find((x) => x.getAttribute('aria-label').startsWith(${JSON.stringify(prefix)}) && x.getAttribute('aria-label').includes(${JSON.stringify(contains)})); if (!c) return false; c.click(); return true; })()`);
const cardAction = (b, otNumber, label) => b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(otNumber)}) && [...d.querySelectorAll('button')].some((x) => x.innerText.trim() === ${JSON.stringify(label)})); const btn = card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === ${JSON.stringify(label)}); if (!btn || btn.disabled) return false; btn.click(); return true; })()`);
const toBobinas = async (b) => { await nav(b, "Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas ·')", "front Bobinas", 15000); };
const goModule = async (b, label, marker) => { await nav(b, label); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(marker)})`, `módulo ${label}`, 20000); await sleep(600); };
const rows = (sql) => q(sql);
const allRequests = [];
const keep = (b) => { allRequests.push(...b.log.requests); };
let port = 9500;
const nextPort = () => port++;
const ctx = { ot: {}, line: {}, assignment: {}, bobbin: {}, capture: {}, body: {} };

const jefatura = client(), supervision = client(), calidadApi = client(), operacionApi = client();
await jefatura.login("jefatura"); await supervision.login("supervision"); await calidadApi.login("calidad"); await operacionApi.login("operacion");
check("S1 la API real responde con sesión y no hay OT ni capturas previas en la base efímera", (await jefatura.call("GET", "/api/work-orders")).json?.length === 0 && rows("SELECT count(*) FROM vinto_txn.capture")[0] === "0", "", "http");

// ============================================================ E01 · Jefatura: OT de MP1 y MP3 desde la navegación normal
await browser("jef", nextPort(), {}, async (b) => {
  await loginApp(b, "jefatura");
  check("E01.0 Jefatura entra por el login real y ve Bobinas · Programación", /Bobinas · Programaci[oó]n/.test(await b.text()), (await b.text()).slice(0, 200));
  for (const machine of ["MP1", "MP3"]) {
    await b.setField("Máquina", machine);
    await b.setField("PV", `PV-E2EB0-${machine}`); await b.setField("Producto", articles[machine]); await b.setField("Cantidad", "100"); await b.setField("Entrega", "2026-12-01");
    check(`E01.1 ${machine}: crear la OT desde la interfaz con el artículo candidato ${articles[machine]}`, await b.clickText("Crear OT inicial"));
    await b.waitFor(`document.body.innerText.includes('PV-E2EB0-${machine}')`, `OT de ${machine} en la lista`, 20000);
  }
  const listed = await jefatura.call("GET", "/api/work-orders");
  for (const wo of listed.json) ctx.ot[wo.machine.code] = { number: wo.number, id: wo.id };
  check("E01.2 las dos OT existen en PostgreSQL (API central) en borrador con su número real", listed.status === 200 && ["MP1", "MP3"].every((m) => ctx.ot[m] && listed.json.find((w) => w.machine.code === m).status === "draft"), JSON.stringify(ctx.ot), "http");
  for (const machine of ["MP1", "MP3"]) {
    check(`E01.3 ${machine}: publicar la base desde la interfaz`, await cardAction(b, ctx.ot[machine].number, "Publicar base"));
    await b.waitFor(`document.body.innerText.includes(${JSON.stringify(ctx.ot[machine].number)})`, "refresco"); await sleep(1500);
  }
  await b.shot("e01-ot-publicadas.png");
  const after = await jefatura.call("GET", "/api/work-orders");
  check("E01.4 ambas OT quedan PUBLICADAS y la interfaz muestra el estado verdadero", after.json.every((w) => w.status === "published") && (await b.text()).includes("Publicada"), after.json.map((w) => `${w.number}:${w.status}`).join(","), "http");
  for (const machine of ["MP1", "MP3"]) {
    const wo = after.json.find((w) => w.machine.code === machine); ctx.line[machine] = wo.baseline.lines[0];
    const sql = rows(`SELECT wo.status||'|'||m.code||'|'||wov.version_number||'|'||l.line_code||'|'||l.pv_reference||'|'||ar.code||'|'||l.quantity FROM vinto_txn.work_order wo JOIN vinto_master.machine m ON m.id = wo.machine_id JOIN vinto_txn.work_order_version wov ON wov.work_order_id = wo.id JOIN vinto_txn.work_order_line l ON l.work_order_version_id = wov.id JOIN vinto_master.article_version av ON av.id = l.article_version_id JOIN vinto_master.article ar ON ar.id = av.article_id WHERE wo.number = '${ctx.ot[machine].number}'`);
    check(`E01.5 PostgreSQL ${machine}: línea base registrada (OT publicada, una línea, PV y artículo correctos)`, sql.length === 1 && sql[0].startsWith(`published|${machine}|`) && sql[0].includes(`|PV-E2EB0-${machine}|${articles[machine]}|100`), sql.join(" ; "), "sql");
  }
  const dump = await storageDump(b);
  check("E01.6 las OT del circuito central no están en localStorage", !dump.includes(ctx.ot.MP1.number) && !dump.includes("PV-E2EB0"), Object.keys(JSON.parse(dump)).join(","));
  check("E01.7 sin errores de JavaScript ni 4xx/5xx inesperados", b.log.exceptions.length === 0 && b.log.requests.filter((r) => r.status >= 400 && !/api\/auth\/me/.test(r.url)).length === 0, JSON.stringify(b.log.requests.filter((r) => r.status >= 400).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`)));
  await logoutApp(b); keep(b);
});
const baselineBefore = JSON.stringify((await jefatura.call("GET", "/api/work-orders")).json.map((w) => w.baseline));

// ============================================================ E02 · Supervisión: activa las asignaciones
await browser("sup", nextPort(), {}, async (b) => {
  await loginApp(b, "supervision");
  await sleep(1200);
  for (const machine of ["MP1", "MP3"]) {
    check(`E02.1 Supervisión ve la OT publicada de ${machine} y activa la asignación desde la interfaz`, await cardAction(b, ctx.ot[machine].number, "Activar"));
    await sleep(1500);
    const active = await supervision.call("GET", `/api/assignments/active?machine_code=${machine}`);
    const a = active.json?.assignment; ctx.assignment[machine] = a?.id;
    check(`E02.2 ${machine}: la asignación activa tiene máquina, OT, artículo, turno y fecha operativa resueltos por el backend`, active.status === 200 && a?.machine.code === machine && a.work_order.number === ctx.ot[machine].number && a.line.article.code === articles[machine] && /^(DIA|NOCHE)$/.test(a.shift.code) && /^\d{4}-\d{2}-\d{2}$/.test(a.operating_date) && active.json.stale === false, JSON.stringify({ shift: a?.shift?.code, date: a?.operating_date, stale: active.json?.stale }), "http");
    const sql = rows(`SELECT a.status||'|'||m.code||'|'||wo.number||'|'||ar.code||'|'||a.operating_date FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version wov ON wov.id = l.work_order_version_id JOIN vinto_txn.work_order wo ON wo.id = wov.work_order_id JOIN vinto_master.article_version av ON av.id = l.article_version_id JOIN vinto_master.article ar ON ar.id = av.article_id WHERE a.id = '${a?.id}'`);
    check(`E02.3 PostgreSQL ${machine}: asignación activa asociada a la OT y al artículo correctos`, sql.length === 1 && sql[0].startsWith(`active|${machine}|${ctx.ot[machine].number}|${articles[machine]}|`), sql.join(" ; "), "sql");
  }
  await b.shot("e02-asignaciones.png");
  const baselineAfter = JSON.stringify((await jefatura.call("GET", "/api/work-orders")).json.map((w) => w.baseline));
  check("E02.4 la línea base publicada por Jefatura no se altera con la asignación (misma versión y líneas)", baselineBefore === baselineAfter, "", "http");
  await logoutApp(b); keep(b);
});

// ============================================================ E03 / E04 · Operación: F3 y P1-06 en MP1 (+ validación de campos)
const OP_NAV = async (b) => { await goModule(b, "Ejecución", "Punto de captura"); };
await browser("op1", nextPort(), {}, async (b) => {
  await loginApp(b, "operacion");
  await OP_NAV(b);
  await b.clickText("MP1"); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(ctx.ot.MP1.number)})`, "contexto de MP1", 20000); await sleep(800);
  await b.shot("e03-ejecucion-mp1.png");
  const cards = await b.js("[...document.querySelectorAll('button h3')].map((e) => e.innerText.trim())");
  check("E03.0 Operación ve el contexto real de MP1 y los formularios centrales F3 y P1-06 entre las tarjetas", (await b.text()).includes(ctx.ot.MP1.number) && cards.includes("Registro de producción de bobinas") && cards.includes("Registro de control de fardos"), cards.join(" | ").slice(0, 200));
  // --- F3: primero un envío incompleto (validación en el cliente, sin POST)
  check("E03.1 abrir F3 (Registro de producción de bobinas) desde la tarjeta", await clickCard(b, "Registro de producción de bobinas") && await b.waitFor("document.body.innerText.includes('Datos de la bobina')", "pantalla F3", 15000));
  check("E03.2 un envío con campos vacíos se rechaza sin llamar al servidor", await b.clickText("Registrar bobina") && (await sleep(700), (await cap(b)).length === 0 && (await b.js("!!document.querySelector('[role=alert]')"))));
  for (const [i, v] of ["07:10", "08:05", "1250,5", "480,25", "3"].entries()) await setNth(b, "main input", i, v);
  await setNth(b, "main textarea", 0, "bobina ficticia E2E-B0 MP1");
  await b.shot("e03-f3-lleno.png");
  check("E03.3 enviar F3 con los campos del contrato técnico actual", await b.clickText("Registrar bobina"));
  await b.waitFor("!document.body.innerText.includes('Datos de la bobina') && document.body.innerText.includes('Punto de captura')", "regreso a Ejecución tras F3", 30000);
  const f3Posts = (await cap(b)).filter((p) => p.url.endsWith("/api/bobbins")); const sentF3 = JSON.parse(f3Posts[0].body);
  const f3Http = b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/bobbins"));
  check("E03.4 un único POST /api/bobbins = 201 con el payload contratado (capture_id, assignment_id, device_key y los seis valores manuales)", f3Posts.length === 1 && f3Http.length === 1 && f3Http[0].status === 201 && Object.keys(sentF3).sort().join(",") === "assignment_id,capture_id,device_key,values" && Object.keys(sentF3.values).sort().join(",") === "diametro,hora_fin,hora_inicio,numero_de_cortes,observaciones,peso_kg" && sentF3.assignment_id === ctx.assignment.MP1, JSON.stringify(Object.keys(sentF3)));
  ctx.capture.f3_mp1 = sentF3.capture_id;
  const bobbinRow = rows(`SELECT b.id||'|'||b.code||'|'||m.code||'|'||b.sequence_number||'|'||b.diameter_mm||'|'||b.weight_kg||'|'||b.number_of_cuts||'|'||b.start_time||'|'||b.end_time||'|'||coalesce(b.grammage_g_m2::text,'NULL')||'|'||ar.code||'|'||b.source_capture_id FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id JOIN vinto_master.article_version av ON av.id = b.article_version_id JOIN vinto_master.article ar ON ar.id = av.article_id WHERE b.source_capture_id = '${sentF3.capture_id}'`);
  const [bid, bcode, bmach, bseq, bdia, bwt, bcuts, bst, ben, bgram, bart] = (bobbinRow[0] ?? "").split("|");
  ctx.bobbin.MP1 = { id: bid, code: bcode };
  check("E03.5 PostgreSQL: bobina creada en MP1 con su correlativo, medidas EXACTAS de los datos enviados, artículo y gramaje heredado del maestro", bobbinRow.length === 1 && bmach === "MP1" && bseq === "1" && bcode === "1" && bdia === "1250.5" && bwt === "480.25" && bcuts === "3" && bst.startsWith("07:10") && ben.startsWith("08:05") && bart === articles.MP1 && bgram === "22", bobbinRow.join(" ; "), "sql");
  const rel = rows(`SELECT q.status||'|'||coalesce(q.decided_by::text,'-')||'|'||coalesce(q.decided_at::text,'-') FROM vinto_txn.quality_release q WHERE q.bobbin_id = '${bid}'`);
  check("E03.6 estado inicial de Calidad: pending, sin decisión, autor ni fecha de decisión", rel.length === 1 && rel[0] === "pending|-|-", rel.join(" ; "), "sql");
  const chain = rows(`SELECT wo.number||'|'||a.id||'|'||c.status||'|'||c.revision||'|'||c.created_by FROM vinto_txn.bobbin b JOIN vinto_txn.capture c ON c.id = b.source_capture_id JOIN vinto_txn.assignment a ON a.id = c.assignment_id JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version wov ON wov.id = l.work_order_version_id JOIN vinto_txn.work_order wo ON wo.id = wov.work_order_id WHERE b.id = '${bid}'`);
  check("E03.7 la bobina se relaciona con su captura (submitted, revisión 1, autor Operación), la asignación y la OT correctas", chain.length === 1 && chain[0] === `${ctx.ot.MP1.number}|${ctx.assignment.MP1}|submitted|1|${users.operacion.user_id}`, chain.join(" ; "), "sql");
  check("E03.8 auditoría: el alta de la captura y de la bobina quedó registrada con el actor de la sesión", Number(rows(`SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table IN ('capture','bobbin','quality_release') AND actor_id = '${users.operacion.user_id}'`)[0]) >= 3, "", "sql");
  const dumpF3 = await storageDump(b);
  check("E03.9 la captura F3 no está en localStorage (solo la clave técnica del dispositivo)", !dumpF3.includes(sentF3.capture_id) && !dumpF3.includes("bobina ficticia E2E-B0"), Object.keys(JSON.parse(dumpF3)).join(","));
  // --- P1-06
  check("E04.1 abrir P1-06 (Registro de control de fardos) desde la asignación de MP1", await clickCard(b, "Registro de control de fardos") && await b.waitFor("document.body.innerText.includes('Control de fardos')", "pantalla P1-06", 15000));
  await b.setField("Cantidad de fardos", "4"); await b.setField("Punto de merma", "recorte_maquina"); await b.setField("Tipo de producto", "hoja_doble"); await b.setField("Peso real total", "96,5"); await b.setField("Observaciones", "fardos ficticios E2E-B0");
  await b.shot("e04-p106-lleno.png");
  check("E04.2 enviar P1-06", await b.clickText("Enviar registro trazable"));
  await b.waitFor("!document.body.innerText.includes('Control de fardos') || document.body.innerText.includes('Punto de captura')", "regreso tras P1-06", 30000); await sleep(800);
  const p106Posts = (await cap(b)).filter((p) => p.url.endsWith("/api/captures")); const sent106 = JSON.parse(p106Posts[0].body);
  const p106Http = b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/captures"));
  ctx.capture.p106 = sent106.capture_id;
  check("E04.3 un único POST /api/captures = 201 (form_code VINTO-P1-06, assignment_id de MP1)", p106Posts.length === 1 && p106Http.length === 1 && p106Http[0].status === 201 && sent106.form_code === "VINTO-P1-06" && sent106.assignment_id === ctx.assignment.MP1, JSON.stringify({ posts: p106Posts.length, http: p106Http.map((r) => r.status), form: sent106.form_code }));
  const get106 = await operacionApi.call("GET", `/api/captures/${sent106.capture_id}`);
  check("E04.3b la consulta central GET /api/captures/{id} devuelve la captura de P1-06 persistida (200)", get106.status === 200 && get106.json?.id === sent106.capture_id, String(get106.status), "http");
  const row106 = rows(`SELECT c.status||'|'||c.revision||'|'||m.code||'|'||f.code||'|'||c.assignment_id||'|'||c.created_by FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE c.id = '${sent106.capture_id}'`);
  check("E04.4 PostgreSQL: captura P1-06 submitted, revisión 1, MP1, asignación correcta y autor Operación", row106[0] === `submitted|1|MP1|VINTO-P1-06|${ctx.assignment.MP1}|${users.operacion.user_id}`, row106.join(" ; "), "sql");
  const det106 = rows(`SELECT string_agg(f.key||'='||coalesce(d.value_text, d.value_integer::text, d.value_decimal::text), '|' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${sent106.capture_id}'`);
  check("E04.5 PostgreSQL: valores de P1-06 exactos", det106[0]?.includes("cantidad_fardos=4") && det106[0].includes("peso_kg=96.5") && det106[0].includes("punto_merma=recorte_maquina") && det106[0].includes("tipo_producto=hoja_doble"), det106.join(" ; "), "sql");
  await nav(b, "Seguimiento"); await b.waitFor(`document.body.innerText.includes('Control de fardos · registros centrales') && document.body.innerText.includes(${JSON.stringify(ctx.ot.MP1.number)})`, "lista central de P1-06", 20000);
  const centralRow = await b.js(`[...document.querySelectorAll('table tbody tr')].map((r) => r.innerText.replace(/\\s+/g, ' ')).find((r) => r.includes(${JSON.stringify(ctx.ot.MP1.number)}) && /96[.,]5/.test(r)) ?? ''`);
  check("E04.6 la lista central de Seguimiento (Bobinas) muestra la captura de P1-06 leída de PostgreSQL: OT, máquina MP1, fardos y peso", centralRow.includes("MP1") && / 4 /.test(centralRow) && /96[.,]5/.test(centralRow), centralRow.slice(0, 200));
  const dump106 = await storageDump(b);
  check("E04.7 P1-06 no se guarda como captura local del navegador", !dump106.includes(sent106.capture_id) && !dump106.includes("fardos ficticios E2E-B0") && !JSON.parse(dump106)["vinto-p1-records"]?.includes?.("VINTO-P1-06"), Object.keys(JSON.parse(dump106)).join(","));
  check("E04.8 sin errores de JavaScript ni 4xx/5xx inesperados", b.log.exceptions.length === 0 && b.log.requests.filter((r) => r.status >= 400 && !/api\/auth\/me/.test(r.url)).length === 0, JSON.stringify(b.log.requests.filter((r) => r.status >= 400).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`)));
  await logoutApp(b); keep(b);
});

// ============================================================ E11 · MP3: F3 con respuesta perdida y reintento idempotente desde la interfaz
await browser("op2", nextPort(), { fault: "lose-response" }, async (b) => {
  await loginApp(b, "operacion");
  await OP_NAV(b);
  await b.clickText("MP3"); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(ctx.ot.MP3.number)})`, "contexto de MP3", 20000); await sleep(800);
  check("E11.1 Operación ve el contexto real de MP3 y abre F3", (await b.text()).includes(ctx.ot.MP3.number) && await clickCard(b, "Registro de producción de bobinas") && await b.waitFor("document.body.innerText.includes('Datos de la bobina')", "pantalla F3 MP3", 15000));
  for (const [i, v] of ["09:00", "10:20", "980.0", "350", "2"].entries()) await setNth(b, "main input", i, v);
  await b.clickText("Registrar bobina");
  await b.waitFor("document.body.innerText.includes('Reintentar envío')", "aviso de envío incierto", 20000);
  const afterLoss = rows("SELECT count(*) FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id WHERE m.code = 'MP3' AND b.sequence_number IS NOT NULL")[0];
  check("E11.2 la respuesta se perdió pero el servidor ya procesó el POST (1 bobina en MP3) y la interfaz ofrece reintentar el MISMO envío", afterLoss === "1" && (await b.text()).includes("Reintentar envío") && (await b.js("[...document.querySelectorAll('main input')].every((i) => i.disabled)")), afterLoss);
  await b.shot("e11-f3-mp3-incierto.png");
  await b.clickText("Reintentar envío");
  await b.waitFor("!document.body.innerText.includes('Datos de la bobina')", "regreso tras el reintento", 30000); await sleep(800);
  const posts = (await cap(b)).filter((p) => p.url.endsWith("/api/bobbins"));
  ctx.body.f3_mp3 = JSON.parse(posts[0].body);
  const ids = new Set(posts.map((p) => JSON.parse(p.body).capture_id));
  const statuses = b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/bobbins")).map((r) => r.status);
  check("E11.3 el reintento reutiliza el MISMO capture_id (dos POST, un solo identificador) y el servidor responde 200 idempotente", posts.length === 2 && ids.size === 1 && statuses.includes(200), JSON.stringify({ posts: posts.length, ids: ids.size, statuses }));
  const mp3 = rows("SELECT b.id||'|'||b.code||'|'||b.sequence_number||'|'||b.source_capture_id FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id WHERE m.code = 'MP3' AND b.sequence_number IS NOT NULL");
  const [mid, mcode, , mcap] = (mp3[0] ?? "").split("|"); ctx.bobbin.MP3 = { id: mid, code: mcode }; ctx.capture.f3_mp3 = mcap;
  check("E11.4 PostgreSQL: sigue habiendo UNA bobina en MP3 (correlativo 1, independiente del de MP1), una captura y un quality_release", mp3.length === 1 && mcode === "1" && rows(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${mcap}'`)[0] === "1" && rows(`SELECT count(*) FROM vinto_txn.quality_release WHERE bobbin_id = '${mid}'`)[0] === "1", mp3.join(" ; "), "sql");
  await logoutApp(b); keep(b);
});

// ============================================================ E05–E08 · Calidad: bandeja, P1-19, P1-20 e historial
await browser("cal", nextPort(), {}, async (b) => {
  await loginApp(b, "calidad");
  await nav(b, "Calidad"); await b.waitFor("document.body.innerText.includes('Calidad ·')", "front Calidad", 15000);
  await goModule(b, "Ejecución", "Bobinas pendientes de Calidad"); await sleep(1200);
  const inboxPending = await b.js("document.querySelector('table') ? [...document.querySelectorAll('table tbody tr')].map((r) => r.innerText.replace(/\\s+/g, ' ')) : []");
  const mp1Row = inboxPending.find((r) => r.includes(ctx.ot.MP1.number)); const mp3Row = inboxPending.find((r) => r.includes(ctx.ot.MP3.number));
  check("E05.1 la bandeja de Calidad (central) muestra la bobina de MP1 con su OT, máquina y estado Pendiente", !!mp1Row && mp1Row.includes("MP1") && mp1Row.includes("Pendiente") && mp1Row.includes("1250.5") && mp1Row.includes(articles.MP1), (mp1Row ?? "").slice(0, 200));
  check("E05.2 la bandeja muestra además la bobina de MP3 (E11) y ninguna otra", !!mp3Row && mp3Row.includes("MP3") && inboxPending.length === 2, `filas ${inboxPending.length}`);
  await b.shot("e05-bandeja-calidad.png");
  const inboxApi = await calidadApi.call("GET", "/api/quality/bobbins");
  check("E05.3 la bandeja procede de GET /api/quality/bobbins (200) con la bobina de MP1 en estado pending", inboxApi.status === 200 && inboxApi.json.some((i) => i.bobbin.id === ctx.bobbin.MP1.id && i.quality.status === "pending" && i.bobbin.machine.code === "MP1" && i.production.work_order.number === ctx.ot.MP1.number) && b.log.requests.some((r) => r.method === "GET" && r.url.endsWith("/api/quality/bobbins") && r.status === 200), "", "http");
  // la asignación activa de MP1 se termina: la bandeja NO depende de ella
  const fin = await supervision.call("POST", `/api/assignments/${ctx.assignment.MP1}/finish`);
  await b.clickText("Actualizar"); await sleep(1500);
  const afterFinish = await b.js("[...document.querySelectorAll('table tbody tr')].map((r) => r.innerText.replace(/\\s+/g, ' '))");
  check("E05.4 la bandeja no depende de una asignación de operación activa: tras finalizar la asignación de MP1 la bobina sigue pendiente en la bandeja", fin.status === 200 && afterFinish.some((r) => r.includes(ctx.ot.MP1.number) && r.includes("Pendiente")), `finish ${fin.status}`);
  // ---------------- P1-19
  check("E06.1 abrir el control de humedad (P1-19) de la bobina de MP1", await clickAria(b, "Registrar humedad de la bobina", "(MP1") && await b.waitFor("document.body.innerText.includes('Pesos de la muestra')", "pantalla P1-19", 15000));
  for (const [i, v] of ["12,5", "11,0", "12,6", "11,1", "12,4", "10,9"].entries()) await setNth(b, "main input", i, v);
  await setNth(b, "main textarea", 0, "humedad ficticia E2E-B0");
  await b.shot("e06-p119-lleno.png");
  check("E06.2 enviar P1-19", await b.clickText("Registrar control de humedad"));
  await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad') && !document.body.innerText.includes('Pesos de la muestra')", "regreso a la bandeja tras P1-19", 30000);
  const hum = (await cap(b)).filter((p) => p.url.includes("/captures")).map((p) => ({ url: p.url, body: JSON.parse(p.body) }))[0];
  ctx.capture.p119 = hum.body.capture_id; ctx.body.p119 = hum.body;
  check("E06.3 un POST /api/quality/bobbins/{id}/captures = 201 para la bobina de MP1 con form_code VINTO-P1-19", hum.url.endsWith(`/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`) && hum.body.form_code === "VINTO-P1-19" && b.log.requests.some((r) => r.method === "POST" && r.url.includes("/captures") && r.status === 201), hum.url.replace(API, ""));
  const h = rows(`SELECT c.status||'|'||c.revision||'|'||c.bobbin_id||'|'||f.code||'|'||fv.area||'|'||c.created_by FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE c.id = '${hum.body.capture_id}'`);
  check("E06.4 PostgreSQL: captura P1-19 submitted, área quality, asociada a la bobina de MP1 y autor Calidad", h[0] === `submitted|1|${ctx.bobbin.MP1.id}|VINTO-P1-19|quality|${users.calidad.user_id}`, h.join(" ; "), "sql");
  const hd = rows(`SELECT string_agg(f.key||'='||d.value_decimal::text, '|' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${hum.body.capture_id}' AND d.value_decimal IS NOT NULL`);
  check("E06.5 PostgreSQL: los seis pesos exactos se guardaron (no se envía ni almacena la humedad calculada)", hd[0]?.split("|").length === 6 && hd[0].includes("=12.5") && hd[0].includes("=10.9") && !/humedad=|promedio/.test(hd[0]), hd.join(" ; "), "sql");
  // ---------------- P1-20
  check("E07.1 abrir las propiedades físicas (P1-20) de la bobina de MP1", await clickAria(b, "Registrar propiedades físicas de la bobina", "(MP1") && await b.waitFor("document.body.innerText.includes('Mediciones de Calidad')", "pantalla P1-20", 15000));
  const P20 = { crepado: "20", gramaje: "22,1", resistencia_longitudinal_centro: "5,1", resistencia_longitudinal_medio: "5,2", resistencia_longitudinal_extremo: "5,3", resistencia_transversal_centro: "3,1", resistencia_transversal_medio: "3,2", resistencia_transversal_extremo: "3,3", espesor_centro: "0,12", espesor_medio: "0,13", espesor_extremo: "0,14" };
  for (const [k, v] of Object.entries(P20)) await setById(b, `p20-${k}`, v);
  await setById(b, "p20-observaciones", "propiedades ficticias E2E-B0");
  const provisional = (await b.text()).includes("provisionales");
  await b.shot("e07-p120-lleno.png");
  check("E07.2 la pantalla declara las unidades y nombres como provisionales y enviar P1-20", provisional && await b.clickText("Registrar propiedades físicas"));
  await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad') && !document.body.innerText.includes('Mediciones de Calidad')", "regreso a la bandeja tras P1-20", 30000);
  const phy = (await cap(b)).filter((p) => p.url.includes("/captures")).map((p) => ({ url: p.url, body: JSON.parse(p.body) })).find((p) => p.body.form_code === "VINTO-P1-20");
  ctx.capture.p120 = phy.body.capture_id; ctx.body.p120 = phy.body;
  const p = rows(`SELECT c.status||'|'||c.bobbin_id||'|'||f.code||'|'||count(d.*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id JOIN vinto_txn.capture_detail d ON d.capture_id = c.id WHERE c.id = '${phy.body.capture_id}' GROUP BY c.status, c.bobbin_id, f.code`);
  check("E07.3 PostgreSQL: captura P1-20 submitted asociada a la bobina de MP1 con sus 12 detalles", p[0] === `submitted|${ctx.bobbin.MP1.id}|VINTO-P1-20|12`, p.join(" ; "), "sql");
  const pd = rows(`SELECT string_agg(f.key||'='||coalesce(d.value_decimal::text,d.value_text), '|' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${phy.body.capture_id}'`);
  check("E07.4 PostgreSQL: valores exactos de P1-20 (espesor 0.12, gramaje 22.1, resistencias) sin tolerancias ni conformidad almacenadas", pd[0]?.includes("espesor_centro=0.12") && pd[0].includes("gramaje=22.1") && pd[0].includes("resistencia_transversal_extremo=3.3") && !/conform|toleranc|limite|ok=/i.test(pd[0]), pd.join(" ; ").slice(0, 300), "sql");
  const unitRows = rows(`SELECT string_agg(f.key||':'||coalesce(u.code,'sin-unidad'), ',' ORDER BY f.display_order) FROM vinto_config.field_definition f LEFT JOIN vinto_master.unit u ON u.id = f.unit_id JOIN vinto_config.form_version fv ON fv.id = f.form_version_id JOIN vinto_config.form fo ON fo.id = fv.form_id WHERE fo.code = 'VINTO-P1-20'`).join("");
  check("E07.5 las unidades provisionales de P1-20 se conservan tal como están en la definición candidata (gramaje, crepado y resistencias sin unidad de catálogo)", /gramaje:sin-unidad/.test(unitRows) && /crepado:sin-unidad/.test(unitRows), unitRows.slice(0, 220), "sql");
  // ---------------- historial
  check("E08.1 abrir el historial (Ver controles) de la bobina de MP1", await clickAria(b, "Ver controles de la bobina", "(MP1") && await b.waitFor("document.body.innerText.includes('Controles registrados')", "historial", 20000));
  await sleep(1200);
  const hist1 = await b.text();
  check("E08.2 el historial muestra P1-19 y P1-20 de la misma bobina (2 controles) con sus ID de captura", hist1.includes("Controles registrados: 2") && hist1.includes("VINTO-P1-19") && hist1.includes("VINTO-P1-20") && hist1.includes(ctx.capture.p119) && hist1.includes(ctx.capture.p120) && hist1.includes(`Bobina ${ctx.bobbin.MP1.code}`), hist1.replace(/\s+/g, " ").slice(0, 160));
  await b.shot("e08-historial.png");
  const histApi = await calidadApi.call("GET", `/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`);
  check("E08.3 los datos del historial coinciden con la API y con PostgreSQL (2 capturas de la bobina: P1-19 y P1-20)", histApi.status === 200 && histApi.json.length === 2 && rows(`SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = '${ctx.bobbin.MP1.id}'`)[0] === "2" && histApi.json.map((c) => c.form.code).sort().join() === "VINTO-P1-19,VINTO-P1-20", histApi.json.map((c) => c.form.code).join(), "http");
  // reabrir: el historial de la otra bobina (MP3) no reutiliza información obsoleta de MP1
  await b.clickText("Volver al inbox"); await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad')", "inbox", 15000);
  check("E08.4 reabrir el historial de la bobina de MP3 (sin controles) no muestra los controles de MP1", await clickAria(b, "Ver controles de la bobina", "(MP3") && await b.waitFor("document.body.innerText.includes('Controles registrados')", "historial MP3", 20000));
  await sleep(1200);
  const hist3 = await b.text();
  check("E08.5 el historial de MP3 está vacío y no contiene ID ni valores de MP1", !hist3.includes(ctx.capture.p119) && !hist3.includes(ctx.capture.p120) && /Controles registrados: 0|No hay controles|sin controles/i.test(hist3), hist3.replace(/\s+/g, " ").slice(0, 200));
  await b.clickText("Volver al inbox"); await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad')", "inbox", 15000);
  check("E08.6 reabrir el historial de MP1 recarga desde el servidor (nuevos GET) y mantiene los 2 controles", await clickAria(b, "Ver controles de la bobina", "(MP1") && await b.waitFor("document.body.innerText.includes('Controles registrados: 2')", "historial MP1 recargado", 20000) && b.log.requests.filter((r) => r.method === "GET" && r.url.endsWith(`/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`)).length >= 2);
  await b.clickText("Volver al inbox"); await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad')", "inbox", 15000);
  // no hay acciones de liberación/rechazo
  const labels = await b.js("[...document.querySelectorAll('button')].map((x) => x.innerText.trim()).filter(Boolean)");
  check("E09.1 la interfaz de Calidad no ofrece acciones de Liberar ni Rechazar (solo registrar humedad, propiedades y ver controles)", !labels.some((l) => /liberar|rechazar|aprobar/i.test(l)) && labels.includes("Registrar humedad") && !(await b.text()).includes("Liberada"), labels.join(" | ").slice(0, 220));
  const stillPending = rows("SELECT string_agg(status, ',') FROM vinto_txn.quality_release")[0];
  check("E09.2 PostgreSQL: tras todas las capturas de Calidad, ninguna bobina fue liberada ni rechazada (capturar no es liberar)", stillPending === "pending,pending" && rows("SELECT count(*) FROM vinto_txn.quality_release WHERE decided_by IS NOT NULL OR decided_at IS NOT NULL OR decision_reason IS NOT NULL")[0] === "0", stillPending, "sql");
  check("E08.7 sin errores de JavaScript ni 4xx/5xx inesperados en Calidad", b.log.exceptions.length === 0 && b.log.requests.filter((r) => r.status >= 400 && !/api\/auth\/me/.test(r.url)).length === 0, JSON.stringify(b.log.requests.filter((r) => r.status >= 400).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`)));
  // ---------------- pérdida de sesión: el servidor revoca la sesión y la siguiente consulta devuelve al ingreso
  await b.js(`fetch(${JSON.stringify(API + "/api/auth/logout")}, { method: "POST", credentials: "include" }).then((r) => r.status)`);
  await b.clickText("Actualizar");
  check("E09.3 pérdida de sesión: con la sesión revocada la aplicación vuelve al ingreso y no deja datos de Calidad en pantalla", await b.waitFor("!!document.getElementById('vinto-username')", "ingreso tras pérdida de sesión", 20000) && !(await b.text()).includes(ctx.ot.MP1.number));
  keep(b);
});

// ============================================================ E09 · seguridad y permisos (HTTP complementario)
const anon = client(), op = operacionApi, sup = supervision, jef = jefatura, cal = calidadApi;
const dataApi = client(), calSin = client(), opSin = client();
await dataApi.login("data_baltrek"); await calSin.login("calidad_sin_sector"); await opSin.login("operacion_sin_sector");
const status = async (c, method, path, payload) => (await c.call(method, path, payload)).status;
const fakeUuid = () => crypto.randomUUID();
const noAuth = [await status(anon, "GET", "/api/work-orders"), await status(anon, "GET", "/api/quality/bobbins"), await status(anon, "POST", "/api/bobbins", {}), await status(anon, "GET", `/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`), await status(anon, "POST", "/api/assignments/activate", {})];
check("E09.4 solicitudes sin sesión: 401 en OT, bandeja de Calidad, captura de bobina, historial y asignaciones", noAuth.every((s) => s === 401), noAuth.join(","), "http");
const denied = {
  "Operación no lee la bandeja de Calidad": await status(op, "GET", "/api/quality/bobbins"),
  "Operación no captura Calidad": await status(op, "POST", `/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`, { capture_id: fakeUuid(), form_code: "VINTO-P1-19", device_key: fakeUuid(), values: {} }),
  "Operación no crea OT": await status(op, "POST", "/api/work-orders", { machine_code: "MP1", lines: [] }),
  "Calidad no captura producción": await status(cal, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: {} }),
  "Calidad no crea OT": await status(cal, "POST", "/api/work-orders", { machine_code: "MP1", lines: [] }),
  "Calidad no activa asignaciones": await status(cal, "POST", "/api/assignments/activate", { work_order_id: ctx.ot.MP1.id, baseline_line_id: ctx.line.MP1.id }),
  "Jefatura no captura producción": await status(jef, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: {} }),
  "Jefatura no activa asignaciones": await status(jef, "POST", "/api/assignments/activate", { work_order_id: ctx.ot.MP3.id, baseline_line_id: ctx.line.MP3.id }),
  "Supervisión no captura producción": await status(sup, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: {} }),
  "Supervisión no crea OT": await status(sup, "POST", "/api/work-orders", { machine_code: "MP1", lines: [] }),
  "DATA_BALTREK no lee la bandeja de Calidad": await status(dataApi, "GET", "/api/quality/bobbins"),
  "DATA_BALTREK no captura producción": await status(dataApi, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: {} }),
};
check("E09.5 acceso por rol: cada acción fuera del perfil responde 403 (Operación, Calidad, Jefatura, Supervisión y DATA_BALTREK)", Object.values(denied).every((s) => s === 403), JSON.stringify(denied), "http");
const calSinInbox = await calSin.call("GET", "/api/quality/bobbins");
const opSinMachines = await opSin.call("GET", "/api/production/machines");
const opSinPost = await opSin.call("POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: { hora_inicio: "07:00", hora_fin: "08:00", diametro: "1000", peso_kg: "400", numero_de_cortes: "1" } });
check("E09.6 sin concesión de sector no se ve ni se opera nada: bandeja vacía o denegada, sin máquinas y la captura de bobina se rechaza", ((calSinInbox.status === 403) || (calSinInbox.status === 200 && calSinInbox.json.length === 0)) && (opSinMachines.status === 403 || (opSinMachines.status === 200 && opSinMachines.json.sectors.length === 0)) && opSinPost.status >= 400 && opSinPost.status < 500, JSON.stringify({ inbox: calSinInbox.status, machines: opSinMachines.status, post: opSinPost.status }), "http");
const machinesJef = await jef.call("GET", "/api/production/machines");
check("E09.7 la disponibilidad real expone únicamente BOBINAS (MP1 y MP3) y solo VINTO-P1-06 como formulario central de producción", machinesJef.status === 200 && JSON.stringify(machinesJef.json.sectors.map((s) => s.code)) === JSON.stringify(["BOBINAS"]) && machinesJef.json.sectors[0].machines.map((m) => m.code).sort().join() === "MP1,MP3" && machinesJef.json.sectors[0].machines.every((m) => JSON.stringify(m.forms.map((f) => f.code)) === JSON.stringify(["VINTO-P1-06"])), JSON.stringify(machinesJef.json.sectors.map((s) => [s.code, s.machines.map((m) => m.code + ":" + m.forms.map((f) => f.code))])), "http");
const reb = [await status(jef, "POST", "/api/work-orders", { machine_code: "COPASA", lines: [{ pv_reference: "PV-X", article_code: articles.MP1, quantity: "1", due_date: "2026-12-01" }] }), await status(jef, "POST", "/api/work-orders", { machine_code: "GAMBINI", lines: [{ pv_reference: "PV-X", article_code: articles.MP1, quantity: "1", due_date: "2026-12-01" }] }), await status(op, "POST", "/api/captures", { capture_id: fakeUuid(), form_code: "VINTO-P1-10", assignment_id: fakeUuid(), device_key: fakeUuid(), values: {} }), await status(op, "POST", "/api/captures", { capture_id: fakeUuid(), form_code: "VINTO-P1-03", assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: {} })];
check("E09.8 Rebobinado y Conversión no son operativos: crear OT de COPASA o GAMBINI y capturar P1-10 por la ruta genérica se rechaza (4xx) y F3 no se acepta por /api/captures", reb.every((s) => s >= 400 && s < 500) && rows("SELECT count(*) FROM vinto_txn.work_order wo JOIN vinto_master.machine m ON m.id = wo.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id WHERE s.code <> 'BOBINAS'")[0] === "0", reb.join(","), "http");
const openapi = await anon.call("GET", "/openapi.json");
if (openapi.status === 200) {
  const paths = Object.keys(openapi.json.paths);
  check("E09.9 el contrato OpenAPI no contiene rutas de liberación, rechazo ni decisión de Calidad", !paths.some((p) => /releas|reject|decision|liberar|rechaz|approve/i.test(p)), paths.filter((p) => /quality/.test(p)).join(" "), "http");
} else check("E09.9 el contrato OpenAPI no está publicado (404); se sondean directamente las rutas de decisión", true, `openapi ${openapi.status}`, "http");
const probes = [];
for (const verb of ["release", "reject", "decision", "decide"]) for (const m of ["POST", "PUT", "PATCH"]) probes.push(await status(cal, m, `/api/quality/bobbins/${ctx.bobbin.MP1.id}/${verb}`, { reason: "x" }));
check("E09.10 sondeo directo: ninguna ruta de liberación/rechazo existe (todas 404/405) y quality_release permanece pending", probes.every((s) => s === 404 || s === 405) && rows("SELECT string_agg(DISTINCT status, ',') FROM vinto_txn.quality_release")[0] === "pending", probes.join(","), "http");

// ============================================================ Robustez HTTP: idempotencia, rechazos, concurrencia
const f3Body = ctx.body.f3_mp3;
const before = rows("SELECT count(*) FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL")[0];
const replay = await op.call("POST", "/api/bobbins", f3Body);
check("R1 reintento idéntico de F3 (mismo capture_id y contenido) = 200 y la MISMA bobina, sin duplicados", replay.status === 200 && replay.json?.bobbin?.id === ctx.bobbin.MP3.id && rows("SELECT count(*) FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL")[0] === before, JSON.stringify({ s: replay.status, same: replay.json?.bobbin?.id === ctx.bobbin.MP3.id }), "http");
const conflict = await op.call("POST", "/api/bobbins", { ...f3Body, values: { ...f3Body.values, peso_kg: "351" } });
check("R2 mismo capture_id con contenido distinto = 409 CAPTURE_IDEMPOTENCY_CONFLICT y la bobina original no cambia", conflict.status === 409 && conflict.json?.code === "CAPTURE_IDEMPOTENCY_CONFLICT" && rows(`SELECT weight_kg FROM vinto_txn.bobbin WHERE id = '${ctx.bobbin.MP3.id}'`)[0] === "350", JSON.stringify(conflict.json).slice(0, 120), "http");
const bad = [
  await status(op, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: { ...f3Body.values, peso_kg: "abc" } }),
  await status(op, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: { hora_inicio: "07:00" } }),
  await status(op, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: { ...f3Body.values, peso_kg: "-5" } }),
  await status(op, "POST", "/api/bobbins", { capture_id: "no-es-uuid", assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: f3Body.values }),
  await status(op, "POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP3, device_key: fakeUuid(), values: { ...f3Body.values, extra_no_contratado: "1" } }),
];
check("R3 intentos inválidos de F3 (peso no numérico, campos faltantes, peso negativo, capture_id mal formado, campo no contratado) se rechazan con 4xx sin crear bobinas", bad.every((s) => s >= 400 && s < 500) && rows("SELECT count(*) FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL")[0] === before, bad.join(","), "http");
const onFinished = await op.call("POST", "/api/bobbins", { capture_id: fakeUuid(), assignment_id: ctx.assignment.MP1, device_key: fakeUuid(), values: f3Body.values });
check("R4 capturar contra la asignación FINALIZADA de MP1 se rechaza (4xx) y no crea bobina", onFinished.status >= 400 && onFinished.status < 500 && rows("SELECT count(*) FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL")[0] === before, `${onFinished.status} ${onFinished.json?.code ?? ""}`, "http");
// concurrencia: 5 POST simultáneos idénticos = una sola bobina; 3 POST simultáneos distintos = tres bobinas con correlativos distintos
const same = { ...f3Body, capture_id: fakeUuid(), device_key: f3Body.device_key };
const sameResults = await Promise.all(Array.from({ length: 5 }, () => op.call("POST", "/api/bobbins", same)));
const created = sameResults.filter((r) => r.status === 201).length, ok200 = sameResults.filter((r) => r.status === 200).length;
check("R5 cinco POST concurrentes idénticos: exactamente una creación (201) y el resto idempotente (200), una sola bobina para ese capture_id", created === 1 && ok200 === 4 && rows(`SELECT count(*) FROM vinto_txn.bobbin WHERE source_capture_id = '${same.capture_id}'`)[0] === "1" && new Set(sameResults.map((r) => r.json?.bobbin?.id)).size === 1, `201×${created} 200×${ok200}`, "http");
const diff = await Promise.all(Array.from({ length: 3 }, (_, i) => op.call("POST", "/api/bobbins", { ...f3Body, capture_id: fakeUuid(), values: { ...f3Body.values, peso_kg: String(360 + i) } })));
const seqs = rows("SELECT string_agg(sequence_number::text, ',' ORDER BY sequence_number) FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id WHERE m.code = 'MP3' AND b.sequence_number IS NOT NULL")[0];
check("R6 tres POST concurrentes con capture_id distintos: tres bobinas y correlativos de MP3 consecutivos y sin repetir (1..5)", diff.every((r) => r.status === 201) && seqs === "1,2,3,4,5", `${diff.map((r) => r.status).join(",")} seq=${seqs}`, "http");
const q19 = await cal.call("POST", `/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`, ctx.body.p119);
check("R7 reintento idéntico de P1-19 = 200 already_submitted sin duplicar", q19.status === 200 && q19.json?.already_submitted === true && rows(`SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = '${ctx.bobbin.MP1.id}'`)[0] === "2", `${q19.status}`, "http");
const q19c = await cal.call("POST", `/api/quality/bobbins/${ctx.bobbin.MP1.id}/captures`, { ...ctx.body.p119, values: { ...ctx.body.p119.values, peso_seco_medio: "9,9" } });
const q19bad = [await status(cal, "POST", `/api/quality/bobbins/${ctx.bobbin.MP3.id}/captures`, { ...ctx.body.p119, capture_id: fakeUuid(), values: { ...ctx.body.p119.values, peso_humedo_comando: "x" } }), await status(cal, "POST", `/api/quality/bobbins/${fakeUuid()}/captures`, { ...ctx.body.p119, capture_id: fakeUuid() }), await status(cal, "POST", `/api/quality/bobbins/${ctx.bobbin.MP3.id}/captures`, { ...ctx.body.p119, capture_id: fakeUuid(), form_code: "VINTO-P1-99" })];
check("R8 P1-19: mismo capture_id con otros valores = 409; valor inválido, bobina inexistente y formulario desconocido se rechazan (4xx) sin crear capturas", q19c.status === 409 && q19bad.every((s) => s >= 400 && s < 500) && rows(`SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id IN ('${ctx.bobbin.MP1.id}','${ctx.bobbin.MP3.id}')`)[0] === "2", `${q19c.status} ${q19bad.join(",")}`, "http");

// ============================================================ Roles en la interfaz, Rebobinado/Conversión y E10 · Seguimiento saneado
await browser("ops-ui", nextPort(), {}, async (b) => {
  await loginApp(b, "operacion");
  await nav(b, "Calidad"); await b.waitFor("document.body.innerText.includes('Calidad ·')", "front Calidad", 15000); await goModule(b, "Ejecución", "Calidad ·");
  check("E09.11 Operación en el front Calidad: sin acceso al inbox y sin acciones de Calidad", (await b.text()).includes("Tu perfil no tiene acceso al inbox de Calidad") && !(await b.text()).includes("Registrar humedad"));
  for (const [front, marker] of [["Rebobinado", "Rebobinado no está habilitado"], ["Conversión", "no está habilitado"]]) {
    await nav(b, front); await sleep(1500);
    const t = await b.text();
    check(`E09.12 ${front} sigue sin disponibilidad operativa en la navegación: aviso de no habilitado, sin formularios ni creación de OT`, t.includes(marker) && !(await b.js("document.querySelectorAll('[data-form]').length")) && !/Crear OT inicial/.test(t), t.replace(/\s+/g, " ").slice(0, 140));
    for (const m of ["Programación", "Ejecución", "Seguimiento"]) { await nav(b, m); await sleep(500); }
    check(`E09.13 ${front}: ningún POST de escritura desde la navegación bloqueada`, (await cap(b)).length === 0);
  }
  // ---- E10 · Seguimiento de Bobinas saneado
  await toBobinas(b); await goModule(b, "Seguimiento", "Registros centrales");
  await sleep(1500);
  const t = await b.text();
  const centralValue = await b.js("[...document.querySelectorAll('p.text-3xl')].map((e) => e.innerText.trim())");
  const countApi = await op.call("GET", "/api/captures/count?front=Bobinas");
  await b.shot("e10-seguimiento-bobinas.png");
  check("E10.1 Seguimiento de Bobinas no muestra la bobina ficticia BM-2609-001 ni liberaciones/rechazos ficticios", !t.includes("BM-2609-001") && !/\bLiberada\b|\bRechazada\b/.test(t) && !/Liberar|Rechazar/.test(t), "");
  check("E10.2 «Bobinas liberadas» figura como funcionalidad pendiente (no como un cero) y la genealogía como pendiente", t.includes("Funcionalidad pendiente") && /Bobinas liberadas[\s\S]{0,40}Funcionalidad pendiente/.test(t) && !/Bobinas liberadas\s*0/.test(t));
  check("E10.3 los conteos central y local están diferenciados: «Registros centrales» coincide con la API y el local se rotula como de este navegador y sin sumarse", t.includes("Registros centrales") && centralValue.includes(String(countApi.json?.count)) && /Registros locales \(este navegador\): \d+\. No representan la producción central de Bobinas ni se suman al conteo central/.test(t), `central=${centralValue.join("/")} api=${countApi.json?.count}`);
  check("E10.4 las OT y asignaciones centrales siguen visibles (OT de MP1 y MP3 con su línea y su asignación)", t.includes(ctx.ot.MP1.number) && t.includes(ctx.ot.MP3.number) && t.includes(`PV-E2EB0-MP1`) && t.includes("Activa"));
  check("E10.5 los reportes no implementados aparecen como pendientes y no como operativos", t.includes("Todavía no existen reportes centrales") && (await b.js("[...document.querySelectorAll('span')].filter((e) => e.innerText.trim() === 'Pendiente').length")) >= 4 && !/Se generan desde registros fuente/.test(t));
  check("E10.6 no hay descarga de historial de tubetes y las descargas se rotulan como locales de este navegador", !/Historial de tubetes/.test(t) && t.includes("Descargas de registros locales (este navegador)"));
  await b.js("window.__block.push('/api/captures/count')");
  await b.clickText("Actualizar");
  await b.waitFor("document.body.innerText.includes('Consulta central no disponible')", "estado no disponible", 20000);
  const unknown = await b.js("[...document.querySelectorAll('p.text-3xl')].map((e) => e.innerText.trim())");
  const tUnknown = await b.text();
  await b.shot("e10-conteo-no-disponible.png");
  check("E10.7 con el conteo central no disponible, el valor es «—» (nunca cero ni el conteo local) y el local queda como dato secundario", unknown.includes("—") && !unknown.includes("0") && /Registros locales \(este navegador\): \d+\./.test(tUnknown) && tUnknown.includes("No representan la producción central"), JSON.stringify(unknown));
  const lsDump = await storageDump(b);
  check("E10.8 no se mezcla información local con la producción central: ninguna OT, bobina ni captura central está en localStorage", !lsDump.includes(ctx.ot.MP1.number) && !lsDump.includes(ctx.capture.f3_mp1) && !lsDump.includes(ctx.capture.p106), Object.keys(JSON.parse(lsDump)).join(","));
  check("E10.9 sin errores de JavaScript inesperados en Seguimiento", b.log.exceptions.length === 0, JSON.stringify(b.log.exceptions).slice(0, 160));
  await logoutApp(b); keep(b);
});
await browser("cal-ui", nextPort(), {}, async (b) => {
  await loginApp(b, "calidad");
  await toBobinas(b); await goModule(b, "Ejecución", "Punto de captura");
  check("E09.14 Calidad en el front Bobinas: puede consultar pero no capturar producción (aviso) y la tarjeta de F3 no abre la captura", (await b.text()).includes("puede consultar este frente, pero no capturar") && await clickCard(b, "Registro de producción de bobinas") && (await sleep(800), !(await b.text()).includes("Datos de la bobina")));
  await nav(b, "Calidad"); await goModule(b, "Seguimiento", "Calidad ·"); await sleep(800);
  const t = await b.text();
  check("E10.10 Seguimiento de Calidad indica que el resumen central no está disponible y no simula liberaciones ni usa OT locales", t.includes("Resumen central todavía no disponible") && !t.includes("BM-2609-001") && !/\bLiberada\b|\bRechazada\b|Liberar|Rechazar/.test(t) && !t.includes("OT visibles"));
  await b.shot("e10-seguimiento-calidad.png");
  await logoutApp(b); keep(b);
});
await browser("jef-ui", nextPort(), {}, async (b) => {
  await loginApp(b, "jefatura");
  await toBobinas(b); await goModule(b, "Ejecución", "Punto de captura");
  check("E09.15 Jefatura en Ejecución de Bobinas: consulta sin capturar (aviso) y la tarjeta de P1-06 no abre la captura", (await b.text()).includes("puede consultar este frente, pero no capturar") && await clickCard(b, "Registro de control de fardos") && (await sleep(800), !(await b.text()).includes("Control de fardos") || (await b.text()).includes("no tiene permiso")));
  await logoutApp(b); keep(b);
});
await browser("sinsector", nextPort(), {}, async (b) => {
  await loginApp(b, "operacion_sin_sector");
  await sleep(1500);
  const t = await b.text();
  await goModule(b, "Ejecución", "Punto de captura"); await sleep(1000);
  const opened = (await clickCard(b, "Registro de producción de bobinas")) && (await sleep(800), (await b.text()).includes("Datos de la bobina"));
  const tEx = await b.text();
  check("E09.16 un usuario sin concesión de sector no ve ninguna OT ni bobina de Bobinas y no puede abrir una captura (no hay contexto de asignación)", !t.includes(ctx.ot.MP1.number) && !t.includes(ctx.ot.MP3.number) && !tEx.includes(ctx.ot.MP1.number) && !opened && !(await cap(b)).length, tEx.replace(/\s+/g, " ").slice(-260));
  await logoutApp(b).catch(() => {}); keep(b);
});

// ============================================================ Integridad final, auditoría, aislamiento y configuración real
const counts = rows("SELECT m.code||'='||count(*) FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id WHERE b.sequence_number IS NOT NULL GROUP BY m.code ORDER BY m.code").join(",");
check("Z1 integridad: cada bobina tiene exactamente una captura F3 origen y una fila quality_release; sin correlativos repetidos; ninguna decisión registrada", rows("SELECT count(*) FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL")[0] === rows("SELECT count(DISTINCT source_capture_id) FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL")[0] && rows("SELECT count(*) FROM vinto_txn.bobbin b WHERE b.sequence_number IS NOT NULL AND (SELECT count(*) FROM vinto_txn.quality_release q WHERE q.bobbin_id = b.id) <> 1")[0] === "0" && rows("SELECT count(*) FROM (SELECT machine_id, management_start_year, sequence_number FROM vinto_txn.bobbin WHERE sequence_number IS NOT NULL GROUP BY 1,2,3 HAVING count(*) > 1) d")[0] === "0" && rows("SELECT count(*) FROM vinto_txn.quality_release WHERE status <> 'pending'")[0] === "0", counts, "sql");
const audited = rows("SELECT string_agg(DISTINCT entity_table, ',' ORDER BY entity_table) FROM vinto_audit.audit_event")[0];
check("Z2 auditoría: quedaron eventos de OT, asignación, captura, bobina y quality_release con actor y request_id", ["work_order", "assignment", "capture", "bobbin", "quality_release"].every((t) => audited.split(",").includes(t)) && rows("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table IN ('capture','bobbin','work_order','assignment') AND (actor_id IS NULL OR request_id IS NULL)")[0] === "0", audited, "sql");
const external = allRequests.filter((r) => { try { const u = new URL(r.url); return !["data:", "blob:", "about:"].includes(u.protocol) && !(u.hostname === "127.0.0.1" && ["8190", "8796"].includes(u.port)); } catch { return false; } });
check("Z3 aislamiento: todas las solicitudes del navegador fueron solo a 127.0.0.1:8190 (API de E2E-B0) y 127.0.0.1:8796 (frontend); ninguna a DEV, PROD ni a hosts externos", allRequests.length > 100 && external.length === 0, `${allRequests.length} solicitudes; fuera de alcance: ${external.length}`);
const sessions = rows("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0];
for (const c of [jefatura, supervision, calidadApi, operacionApi, dataApi, calSin, opSin]) await c.call("POST", "/api/auth/logout");
check("Z4 sin sesiones activas de prueba tras los logouts", rows("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0] === "0", `activas antes del cierre final: ${sessions}`, "sql");
const sectorsSrc = readFileSync(new URL("../../backend/app/sectors.py", import.meta.url), "utf8"), captureSrc = readFileSync(new URL("../../backend/app/capture_service.py", import.meta.url), "utf8");
check("Z5 configuración real intacta: DEFAULT_OPERATIONAL_SECTORS = (SECTOR_BOBINAS,) y CENTRAL_FORM_CODES = frozenset({FORM_CODE}) con FORM_CODE = VINTO-P1-06", /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m.test(sectorsSrc) && /^FORM_CODE = "VINTO-P1-06"/m.test(captureSrc) && /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m.test(captureSrc), "", "static");
const evidence = { generated: "E2E-B0", database, counts, results };
writeFileSync(join(outDir, "resultados-e2e-b0.json"), JSON.stringify(evidence, null, 2));
const fails = results.filter((r) => !r.ok);
const by = (k) => results.filter((r) => r.kind === k).length;
console.log(`\nTOTAL ${results.length} (navegador ${by("browser")}, http ${by("http")}, sql ${by("sql")}, static ${by("static")}) · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
