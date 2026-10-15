// node scripts/e2e/qa3f01-e2e.mjs <creds.json> <evidence-dir> <manifest.json> <enabled|closed>   (solo desde scripts/e2e/qa3f01-run.mjs)
// QA-3F-01 · integración E2E de los TRES frentes (Bobinas, Rebobinado, Conversión) y Calidad en UNA sola instancia de FastAPI/React/PostgreSQL 17,
// desde la NAVEGACIÓN NORMAL de VINTO (la aplicación real en `/`, sin harness de formulario ni ruta de QA). Reutiliza EXACTAMENTE los selectores y
// el patrón ya probados de scripts/e2e/b0-e2e.mjs (Bobinas F3/P1-06/Calidad P1-19, con la política real) y de scripts/e2e/m4a-e2e.mjs /
// scripts/e2e/m6a-e2e.mjs (Rebobinado P1-10 y Conversión P1-16 desde el shell central). No es una regresión exhaustiva de ningún frente por
// separado (esas ya existen y se reutilizan); demuestra que los tres pueden operar JUNTOS, en la MISMA base, sin interferirse.
//
// Fase «enabled» (backend/tests/e2e_qa3f01_server.py con E2E_3F=on): los tres sectores y VINTO-P1-06/P1-10/P1-16 operativos SOLO en ese proceso.
// Fase «closed» (E2E_3F=off): la configuración REAL (solo BOBINAS operativo); Rebobinado y Conversión quedan CONCEDIDOS pero NO operativos.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787) o no son 127.0.0.1, si la base no termina en `_test`, si no es
// current_database(), si el contenedor de PostgreSQL no es el exclusivo de QA-3F-01, si el SHA probado cambió o si el navegador llama al puerto
// 8000. Las lecturas SQL son SELECT en transacciones de solo lectura.
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FIXED = Object.freeze({ api: "http://127.0.0.1:8192", web: "http://127.0.0.1:8799", container: "vinto-qa3f01-pg", pgPort: 55440 });
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
if (!["enabled", "closed"].includes(phase)) abort("uso: node scripts/e2e/qa3f01-e2e.mjs <creds.json> <evidence-dir> <manifest.json> <enabled|closed>; solo se ejecuta desde scripts/e2e/qa3f01-run.mjs");
for (const [name, expected] of [["E2E_API", FIXED.api], ["E2E_WEB", FIXED.web], ["E2E_PG_CONTAINER", FIXED.container]]) if (process.env[name] !== undefined && process.env[name] !== expected) abort(`la variable heredada ${name} intenta redirigir la prueba; los destinos son fijos y los define scripts/e2e/qa3f01-run.mjs`);
if (process.env.E2E_CHROME !== undefined) abort("la variable heredada E2E_CHROME no se admite: el navegador es el instalado en la ruta fija");
if (!credsPath || !outDir || !manifestPath) abort("faltan argumentos");
let manifest; try { manifest = JSON.parse(readFileSync(manifestPath, "utf8")); } catch { abort("el manifiesto de la corrida es ilegible"); }
if (!/^\d{8}T\d{6}Z-[0-9a-f]{8}$/.test(manifest?.runId ?? "")) abort("el manifiesto no trae un identificador de corrida válido");
if (manifest.api !== FIXED.api || manifest.web !== FIXED.web || manifest.container !== FIXED.container || manifest.pgPort !== FIXED.pgPort) abort("el manifiesto no coincide con los destinos fijos de QA-3F-01");
if (manifest.phase !== phase) abort("el manifiesto no corresponde a la fase pedida");
const apiUrl = new URL(API), webUrl = new URL(WEB);
if (apiUrl.port === "8000" || webUrl.port === "8787" || apiUrl.port === "5432") abort("la API o el frontend apuntan a puertos de DEV");
if (apiUrl.hostname !== "127.0.0.1" || webUrl.hostname !== "127.0.0.1") abort("solo se admite 127.0.0.1");
if (!/^vinto-qa3f01-/.test(PG_CONTAINER)) abort(`el contenedor ${PG_CONTAINER} no es el PostgreSQL exclusivo de QA-3F-01`);
if (!/^[0-9a-f]{40}$/.test(manifest.commit ?? "")) abort("el manifiesto no trae el SHA probado");
if (!/_test$/.test(manifest.database ?? "") || FORBIDDEN_DB.includes(manifest.database)) abort(`la base ${manifest.database} no es una base efímera *_test exclusiva`);
let creds; try { creds = JSON.parse(readFileSync(credsPath, "utf8")); } catch { abort("las credenciales de la corrida son ilegibles"); }
const { database, users, articles, rebobinado_machine: REB_MACHINE, conversion_machine: CONV_MACHINE } = creds;
if (database !== manifest.database) abort("la base de las credenciales no es la declarada en el manifiesto de la corrida");
if (basename(resolve(outDir)) !== manifest.runId) abort("el directorio de evidencias no corresponde al identificador de esta corrida");
const resultsFile = join(outDir, `resultados-qa3f01-${phase}.json`);
if (existsSync(resultsFile)) abort(`${resultsFile} ya existe; cada fase escribe su propio archivo una sola vez`);
if (execFileSync("git", ["rev-parse", "HEAD"], { cwd: REPO, encoding: "utf8" }).trim() !== manifest.commit) abort("el código cambió desde que el orquestador fijó el SHA probado");
mkdirSync(outDir, { recursive: true });

const inspect = (format) => execFileSync("docker", ["inspect", "-f", format, PG_CONTAINER], { encoding: "utf8" }).trim();
let labelRun, portMap;
try { labelRun = inspect('{{index .Config.Labels "vinto.qa3f01.run"}}'); portMap = execFileSync("docker", ["port", PG_CONTAINER, "5432/tcp"], { encoding: "utf8" }).trim(); } catch { abort(`no existe el contenedor ${PG_CONTAINER}`); }
if (labelRun !== manifest.runId || !portMap.split("\n").every((l) => l.trim() === `127.0.0.1:${FIXED.pgPort}`)) abort("el contenedor de PostgreSQL no es el creado por esta corrida (etiqueta o puerto distintos)");
const pgUser = execFileSync("docker", ["exec", PG_CONTAINER, "printenv", "POSTGRES_USER"], { encoding: "utf8" }).trim();
const q = (sql, db = database) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", `BEGIN READ ONLY; ${sql}; COMMIT;`], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check(`S0 [${phase}] la base del recorrido es efímera (*_test) y su identidad se verificó con current_database() dentro del PostgreSQL exclusivo de QA-3F-01`, identity === database && identity.endsWith("_test"), identity, "sql");
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
  const profile = mkdtempSync(join(tmpdir(), `qa3f01-${manifest.runId}-${label}-`));
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

if (phase === "enabled") {
  const jefatura = client(), supervision = client(), calidadApi = client(), operacionApi = client();
  await jefatura.login("jefatura"); await supervision.login("supervision"); await calidadApi.login("calidad"); await operacionApi.login("operacion");
  check("S1 la API real responde con sesión y no hay OT ni capturas previas en la base efímera", (await jefatura.call("GET", "/api/work-orders")).json?.length === 0 && rows("SELECT count(*) FROM vinto_txn.capture")[0] === "0", "", "http");

  // ======================================================== FASE A · Bobinas (F3 + P1-06 + Calidad P1-19), política REAL de Calidad intacta
  await browser("jef-bobinas", {}, async (b) => {
    await loginApp(b, "jefatura");
    check("A1 Jefatura ve Bobinas · Programación por defecto", /Bobinas · Programaci[oó]n/.test(await b.text()));
    await b.setField("Máquina", "MP1"); await b.setField("PV", "PV-3F01-MP1"); await b.setField("Producto", articles.MP1); await b.setField("Cantidad", "50"); await b.setField("Entrega", "2026-12-01");
    check("A2 crear la OT de MP1 desde la interfaz", await b.clickText("Crear OT inicial"));
    await b.waitFor("document.body.innerText.includes('PV-3F01-MP1')", "OT de MP1 en la lista", 20000);
    const listed = await jefatura.call("GET", "/api/work-orders");
    ctx.ot.MP1 = listed.json.find((w) => w.machine.code === "MP1");
    check("A3 la OT de MP1 existe en PostgreSQL en borrador", listed.status === 200 && ctx.ot.MP1?.status === "draft", JSON.stringify(ctx.ot.MP1), "http");
    check("A4 publicar la base de MP1", await cardAction(b, ctx.ot.MP1.number, "Publicar base"));
    await sleep(1500);
    const after = await jefatura.call("GET", "/api/work-orders"); ctx.ot.MP1 = after.json.find((w) => w.machine.code === "MP1");
    check("A5 la OT de MP1 queda PUBLICADA en PostgreSQL", ctx.ot.MP1.status === "published", ctx.ot.MP1.status, "http");
    await b.shot("a1-ot-mp1-publicada.png");
    await logoutApp(b);
  });

  await browser("sup-bobinas", {}, async (b) => {
    await loginApp(b, "supervision"); await sleep(1000);
    check("A6 Supervisión activa la asignación de MP1 desde la interfaz", await cardAction(b, ctx.ot.MP1.number, "Activar"));
    await sleep(1500);
    const active = await supervision.call("GET", "/api/assignments/active?machine_code=MP1");
    ctx.assignment.MP1 = active.json?.assignment?.id;
    check("A7 la asignación de MP1 existe en PostgreSQL con OT, artículo, turno y fecha operativa resueltos por el backend", active.status === 200 && active.json.assignment?.machine.code === "MP1" && active.json.assignment.work_order.number === ctx.ot.MP1.number && active.json.stale === false, JSON.stringify(active.json?.assignment?.shift), "http");
    await logoutApp(b);
  });

  await browser("op-bobinas", {}, async (b) => {
    await loginApp(b, "operacion");
    await goModule(b, "Ejecución", "Punto de captura");
    await b.clickText("MP1"); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(ctx.ot.MP1.number)})`, "contexto de MP1", 20000); await sleep(800);
    check("A8 Operación ve el contexto real de MP1 y F3/P1-06 entre las tarjetas", await clickCard(b, "Registro de producción de bobinas") && await b.waitFor("document.body.innerText.includes('Datos de la bobina')", "pantalla F3", 15000));
    for (const [i, v] of ["07:00", "08:00", "1000,0", "400,0", "2"].entries()) await setNth(b, "main input", i, v);
    await setNth(b, "main textarea", 0, "bobina ficticia QA-3F-01");
    check("A9 enviar F3 (Registro de producción de bobinas)", await b.clickText("Registrar bobina"));
    await b.waitFor("!document.body.innerText.includes('Datos de la bobina') && document.body.innerText.includes('Punto de captura')", "regreso tras F3", 30000);
    const f3Posts = (await cap(b)).filter((p) => p.url.endsWith("/api/bobbins")); const sentF3 = JSON.parse(f3Posts[0].body);
    ctx.capture.f3 = sentF3.capture_id;
    const bobbinRow = rows(`SELECT b.id||'|'||b.code FROM vinto_txn.bobbin b WHERE b.source_capture_id = '${sentF3.capture_id}'`);
    const [bid, bcode] = (bobbinRow[0] ?? "").split("|"); ctx.bobbin.MP1 = { id: bid, code: bcode };
    check("A10 PostgreSQL: F3 crea UNA bobina de MP1 asociada a esa captura", bobbinRow.length === 1 && !!bid, bobbinRow.join(" ; "), "sql");
    const rel = rows(`SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = '${bid}'`);
    check("A11 estado inicial de Calidad: pending (F3 no decide Calidad)", rel[0] === "pending", rel.join(" ; "), "sql");
    check("A12 abrir P1-06 (Registro de control de fardos)", await clickCard(b, "Registro de control de fardos") && await b.waitFor("document.body.innerText.includes('Control de fardos')", "pantalla P1-06", 15000));
    await b.setField("Cantidad de fardos", "2"); await b.setField("Punto de merma", "recorte_maquina"); await b.setField("Tipo de producto", "hoja_doble"); await b.setField("Peso real total", "50,0"); await b.setField("Observaciones", "fardos QA-3F-01");
    check("A13 enviar P1-06", await b.clickText("Enviar registro trazable"));
    await b.waitFor("!document.body.innerText.includes('Control de fardos') || document.body.innerText.includes('Punto de captura')", "regreso tras P1-06", 30000);
    const p106Posts = (await cap(b)).filter((p) => p.url.endsWith("/api/captures")); const sent106 = JSON.parse(p106Posts[0].body);
    check("A14 PostgreSQL: captura P1-06 submitted en MP1 con la asignación correcta", rows(`SELECT c.status||'|'||c.assignment_id FROM vinto_txn.capture c WHERE c.id = '${sent106.capture_id}'`)[0] === `submitted|${ctx.assignment.MP1}`, "", "sql");
    const dump = await storageDump(b);
    check("A15 ninguna captura de Bobinas está en localStorage (solo la clave técnica del dispositivo)", !dump.includes(sentF3.capture_id) && !dump.includes(sent106.capture_id) && !dump.includes("QA-3F-01"), Object.keys(JSON.parse(dump)).join(","));
    await b.shot("a2-bobinas-capturado.png");
    await logoutApp(b);
  });

  await browser("cal-bobinas", {}, async (b) => {
    await loginApp(b, "calidad");
    await nav(b, "Calidad"); await b.waitFor("document.body.innerText.includes('Calidad ·')", "front Calidad", 15000);
    await goModule(b, "Ejecución", "Bobinas pendientes de Calidad"); await sleep(1200);
    const inboxRow = await b.js(`document.querySelector('table') ? [...document.querySelectorAll('table tbody tr')].map((r) => r.innerText.replace(/\\s+/g, ' ')).find((r) => r.includes(${JSON.stringify(ctx.ot.MP1.number)})) : null`);
    check("A16 la bandeja de Calidad (política REAL, sin candidatos) muestra la bobina de MP1 pendiente", !!inboxRow && inboxRow.includes("Pendiente"), (inboxRow ?? "").slice(0, 160));
    check("A17 abrir el control de humedad (P1-19) de la bobina de MP1", await clickAria(b, "Registrar humedad de la bobina", "(MP1") && await b.waitFor("document.body.innerText.includes('Pesos de la muestra')", "pantalla P1-19", 15000));
    for (const [i, v] of ["10,0", "9,0", "10,1", "9,1", "9,9", "8,9"].entries()) await setNth(b, "main input", i, v);
    check("A18 enviar P1-19", await b.clickText("Registrar control de humedad"));
    await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad') && !document.body.innerText.includes('Pesos de la muestra')", "regreso a la bandeja tras P1-19", 30000);
    const hum = (await cap(b)).filter((p) => p.url.includes("/captures")).map((p) => JSON.parse(p.body))[0];
    ctx.capture.p119 = hum.capture_id;
    check("A19 PostgreSQL: captura P1-19 submitted, área quality, asociada a la bobina de MP1", rows(`SELECT c.status||'|'||c.bobbin_id||'|'||fv.area FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id WHERE c.id = '${hum.capture_id}'`)[0] === `submitted|${ctx.bobbin.MP1.id}|quality`, "", "sql");
    check("A20 abrir el historial (Ver controles) de la bobina de MP1 y ver P1-19", await clickAria(b, "Ver controles de la bobina", "(MP1") && await b.waitFor("document.body.innerText.includes('Controles registrados: 1') && document.body.innerText.includes('VINTO-P1-19')", "historial", 20000));
    await b.shot("a3-calidad-historial.png");
    check("A21 PostgreSQL: Calidad sigue pendiente (capturar P1-19 no libera ni rechaza)", rows(`SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = '${ctx.bobbin.MP1.id}'`)[0] === "pending", "", "sql");
    // el historial (QualityBobbinHistory) sustituye todo el chrome de la aplicación (sin barra de "Cerrar sesión"): hay que volver al inbox antes de cerrar sesión
    await b.clickText("Volver al inbox"); await b.waitFor("document.body.innerText.includes('Bobinas pendientes de Calidad')", "inbox", 15000);
    await logoutApp(b);
  });

  // ======================================================== FASE B · Rebobinado (P1-10), MISMA base/instancia
  await browser("jef-rebobinado", {}, async (b) => {
    await loginApp(b, "jefatura");
    await nav(b, "Rebobinado"); await b.waitFor("document.querySelector('[data-rebobinado=\"programacion\"]')", "programación de Rebobinado", 20000);
    await b.setField("Máquina", REB_MACHINE); await b.setField("PV", "PV-3F01-REB"); await b.setField("Producto", articles.MP1); await b.setField("Cantidad", "10"); await b.setField("Entrega", "2026-12-01");
    check("B1 crear la OT de Rebobinado desde la interfaz", await b.clickText("Crear OT inicial"));
    await b.waitFor("document.body.innerText.includes('PV-3F01-REB')", "OT de Rebobinado en la lista", 20000);
    const listed = await jefatura.call("GET", "/api/work-orders");
    ctx.ot.REB = listed.json.find((w) => w.machine.code === REB_MACHINE);
    check("B2 la OT de Rebobinado existe en PostgreSQL en borrador", ctx.ot.REB?.status === "draft", JSON.stringify(ctx.ot.REB), "http");
    check("B3 publicar la base de Rebobinado", await cardAction(b, ctx.ot.REB.number, "Publicar base"));
    await sleep(1500);
    ctx.ot.REB = (await jefatura.call("GET", "/api/work-orders")).json.find((w) => w.machine.code === REB_MACHINE);
    check("B4 la OT de Rebobinado queda PUBLICADA", ctx.ot.REB.status === "published", ctx.ot.REB.status, "http");
    await nav(b, "Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas ·')", "Bobinas", 15000); await sleep(800);
    check("B5 Bobinas no cambia: su programación central sigue ofreciendo solo MP1/MP3 (no las máquinas de Rebobinado)", await b.js(`[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'MP1') && ![...s.options].some((o) => o.value === ${JSON.stringify(REB_MACHINE)}))`));
    await logoutApp(b);
  });

  await browser("sup-rebobinado", {}, async (b) => {
    await loginApp(b, "supervision");
    await nav(b, "Rebobinado"); await b.waitFor("document.querySelector('[data-rebobinado=\"programacion\"]')", "programación", 20000); await sleep(800);
    check("B6 Supervisión activa la asignación de Rebobinado desde la interfaz", await cardAction(b, ctx.ot.REB.number, "Activar"));
    await sleep(1500);
    const active = await supervision.call("GET", `/api/assignments/active?machine_code=${REB_MACHINE}`);
    ctx.assignment.REB = active.json?.assignment?.id;
    check("B7 la asignación de Rebobinado existe en PostgreSQL", active.status === 200 && active.json.assignment?.machine.code === REB_MACHINE && active.json.stale === false, "", "http");
    await logoutApp(b);
  });

  await browser("op-rebobinado", {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Rebobinado"); await nav(b, "Ejecución"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "ejecución", 20000);
    await b.waitFor(`document.body.innerText.includes(${JSON.stringify(ctx.ot.REB.number)})`, "contexto de Rebobinado", 20000); await sleep(800);
    const forms = await b.js("[...document.querySelectorAll('[data-form]')].map((e) => e.dataset.form)");
    check("B8 Rebobinado ofrece VINTO-P1-10 (y ningún formulario de Conversión)", forms.includes("VINTO-P1-10") && !forms.includes("VINTO-P1-16"), JSON.stringify(forms));
    check("B9 abrir P1-10 desde la navegación normal", await b.click('[data-form="VINTO-P1-10"]') && await b.waitFor("document.querySelectorAll('main input').length === 3", "pantalla P1-10", 15000));
    for (const [i, v] of ["PROD-3F01", "FARDO-3F01", "5,0 (texto)"].entries()) await setNth(b, "main input", i, v);
    await setNth(b, "main textarea", 0, "dato ficticio QA-3F-01");
    check("B10 enviar P1-10", await b.clickText("Enviar registro trazable"));
    await b.waitFor("document.querySelector('[data-section=saved]')", "P1-10 guardado", 30000);
    const sent = JSON.parse((await cap(b)).filter((p) => p.url.endsWith("/api/captures"))[0].body);
    ctx.capture.p110 = sent.capture_id;
    check("B11 PostgreSQL: captura P1-10 submitted en Rebobinado con la asignación correcta", rows(`SELECT c.status||'|'||c.assignment_id FROM vinto_txn.capture c WHERE c.id = '${sent.capture_id}'`)[0] === `submitted|${ctx.assignment.REB}`, "", "sql");
    await b.clickText("Volver"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "regreso", 15000);
    await nav(b, "Seguimiento"); await b.waitFor(`document.querySelector('[data-capture="${sent.capture_id}"]')`, "historial de P1-10", 20000);
    check("B12 Seguimiento muestra el registro REAL de P1-10 (parser específico)", (await b.js(`document.querySelector('[data-capture="${sent.capture_id}"]').innerText`)).includes("FARDO-3F01"));
    await b.shot("b1-rebobinado-p110.png");
    const dump = await storageDump(b);
    check("B13 ningún dato de Rebobinado está en localStorage", !dump.includes(sent.capture_id) && !dump.includes(ctx.ot.REB.number));
    await logoutApp(b);
  });

  // ======================================================== FASE C · Conversión (P1-16), MISMA base/instancia
  await browser("jef-conversion", {}, async (b) => {
    await loginApp(b, "jefatura");
    await nav(b, "Conversión"); await b.waitFor("document.querySelector('[data-conversion=\"programacion\"]')", "programación de Conversión", 20000);
    await b.setField("Máquina", CONV_MACHINE); await b.setField("PV", "PV-3F01-CONV"); await b.setField("Producto", articles.MP1); await b.setField("Cantidad", "10"); await b.setField("Entrega", "2026-12-01");
    check("C1 crear la OT de Conversión desde la interfaz", await b.clickText("Crear OT inicial"));
    await b.waitFor("document.body.innerText.includes('PV-3F01-CONV')", "OT de Conversión en la lista", 20000);
    const listed = await jefatura.call("GET", "/api/work-orders");
    ctx.ot.CONV = listed.json.find((w) => w.machine.code === CONV_MACHINE);
    check("C2 la OT de Conversión existe en PostgreSQL en borrador", ctx.ot.CONV?.status === "draft", JSON.stringify(ctx.ot.CONV), "http");
    check("C3 publicar la base de Conversión", await cardAction(b, ctx.ot.CONV.number, "Publicar base"));
    await sleep(1500);
    ctx.ot.CONV = (await jefatura.call("GET", "/api/work-orders")).json.find((w) => w.machine.code === CONV_MACHINE);
    check("C4 la OT de Conversión queda PUBLICADA", ctx.ot.CONV.status === "published", ctx.ot.CONV.status, "http");
    await logoutApp(b);
  });

  await browser("sup-conversion", {}, async (b) => {
    await loginApp(b, "supervision");
    await nav(b, "Conversión"); await b.waitFor("document.querySelector('[data-conversion=\"programacion\"]')", "programación", 20000); await sleep(800);
    check("C5 Supervisión activa la asignación de Conversión desde la interfaz", await cardAction(b, ctx.ot.CONV.number, "Activar"));
    await sleep(1500);
    const active = await supervision.call("GET", `/api/assignments/active?machine_code=${CONV_MACHINE}`);
    ctx.assignment.CONV = active.json?.assignment?.id;
    check("C6 la asignación de Conversión existe en PostgreSQL", active.status === 200 && active.json.assignment?.machine.code === CONV_MACHINE && active.json.stale === false, "", "http");
    await logoutApp(b);
  });

  let sentP116 = null;
  await browser("op-conversion", {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Conversión"); await nav(b, "Ejecución"); await b.waitFor("document.querySelector('[data-conversion=\"ejecucion\"]')", "ejecución", 20000);
    await b.waitFor(`document.body.innerText.includes(${JSON.stringify(ctx.ot.CONV.number)})`, "contexto de Conversión", 20000);
    const forms = await b.js("[...document.querySelectorAll('[data-form]')].map((e) => e.dataset.form)");
    check("C7 Conversión ofrece VINTO-P1-16 (y ningún formulario de Rebobinado)", forms.includes("VINTO-P1-16") && !forms.includes("VINTO-P1-10"), JSON.stringify(forms));
    check("C8 abrir P1-16 desde la navegación normal", await b.click('[data-form="VINTO-P1-16"]') && await b.waitFor("document.querySelectorAll('main select').length === 2 && document.querySelectorAll('main input').length === 1", "pantalla P1-16", 15000));
    await b.setField("Tipo de merma", "carton"); await b.setField("Origen de la merma", "cola"); await b.setField("Peso real", "6,5");
    check("C9 enviar P1-16", await b.clickText("Enviar registro trazable"));
    await b.waitFor("document.querySelector('[data-section=saved]')", "P1-16 guardado", 30000);
    sentP116 = JSON.parse((await cap(b)).filter((p) => p.url.endsWith("/api/captures"))[0].body);
    ctx.capture.p116 = sentP116.capture_id;
    check("C10 PostgreSQL: captura P1-16 submitted en Conversión con los 3 detalles tipados", rows(`SELECT c.status||'|'||count(d.*) FROM vinto_txn.capture c JOIN vinto_txn.capture_detail d ON d.capture_id = c.id WHERE c.id = '${sentP116.capture_id}' GROUP BY c.status`)[0] === "submitted|3", "", "sql");
    await b.clickText("Volver"); await b.waitFor("document.querySelector('[data-conversion=\"ejecucion\"]')", "regreso", 15000);
    await nav(b, "Seguimiento"); await b.waitFor(`document.querySelector('[data-capture="${sentP116.capture_id}"]')`, "historial de P1-16", 20000);
    check("C11 Seguimiento muestra el registro REAL de P1-16 (parser específico)", (await b.js(`document.querySelector('[data-capture="${sentP116.capture_id}"]').innerText`)).includes("Cartón"));
    await b.shot("c1-conversion-p116.png");
    const dump = await storageDump(b);
    check("C12 ningún dato de Conversión está en localStorage", !dump.includes(sentP116.capture_id) && !dump.includes(ctx.ot.CONV.number));
    await logoutApp(b);
  });

  // ======================================================== FASE D · integración transversal
  const machinesApi = await jefatura.call("GET", "/api/production/machines");
  const sectorsApi = Object.fromEntries(machinesApi.json.sectors.map((s) => [s.code, s.machines.map((m) => `${m.code}:${m.forms.map((f) => f.code).join("+")}`)]));
  check("D1 el backend publica los tres sectores, cada uno con SUS formularios: P1-10 solo en Rebobinado, P1-16 solo en Conversión", JSON.stringify(sectorsApi.REBOBINADO).includes(`${REB_MACHINE}:VINTO-P1-10`) && JSON.stringify(sectorsApi.CONVERSION).includes(`${CONV_MACHINE}:VINTO-P1-16`) && !JSON.stringify(sectorsApi.REBOBINADO).includes("VINTO-P1-16") && !JSON.stringify(sectorsApi.CONVERSION).includes("VINTO-P1-10"), JSON.stringify(sectorsApi), "http");
  const allOrders = await jefatura.call("GET", "/api/work-orders");
  // "in_progress": las tres OT ya tienen una asignación activada (B6/C5/A6); publicada -> en curso es la transición esperada, no un error.
  check("D2 las tres OT (Bobinas MP1, Rebobinado, Conversión) coexisten, cada una con la asignación de SU máquina activada, en la misma base", ["MP1", REB_MACHINE, CONV_MACHINE].every((m) => allOrders.json.some((w) => w.machine.code === m && w.status === "in_progress")), allOrders.json.map((w) => `${w.machine.code}:${w.status}`).join(","), "http");
  const activeByMachine = rows(`SELECT m.code||'='||count(*) FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id WHERE a.status = 'active' GROUP BY m.code ORDER BY m.code`);
  const expectedActive = [...new Set(["MP1=1", `${REB_MACHINE}=1`, `${CONV_MACHINE}=1`])].sort();
  check("D3 las tres asignaciones permanecen asociadas cada una a SU máquina (sin mezclarse)", JSON.stringify(activeByMachine) === JSON.stringify(expectedActive), activeByMachine.join(","), "sql");
  // VINTO-P1-03 es el código interno de F3 (registro de producción de bobinas, backend/app/bobbins/service.py); los otros cuatro son P1-06/P1-10/P1-16/P1-19.
  const totalsByForm = rows(`SELECT f.code||'='||count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id GROUP BY f.code ORDER BY f.code`).join(",");
  check("D4 ninguna captura quedó cruzada entre formularios/sectores: un registro por formulario, sin duplicados", totalsByForm === "VINTO-P1-03=1,VINTO-P1-06=1,VINTO-P1-10=1,VINTO-P1-16=1,VINTO-P1-19=1", totalsByForm, "sql");
  check("D5 quality_release sigue pendiente y sin decisión: ninguna captura de los tres frentes la tocó", rows("SELECT status||'|'||coalesce(decided_by::text,'-') FROM vinto_txn.quality_release")[0] === "pending|-", "", "sql");

  // D: idempotencia — reenviar EXACTAMENTE el mismo payload de P1-16 por la API no duplica ni cambia el valor guardado
  const opr = client(); await opr.login("operacion");
  const replay = await opr.call("POST", "/api/captures", sentP116);
  check("D6 un reintento idéntico (mismo capture_id y contenido) de P1-16 es 200 already_submitted y no crea otra fila", replay.status === 200 && replay.json.created === false && replay.json.already_submitted === true && rows(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${sentP116.capture_id}'`)[0] === "1", "", "http");
  await opr.call("POST", "/api/auth/logout");

  // D: la concesión por sector sigue limitando la disponibilidad aunque Rebobinado/Conversión sean operativos
  await browser("scope-solo-bobinas", {}, async (b) => {
    await loginApp(b, "operacion_solo_bobinas");
    let disabledEverywhere = true;
    for (const [frente, attr] of [["Rebobinado", "data-rebobinado"], ["Conversión", "data-conversion"]]) {
      await nav(b, frente); await b.waitFor(`!!document.querySelector('[${attr}]')`, `panel de ${frente}`, 20000); await sleep(800);
      disabledEverywhere = disabledEverywhere && await b.js(`!!document.querySelector('[${attr}="disabled"]')`) && !(await b.js("document.querySelectorAll('[data-form]').length"));
    }
    check("D7 un usuario sin concesión de Rebobinado/Conversión no los ve operativos aunque el backend los tenga habilitados en esta prueba", disabledEverywhere);
    // Operación no gestiona OT (sin canManageOrders: Programación no muestra el selector de máquina); se verifica Bobinas por Ejecución, como el resto del recorrido de Operación.
    await nav(b, "Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas ·')", "Bobinas", 15000);
    await goModule(b, "Ejecución", "Punto de captura");
    check("D8 el mismo usuario SÍ opera Bobinas (su único sector concedido): ve MP1/MP3 en el punto de captura", await b.js("[...document.querySelectorAll('button')].some((x) => x.innerText.trim() === 'MP1')"));
    await logoutApp(b);
  });
  await jefatura.call("POST", "/api/auth/logout"); await supervision.call("POST", "/api/auth/logout"); await calidadApi.call("POST", "/api/auth/logout"); await operacionApi.call("POST", "/api/auth/logout");
  const sessions = rows("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0];
  check("Z1 sin sesiones activas de prueba tras los logouts", sessions === "0", `activas ${sessions}`, "sql");
} else {
  // ======================================================== FASE «política cerrada»: configuración REAL (Rebobinado/Conversión concedidos, NO operativos)
  const jef = client(); await jef.login("jefatura");
  const avail = await jef.call("GET", "/api/production/machines");
  check("E1 con la configuración real el backend NO expone Rebobinado ni Conversión aunque los usuarios tengan la concesión (solo BOBINAS)", avail.status === 200 && JSON.stringify(avail.json.sectors.map((s) => s.code)) === JSON.stringify(["BOBINAS"]), JSON.stringify(avail.json.sectors?.map((s) => s.code)), "http");
  const op = client(); await op.login("operacion");
  const p10Blocked = await op.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-10", assignment_id: crypto.randomUUID(), device_key: crypto.randomUUID(), values: {} });
  const p16Blocked = await op.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-16", assignment_id: crypto.randomUUID(), device_key: crypto.randomUUID(), values: {} });
  check("E2 con la política real, P1-10 y P1-16 se rechazan (422 UNSUPPORTED_FORM) y sus máquinas no tienen alcance (422 en asignaciones activas)", p10Blocked.status === 422 && p10Blocked.json.code === "UNSUPPORTED_FORM" && p16Blocked.status === 422 && p16Blocked.json.code === "UNSUPPORTED_FORM" && (await op.call("GET", `/api/assignments/active?machine_code=${REB_MACHINE}`)).status === 422 && (await op.call("GET", `/api/assignments/active?machine_code=${CONV_MACHINE}`)).status === 422, JSON.stringify({ p10: p10Blocked.status, p16: p16Blocked.status }), "http");
  await op.call("POST", "/api/auth/logout"); await jef.call("POST", "/api/auth/logout");

  for (const who of ["jefatura", "operacion"]) {
    await browser(`closed-${who}`, {}, async (b) => {
      await loginApp(b, who);
      for (const [frente, attr, title] of [["Rebobinado", "data-rebobinado", "Rebobinado no está habilitado"], ["Conversión", "data-conversion", "Conversión no está habilitado"]]) {
        await nav(b, frente); await b.waitFor(`!!document.querySelector('[${attr}]')`, `panel de ${frente}`, 20000); await sleep(800);
        check(`E3 ${who}: con la configuración real, ${frente} se muestra NO habilitado, sin formularios ni OT candidata alguna`, await b.js(`!!document.querySelector('[${attr}="disabled"]')`) && (await b.text()).includes(title) && !(await b.js("document.querySelectorAll('[data-form]').length")));
      }
      if (who === "jefatura") {
        await nav(b, "Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas ·')", "Bobinas", 15000); await sleep(800);
        check("E4 Bobinas sigue operativo con la configuración real: su programación central (MP1/MP3) se muestra", await b.js("[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'MP1'))"));
      }
      check(`E5 ${who}: ningún POST de escritura a OT/asignaciones/capturas desde la navegación bloqueada`, b.log.requests.filter((r) => r.method === "POST" && /\/api\/(captures|work-orders|assignments|bobbins)/.test(r.url)).length === 0);
      const dump = JSON.parse(await storageDump(b));
      check(`E6 ${who}: sin respaldo local de Rebobinado/Conversión (no hay alternativa local)`, !JSON.stringify(dump).includes("VINTO-P1-10") && !JSON.stringify(dump).includes("VINTO-P1-16"), Object.keys(dump).join(","));
      await logoutApp(b);
    });
  }
  check("E7 con la política real, no se escribió ninguna captura ni OT de Rebobinado/Conversión en la base efímera (solo lo que el entorno siembra)", rows("SELECT count(*) FROM vinto_txn.work_order")[0] === "0" && rows("SELECT count(*) FROM vinto_txn.capture")[0] === "0", "", "sql");
  const sessionsClosed = rows("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0];
  check("Z1 sin sesiones activas de prueba tras los logouts (fase cerrada)", sessionsClosed === "0", `activas ${sessionsClosed}`, "sql");
}

writeFileSync(resultsFile, JSON.stringify({ runId: manifest.runId, commit: manifest.commit, database, phase, total: results.length, pass: results.filter((r) => r.ok).length, fail: results.filter((r) => !r.ok).length, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL [${phase}] ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
