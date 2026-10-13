// node scripts/e2e/m4a-e2e.mjs <creds.json> <evidence-dir> <enabled|disabled>
// M4-A · circuito CENTRAL de Rebobinado desde la NAVEGACIÓN NORMAL de VINTO (la aplicación real en `/`, sin harness de formulario): login de Jefatura -> crear y publicar OT -> login de Supervisión -> activar
// asignación -> login de Operación -> abrir P1-10 / P1-29 -> guardar en PostgreSQL efímero -> GET e historial (Seguimiento) -> logout. Fase `enabled`: backend de prueba con Rebobinado habilitado SOLO en su proceso
// (backend/tests/e2e_p110_server.py, E2E_REBOBINADO=on). Fase `disabled`: el mismo backend con la configuración REAL (Rebobinado concedido pero NO operativo, política solo F6). TODOS los datos son FICTICIOS.
// El frontend se construye SIN ruta de QA (la aplicación tal cual) con NEXT_PUBLIC_API_URL = backend de prueba y se sirve en el puerto 8796; no se crea ninguna ruta pública.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787), si la base no termina en `_test`, si no es `current_database()`, si el backend no sirve esa base o si el navegador llama al puerto
// 8000. Lecturas de PostgreSQL = SELECT en transacciones de solo lectura (también sobre DEV, solo para comprobar que no cambió); las únicas escrituras son manipulaciones explícitas de la base EFÍMERA (asignación vencida).
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [credsPath, outDir, phase] = process.argv.slice(2);
if (!["enabled", "disabled"].includes(phase)) { console.error("fase inválida: enabled | disabled"); process.exit(2); }
const API = process.env.E2E_API ?? "http://127.0.0.1:8190", WEB = process.env.E2E_WEB ?? "http://127.0.0.1:8796";
const PG_CONTAINER = process.env.E2E_PG_CONTAINER ?? "vinto-local-postgres-1";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const creds = JSON.parse(readFileSync(credsPath, "utf8"));
const { database, users } = creds;
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
const run = (db, sql, readOnly) => execFileSync("docker", ["exec", PG_CONTAINER, "psql", "-U", pgUser, "-d", db, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "-c", readOnly ? `BEGIN READ ONLY; ${sql}; COMMIT;` : sql], { encoding: "utf8" })
  .split("\n").filter((l) => l && l !== "BEGIN" && l !== "COMMIT");
const psql = (db, sql) => run(db, sql, true);
const q = (sql) => psql(database, sql);
const qw = (sql) => { if (!/_test$/.test(database) || database === "vinto") abort("escritura rechazada: no es la base efímera"); return run(database, sql, false); }; // SOLO la base efímera
const identity = q("SELECT current_database()")[0];
if (identity !== database || !identity.endsWith("_test")) abort(`identidad de base inesperada: ${identity}`);
check("S0 la base del recorrido es efímera (*_test) y su identidad se verificó con current_database()", true, identity);
const DEV_SQL = "SELECT (SELECT count(*) FROM vinto_txn.capture)||'|'||(SELECT count(*) FROM vinto_txn.capture_group_row)||'|'||(SELECT count(*) FROM vinto_audit.audit_event)||'|'||(SELECT count(*) FROM vinto_auth.session)||'|'||(SELECT count(*) FROM vinto_auth.auth_event)||'|'||(SELECT count(*) FROM vinto_master.user_sector)||'|'||(SELECT count(*) FROM vinto_txn.work_order)";
const DEV_READ = process.env.E2E_DEV_READ !== "off"; // E2E_DEV_READ=off: no se abre NINGUNA conexión de lectura a DEV (usado cuando el entorno prohíbe tocar DEV)
const devBefore = DEV_READ ? psql("vinto", DEV_SQL)[0] : "omitido";

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

// ---------------------------------------------------------------- Chrome (CDP) sobre la aplicación real
const FAULT_SCRIPT = (mode) => `(() => { const w = window; if (w.__fault) return; w.__fault = true; w.__posts = []; const real = w.fetch.bind(w); let armed = ${JSON.stringify(mode)} !== "none";
  w.fetch = async (input, init) => { const post = (init && init.method === "POST") && String(input).endsWith("/api/captures"); if (post) w.__posts.push(String(init.body ?? ""));
    if (post && armed && ${JSON.stringify(mode)} === "lose-request") { armed = false; throw new TypeError("simulated: request never reached the server"); }
    const response = await real(input, init); if (post && armed && ${JSON.stringify(mode)} === "lose-response") { armed = false; throw new TypeError("simulated: response lost after the server processed the request"); } return response; }; })();`;
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
const posts = (b) => b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/captures"));
const storageDump = (b) => b.js("JSON.stringify(Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])))");
const dbRows = (id) => q(`SELECT g.code||'|'||r.row_number||'|'||coalesce((SELECT string_agg(f.key||'='||coalesce(d.value_text, d.value_decimal::text, d.value_date::text), ',' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.group_row_id = r.id), '') FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = '${id}' ORDER BY g.display_order, r.row_number`);
const formFields = (b) => b.js("document.querySelectorAll('main input, main textarea').length");
const setNth = (b, selector, i, value) => b.js(`(() => { const el = document.querySelectorAll(${JSON.stringify(selector)})[${i}]; if (!el) return false; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const GROUP = { rodelas: '[data-group="Rodelas de papel kraft"]', formatos: '[data-group="Formatos de tubete"]' };
const setCell = (b, group, row, i, value) => setNth(b, `${GROUP[group]} li[data-row="${row}"] input, ${GROUP[group]} li[data-row="${row}"] textarea`, i, value);

async function fillP110(b, v) { for (const [i, value] of [v.codigo, v.fardo, v.peso].entries()) await setNth(b, "main input", i, value); await setNth(b, "main textarea", 0, v.obs); }
async function fillP129(b, lote) {
  for (const [i, v] of ["2026-01-15", lote, "12,5 (texto de ejemplo)", "100,0 (texto de ejemplo)", "MRP-FICTICIO-M4A"].entries()) await setNth(b, "main input", i, v);
  await setNth(b, "main textarea", 0, "dato ficticio M4-A");
  await b.click(`${GROUP.rodelas} button`); await b.click(`${GROUP.formatos} button`);
  for (const [r, cells] of [["RODELA-FICTICIA-A", "10,250"], ["RODELA-FICTICIA-B", "8.100"]].entries()) for (const [i, v] of cells.entries()) await setCell(b, "rodelas", r + 1, i, v);
  for (const [r, cells] of [["FORMATO-FICTICIO-1", "120 (texto)", "3 observados", "0,500", "38.10", "42.00", "4", "1.800", "6,750"], ["FORMATO-FICTICIO-2", "80", "", "0.250", "30.00", "34.00", "3", "1.500", "4.125"]].entries()) for (const [i, v] of cells.entries()) await setCell(b, "formatos", r + 1, i, v);
}
const P129_EXPECTED_ROWS = ["rodelas|1|rodela_papel_kraft_identificacion=RODELA-FICTICIA-A,rodela_papel_kraft_peso_kg=10.250", "rodelas|2|rodela_papel_kraft_identificacion=RODELA-FICTICIA-B,rodela_papel_kraft_peso_kg=8.100",
  "formatos|1|formato_tipo_de_tubete=FORMATO-FICTICIO-1,cantidad_tubetes_producidos_por_formato=120 (texto),cantidad_tubetes_observados_por_formato=3 observados,merma_kg_por_formato=0.500,diametro_interno_mm_por_formato=38.10,diametro_externo_mm_por_formato=42.00,cantidad_de_hojas_por_formato=4,espesor_mm_por_formato=1.800,peso_kg_por_formato=6.750",
  "formatos|2|formato_tipo_de_tubete=FORMATO-FICTICIO-2,cantidad_tubetes_producidos_por_formato=80,merma_kg_por_formato=0.250,diametro_interno_mm_por_formato=30.00,diametro_externo_mm_por_formato=34.00,cantidad_de_hojas_por_formato=3,espesor_mm_por_formato=1.500,peso_kg_por_formato=4.125"];

const article = creds.article_code;
let port = 9400;
const nextPort = () => port++;

if (phase === "enabled") {
  const jefatura = client(), supervision = client();
  await jefatura.login("jefatura"); await supervision.login("supervision");
  const otNumbers = {};
  // ============================================================ 1. Jefatura: OT desde la navegación normal
  await browser("jef", nextPort(), {}, async (b) => {
    await loginApp(b, "jefatura");
    check("J1 Jefatura entra por la navegación normal (login real) y ve Bobinas por defecto", (await b.text()).includes("Bobinas · Programacion") || (await b.text()).includes("Bobinas · Programación"), (await b.text()).slice(0, 300));
    check("J2 el front Rebobinado se abre desde la barra de navegación", await b.clickText("Rebobinado") && await b.waitFor("document.querySelector('[data-rebobinado=\"programacion\"]')", "programación de Rebobinado", 20000).catch(async (e) => { console.error("DOM:", await b.js("document.body.innerHTML.length + ' ' + [...document.querySelectorAll('[data-rebobinado]')].length + ' ' + document.querySelector('[data-rebobinado]').outerHTML.slice(0, 200)")); throw e; }));
    const machines = await b.js("[...document.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === 'COPASA'))?.innerText ?? ''");
    check("J3 la lista de máquinas sale del backend (COPASA y TUBETERA de prueba; NO las máquinas de la lista legacy Beloit/Over/Perichun)", machines.includes("COPASA") && machines.includes("TUBETERA") && !/Beloit|Over|Perichun/i.test(machines), machines.replace(/\s+/g, " "));
    await b.shot("j1-programacion-rebobinado.png");
    for (const machine of ["COPASA", "TUBETERA"]) {
      await b.setField("Máquina", machine);
      const products = await b.js(`[...[...document.querySelectorAll('label')].find((l) => l.innerText.trim() === 'Producto').parentElement.querySelectorAll('option')].map((o) => o.value).filter(Boolean)`);
      check(`J4 ${machine}: el catálogo de productos sale del backend (solo los artículos vinculados a la máquina)`, JSON.stringify(products) === JSON.stringify([article]), JSON.stringify(products));
      await b.setField("PV", `PV-M4A-${machine}`); await b.setField("Producto", article); await b.setField("Cantidad", "10"); await b.setField("Entrega", "2026-11-01");
      check(`J5 ${machine}: crear la OT desde la interfaz`, await b.clickText("Crear OT inicial"));
      await b.waitFor(`document.body.innerText.includes('PV-M4A-${machine}')`, `OT de ${machine} en la lista`, 20000);
    }
    const listed = await jefatura.call("GET", "/api/work-orders");
    for (const wo of listed.json) otNumbers[wo.machine.code] = wo.number;
    check("J6 las OT existen en PostgreSQL (API central) en estado borrador y la interfaz las muestra con su número real", listed.status === 200 && ["COPASA", "TUBETERA"].every((m) => otNumbers[m] && listed.json.find((w) => w.machine.code === m).status === "draft") && (await b.text()).includes(otNumbers.COPASA) && (await b.text()).includes(otNumbers.TUBETERA), JSON.stringify(otNumbers));
    for (const machine of ["COPASA", "TUBETERA"]) {
      check(`J7 ${machine}: publicar la base`, await b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(otNumbers[machine])}) && [...d.querySelectorAll('button')].some((x) => x.innerText.trim() === 'Publicar base')); const btn = card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Publicar base'); if (!btn) return false; btn.click(); return true; })()`));
      await b.waitFor(`(async () => true)() && document.body.innerText.includes(${JSON.stringify(otNumbers[machine])})`, "refresco");
      await sleep(1200);
    }
    const after = await jefatura.call("GET", "/api/work-orders");
    check("J8 ambas OT quedan PUBLICADAS en PostgreSQL y la interfaz muestra el estado verdadero", after.json.every((w) => w.status === "published") && (await b.text()).includes("Publicada"), after.json.map((w) => `${w.number}:${w.status}`).join(","));
    await b.shot("j2-ot-publicadas.png");
    const keys = JSON.parse(await storageDump(b));
    check("J9 las OT del circuito central no están en localStorage (vinto-ot / vinto-asg / vinto-p1-records no las contienen)", !JSON.stringify(keys).includes(otNumbers.COPASA) && !JSON.stringify(keys).includes("PV-M4A"), Object.keys(keys).join(","));
    await nav(b, "Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas · Programacion') || document.body.innerText.includes('Bobinas · Programación')", "Bobinas", 15000);
    await sleep(1000);
    check("J10 Bobinas no cambia: su programación central no lista las OT de Rebobinado y sigue ofreciendo solo MP1 y MP3", (await b.text()).includes("Todavía no hay OT de Bobinas") && await b.js("[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'MP1') && ![...s.options].some((o) => o.value === 'COPASA'))"), "noOT=" + !(await b.text()).includes(otNumbers.COPASA) + " ot=" + otNumbers.COPASA + " ||" + await b.js("[...document.querySelectorAll('select')].map((s) => [...s.options].map((o) => o.value).join('/')).join(' ; ')"));
    check("J11 sin errores de JavaScript ni 4xx/5xx inesperados", b.log.exceptions.length === 0 && b.log.requests.filter((r) => r.status >= 400 && !/api\/auth\/me/.test(r.url)).length === 0, JSON.stringify(b.log.requests.filter((r) => r.status >= 400).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`)));
    await logoutApp(b);
  });

  // ============================================================ 2. Supervisión: activa COPASA (TUBETERA queda sin asignación a propósito)
  const activate = async (b, machine) => {
    await nav(b, "Rebobinado"); await b.waitFor("document.querySelector('[data-rebobinado=\"programacion\"]')", "programación", 20000);
    await sleep(800);
    const ok = await b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(otNumbers[machine])}) && [...d.querySelectorAll('button')].some((x) => x.innerText.trim() === 'Activar')); const btn = card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Activar'); if (!btn || btn.disabled) return false; btn.click(); return true; })()`);
    await sleep(1500); return ok;
  };
  await browser("sup", nextPort(), {}, async (b) => {
    await loginApp(b, "supervision");
    check("K1 Supervisión ve la OT publicada de Rebobinado y activa la asignación de COPASA desde la interfaz", await activate(b, "COPASA"));
    const active = await supervision.call("GET", "/api/assignments/active?machine_code=COPASA");
    check("K2 la asignación existe en PostgreSQL: máquina, turno ficticio, fecha operativa y línea los resolvió el backend", active.status === 200 && active.json.assignment?.machine.code === "COPASA" && active.json.assignment.shift.code.startsWith("FICT_") && active.json.stale === false && active.json.assignment.work_order.number === otNumbers.COPASA, JSON.stringify(active.json?.assignment?.shift));
    await b.shot("k1-asignacion-copasa.png");
    await logoutApp(b);
  });

  // ============================================================ 3. Operación: bloqueos y P1-10 en COPASA
  await browser("op1", nextPort(), {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Rebobinado"); await nav(b, "Ejecución");
    await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]') && document.body.innerText.includes(" + JSON.stringify(otNumbers.COPASA) + ")", "contexto de COPASA", 20000);
    check("O1 Operación ve el contexto REAL de COPASA (OT, turno ficticio, fecha operativa) venido de la API central", (await b.text()).includes(otNumbers.COPASA) && /Día \(ficticio|Noche \(ficticio/.test(await b.text()));
    const formsCopasa = await b.js("[...document.querySelectorAll('[data-form]')].map((e) => e.dataset.form)");
    check("O2 COPASA ofrece P1-10 (más la ficha SINTÉTICA de pruebas, sin pantalla central); P1-29 no se ofrece en COPASA", formsCopasa.includes("VINTO-P1-10") && !formsCopasa.includes("VINTO-P1-29") && formsCopasa.filter((f) => f !== "VINTO-P1-10").every((f) => f === "VINTO-TEST-GRP-1"), JSON.stringify(formsCopasa));
    await b.shot("o1-ejecucion-copasa.png");
    // TUBETERA sin asignación activa: no hay captura
    check("O3 seleccionar TUBETERA", await b.clickText("TUBETERA"));
    await b.waitFor("document.body.innerText.includes('Sin asignación activa')", "banner sin asignación", 20000);
    const formsTub = await b.js("[...document.querySelectorAll('[data-form]')].map((e) => e.dataset.form)");
    check("O4 TUBETERA sin asignación activa: se avisa, solo se ofrece P1-29 y NO se abre la captura al intentarlo", JSON.stringify(formsTub) === JSON.stringify(["VINTO-P1-29"]) && await b.click('[data-form="VINTO-P1-29"]') && (await sleep(800), !(await b.text()).includes("Ficha candidata — No homologada")) && (await b.text()).includes("Sin asignación activa"));
    await b.shot("o2-tubetera-sin-asignacion.png");
    // P1-10 en COPASA
    await b.clickText("COPASA"); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(otNumbers.COPASA)})`, "COPASA");
    await sleep(800);
    check("O5 abrir P1-10 desde la navegación normal", await b.click('[data-form="VINTO-P1-10"]') && await b.waitFor("document.body.innerText.includes('Ficha NO homologada') && document.querySelectorAll('main input').length === 3", "pantalla P1-10", 15000));
    await fillP110(b, { codigo: "EJEMPLO-PRODUCTO-M4A", fardo: "EJEMPLO-000-M4A", peso: "12,5 (texto de ejemplo)", obs: "dato ficticio M4-A" });
    await b.shot("o3-p110-lleno.png");
    check("O6 enviar P1-10", await b.clickText("Enviar registro trazable"));
    await b.waitFor("document.querySelector('[data-section=saved]') && document.body.innerText.includes('Verificada con una consulta posterior')", "P1-10 guardado y verificado", 30000);
    const p110Posts = posts(b); const sent110 = JSON.parse((await cap(b))[0]);
    check("O7 un único POST = 201 y GET por id = 200; el payload solo lleva capture_id, form_code, assignment_id, device_key y los 4 valores", p110Posts.length === 1 && p110Posts[0].status === 201 && b.log.requests.some((r) => r.method === "GET" && /\/api\/captures\/[0-9a-f-]{36}$/.test(r.url) && r.status === 200) && JSON.stringify(Object.keys(sent110).sort()) === JSON.stringify(["assignment_id", "capture_id", "device_key", "form_code", "values"]) && sent110.form_code === "VINTO-P1-10");
    const row110 = q(`SELECT c.status||'|'||c.revision||'|'||m.code||'|'||f.code||'|'||c.created_by FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE c.id = '${sent110.capture_id}'`)[0];
    check("O8 PostgreSQL: capture submitted, revision 1, COPASA, VINTO-P1-10 y el actor de la sesión; valores exactos como texto", row110 === `submitted|1|COPASA|VINTO-P1-10|${users.operacion.user_id}` && q(`SELECT string_agg(f.key||'='||d.value_text, '|' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${sent110.capture_id}'`)[0] === "codigo_numero_de_producto=EJEMPLO-PRODUCTO-M4A|numero_de_fardo=EJEMPLO-000-M4A|peso_fardo=12,5 (texto de ejemplo)|observaciones=dato ficticio M4-A", row110);
    check("O9 auditoría: el alta de la captura quedó registrada con el actor", Number(q(`SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'capture' AND actor_id = '${users.operacion.user_id}'`)[0]) >= 1);
    await b.clickText("Volver"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "regreso a Ejecución", 15000);
    await nav(b, "Seguimiento"); await b.waitFor(`document.querySelector('[data-capture="${sent110.capture_id}"]')`, "historial de P1-10", 20000);
    const historyRow = await b.js(`document.querySelector('[data-capture="${sent110.capture_id}"]').innerText.replace(/\\s+/g, ' ')`);
    check("O10 Seguimiento muestra el registro REAL de P1-10 desde PostgreSQL (parser específico), con su número de fardo y OT", historyRow.includes("EJEMPLO-000-M4A") && historyRow.includes(otNumbers.COPASA) && historyRow.includes("COPASA"), historyRow.slice(0, 160));
    await b.shot("o4-seguimiento-p110.png");
    const dump = await storageDump(b);
    check("O11 ningún dato del recorrido central está en localStorage (solo la clave técnica del dispositivo y los datos legacy ajenos)", !/EJEMPLO|FICTICI|PV-M4A|M4-A/.test(dump) && !dump.includes(sent110.capture_id) && !dump.includes(otNumbers.COPASA), Object.keys(JSON.parse(dump)).join(","));
    check("O12 sin errores de JavaScript ni de CORS", b.log.exceptions.length === 0 && b.log.consoleErrors.filter((e) => !/401/.test(e)).length === 0, JSON.stringify([...b.log.exceptions, ...b.log.consoleErrors]).slice(0, 200));
    await logoutApp(b);
  });

  // ============================================================ 4. Supervisión activa TUBETERA; Operación registra P1-29
  await browser("sup2", nextPort(), {}, async (b) => {
    await loginApp(b, "supervision");
    check("K3 Supervisión activa la asignación de TUBETERA desde la interfaz", await activate(b, "TUBETERA"));
    check("K4 la asignación de TUBETERA existe y está vigente", (await supervision.call("GET", "/api/assignments/active?machine_code=TUBETERA")).json?.assignment?.machine.code === "TUBETERA");
    await logoutApp(b);
  });
  let sent129 = null;
  await browser("op2", nextPort(), {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Rebobinado"); await nav(b, "Ejecución"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "ejecución", 20000);
    await b.clickText("TUBETERA"); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(otNumbers.TUBETERA)})`, "contexto de TUBETERA", 20000);
    await sleep(800);
    check("P1 abrir P1-29 desde la navegación normal (ficha candidata, contexto de la asignación)", await b.click('[data-form="VINTO-P1-29"]') && await b.waitFor("document.body.innerText.includes('Ficha candidata — No homologada') && document.body.innerText.includes('Producción Tubetera')", "pantalla P1-29", 15000) && (await b.text()).includes(otNumbers.TUBETERA));
    await fillP129(b, "LOTE-FICTICIO-M4A");
    await b.shot("p1-p129-lleno.png");
    check("P2 enviar P1-29 con dos rodelas y dos formatos", await b.clickText("Enviar registro trazable"));
    await b.waitFor("document.querySelector('[data-section=saved]') && document.querySelector('[data-readback]')?.dataset.readback === 'ok'", "P1-29 guardado y verificado", 30000);
    sent129 = JSON.parse((await cap(b))[0]);
    check("P3 un único POST = 201 y GET por id = 200; payload con values._groups y sin ids de fila ni campos automáticos", posts(b).length === 1 && posts(b)[0].status === 201 && Array.isArray(sent129.values._groups.rodelas) && sent129.values._groups.rodelas.length === 2 && sent129.values._groups.formatos.length === 2 && !JSON.stringify(sent129).match(/rowKey|row_number|group_row|"operador"|"turno"|"visto_bueno_responsable"/));
    check("P4 PostgreSQL: dos rodelas y dos formatos en orden con valores exactos (decimales con su escala, cantidades como texto)", JSON.stringify(dbRows(sent129.capture_id)) === JSON.stringify(P129_EXPECTED_ROWS), dbRows(sent129.capture_id).length + " filas");
    check("P5 PostgreSQL: capture TUBETERA / VINTO-P1-29 submitted, revision 1, 27 detalles (6 simples + 21 de fila) y auditoría de las filas", q(`SELECT c.status||'|'||c.revision||'|'||m.code FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id WHERE c.id = '${sent129.capture_id}'`)[0] === "submitted|1|TUBETERA" && q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent129.capture_id}'`)[0] === "27" && Number(q(`SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'capture_group_row' AND actor_id = '${users.operacion.user_id}'`)[0]) >= 4);
    await b.clickText("Volver"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "regreso", 15000);
    await nav(b, "Seguimiento"); await b.waitFor(`document.querySelector('[data-capture="${sent129.capture_id}"]')`, "historial de P1-29", 20000);
    const row = await b.js(`document.querySelector('[data-capture="${sent129.capture_id}"]').innerText.replace(/\\s+/g, ' ')`);
    check("P6 Seguimiento muestra el registro REAL de P1-29 (parser específico): lote, fecha de producción, 2 rodelas y 2 formatos", row.includes("LOTE-FICTICIO-M4A") && row.includes("2026-01-15") && /\b2\b.*\b2\b/.test(row) && row.includes("TUBETERA"), row.slice(0, 200));
    check("P7 el historial de P1-10 sigue mostrando solo P1-10 y el de P1-29 solo P1-29 (sin mezclar formularios)", !(await b.js(`document.querySelector('[data-history^="Registro de fardos"]')?.innerText ?? ''`)).includes("LOTE-FICTICIO-M4A") && !(await b.js(`document.querySelector('[data-history^="Producción Tubetera"]')?.innerText ?? ''`)).includes("EJEMPLO-000-M4A"));
    await b.shot("p2-seguimiento-p129.png");
    const dump = await storageDump(b);
    check("P8 ningún dato del recorrido de P1-29 está en localStorage", !/LOTE-FICTICIO-M4A|RODELA-FICTICIA|FORMATO-FICTICIO|MRP-FICTICIO-M4A/.test(dump) && !dump.includes(sent129.capture_id), Object.keys(JSON.parse(dump)).join(",") + " :: " + "");
    await logoutApp(b);
  });

  // ============================================================ 5. reintentos: sin duplicados (respuesta perdida / petición perdida)
  const faultRun = async (fault, form, label) => {
    let out = {};
    await browser(label, nextPort(), { fault }, async (b) => {
      await loginApp(b, "operacion");
      await nav(b, "Rebobinado"); await nav(b, "Ejecución"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "ejecución", 20000);
      if (form === "p129") { await b.clickText("TUBETERA"); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(otNumbers.TUBETERA)})`, "TUBETERA", 20000); await sleep(800); await b.click('[data-form="VINTO-P1-29"]'); await b.waitFor("document.querySelectorAll('main input').length > 5", "P1-29"); await fillP129(b, `LOTE-${label}`); }
      else { await sleep(800); await b.click('[data-form="VINTO-P1-10"]'); await b.waitFor("document.querySelectorAll('main input').length === 3", "P1-10"); await fillP110(b, { codigo: `PROD-${label}`, fardo: `FARDO-${label}`, peso: "1,5 (texto)", obs: "" }); }
      await b.clickText("Enviar registro trazable");
      if (fault === "lose-request") {
        await b.waitFor("document.body.innerText.includes('El registro no se guardó')", "no guardado", 30000);
        const locked = await b.js("[...document.querySelectorAll('main input, main textarea')].every((e) => e.disabled) && [...document.querySelectorAll('main button')].filter((x) => /Agregar|Eliminar/.test(x.innerText)).every((x) => x.disabled)");
        check(`${label} con el intento pendiente los campos y las filas quedan bloqueados`, locked);
        await b.clickText("Reintentar envío");
      }
      await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación", 30000);
      out = { sent: (await cap(b)).map((x) => JSON.parse(x)), requests: [...b.log.requests] };
      await b.clickText("Volver"); await sleep(500);
      await logoutApp(b);
    });
    return out;
  };
  const lr = await faultRun("lose-response", "p110", "R1");
  check("R1 P1-10, respuesta perdida tras guardar: la reconciliación por GET encuentra la captura (1 POST, 1 fila, sin duplicar)", lr.sent.length === 1 && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${lr.sent[0].capture_id}'`)[0] === "1" && lr.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${lr.sent[0].capture_id}`) && r.status === 200));
  const lq = await faultRun("lose-request", "p129", "R2");
  check("R2 P1-29, petición perdida: GET 404 -> reintento con el MISMO capture_id y las MISMAS filas -> una sola captura con sus 4 filas", lq.sent.length === 2 && JSON.stringify(lq.sent[0]) === JSON.stringify(lq.sent[1]) && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${lq.sent[0].capture_id}'`)[0] === "1" && dbRows(lq.sent[0].capture_id).length === 4 && lq.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${lq.sent[0].capture_id}`) && r.status === 404));

  // ============================================================ 6. asignación vencida, formulario no vinculado, alcance
  qw("SET session_replication_role = replica; UPDATE vinto_txn.assignment SET operating_date = operating_date - 1 WHERE status = 'active' AND machine_id = (SELECT id FROM vinto_master.machine WHERE code = 'COPASA')");
  const stalePosts = (await (async () => { const op = client(); await op.login("operacion"); const active = await op.call("GET", "/api/assignments/active?machine_code=COPASA"); const r = await op.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-10", assignment_id: active.json.assignment.id, device_key: crypto.randomUUID(), values: { codigo_numero_de_producto: "A", numero_de_fardo: "B", peso_fardo: "C" } }); await op.call("POST", "/api/auth/logout"); return { active, r }; })());
  check("X1 asignación VENCIDA: el backend la marca stale y el POST se rechaza con 409 ASSIGNMENT_STALE (nada se escribe)", stalePosts.active.json.stale === true && stalePosts.r.status === 409 && stalePosts.r.json.code === "ASSIGNMENT_STALE");
  await browser("stale", nextPort(), {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Rebobinado"); await nav(b, "Ejecución"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "ejecución", 20000);
    await b.waitFor("document.body.innerText.includes('otro turno o fecha operativa')", "aviso de asignación vencida", 20000);
    const opened = await b.click('[data-form="VINTO-P1-10"]'); await sleep(800);
    check("X2 la interfaz muestra la asignación vencida y NO abre la captura", opened && !(await b.text()).includes("Ficha NO homologada") && posts(b).length === 0);
    await b.shot("x1-asignacion-vencida.png");
    await logoutApp(b);
  });
  qw("SET session_replication_role = replica; UPDATE vinto_txn.assignment SET operating_date = operating_date + 1 WHERE status = 'active' AND machine_id = (SELECT id FROM vinto_master.machine WHERE code = 'COPASA')");
  const opx = client(); await opx.login("operacion");
  const tubAssign = (await opx.call("GET", "/api/assignments/active?machine_code=TUBETERA")).json.assignment, copAssign = (await opx.call("GET", "/api/assignments/active?machine_code=COPASA")).json.assignment;
  const p110body = { codigo_numero_de_producto: "A", numero_de_fardo: "B", peso_fardo: "C" };
  const wrong1 = await opx.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-10", assignment_id: tubAssign.id, device_key: crypto.randomUUID(), values: p110body });
  const wrong2 = await opx.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-29", assignment_id: copAssign.id, device_key: crypto.randomUUID(), values: structuredClone(sent129.values) });
  check("X3 un formulario NO vinculado a la máquina no se puede usar: P1-10 en TUBETERA y P1-29 en COPASA = 409 FORM_NOT_AVAILABLE", wrong1.status === 409 && wrong1.json.code === "FORM_NOT_AVAILABLE" && wrong2.status === 409 && wrong2.json.code === "FORM_NOT_AVAILABLE");
  await opx.call("POST", "/api/auth/logout");
  await browser("scope", nextPort(), {}, async (b) => {
    await loginApp(b, "operacion_solo_bobinas");
    await nav(b, "Rebobinado"); await b.waitFor("!!document.querySelector('[data-rebobinado]')", "panel de Rebobinado", 20000);
    let disabledEverywhere = true;
    for (const m of ["Programación", "Ejecución", "Seguimiento"]) { await nav(b, m); await sleep(900); disabledEverywhere = disabledEverywhere && await b.js("!!document.querySelector('[data-rebobinado=\"disabled\"]')") && !(await b.js("document.querySelectorAll('[data-form]').length")); }
    check("X4 sin concesión de Rebobinado el backend no lo expone: la navegación lo muestra NO habilitado en los tres módulos, sin formularios ni datos", disabledEverywhere && (await b.text()).includes("Rebobinado no está habilitado"), (await b.text()).replace(/\s+/g, " ").slice(-400));
    await b.shot("x2-sin-concesion.png");
    await logoutApp(b);
  });

  // ============================================================ 7. móvil
  await browser("mob", nextPort(), { mobile: true }, async (b) => {
    await loginApp(b, "operacion");
    await b.clickText("Rebobinado"); await b.clickText("Ejecucion").then(async (ok) => { if (!ok) await b.clickText("ejecucion"); });
    await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "ejecución móvil", 20000); await sleep(900);
    const o1 = await b.overflow(); await b.shot("m1-ejecucion-movil.png");
    await b.clickText("TUBETERA"); await sleep(1500);
    await b.click('[data-form="VINTO-P1-29"]'); await b.waitFor("document.body.innerText.includes('Ficha candidata — No homologada')", "P1-29 móvil", 15000);
    const o2 = await b.overflow(); await b.shot("m2-p129-movil.png");
    await b.clickText("Volver"); await b.waitFor("document.querySelector('[data-rebobinado=\"ejecucion\"]')", "regreso", 15000);
    await b.clickText("Seguimiento").then(async (ok) => { if (!ok) await b.clickText("seguimiento"); }); await b.waitFor("document.querySelector('[data-rebobinado=\"seguimiento\"]')", "seguimiento móvil", 20000); await sleep(1200);
    const o3 = await b.overflow(); await b.shot("m3-seguimiento-movil.png");
    check("M1 versión móvil (390 px): ejecución, P1-29 y seguimiento sin desborde horizontal de la página", o1 <= 0 && o2 <= 0 && o3 <= 0, `${o1}/${o2}/${o3}`);
    await logoutApp(b).catch(() => {});
  });
  await jefatura.call("POST", "/api/auth/logout"); await supervision.call("POST", "/api/auth/logout");
  const sessions = q(`SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()`)[0];
  check("Z1 sin sesiones activas de prueba tras los logouts", sessions === "0", `activas ${sessions} :: ` + q(`SELECT user_id||'='||count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now() GROUP BY user_id`).map((row) => Object.entries(users).reduce((r, [name, u]) => r.replace(u.user_id, name), row)).join(","));
  const totals = q(`SELECT f.code||'='||count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id GROUP BY f.code ORDER BY f.code`).join(",");
  check("Z2 totales en la base efímera: P1-10 = 2 (O y R1) y P1-29 = 2 (P y R2), sin duplicados", totals === "VINTO-P1-10=2,VINTO-P1-29=2", totals);
} else {
  // ============================================================ FASE disabled: configuración REAL (Rebobinado concedido pero NO operativo)
  const jef = client(); await jef.login("jefatura");
  const avail = await jef.call("GET", "/api/production/machines");
  check("D1 con la configuración real el backend NO expone Rebobinado aunque el usuario tenga la concesión (solo BOBINAS)", avail.status === 200 && JSON.stringify(avail.json.sectors.map((s) => s.code)) === JSON.stringify(["BOBINAS"]), JSON.stringify(avail.json.sectors?.map((s) => s.code)));
  const op = client(); await op.login("operacion");
  const apiBlocks = await op.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-10", assignment_id: crypto.randomUUID(), device_key: crypto.randomUUID(), values: {} });
  check("D2 con la política real P1-10 no se acepta (422 UNSUPPORTED_FORM) y las máquinas de Rebobinado se rechazan por alcance (422)", apiBlocks.status === 422 && apiBlocks.json.code === "UNSUPPORTED_FORM" && (await op.call("GET", "/api/assignments/active?machine_code=COPASA")).status === 422 && (await jef.call("POST", "/api/work-orders", { machine_code: "COPASA", lines: [{ pv_reference: "PV", article_code: article, quantity: 1, due_date: "2026-11-01" }] })).status === 422);
  await op.call("POST", "/api/auth/logout"); await jef.call("POST", "/api/auth/logout");
  for (const who of ["jefatura", "operacion"]) {
    await browser(`dis-${who}`, nextPort(), {}, async (b) => {
      await loginApp(b, who);
      await b.clickText("Rebobinado"); await b.waitFor("!!document.querySelector('[data-rebobinado]')", "panel de Rebobinado", 20000);
      const seen = [];
      for (const m of ["Programación", "Ejecución", "Seguimiento"]) {
        await nav(b, m); await sleep(1000);
        const t = await b.text();
        seen.push(await b.js("!!document.querySelector('[data-rebobinado=\"disabled\"]')") && t.includes("Rebobinado no está habilitado") && !(await b.js("document.querySelectorAll('[data-form]').length")) && !/Crear OT inicial|Beloit|Perichun|Tubetera|Copasa|Registro de control/i.test(t.replace(/Rebobinado no está habilitado[\s\S]*$/, "")) );
      }
      check(`D3 ${who}: con Rebobinado no operativo la navegación lo muestra NO habilitado en Programación, Ejecución y Seguimiento, sin formularios, sin crear OT y sin datos demo ni legacy como respaldo`, seen.every(Boolean), JSON.stringify(seen));
      if (who === "operacion") await b.shot("d1-rebobinado-no-habilitado.png");
      check(`D4 ${who}: ningún POST a /api/captures, /api/work-orders ni /api/assignments desde la navegación bloqueada`, b.log.requests.filter((r) => r.method === "POST" && /\/api\/(captures|work-orders|assignments)/.test(r.url)).length === 0);
      const dump = JSON.parse(await storageDump(b));
      check(`D5 ${who}: el almacenamiento del navegador no contiene capturas ni OT centrales de Rebobinado (no hay respaldo silencioso)`, !JSON.stringify(dump).includes("VINTO-P1-10") && !JSON.stringify(dump).includes("VINTO-P1-29") && !/"central"/.test(JSON.stringify(dump)), Object.keys(dump).join(","));
      if (who === "jefatura") {
        await b.clickText("Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas ·')", "Bobinas", 15000); await nav(b, "Programación"); await sleep(1500);
        check("D6 Bobinas sigue operativo con la configuración real: su programación central (MP1 / MP3) se muestra", await b.js("[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'MP1'))"));
      }
      await logoutApp(b);
    });
  }
  check("D7 con Rebobinado deshabilitado no se escribió ninguna captura ni OT en la base efímera", q("SELECT (SELECT count(*) FROM vinto_txn.capture)||'|'||(SELECT count(*) FROM vinto_txn.work_order)")[0] === "0|0");
  check("D8 sin sesiones activas de prueba tras los logouts", q("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0] === "0");
}
const devAfter = DEV_READ ? psql("vinto", DEV_SQL)[0] : "omitido";
if (DEV_READ) check("Z9 DEV intacto: capturas | filas de grupo | auditoría | sesiones | auth_event | concesiones | OT idénticos antes y después (solo SELECT)", devBefore === devAfter, `${devBefore} -> ${devAfter}`);
writeFileSync(join(outDir, `resultados-m4a-${phase}.json`), JSON.stringify({ phase, database, devBefore, devAfter, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
