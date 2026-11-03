// node scripts/e2e/pra-e2e.mjs <creds.json> <evidence-dir> <manifest.json> <enabled|closed>   (solo desde scripts/e2e/pra-run.mjs)
// PR-A-QA · integración E2E de los TRES frentes (Bobinas, Rebobinado, Conversión) y Calidad en UNA sola instancia de FastAPI/React/PostgreSQL 17,
// desde la NAVEGACIÓN NORMAL de VINTO (la aplicación real en `/`, sin harness de formulario ni ruta de QA). Reutiliza EXACTAMENTE los selectores y
// el patrón ya probados de scripts/e2e/b0-e2e.mjs (Bobinas F3/P1-06/Calidad P1-19, con la política real) y de scripts/e2e/m4a-e2e.mjs /
// scripts/e2e/m6a-e2e.mjs (Rebobinado P1-10 y Conversión P1-16 desde el shell central). No es una regresión exhaustiva de ningún frente por
// separado (esas ya existen y se reutilizan); demuestra que los tres pueden operar JUNTOS, en la MISMA base, sin interferirse.
//
// Fase «enabled» (backend/tests/e2e_pra_server.py con E2E_3F=on): los tres sectores y VINTO-P1-06/P1-10/P1-16 operativos SOLO en ese proceso.
// Fase «closed» (E2E_3F=off): la configuración REAL (solo BOBINAS operativo); Rebobinado y Conversión quedan CONCEDIDOS pero NO operativos.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787) o no son 127.0.0.1, si la base no termina en `_test`, si no es
// current_database(), si el contenedor de PostgreSQL no es el exclusivo de PR-A-QA, si el SHA probado cambió o si el navegador llama al puerto
// 8000. Las lecturas SQL son SELECT en transacciones de solo lectura.
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FIXED = Object.freeze({ api: "http://127.0.0.1:8194", web: "http://127.0.0.1:8797", container: "vinto-pra-pg", pgPort: 55442 });
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
if (!["enabled", "closed"].includes(phase)) abort("uso: node scripts/e2e/pra-e2e.mjs <creds.json> <evidence-dir> <manifest.json> <enabled|closed>; solo se ejecuta desde scripts/e2e/pra-run.mjs");
for (const [name, expected] of [["E2E_API", FIXED.api], ["E2E_WEB", FIXED.web], ["E2E_PG_CONTAINER", FIXED.container]]) if (process.env[name] !== undefined && process.env[name] !== expected) abort(`la variable heredada ${name} intenta redirigir la prueba; los destinos son fijos y los define scripts/e2e/pra-run.mjs`);
if (process.env.E2E_CHROME !== undefined) abort("la variable heredada E2E_CHROME no se admite: el navegador es el instalado en la ruta fija");
if (!credsPath || !outDir || !manifestPath) abort("faltan argumentos");
let manifest; try { manifest = JSON.parse(readFileSync(manifestPath, "utf8")); } catch { abort("el manifiesto de la corrida es ilegible"); }
if (!/^\d{8}T\d{6}Z-[0-9a-f]{8}$/.test(manifest?.runId ?? "")) abort("el manifiesto no trae un identificador de corrida válido");
if (manifest.api !== FIXED.api || manifest.web !== FIXED.web || manifest.container !== FIXED.container || manifest.pgPort !== FIXED.pgPort) abort("el manifiesto no coincide con los destinos fijos de PR-A-QA");
if (manifest.phase !== phase) abort("el manifiesto no corresponde a la fase pedida");
const apiUrl = new URL(API), webUrl = new URL(WEB);
if (apiUrl.port === "8000" || webUrl.port === "8787" || apiUrl.port === "5432") abort("la API o el frontend apuntan a puertos de DEV");
if (apiUrl.hostname !== "127.0.0.1" || webUrl.hostname !== "127.0.0.1") abort("solo se admite 127.0.0.1");
if (!/^vinto-pra-/.test(PG_CONTAINER)) abort(`el contenedor ${PG_CONTAINER} no es el PostgreSQL exclusivo de PR-A-QA`);
if (!/^[0-9a-f]{40}$/.test(manifest.commit ?? "")) abort("el manifiesto no trae el SHA probado");
if (!/_test$/.test(manifest.database ?? "") || FORBIDDEN_DB.includes(manifest.database)) abort(`la base ${manifest.database} no es una base efímera *_test exclusiva`);
let creds; try { creds = JSON.parse(readFileSync(credsPath, "utf8")); } catch { abort("las credenciales de la corrida son ilegibles"); }
const { database, users, articles, rebobinado_machine: REB_MACHINE, conversion_machine: CONV_MACHINE } = creds;
if (database !== manifest.database) abort("la base de las credenciales no es la declarada en el manifiesto de la corrida");
if (basename(resolve(outDir)) !== manifest.runId) abort("el directorio de evidencias no corresponde al identificador de esta corrida");
const resultsFile = join(outDir, `resultados-pra-${phase}.json`);
if (existsSync(resultsFile)) abort(`${resultsFile} ya existe; cada fase escribe su propio archivo una sola vez`);
if (execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO, encoding: "utf8" }).trim() !== manifest.commit) abort("el código cambió desde que el orquestador fijó el SHA probado");
mkdirSync(outDir, { recursive: true });

const inspect = (format) => execFileSync("docker", ["inspect", "-f", format, PG_CONTAINER], { encoding: "utf8" }).trim();
let labelRun, portMap;
try { labelRun = inspect('{{index .Config.Labels "vinto.pra.run"}}'); portMap = execFileSync("docker", ["port", PG_CONTAINER, "5432/tcp"], { encoding: "utf8" }).trim(); } catch { abort(`no existe el contenedor ${PG_CONTAINER}`); }
if (labelRun !== manifest.runId || !portMap.split("\n").every((l) => l.trim() === `127.0.0.1:${FIXED.pgPort}`)) abort("el contenedor de PostgreSQL no es el creado por esta corrida (etiqueta o puerto distintos)");
const pgUser = execFileSync("docker", ["exec", PG_CONTAINER, "printenv", "POSTGRES_USER"], { encoding: "utf8" }).trim();
const q = (sql, db = database) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", `BEGIN READ ONLY; ${sql}; COMMIT;`], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check(`S0 [${phase}] la base del recorrido es efímera (*_test) y su identidad se verificó con current_database() dentro del PostgreSQL exclusivo de PR-A-QA`, identity === database && identity.endsWith("_test"), identity, "sql");
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
  const profile = mkdtempSync(join(tmpdir(), `pra-${manifest.runId}-${label}-`));
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


// ---------------------------------------------------------------- PR-A · foco y contraste del diálogo de activación masiva (navegador real + HTTP + SQL de solo lectura)
// Entradas REALES por CDP (Input.dispatchMouseEvent / dispatchKeyEvent), no `element.click()`: el clic programático NO da foco al botón (como Safari/Firefox en macOS y como un toque), que es
// justo la diferencia que hay que medir. El «clic programático» se ensaya aparte y por nombre.
const MP1_A = creds.articles.mp1, MP3_A = creds.articles.mp3;
const line = (pv, article, quantity, machine) => ({ pv_reference: pv, article_code: article, quantity, due_date: "2026-12-01", ...(machine ? { machine_code: machine } : {}) });
const jefatura = client(), supervision = client();
await jefatura.login("jefatura"); await supervision.login("supervision");
const makeOrder = async (body) => {
  const created = await jefatura.call("POST", "/api/work-orders", body);
  if (created.status !== 201) throw new Error(`no se pudo crear la OT: ${created.status} ${created.text.slice(0, 200)}`);
  const published = await jefatura.call("POST", `/api/work-orders/${created.json.id}/publish`);
  if (published.status !== 200) throw new Error(`no se pudo publicar: ${published.status}`);
  return published.json;
};
const activeSql = () => rows("SELECT l.line_code FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id WHERE a.status='active' ORDER BY l.line_code");
const finishAll = async () => { const all = (await supervision.call("GET", "/api/assignments?status=active")).json ?? []; for (const a of all) await supervision.call("POST", `/api/assignments/${a.id}/finish`); };

const keyDown = (b, key, code, vk, extra = {}) => b.send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: vk, ...extra }).then(() => b.send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk }));
const press = { Escape: (b) => keyDown(b, "Escape", "Escape", 27), Tab: (b) => keyDown(b, "Tab", "Tab", 9), ShiftTab: (b) => b.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: 8 }).then(() => b.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9, modifiers: 8 })),
  Enter: (b) => keyDown(b, "Enter", "Enter", 13, { text: "\r" }) };
// Clic REAL de ratón en el centro del elemento que devuelve `expr` (una expresión JS que evalúa a un Element).
const realClick = async (b, expr) => {
  const box = await b.js(`(() => { const el = (${expr}); if (!el) return null; el.scrollIntoView({ block: "center" }); const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, disabled: !!el.disabled }; })()`);
  if (!box || box.disabled) return false;
  await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x, y: box.y });
  await b.send("Input.dispatchMouseEvent", { type: "mousePressed", x: box.x, y: box.y, button: "left", clickCount: 1 });
  await b.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: box.x, y: box.y, button: "left", clickCount: 1 });
  return true;
};
const massButton = (number) => `(() => { const card = [...document.querySelectorAll('[data-work-order]')].find((c) => c.getAttribute('data-work-order') === ${JSON.stringify(number)}); return card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Activar todas las líneas'); })()`;
const dialogButton = (label) => `[...document.querySelectorAll('[role=dialog] button')].find((x) => x.innerText.trim().startsWith(${JSON.stringify(label)}))`;
const dialogOpen = (b) => b.js("!!document.querySelector('[role=dialog]')");
const describeFocus = (b) => b.js(`(() => { const e = document.activeElement; if (!e) return "(ninguno)"; const t = (e.innerText || e.getAttribute('aria-label') || '').trim().split('\\n')[0].slice(0, 40); return e.tagName.toLowerCase() + (t ? ':' + t : '') + (e.closest('[role=dialog]') ? ' [en diálogo]' : ''); })()`);
const isTrigger = (b, number) => b.js(`document.activeElement === (${massButton(number)})`);
const openWith = { mouse: (b, n) => realClick(b, massButton(n)), programmatic: (b, n) => b.js(`(() => { const x = ${massButton(n)}; if (!x) return false; x.click(); return true; })()`),
  keyboard: async (b, n) => { const ok = await b.js(`(() => { const x = ${massButton(n)}; if (!x) return false; x.focus(); return document.activeElement === x; })()`); if (!ok) return false; await press.Enter(b); return true; } };
const waitPreview = (b) => b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Líneas por activar') || document.querySelector('[role=dialog]')?.innerText.includes('Conflictos')", "vista previa del diálogo", 20000);
const setScheme = (b, value) => b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value }] }).then(() => sleep(350));

// Auditoría WCAG de TODO el texto visible del diálogo: color efectivo contra el fondo efectivo (canvas convierte oklch/color-mix a RGBA). Texto grande: >= 24 px, o >= 18,66 px en negrita.
const AUDIT = `(() => { const dlg = document.querySelector('[role=dialog]'); if (!dlg) return { min: 0, items: 0, offenders: [{ text: 'sin diálogo', ratio: 0 }] };
  const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (el) => { let acc = null; for (let e = el; e; e = e.parentElement) { const m = rgba(getComputedStyle(e).backgroundColor); if (m[3] > 0.02) { if (!acc) acc = m.slice(0, 3); if (m[3] > 0.95) return acc && m[3] < 1 ? acc : m.slice(0, 3); } } return [255, 255, 255]; };
  const out = []; let min = 99, items = 0;
  const walker = document.createTreeWalker(dlg, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.nodeValue.trim(); if (!text) continue; const el = n.parentElement; if (!el || el.closest('.sr-only')) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const disabled = !!el.closest('button:disabled');
    const fg = rgba(cs.color), bg = bgOf(el); const a = lum(fg.slice(0, 3)), c = lum(bg); const ratio = (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05);
    const px = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700, large = px >= 24 || (px >= 18.66 && bold), need = large ? 3 : 4.5;
    items++; if (!disabled) min = Math.min(min, ratio);
    if (!disabled && ratio < need) out.push({ text: text.slice(0, 40), ratio: Math.round(ratio * 100) / 100, need });
  }
  return { min: Math.round(min * 100) / 100, items, offenders: out.slice(0, 8) }; })()`;
const audit = async (b, label) => {
  const res = {};
  for (const scheme of ["light", "dark"]) { await setScheme(b, scheme); res[scheme] = await b.js(AUDIT); }
  await setScheme(b, "light");
  return res;
};

// ======================================================================= escenarios
const orderA = await makeOrder({ machine_code: "MP1", lines: [line("PV-1", MP1_A[0], 10, "MP1"), line("PV-2", MP1_A[1], 20, "MP1"), line("PV-3", MP3_A[0], 30, "MP3")] });
check("A0 Jefatura crea y publica una OT de 3 líneas en 2 máquinas", orderA.status === "published", orderA.number, "http");

await browser("foco-escritorio", {}, async (b) => {
  await loginApp(b, "supervision"); await sleep(1200);
  const N = orderA.number;
  // ---- foco inicial y retorno con cada forma de abrir y de cerrar
  for (const how of ["mouse", "keyboard", "programmatic"]) {
    check(`F1-${how} abrir el diálogo (${how})`, await openWith[how](b, N) && await waitPreview(b).then(() => true));
    const initial = await describeFocus(b);
    check(`F2-${how} foco inicial dentro del diálogo y NO sobre «Confirmar» (${how})`, initial.includes("[en diálogo]") && !initial.includes("Confirmar"), initial);
    await press.Escape(b); await sleep(500);
    const afterEsc = await describeFocus(b);
    check(`F3-${how} Escape cierra y el foco vuelve al botón «Activar todas las líneas» (${how})`, !(await dialogOpen(b)) && await isTrigger(b, N), `foco: ${afterEsc}`);
  }
  // ---- cerrar con el botón «Cerrar» y con la X, usando ratón real
  await openWith.mouse(b, N); await waitPreview(b);
  check("F4 «Cerrar» (ratón real) cierra y devuelve el foco al invocador", await realClick(b, dialogButton("Cerrar")) && (await sleep(500), !(await dialogOpen(b))) && await isTrigger(b, N), `foco: ${await describeFocus(b)}`);
  await openWith.mouse(b, N); await waitPreview(b);
  check("F5 la X de cierre (ratón real) cierra y devuelve el foco al invocador", await realClick(b, "document.querySelector('[role=dialog] [data-slot=dialog-close]')") && (await sleep(500), !(await dialogOpen(b))) && await isTrigger(b, N), `foco: ${await describeFocus(b)}`);
  // ---- navegación con teclado: trampa de foco y orden
  await openWith.keyboard(b, N); await waitPreview(b);
  const order = [await describeFocus(b)];
  for (let i = 0; i < 6; i++) { await press.Tab(b); await sleep(120); order.push(await describeFocus(b)); }
  check("F6 teclado: Tab recorre solo el diálogo (trampa de foco), en orden Cerrar → Actualizar → Confirmar → X y vuelve a empezar", order.every((x) => x.includes("[en diálogo]")) && order[0].includes("Cerrar") && order[1].includes("Actualizar") && order[2].includes("Confirmar") && order[4].includes("Cerrar"), order.join(" | "));
  await press.ShiftTab(b); await sleep(120);
  check("F7 teclado: Mayús+Tab retrocede dentro del diálogo", (await describeFocus(b)).includes("[en diálogo]"), await describeFocus(b));
  await press.Escape(b); await sleep(500);
  // ---- el invocador deja de ser enfocable mientras el diálogo está abierto: nunca se enfoca algo inexistente o deshabilitado
  await openWith.keyboard(b, N); await waitPreview(b);
  await b.js(`(() => { const x = ${massButton(N)}; x.disabled = true; })()`);
  await press.Escape(b); await sleep(500);
  const afterDisabled = await describeFocus(b);
  check("F8 invocador DESHABILITADO al cerrar: el foco no se pone en él ni se pierde en <body>", !(await dialogOpen(b)) && !afterDisabled.startsWith("body") && !(await b.js(`document.activeElement === (${massButton(N)})`)), `foco: ${afterDisabled}`);
  await b.js(`(() => { const x = ${massButton(N)}; if (x) x.disabled = false; })()`);
  await openWith.keyboard(b, N); await waitPreview(b);
  await b.js(`(() => { const x = ${massButton(N)}; x.style.display = 'none'; })()`);
  await press.Escape(b); await sleep(500);
  const afterHidden = await describeFocus(b);
  check("F9 invocador OCULTO al cerrar: el foco cae en un destino seguro, no en <body>", !(await dialogOpen(b)) && !afterHidden.startsWith("body"), `foco: ${afterHidden}`);
  await b.js(`(() => { const x = ${massButton(N)}; if (x) x.style.display = ''; })()`);
  // ---- contraste de todos los estados en claro y oscuro
  await openWith.mouse(b, N); await waitPreview(b);
  const preview = await audit(b);
  await b.shot("pra-01-vista-previa-claro.png"); await setScheme(b, "dark"); await b.shot("pra-02-vista-previa-oscuro.png"); await setScheme(b, "light");
  check("C1 contraste de la vista previa en tema CLARO (todo el texto >= 4.5:1; grande >= 3:1)", preview.light.offenders.length === 0, `mín ${preview.light.min}; ${JSON.stringify(preview.light.offenders)}`);
  check("C2 contraste de la vista previa en tema OSCURO del sistema", preview.dark.offenders.length === 0, `mín ${preview.dark.min}; ${JSON.stringify(preview.dark.offenders)}`);
  // ---- doble clic real sobre «Confirmar»: una sola confirmación
  const before = (await cap(b)).filter((p) => /activate-all$/.test(p.url) && /"dry_run":false/.test(p.body)).length;
  const box = await b.js(`(() => { const el = ${dialogButton("Confirmar activación")}; const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x, y: box.y });
  for (const n of [1, 2]) { await b.send("Input.dispatchMouseEvent", { type: "mousePressed", x: box.x, y: box.y, button: "left", clickCount: n }); await b.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: box.x, y: box.y, button: "left", clickCount: n }); }
  await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Se activaron')", "resultado", 30000);
  const confirms = (await cap(b)).filter((p) => /activate-all$/.test(p.url) && /"dry_run":false/.test(p.body)).length - before;
  check("D1 doble clic real: UNA sola confirmación y 3 asignaciones activas en PostgreSQL", confirms === 1 && activeSql().join() === "L1,L2,L3", `confirmaciones ${confirms}; activas ${activeSql()}`);
  const result = await audit(b);
  await b.shot("pra-03-resultado-claro.png"); await setScheme(b, "dark"); await b.shot("pra-04-resultado-oscuro.png"); await setScheme(b, "light");
  check("C3 contraste del resultado en tema CLARO", result.light.offenders.length === 0, `mín ${result.light.min}; ${JSON.stringify(result.light.offenders)}`);
  check("C4 contraste del resultado en tema OSCURO", result.dark.offenders.length === 0, `mín ${result.dark.min}; ${JSON.stringify(result.dark.offenders)}`);
  await press.Escape(b); await sleep(500);
  check("F10 tras el resultado, Escape cierra y el foco vuelve al invocador", !(await dialogOpen(b)) && await isTrigger(b, N), `foco: ${await describeFocus(b)}`);

  // ---- conflicto entre OT: contraste de las alertas y de la tabla de bloqueadas
  const orderB = await makeOrder({ machine_code: "MP1", lines: [line("PV-X", MP1_A[2], 5)] });
  await sleep(400); await b.js("location.reload()"); await b.waitFor("document.readyState === 'complete'", "recarga"); await sleep(1800);
  check("K1 abrir el diálogo de una OT que choca con la anterior", await openWith.mouse(b, orderB.number) && await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Conflictos')", "conflicto", 20000));
  const conflict = await audit(b);
  await b.shot("pra-05-conflicto-claro.png"); await setScheme(b, "dark"); await b.shot("pra-06-conflicto-oscuro.png"); await setScheme(b, "light");
  check("C5 contraste del conflicto (alerta, tabla de bloqueadas) en tema CLARO", conflict.light.offenders.length === 0, `mín ${conflict.light.min}; ${JSON.stringify(conflict.light.offenders)}`);
  check("C6 contraste del conflicto en tema OSCURO", conflict.dark.offenders.length === 0, `mín ${conflict.dark.min}; ${JSON.stringify(conflict.dark.offenders)}`);
  await press.Escape(b); await sleep(500);
  await logoutApp(b);
});

// ---------------- confirmación en vuelo: Escape y la X no cierran; estado «incierto» sin red (contraste de la alerta)
await finishAll();
const orderC = await makeOrder({ machine_code: "MP1", lines: [line("PV-C", MP1_A[0], 7)] });
await browser("en-vuelo", {}, async (b) => {
  await loginApp(b, "supervision"); await sleep(1200);
  const N = orderC.number;
  check("V1 abrir el diálogo (ratón real)", await openWith.mouse(b, N) && await waitPreview(b).then(() => true));
  await b.send("Network.emulateNetworkConditions", { offline: false, latency: 3500, downloadThroughput: -1, uploadThroughput: -1 });
  await realClick(b, dialogButton("Confirmar activación")); await sleep(500);
  await press.Escape(b); await sleep(400);
  const stillOpen = await dialogOpen(b), closeHidden = !(await b.js("!!document.querySelector('[role=dialog] [data-slot=dialog-close]')"));
  check("V2 con la confirmación EN VUELO, Escape NO cierra el diálogo y la X de cierre no se ofrece", stillOpen && closeHidden, `abierto=${stillOpen} Xoculta=${closeHidden}`);
  check("V3 con la confirmación en vuelo «Cerrar» y «Confirmar» están deshabilitados", await b.js(`(() => { const c = ${dialogButton("Cerrar")}, k = ${dialogButton("Activando")} || ${dialogButton("Confirmar")}; return !!c && c.disabled && !!k && k.disabled; })()`));
  await b.waitFor("document.querySelector('[role=dialog]')?.innerText.includes('Se activaron')", "resultado tras la latencia", 30000);
  await b.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  check("V4 PostgreSQL: la confirmación en vuelo terminó con UNA asignación activa", activeSql().join() === "L1", String(activeSql()), "sql");
  await press.Escape(b); await sleep(500);
  check("V5 al terminar, Escape cierra y el foco vuelve al invocador", !(await dialogOpen(b)) && await isTrigger(b, N), `foco: ${await describeFocus(b)}`);
  await logoutApp(b);
});
await finishAll();
const orderD = await makeOrder({ machine_code: "MP1", lines: [line("PV-D", MP1_A[1], 9)] });
await browser("incierto", {}, async (b) => {
  await loginApp(b, "supervision"); await sleep(1200);
  await openWith.mouse(b, orderD.number); await waitPreview(b);
  await b.send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
  await realClick(b, dialogButton("Confirmar activación"));
  await b.waitFor("document.querySelector('[role=dialog] [data-problem]')", "estado incierto", 20000);
  const problem = await audit(b);
  await b.shot("pra-07-incierto-claro.png"); await setScheme(b, "dark"); await b.shot("pra-08-incierto-oscuro.png"); await setScheme(b, "light");
  check("C7 contraste del estado «incierto» (alerta y botones) en tema CLARO", problem.light.offenders.length === 0, `mín ${problem.light.min}; ${JSON.stringify(problem.light.offenders)}`);
  check("C8 contraste del estado «incierto» en tema OSCURO", problem.dark.offenders.length === 0, `mín ${problem.dark.min}; ${JSON.stringify(problem.dark.offenders)}`);
  await b.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  check("C9 PostgreSQL: sin red no se activó nada", activeSql().length === 0, String(activeSql()), "sql");
  await press.Escape(b); await sleep(500);
  check("F11 el cierre desde el estado «incierto» también devuelve el foco al invocador", !(await dialogOpen(b)) && await isTrigger(b, orderD.number), `foco: ${await describeFocus(b)}`);
  await logoutApp(b);
});

// ---------------- móvil de 390 px: foco, contraste y desbordamiento
await browser("movil", { mobile: true }, async (b) => {
  await loginApp(b, "supervision"); await sleep(1200);
  check("M1 móvil: abrir el diálogo", await openWith.mouse(b, orderD.number) && await waitPreview(b).then(() => true));
  check("M2 móvil: sin desplazamiento horizontal y el diálogo cabe en la pantalla", (await b.js("document.documentElement.scrollWidth - window.innerWidth")) <= 1 && await b.js("(() => { const r = document.querySelector('[role=dialog]').getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth + 1; })()"));
  const mobile = await audit(b);
  await b.shot("pra-09-movil-claro.png"); await setScheme(b, "dark"); await b.shot("pra-10-movil-oscuro.png"); await setScheme(b, "light");
  check("C10 móvil: contraste en tema CLARO", mobile.light.offenders.length === 0, `mín ${mobile.light.min}; ${JSON.stringify(mobile.light.offenders)}`);
  check("C11 móvil: contraste en tema OSCURO", mobile.dark.offenders.length === 0, `mín ${mobile.dark.min}; ${JSON.stringify(mobile.dark.offenders)}`);
  check("M3 móvil: los botones del pie miden al menos 36 px de alto", await b.js("[...document.querySelectorAll('[role=dialog] button')].filter((x) => x.offsetParent && !x.matches('[data-slot=dialog-close]')).every((x) => x.getBoundingClientRect().height >= 36)"));
  await press.Escape(b); await sleep(500);
  check("F12 móvil: Escape cierra y el foco vuelve al invocador", !(await dialogOpen(b)) && await isTrigger(b, orderD.number), `foco: ${await describeFocus(b)}`);
  await logoutApp(b);
});

await jefatura.call("POST", "/api/auth/logout"); await supervision.call("POST", "/api/auth/logout");
const left = rows("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0];
check("Z1 sin sesiones activas de prueba tras los logouts", left === "0", `activas ${left}`, "sql");
writeFileSync(resultsFile, JSON.stringify({ runId: manifest.runId, commit: manifest.commit, database, phase, total: results.length, pass: results.filter((r) => r.ok).length, fail: results.filter((r) => !r.ok).length, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL [${phase}] ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
