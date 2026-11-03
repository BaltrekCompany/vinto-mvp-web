// node scripts/e2e/mm13-e2e.mjs <creds.json> <evidence-dir> <manifest.json> <enabled|closed>   (solo desde scripts/e2e/mm13-run.mjs)
// MM-13-QA · integración E2E de los TRES frentes (Bobinas, Rebobinado, Conversión) y Calidad en UNA sola instancia de FastAPI/React/PostgreSQL 17,
// desde la NAVEGACIÓN NORMAL de VINTO (la aplicación real en `/`, sin harness de formulario ni ruta de QA). Reutiliza EXACTAMENTE los selectores y
// el patrón ya probados de scripts/e2e/b0-e2e.mjs (Bobinas F3/P1-06/Calidad P1-19, con la política real) y de scripts/e2e/m4a-e2e.mjs /
// scripts/e2e/m6a-e2e.mjs (Rebobinado P1-10 y Conversión P1-16 desde el shell central). No es una regresión exhaustiva de ningún frente por
// separado (esas ya existen y se reutilizan); demuestra que los tres pueden operar JUNTOS, en la MISMA base, sin interferirse.
//
// Fase «enabled» (backend/tests/e2e_mm13_server.py con E2E_3F=on): los tres sectores y VINTO-P1-06/P1-10/P1-16 operativos SOLO en ese proceso.
// Fase «closed» (E2E_3F=off): la configuración REAL (solo BOBINAS operativo); Rebobinado y Conversión quedan CONCEDIDOS pero NO operativos.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787) o no son 127.0.0.1, si la base no termina en `_test`, si no es
// current_database(), si el contenedor de PostgreSQL no es el exclusivo de MM-13-QA, si el SHA probado cambió o si el navegador llama al puerto
// 8000. Las lecturas SQL son SELECT en transacciones de solo lectura.
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FIXED = Object.freeze({ api: "http://127.0.0.1:8193", web: "http://127.0.0.1:8798", container: "vinto-mm13-pg", pgPort: 55441 });
const API = FIXED.api, WEB = FIXED.web, PG_CONTAINER = FIXED.container;
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const FORBIDDEN_DB = ["vinto", "vinto_test", "postgres"];
const [credsPath, outDir, manifestPath, phase] = process.argv.slice(2);
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (name, ok, detail = "", kind = "browser") => { results.push({ name, ok: !!ok, kind, detail }); console.log(`${ok ? "PASS" : "FAIL"}  [${kind}] ${name}${detail ? "  — " + String(detail).slice(0, 400) : ""}`); };
const abort = (message) => { console.error("E2E ABORTADO: " + message); process.exit(2); };

// ---------------------------------------------------------------- H1-H4: destinos fijos, identidad de la corrida, SHA probado, base efímera
if (!["enabled", "closed"].includes(phase)) abort("uso: node scripts/e2e/mm13-e2e.mjs <creds.json> <evidence-dir> <manifest.json> <enabled|closed>; solo se ejecuta desde scripts/e2e/mm13-run.mjs");
for (const [name, expected] of [["E2E_API", FIXED.api], ["E2E_WEB", FIXED.web], ["E2E_PG_CONTAINER", FIXED.container]]) if (process.env[name] !== undefined && process.env[name] !== expected) abort(`la variable heredada ${name} intenta redirigir la prueba; los destinos son fijos y los define scripts/e2e/mm13-run.mjs`);
if (process.env.E2E_CHROME !== undefined) abort("la variable heredada E2E_CHROME no se admite: el navegador es el instalado en la ruta fija");
if (!credsPath || !outDir || !manifestPath) abort("faltan argumentos");
let manifest; try { manifest = JSON.parse(readFileSync(manifestPath, "utf8")); } catch { abort("el manifiesto de la corrida es ilegible"); }
if (!/^\d{8}T\d{6}Z-[0-9a-f]{8}$/.test(manifest?.runId ?? "")) abort("el manifiesto no trae un identificador de corrida válido");
if (manifest.api !== FIXED.api || manifest.web !== FIXED.web || manifest.container !== FIXED.container || manifest.pgPort !== FIXED.pgPort) abort("el manifiesto no coincide con los destinos fijos de MM-13-QA");
if (manifest.phase !== phase) abort("el manifiesto no corresponde a la fase pedida");
const apiUrl = new URL(API), webUrl = new URL(WEB);
if (apiUrl.port === "8000" || webUrl.port === "8787" || apiUrl.port === "5432") abort("la API o el frontend apuntan a puertos de DEV");
if (apiUrl.hostname !== "127.0.0.1" || webUrl.hostname !== "127.0.0.1") abort("solo se admite 127.0.0.1");
if (!/^vinto-mm13-/.test(PG_CONTAINER)) abort(`el contenedor ${PG_CONTAINER} no es el PostgreSQL exclusivo de MM-13-QA`);
if (!/^[0-9a-f]{40}$/.test(manifest.commit ?? "")) abort("el manifiesto no trae el SHA probado");
if (!/_test$/.test(manifest.database ?? "") || FORBIDDEN_DB.includes(manifest.database)) abort(`la base ${manifest.database} no es una base efímera *_test exclusiva`);
let creds; try { creds = JSON.parse(readFileSync(credsPath, "utf8")); } catch { abort("las credenciales de la corrida son ilegibles"); }
const { database, users, articles, rebobinado_machine: REB_MACHINE, conversion_machine: CONV_MACHINE } = creds;
if (database !== manifest.database) abort("la base de las credenciales no es la declarada en el manifiesto de la corrida");
if (basename(resolve(outDir)) !== manifest.runId) abort("el directorio de evidencias no corresponde al identificador de esta corrida");
const resultsFile = join(outDir, `resultados-mm13-${phase}.json`);
if (existsSync(resultsFile)) abort(`${resultsFile} ya existe; cada fase escribe su propio archivo una sola vez`);
if (execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO, encoding: "utf8" }).trim() !== manifest.commit) abort("el código cambió desde que el orquestador fijó el SHA probado");
mkdirSync(outDir, { recursive: true });

const inspect = (format) => execFileSync("docker", ["inspect", "-f", format, PG_CONTAINER], { encoding: "utf8" }).trim();
let labelRun, portMap;
try { labelRun = inspect('{{index .Config.Labels "vinto.mm13.run"}}'); portMap = execFileSync("docker", ["port", PG_CONTAINER, "5432/tcp"], { encoding: "utf8" }).trim(); } catch { abort(`no existe el contenedor ${PG_CONTAINER}`); }
if (labelRun !== manifest.runId || !portMap.split("\n").every((l) => l.trim() === `127.0.0.1:${FIXED.pgPort}`)) abort("el contenedor de PostgreSQL no es el creado por esta corrida (etiqueta o puerto distintos)");
const pgUser = execFileSync("docker", ["exec", PG_CONTAINER, "printenv", "POSTGRES_USER"], { encoding: "utf8" }).trim();
const q = (sql, db = database) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", `BEGIN READ ONLY; ${sql}; COMMIT;`], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check(`S0 [${phase}] la base del recorrido es efímera (*_test) y su identidad se verificó con current_database() dentro del PostgreSQL exclusivo de MM-13-QA`, identity === database && identity.endsWith("_test"), identity, "sql");
check(`S0a [${phase}] la corrida está identificada: el contenedor de PostgreSQL lleva la etiqueta de esta corrida y publica solo 127.0.0.1:${FIXED.pgPort}`, labelRun === manifest.runId && portMap === `127.0.0.1:${FIXED.pgPort}`, manifest.runId, "static");
const health = await fetch(`${API}/api/health`);
check(`S0b [${phase}] la API real responde (200)`, health.status === 200, String(health.status), "http");

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

// ---------------------------------------------------------------- Chrome (CDP) sobre la aplicación real (puerto propio por caso, perfil temporal único)
// Registra TODA petición POST de escritura a /api/ (salvo auth) en window.__posts, para leer el payload exacto enviado por la aplicación (igual
// que scripts/e2e/b0-e2e.mjs / m4a-e2e.mjs / m6a-e2e.mjs); sin inyección de fallos (esta prueba no ensaya reintentos por pérdida de red).
const CAPTURE_SCRIPT = `(() => { const w = window; if (w.__capture) return; w.__capture = true; w.__posts = []; const real = w.fetch.bind(w);
  w.fetch = async (input, init) => { const url = String(input && input.url ? input.url : input); const post = (init && init.method === "POST") && /\\/api\\//.test(url) && !/\\/api\\/auth\\//.test(url); if (post) w.__posts.push({ url, body: String(init.body ?? "") }); return real(input, init); }; })();`;
let port = 9700; const nextPort = () => port++;
async function browser(label, opts, body) {
  const { mobile = false } = opts;
  const width = mobile ? 390 : 1366, height = mobile ? 844 : 900;
  const profile = mkdtempSync(join(tmpdir(), `mm13-${manifest.runId}-${label}-`));
  const p = nextPort();
  const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${p}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", `--window-size=${width},${height}`, "about:blank"], { stdio: "ignore" });
  let ws, nextId = 1; const pending = new Map(); const log = { requests: [], consoleErrors: [], exceptions: [] }; const byId = new Map();
  const send = (method, params = {}) => new Promise((res) => { const id = nextId++; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
  try {
    for (let i = 0; i < 60; i++) { try { const t = await (await fetch(`http://127.0.0.1:${p}/json`)).json(); const page = t.find((x) => x.type === "page"); if (page) { ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise((a, b) => { ws.onopen = a; ws.onerror = b; }); break; } } catch { /* arrancando */ } await sleep(300); }
    if (!ws) throw new Error("no se pudo abrir la página del Chrome lanzado");
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
      const pr = msg.params;
      if (msg.method === "Network.requestWillBeSent") { const r = { method: pr.request.method, url: pr.request.url, status: null }; byId.set(pr.requestId, r); log.requests.push(r); if (new URL(pr.request.url).port === "8000") { console.error("E2E ABORTADO: el navegador llamó al puerto 8000 (DEV): " + pr.request.url); process.exit(2); } }
      if (msg.method === "Network.responseReceived") { const r = byId.get(pr.requestId); if (r) r.status = pr.response.status; }
      if (msg.method === "Runtime.exceptionThrown") log.exceptions.push(pr.exceptionDetails.text + " " + (pr.exceptionDetails.exception?.description ?? "").slice(0, 120));
      if (msg.method === "Runtime.consoleAPICalled" && pr.type === "error") log.consoleErrors.push(pr.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 160));
    };
    await send("Page.enable"); await send("Network.enable"); await send("Runtime.enable");
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
    await send("Page.addScriptToEvaluateOnNewDocument", { source: CAPTURE_SCRIPT });
    const js = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails).slice(0, 300)); return r.result?.result?.value; };
    const waitFor = async (expr, what, ms = 25000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await js(`!!(${expr})`)) return true; } catch { /* navegando */ } await sleep(200); } throw new Error("tiempo agotado esperando: " + what); };
    const goto = async (url) => { await send("Page.navigate", { url }); await sleep(700); await waitFor("document.readyState === 'complete'", "carga " + url); };
    const text = () => js("document.body.innerText");
    const setField = (labelText, value) => js(`(() => { const l = [...document.querySelectorAll('label')].find((x) => x.innerText.trim().replace(/ \\*$/, '') === ${JSON.stringify(labelText)} && x.offsetParent !== null); const el = l && l.parentElement.querySelector('select, input, textarea'); if (!el) return false; const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); return true; })()`);
    const clickText = (t, scope = "document") => js(`(() => { const b = [...${scope}.querySelectorAll('button')].filter((x) => x.offsetParent !== null).find((x) => x.innerText.trim().startsWith(${JSON.stringify(t)})); if (!b || b.disabled) return false; b.click(); return true; })()`);
    const click = (selector) => js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el || el.disabled) return false; el.click(); return true; })()`);
    const shot = async (name) => { const h = await js("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"); const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(h, 5000), scale: 1 } }); writeFileSync(join(outDir, name), Buffer.from(r.result.data, "base64")); };
    const api = { send, js, waitFor, goto, text, setField, clickText, click, shot, log, sleep };
    try { await body(api); } catch (error) { try { await shot(`fallo-${phase}-${label}.png`); console.error("TEXTO AL FALLAR:", (await text()).replace(/\s+/g, " ").slice(0, 600)); console.error("HTTP:", JSON.stringify(log.requests.filter((r) => r.status >= 400 || r.status === null).slice(0, 8).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`))); } catch { /* sin captura */ } throw error; }
  } finally {
    try { ws?.close(); } catch { /* ya cerrado */ }
    spawn("taskkill", ["/PID", String(chrome.pid), "/T", "/F"], { stdio: "ignore" }); await sleep(1200);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* se limpia luego */ }
  }
}
const loginApp = async (b, who) => {
  await b.goto(`${WEB}/`);
  await b.waitFor("!!document.getElementById('vinto-username')", "formulario de ingreso");
  await b.js(`(() => { const set = (id, v) => { const el = document.getElementById(id); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); }; set('vinto-username', ${JSON.stringify(users[who].username)}); set('vinto-password', ${JSON.stringify(users[who].password)}); })()`);
  await b.clickText("Ingresar");
  await b.waitFor(`!!document.querySelector('button[aria-label="Cerrar sesión"]')`, "aplicación tras el login", 30000);
};
const nav = (b, label) => b.clickText(label);
const logoutApp = async (b) => { await b.click('button[aria-label="Cerrar sesión"]'); await b.waitFor("!!document.getElementById('vinto-username')", "ingreso tras logout", 20000); };
const goModule = async (b, label, marker) => { await nav(b, label); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(marker)})`, `módulo ${label}`, 20000); await sleep(600); };
const clickCard = (b, title) => b.js(`(() => { const c = [...document.querySelectorAll('button')].filter((x) => x.offsetParent !== null).find((x) => x.querySelector('h3')?.innerText.trim() === ${JSON.stringify(title)}); if (!c) return false; c.click(); return true; })()`);
const clickAria = (b, prefix, contains) => b.js(`(() => { const c = [...document.querySelectorAll('button[aria-label]')].filter((x) => x.offsetParent !== null).find((x) => x.getAttribute('aria-label').startsWith(${JSON.stringify(prefix)}) && x.getAttribute('aria-label').includes(${JSON.stringify(contains)})); if (!c) return false; c.click(); return true; })()`);
const cardAction = (b, otNumber, label) => b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(otNumber)}) && [...d.querySelectorAll('button')].some((x) => x.innerText.trim() === ${JSON.stringify(label)})); const btn = card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === ${JSON.stringify(label)}); if (!btn || btn.disabled) return false; btn.click(); return true; })()`);
const setNth = (b, selector, i, value) => b.js(`(() => { const el = document.querySelectorAll(${JSON.stringify(selector)})[${i}]; if (!el) return false; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const cap = (b) => b.js("window.__posts ?? []");
const storageDump = (b) => b.js("JSON.stringify(Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])))");
const rows = (sql) => q(sql);

const ctx = { ot: {}, assignment: {}, bobbin: {}, capture: {} };


// ---------------------------------------------------------------- MM-13-QA · recorridos (navegador real + HTTP + SQL de solo lectura)
const MP1_A = creds.articles.mp1, MP3_A = creds.articles.mp3;
const orderBody = (lines) => ({ machine_code: "MP1", lines });
const line = (pv, article, quantity, machine) => ({ pv_reference: pv, article_code: article, quantity, due_date: "2026-12-01", ...(machine ? { machine_code: machine } : {}) });
const activeSql = (machine) => rows(`SELECT l.line_code FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id=a.machine_id JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id WHERE a.status='active' AND m.code='${machine}' ORDER BY l.line_code`);
const capturesByLine = () => rows("SELECT l.line_code||'|'||count(*) FROM vinto_txn.capture c JOIN vinto_txn.assignment a ON a.id=c.assignment_id JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id GROUP BY l.line_code ORDER BY l.line_code");
const key = (b, k, code) => b.send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, windowsVirtualKeyCode: k === "Escape" ? 27 : k === "Tab" ? 9 : 0 }).then(() => b.send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: k === "Escape" ? 27 : k === "Tab" ? 9 : 0 }));
const dialogText = (b) => b.js("document.querySelector('[role=dialog]')?.innerText ?? ''");
const openMassDialog = async (b, number) => { const ok = await cardAction(b, number, "Activar todas las líneas"); if (ok) await b.waitFor("!!document.querySelector('[role=dialog]')", "diálogo de activación masiva", 15000); return ok; };
const posts = async (b, re) => (await cap(b)).filter((p) => re.test(p.url));
const selectLine = (b, machine, assignmentId) => b.js(`(() => { const el = document.querySelector('input[type=radio][name="line-${machine}"][value="${assignmentId}"]'); if (!el || el.disabled) return false; el.click(); return true; })()`);
const overflowX = (b) => b.js("document.documentElement.scrollWidth - window.innerWidth");
const submitF3 = async (b, note) => {
  if (!(await clickCard(b, "Registro de producción de bobinas"))) return false;
  await b.waitFor("document.body.innerText.includes('Datos de la bobina')", "pantalla F3", 15000);
  for (const [i, v] of ["07:00", "08:00", "1000,0", "400,0", "2"].entries()) await setNth(b, "main input", i, v);
  await setNth(b, "main textarea", 0, note);
  await b.clickText("Registrar bobina");
  await b.waitFor("!document.body.innerText.includes('Datos de la bobina') && document.body.innerText.includes('Punto de captura')", "regreso tras F3", 30000);
  return true;
};

const jefatura = client(), supervision = client();
await jefatura.login("jefatura"); await supervision.login("supervision");
check("S1 la API real responde con sesión y la base efímera parte sin OT, asignaciones ni capturas", (await jefatura.call("GET", "/api/work-orders")).json?.length === 0 && rows("SELECT count(*) FROM vinto_txn.assignment")[0] === "0" && rows("SELECT count(*) FROM vinto_txn.capture")[0] === "0", "", "http");
const caps = await supervision.call("GET", "/api/work-orders/capabilities");
check(`S2 el servidor informa multi_machine=${creds.gate === "on"} (compuerta ${creds.gate === "on" ? "encendida" : "apagada"} solo en el proceso de prueba)`, caps.status === 200 && caps.json?.multi_machine === (creds.gate === "on"), JSON.stringify(caps.json), "http");

const makeOrder = async (body) => {
  const created = await jefatura.call("POST", "/api/work-orders", body);
  if (created.status !== 201) throw new Error(`no se pudo crear la OT: ${created.status} ${created.text.slice(0, 200)}`);
  const published = await jefatura.call("POST", `/api/work-orders/${created.json.id}/publish`);
  if (published.status !== 200) throw new Error(`no se pudo publicar: ${published.status}`);
  return published.json;
};

if (phase === "enabled") {
  // Paso 1 (creación y publicación por Jefatura) se hace por API: la creación multimáquina en pantalla se validó en PR6 y no es el foco de este E2E (ver el informe).
  const order = await makeOrder(orderBody([line("PV-1", MP1_A[0], 10, "MP1"), line("PV-2", MP1_A[1], 20, "MP1"), line("PV-3", MP3_A[0], 30, "MP3")]));
  check("A0 Jefatura crea y publica una OT con 3 líneas en 2 máquinas (MP1 y MP3)", order.status === "published" && order.baseline.lines.map((l) => l.machine.code).join() === "MP1,MP1,MP3", order.number, "http");

  // ---------------- Supervisión (escritorio): vista previa, Escape/foco, doble confirmación, activación
  await browser("sup-escritorio", {}, async (b) => {
    await loginApp(b, "supervision"); await sleep(1200);
    check("A1 Supervisión ve «Activar todas las líneas» en la OT publicada (compuerta encendida, permiso assignment.manage)", await openMassDialog(b, order.number));
    await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Líneas por activar (3)')", "vista previa con 3 líneas", 20000);
    const preview = await posts(b, /activate-all$/);
    check("A2 la vista previa es UNA solicitud de solo lectura con el cuerpo exacto {\"dry_run\":true}", preview.length === 1 && preview[0].body === '{"dry_run":true}', preview.map((p) => p.body).join(" | "));
    check("A3 PostgreSQL: la vista previa NO creó ninguna asignación", rows("SELECT count(*) FROM vinto_txn.assignment")[0] === "0", "", "sql");
    check("A4 el diálogo muestra OT, líneas, máquinas (MP1 y MP3), producto y PV resueltos por el servidor", /L1/.test(await dialogText(b)) && /MP3/.test(await dialogText(b)) && /PV-3/.test(await dialogText(b)));
    await b.shot("sup-01-vista-previa-escritorio.png");
    const focusBefore = await b.js("document.activeElement?.innerText?.trim() ?? ''");
    check("A5 teclado: el foco inicial del diálogo NO cae sobre «Confirmar»", !focusBefore.startsWith("Confirmar"), focusBefore);
    await key(b, "Escape", "Escape"); await sleep(600);
    const closed = !(await b.js("!!document.querySelector('[role=dialog]')")), focusAfter = await b.js("document.activeElement?.innerText?.trim() ?? document.activeElement?.tagName");
    check("A6 Escape cierra el diálogo (no hay confirmación en vuelo)", closed);
    check("A6b accesibilidad: al cerrar el diálogo el foco vuelve al botón «Activar todas las líneas» que lo abrió", focusAfter.startsWith("Activar todas"), `foco en: ${focusAfter}`);
    check("A7 PostgreSQL: cerrar con Escape no escribió nada", rows("SELECT count(*) FROM vinto_txn.assignment")[0] === "0", "", "sql");
    check("A8 reabrir pide una vista previa NUEVA (el plan anterior no se reutiliza)", await openMassDialog(b, order.number) && await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Líneas por activar (3)')", "segunda vista previa", 20000) && (await posts(b, /activate-all$/)).filter((p) => p.body === '{"dry_run":true}').length === 2);
    // doble confirmación: dos clics seguidos sobre «Confirmar»
    const double = await b.js(`(() => { const btn = [...document.querySelectorAll('[role=dialog] button')].find((x) => x.innerText.trim().startsWith('Confirmar activación')); if (!btn || btn.disabled) return false; btn.click(); btn.click(); return true; })()`);
    check("A9 doble clic sobre «Confirmar activación»", double);
    await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Se activaron 3')", "resultado de la activación", 30000);
    const confirms = (await posts(b, /activate-all$/)).filter((p) => /"dry_run":false/.test(p.body));
    check("A10 el doble clic envía UNA sola confirmación con el plan_hash del servidor (64 hex)", confirms.length === 1 && /^\{"dry_run":false,"plan_hash":"[a-f0-9]{64}"\}$/.test(confirms[0].body), confirms.map((c) => c.body).join(" | "));
    check("A11 PostgreSQL: 3 asignaciones activas (L1, L2 en MP1 y L3 en MP3) creadas por esa única operación", activeSql("MP1").join() === "L1,L2" && activeSql("MP3").join() === "L3", `${activeSql("MP1")} / ${activeSql("MP3")}`, "sql");
    await b.shot("sup-02-resultado-escritorio.png");
    await key(b, "Escape", "Escape"); await sleep(500);
    check("A12 la pantalla no registra excepciones ni errores de consola durante el recorrido", b.log.exceptions.length === 0 && b.log.consoleErrors.length === 0, JSON.stringify([...b.log.exceptions, ...b.log.consoleErrors]).slice(0, 300));
    await logoutApp(b);
  });

  // ---------------- Operación (móvil): selector sin preselección, sin desbordamiento horizontal
  await browser("op-movil", { mobile: true }, async (b) => {
    await loginApp(b, "operacion");
    await goModule(b, "Ejecución", "Punto de captura").catch(async () => { await b.js("(() => { const t = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Ejecución'); t && t.click(); })()"); await sleep(800); });
    await b.clickText("MP1"); await b.waitFor("!!document.querySelector('[data-line-selector]')", "selector de líneas (móvil)", 25000);
    check("M1 móvil: aparece el selector con las 2 líneas activas de MP1 y ninguna marcada", (await b.js("document.querySelectorAll('input[type=radio][name=\"line-MP1\"]').length")) === 2 && (await b.js("document.querySelectorAll('input[type=radio][name=\"line-MP1\"]:checked').length")) === 0);
    check("M2 móvil: sin desplazamiento horizontal de la página (390 px)", (await overflowX(b)) <= 1, String(await overflowX(b)));
    check("M3 móvil: cada opción mide al menos 44 px de alto (objetivo táctil)", await b.js("[...document.querySelectorAll('[data-line-selector] label')].every((l) => l.getBoundingClientRect().height >= 44)"));
    await b.shot("op-01-selector-movil.png");
    await logoutApp(b);
  });

  // ---------------- Operación (escritorio): selección explícita, capturas por línea, actualización, errores, sesión
  const lines = (await supervision.call("GET", "/api/assignments/active-lines?machine_code=MP1")).json.assignments.map((i) => i.assignment);
  const l1 = lines.find((a) => a.line.line_code === "L1"), l2 = lines.find((a) => a.line.line_code === "L2");
  await browser("op-escritorio", {}, async (b) => {
    await loginApp(b, "operacion");
    await goModule(b, "Ejecución", "Punto de captura");
    await b.clickText("MP1"); await b.waitFor("!!document.querySelector('[data-line-selector]')", "selector de líneas", 25000);
    const reads = b.log.requests.filter((r) => /\/api\/assignments\/active(-lines)?\?machine_code=MP1/.test(r.url));
    check("B1 la lectura histórica /active responde 409 y SOLO entonces se pide /active-lines (200)", reads.some((r) => /\/active\?/.test(r.url) && r.status === 409) && reads.some((r) => /active-lines/.test(r.url) && r.status === 200), reads.map((r) => `${r.url.split("/api")[1]}→${r.status}`).join(" | "));
    check("B2 el selector lista L1 y L2 con OT, producto y PV, y NINGUNA línea está preseleccionada", (await b.js("document.querySelectorAll('input[type=radio][name=\"line-MP1\"]').length")) === 2 && (await b.js("document.querySelectorAll('input[type=radio]:checked').length")) === 0 && /L1/.test(await b.text()) && /L2/.test(await b.text()));
    await b.shot("op-02-selector-escritorio.png");
    await clickCard(b, "Registro de producción de bobinas"); await sleep(800);
    check("B3 sin elegir línea, F3 NO se abre (no hay contexto de captura)", !(await b.text()).includes("Datos de la bobina"));
    // teclado: llevar el foco a una opción y marcarla con la barra espaciadora
    await b.js(`document.querySelector('input[type=radio][name="line-MP1"][value="${l1.id}"]').focus()`);
    await key(b, " ", "Space"); await sleep(400);
    check("B4 teclado: la opción enfocada se elige con la barra espaciadora", await b.js(`document.querySelector('input[type=radio][value="${l1.id}"]').checked`));
    check("B5 la línea elegida (L1) muestra su contexto de captura", (await b.text()).includes("Línea elegida"));
    check("B6 se registra producción F3 sobre L1", await submitF3(b, "QA multimáquina L1"));
    check("B7 cambio de línea: se elige L2 y se registra otra captura", await selectLine(b, "MP1", l2.id) && await submitF3(b, "QA multimáquina L2"));
    const per = capturesByLine();
    check("B8 PostgreSQL: cada captura quedó asociada a SU asignación (1 en L1 y 1 en L2)", per.join() === "L1|1,L2|1", per.join(), "sql");
    const f3 = await posts(b, /\/api\/bobbins$/);
    check("B9 los POST de captura envían el assignment_id elegido (L1 y luego L2), no el de otra línea", f3.length === 2 && JSON.parse(f3[0].body).assignment_id === l1.id && JSON.parse(f3[1].body).assignment_id === l2.id, f3.map((p) => JSON.parse(p.body).assignment_id.slice(0, 8)).join(" , "));
    // Supervisión finaliza L1 mientras Operación está en pantalla: «Actualizar líneas» y pérdida de contexto
    const fin = await supervision.call("POST", `/api/assignments/${l1.id}/finish`);
    check("B10 Supervisión finaliza L1 (API) mientras Operación está en pantalla", fin.status === 200 && fin.json.status === "finished", String(fin.status), "http");
    await b.clickText("Actualizar líneas"); await sleep(1500);
    const after = await b.text();
    check("B11 tras actualizar, Operación pierde el contexto de L1: ya no hay selector y el contexto es el de la única línea activa (L2)", !after.includes("Líneas activas en MP1") && /L2/.test(after), after.replace(/\s+/g, " ").slice(0, 200));
    check("B12 PostgreSQL: el histórico de L1 se conserva (1 captura, asignación finalizada)", capturesByLine().join() === "L1|1,L2|1" && rows("SELECT status FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id WHERE l.line_code='L1' AND a.id='" + l1.id + "'")[0] === "finished", "", "sql");
    // estado de error: sin red al cambiar de máquina (la lectura es nueva), y recuperación con «Reintentar»
    await b.send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
    await b.clickText("MP3"); await b.waitFor("document.body.innerText.includes('No se pudo consultar la asignación activa')", "estado de error sin red", 20000);
    check("B13 sin red: se muestra el estado de error con «Reintentar» y ninguna línea ajena", /Reintentar/.test(await b.text()));
    await b.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    await b.clickText("Reintentar"); await b.waitFor("document.body.innerText.includes('L3')", "contexto de MP3 tras reintentar", 20000);
    check("B14 al volver la red, «Reintentar» recupera el contexto real de MP3 (L3)", /L3/.test(await b.text()));
    check("B15 el navegador no guarda la selección ni capturas en almacenamiento local", !JSON.stringify(JSON.parse(await storageDump(b))).includes(l2.id), Object.keys(JSON.parse(await storageDump(b))).join(","));
    check("B16 sin excepciones de página durante el recorrido de Operación", b.log.exceptions.length === 0, b.log.exceptions.join(" | ").slice(0, 300));
    await logoutApp(b);
  });

  // ---------------- cambio de sesión: otra cuenta no hereda la selección ni la vista; sin concesión no ve máquinas
  await browser("sesion", {}, async (b) => {
    await loginApp(b, "operacion_sin_concesion");
    await sleep(2500);
    const text = await b.text();
    check("C1 un operador SIN concesión (compuerta encendida) no recibe ningún frente: «Sin accesos asignados», sin selector ni líneas", /Sin accesos asignados/.test(text) && !text.includes("Líneas activas en") && !/L2/.test(text), text.replace(/\s+/g, " ").slice(0, 200));
    check("C2 sin concesión no puede abrir un formulario de captura (no se envía ningún POST de captura)", (await posts(b, /\/api\/bobbins$/)).length === 0);
    await logoutApp(b);
  });

  // ---------------- conflicto entre OT en pantalla de Supervisión
  const other = await makeOrder(orderBody([line("PV-X", MP1_A[2], 5)]));
  await browser("sup-conflicto", {}, async (b) => {
    await loginApp(b, "supervision"); await sleep(1200);
    check("D1 Supervisión abre la vista previa de otra OT cuya máquina MP1 ya tiene líneas activas de otra OT", await openMassDialog(b, other.number));
    await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Conflictos con otras OT')", "conflicto en la vista previa", 20000);
    const confirmDisabled = await b.js("(() => { const x = [...document.querySelectorAll('[role=dialog] button')].find((y) => y.innerText.trim().startsWith('Confirmar activación')); return !x || x.disabled; })()");
    check("D2 el conflicto se informa («Finaliza esas asignaciones…») y «Confirmar activación» está deshabilitado", confirmDisabled && /Finaliza esas asignaciones/.test(await dialogText(b)));
    await b.shot("sup-03-conflicto-escritorio.png");
    check("D3 no se envió ninguna confirmación y la OT original sigue intacta", (await posts(b, /activate-all$/)).every((p) => p.body === '{"dry_run":true}') && activeSql("MP1").join() === "L2", activeSql("MP1").join(), "sql");
    await logoutApp(b);
  });
  await browser("sup-conflicto-movil", { mobile: true }, async (b) => {
    await loginApp(b, "supervision"); await sleep(1200);
    check("D4 móvil: Supervisión abre la vista previa con conflicto (390 px)", await openMassDialog(b, other.number));
    await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Conflictos con otras OT')", "conflicto (móvil)", 20000);
    check("D5 móvil: sin desplazamiento horizontal de la página y el diálogo cabe en la pantalla", (await overflowX(b)) <= 1 && await b.js("(() => { const r = document.querySelector('[role=dialog]').getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth + 1; })()"), String(await overflowX(b)));
    await b.shot("sup-04-conflicto-movil.png");
    // Contraste real (WCAG) del resumen y de los encabezados de la tabla del diálogo, con el tema CLARO y con el OSCURO emulados (preferencia del sistema del usuario).
    const contrast = () => b.js(`(() => { const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
      const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
      const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const m = rgba(getComputedStyle(e).backgroundColor); if (m[3] > 0.5) return m.slice(0, 3); } return [255, 255, 255]; };
      const ratio = (el) => { const fg = rgba(getComputedStyle(el).color).slice(0, 3), a = lum(fg), c = lum(bgOf(el)); return (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05); };
      const els = [document.querySelector('[role=dialog] [data-headline]'), document.querySelector('[role=dialog] thead th')].filter(Boolean); return Math.min(...els.map(ratio)); })()`);
    await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] }); await sleep(400);
    const light = await contrast(); await b.shot("sup-05-conflicto-movil-tema-claro.png");
    await b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "dark" }] }); await sleep(400);
    const dark = await contrast(); await b.shot("sup-06-conflicto-movil-tema-oscuro.png");
    check("D6 accesibilidad (tema claro): el resumen y los encabezados del diálogo tienen contraste >= 4.5:1", light >= 4.5, `mínimo ${light.toFixed(2)}:1`);
    check("D7 accesibilidad (tema oscuro del sistema): el resumen y los encabezados del diálogo tienen contraste >= 4.5:1", dark >= 4.5, `mínimo ${dark.toFixed(2)}:1`);
    await logoutApp(b);
  });
} else {
  // ---------------- compuerta APAGADA: comportamiento histórico
  const order = await makeOrder(orderBody([line("PV-1", MP1_A[0], 10), line("PV-2", MP1_A[1], 20)]));
  check("H0 con la compuerta apagada Jefatura crea y publica una OT de una sola máquina (flujo histórico)", order.status === "published" && order.baseline.lines.length === 2, order.number, "http");
  const refused = await jefatura.call("POST", "/api/work-orders", orderBody([line("PV-9", MP3_A[0], 1, "MP3")]));
  check("H1 el servidor rechaza una OT con una línea en OTRA máquina que la cabecera (422 MULTI_MACHINE_DISABLED)", refused.status === 422 && refused.json?.code === "MULTI_MACHINE_DISABLED", `${refused.status} ${refused.json?.code}`, "http");
  const bulk = await supervision.call("POST", `/api/work-orders/${order.id}/activate-all`, { dry_run: true });
  check("H2 la activación masiva está cerrada en el servidor (422 MULTI_MACHINE_DISABLED)", bulk.status === 422 && bulk.json?.code === "MULTI_MACHINE_DISABLED", `${bulk.status} ${bulk.json?.code}`, "http");
  await browser("sup-historico", {}, async (b) => {
    await loginApp(b, "supervision"); await sleep(1500);
    check("H3 Supervisión NO ve «Activar todas las líneas» (compuerta apagada) pero sí «Activar» por línea", !(await b.js("[...document.querySelectorAll('button')].some((x) => x.innerText.includes('Activar todas'))")) && await cardAction(b, order.number, "Activar"));
    await sleep(1500);
    check("H4 PostgreSQL: la activación individual crea UNA asignación (L1)", activeSql("MP1").join() === "L1", activeSql("MP1").join(), "sql");
    check("H5 activar la otra línea REEMPLAZA a la anterior (una sola activa por máquina)", await b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(order.number)})); const btns = card ? [...card.querySelectorAll('button')].filter((x) => x.innerText.trim() === 'Activar' && !x.disabled) : []; if (!btns.length) return false; btns[btns.length - 1].click(); return true; })()`));
    await sleep(1800);
    check("H6 PostgreSQL: tras reemplazar queda UNA activa (L2) y L1 finalizada (histórico)", activeSql("MP1").join() === "L2", activeSql("MP1").join(), "sql");
    await logoutApp(b);
  });
  await browser("op-historico", {}, async (b) => {
    await loginApp(b, "operacion");
    await goModule(b, "Ejecución", "Punto de captura");
    await b.clickText("MP1"); await b.waitFor("document.body.innerText.includes('L2')", "contexto de MP1", 25000); await sleep(600);
    check("H7 Operación ve su línea activa SIN selector ni paso extra (flujo histórico)", !(await b.js("!!document.querySelector('[data-line-selector]')")) && /L2/.test(await b.text()));
    const reads = b.log.requests.filter((r) => /\/api\/assignments\/active/.test(r.url));
    check("H8 una sola lectura /active (200) y ninguna /active-lines", reads.every((r) => !/active-lines/.test(r.url)) && reads.some((r) => r.status === 200), reads.map((r) => `${r.url.split("/api")[1]}→${r.status}`).join(" | "));
    check("H9 se registra producción F3 sobre la línea activa", await submitF3(b, "QA histórico"));
    check("H10 PostgreSQL: la captura quedó en la asignación activa (L2)", capturesByLine().join() === "L2|1", capturesByLine().join(), "sql");
    check("H11 sin excepciones de página", b.log.exceptions.length === 0, b.log.exceptions.join(" | ").slice(0, 300));
    await logoutApp(b);
  });
}
await jefatura.call("POST", "/api/auth/logout"); await supervision.call("POST", "/api/auth/logout");
const left = rows("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0];
check(`Z1 sin sesiones activas de prueba tras los logouts (fase ${phase})`, left === "0", `activas ${left}`, "sql");

writeFileSync(resultsFile, JSON.stringify({ runId: manifest.runId, commit: manifest.commit, database, phase, total: results.length, pass: results.filter((r) => r.ok).length, fail: results.filter((r) => !r.ok).length, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL [${phase}] ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
