// node scripts/e2e/m6b-e2e.mjs <creds.json> <evidence-dir> <enabled|disabled>
// M6-B · circuito CENTRAL CANDIDATO de P1-12 (UN pallet por captura) en Conversión desde la NAVEGACIÓN NORMAL de VINTO (la aplicación real en `/`, sin harness): Jefatura crea y publica la OT -> Supervisión activa
// la asignación -> Operación abre P1-12 -> PostgreSQL efímero -> Seguimiento; con P1-16 funcionando en el mismo entorno. Fase `enabled`: backend de prueba con Conversión + P1-12 habilitados SOLO en su proceso
// (backend/tests/e2e_m6a_server.py con E2E_P112=on). Fase `disabled`: el mismo backend con la configuración REAL. TODOS los datos son FICTICIOS; el contrato de P1-12 y los turnos son HIPÓTESIS DE PRUEBA.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787), si la base no termina en `_test`, si no es `current_database()` o si el navegador llama al puerto 8000. NO lee ni escribe DEV: las
// únicas escrituras son manipulaciones explícitas de la base EFÍMERA (asignación vencida). Un registro LEGACY sembrado en el navegador comprueba que localStorage no se borra ni se convierte.
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
const LEGACY_SEED = `(() => { try { if (localStorage.getItem('__m6a_seeded')) return; localStorage.setItem('__m6a_seeded', '1'); localStorage.setItem('vinto-p1-records', JSON.stringify([{ id: 'LEGACY-M6A-MARKER', formId: 'form_16_registro_de_control_de_merma', formVersion: 2, formName: 'Registro de control de merma', area: 'production', sector: 'conversion', machine: 'Gambini', userId: 'usuario-demo', deviceId: 'equipo-Gambini', capturedAt: '2026-01-01T00:00:00.000Z', operatingDate: '2026-01-01', shiftId: 'Mañana', syncStatus: 'synced', workflowStatus: 'submitted', values: { tipo_merma: 'Cartón', origen_merma: 'Cola', peso_merma_kg: 99, orden_trabajo: 'OT-LEGACY-M6A' } }])); } catch (e) { /* sin almacenamiento */ } })();`;
async function browser(label, port, opts, body) {
  const { mobile = false, fault = "none", seedLegacy = false } = opts;
  const width = mobile ? 390 : 1366, height = mobile ? 844 : 900;
  const profile = mkdtempSync(join(tmpdir(), `m6a-${label}-`));
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
    if (seedLegacy) await send("Page.addScriptToEvaluateOnNewDocument", { source: LEGACY_SEED }); // registro legacy de Conversión que NO debe borrarse ni convertirse
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

const article = creds.article_code, MACHINE = creds.conversion_machine, MACHINE_NO_FORM = creds.conversion_machine_no_form;
let port = 9600;
const nextPort = () => port++;
const MARKER = "LEGACY-M6A-MARKER";
const legacyKept = async (b) => { const raw = JSON.parse(await storageDump(b))["vinto-p1-records"]; return !!raw && JSON.parse(raw).some((r) => r.id === MARKER); };
const fillP112 = async (b, v) => { await b.setField("Cantidad de jabas", v.jabas); await b.setField("Hora inicio del pallet", v.ini); await b.setField("Hora fin del pallet", v.fin); };
const conv = (b, module) => b.waitFor(`document.querySelector('[data-conversion="${module}"]')`, `Conversión · ${module}`, 20000);

if (phase === "enabled") {
  const jefatura = client(), supervision = client();
  await jefatura.login("jefatura"); await supervision.login("supervision");
  const otNumbers = {};
  // ============================================================ 1. Jefatura: OT de Conversión desde la navegación normal
  await browser("jef", nextPort(), { seedLegacy: true }, async (b) => {
    await loginApp(b, "jefatura");
    check("J1 Jefatura entra por la navegación normal (login real) y ve Bobinas por defecto", (await b.text()).includes("Bobinas · Programacion") || (await b.text()).includes("Bobinas · Programación"));
    check("J2 el front Conversión se abre desde la barra de navegación y es el shell CENTRAL (no la pantalla legacy)", await b.clickText("Conversión") && await conv(b, "programacion").then(() => true));
    const machines = await b.js("[...document.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === " + JSON.stringify(MACHINE) + "))?.innerText ?? ''");
    check("J3 la lista de máquinas sale del backend (solo las de prueba GAMBINI y WALLY; NO la lista legacy Sincro / OMET / 8.2 / Pañuelera)", machines.includes(MACHINE) && machines.includes(MACHINE_NO_FORM) && !/Sincro|OMET|Pañuelera|Serv 4|8002/i.test(machines), machines.replace(/\s+/g, " "));
    await b.shot("j1-programacion-conversion.png");
    for (const machine of [MACHINE, MACHINE_NO_FORM]) {
      await b.setField("Máquina", machine);
      const products = await b.js(`[...[...document.querySelectorAll('label')].find((l) => l.innerText.trim() === 'Producto').parentElement.querySelectorAll('option')].map((o) => o.value).filter(Boolean)`);
      check(`J4 ${machine}: el catálogo de productos sale del backend (solo los artículos vinculados a la máquina)`, JSON.stringify(products) === JSON.stringify([article]), JSON.stringify(products));
      await b.setField("PV", `PV-M6A-${machine}`); await b.setField("Producto", article); await b.setField("Cantidad", "10"); await b.setField("Entrega", "2026-11-01");
      check(`J5 ${machine}: crear la OT desde la interfaz`, await b.clickText("Crear OT inicial"));
      await b.waitFor(`document.body.innerText.includes('PV-M6A-${machine}')`, `OT de ${machine} en la lista`, 20000);
    }
    const listed = await jefatura.call("GET", "/api/work-orders");
    for (const wo of listed.json) otNumbers[wo.machine.code] = wo.number;
    check("J6 las OT existen en PostgreSQL (API central) en estado borrador y la interfaz las muestra con su número real", listed.status === 200 && [MACHINE, MACHINE_NO_FORM].every((m) => otNumbers[m] && listed.json.find((w) => w.machine.code === m).status === "draft") && (await b.text()).includes(otNumbers[MACHINE]), JSON.stringify(otNumbers));
    for (const machine of [MACHINE, MACHINE_NO_FORM]) {
      check(`J7 ${machine}: publicar la base`, await b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(otNumbers[machine])}) && [...d.querySelectorAll('button')].some((x) => x.innerText.trim() === 'Publicar base')); const btn = card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Publicar base'); if (!btn) return false; btn.click(); return true; })()`));
      await sleep(1500);
    }
    const after = await jefatura.call("GET", "/api/work-orders");
    check("J8 ambas OT quedan PUBLICADAS en PostgreSQL y la interfaz muestra el estado verdadero", after.json.every((w) => w.status === "published") && (await b.text()).includes("Publicada"), after.json.map((w) => `${w.number}:${w.status}`).join(","));
    await b.shot("j2-ot-publicadas.png");
    const dump = await storageDump(b);
    check("J9 las OT del circuito central no están en localStorage", !dump.includes(otNumbers[MACHINE]) && !dump.includes("PV-M6A"), Object.keys(JSON.parse(dump)).join(","));
    check("J10 el registro legacy sembrado en el navegador se CONSERVA intacto y la pantalla central de Conversión no lo muestra ni lo convierte", await legacyKept(b) && !(await b.text()).includes(MARKER) && !(await b.text()).includes("OT-LEGACY-M6A"));
    await nav(b, "Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas · Programacion') || document.body.innerText.includes('Bobinas · Programación')", "Bobinas", 15000); await sleep(1000);
    check("J11 Bobinas no cambia: su programación central no lista las OT de Conversión y sigue ofreciendo solo MP1 y MP3", (await b.text()).includes("Todavía no hay OT de Bobinas") && await b.js("[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'MP1') && ![...s.options].some((o) => o.value === " + JSON.stringify(MACHINE) + "))"), (await b.text()).slice(0, 200));
    await nav(b, "Rebobinado"); await b.waitFor("document.querySelector('[data-rebobinado=\"programacion\"]')", "Rebobinado", 20000);
    check("J12 Rebobinado sigue siendo su shell (data-rebobinado), con sus máquinas COPASA y TUBETERA y sin las de Conversión", await b.js("[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'COPASA') && [...s.options].some((o) => o.value === 'TUBETERA') && ![...s.options].some((o) => o.value === " + JSON.stringify(MACHINE) + "))"));
    check("J13 sin errores de JavaScript ni 4xx/5xx inesperados", b.log.exceptions.length === 0 && b.log.requests.filter((r) => r.status >= 400 && !/api\/auth\/me/.test(r.url)).length === 0, JSON.stringify(b.log.requests.filter((r) => r.status >= 400).map((r) => `${r.method} ${new URL(r.url).pathname} ${r.status}`)));
    await logoutApp(b);
  });

  // ============================================================ 2. Supervisión: activa GAMBINI y WALLY
  const activate = async (b, machine) => {
    await nav(b, "Conversión"); await conv(b, "programacion"); await sleep(800);
    const ok = await b.js(`(() => { const card = [...document.querySelectorAll('div.rounded-2xl.border')].find((d) => d.innerText.includes(${JSON.stringify(otNumbers[machine])}) && [...d.querySelectorAll('button')].some((x) => x.innerText.trim() === 'Activar')); const btn = card && [...card.querySelectorAll('button')].find((x) => x.innerText.trim() === 'Activar'); if (!btn || btn.disabled) return false; btn.click(); return true; })()`);
    await sleep(1500); return ok;
  };
  await browser("sup", nextPort(), {}, async (b) => {
    await loginApp(b, "supervision");
    check("K1 Supervisión ve la OT publicada de Conversión y activa la asignación de GAMBINI desde la interfaz", await activate(b, MACHINE));
    check("K2 Supervisión activa también la asignación de WALLY (máquina SIN formulario vinculado)", await activate(b, MACHINE_NO_FORM));
    const active = await supervision.call("GET", `/api/assignments/active?machine_code=${MACHINE}`);
    check("K3 la asignación existe en PostgreSQL: máquina, turno de hipótesis (FICT_CONV_*), fecha operativa y línea los resolvió el backend", active.status === 200 && active.json.assignment?.machine.code === MACHINE && /^FICT_CONV_(MANANA|TARDE|NOCHE)$/.test(active.json.assignment.shift.code) && active.json.stale === false && active.json.assignment.work_order.number === otNumbers[MACHINE], JSON.stringify(active.json?.assignment?.shift));
    await b.shot("k1-asignacion-gambini.png");
    await logoutApp(b);
  });

  // ============================================================ 3. Operación: P1-12 (un pallet) y P1-16 en GAMBINI
  let sent = null, sent116 = null;
  await browser("op1", nextPort(), { seedLegacy: true }, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Conversión"); await nav(b, "Ejecución");
    await b.waitFor("document.querySelector('[data-conversion=\"ejecucion\"]') && document.body.innerText.includes(" + JSON.stringify(otNumbers[MACHINE]) + ")", "contexto de GAMBINI", 20000);
    const text0 = await b.text();
    check("O1 Operación ve el contexto REAL de GAMBINI (OT, turno de hipótesis, fecha operativa) venido de la API central", text0.includes(otNumbers[MACHINE]) && text0.includes("(ficticio, prueba)"));
    const forms = await b.js("[...document.querySelectorAll('[data-form]')].map((e) => e.dataset.form)");
    check("O2 GAMBINI ofrece exactamente P1-12 y P1-16 (fichas candidatas); el formulario vinculado pero SIN publicar NO se ofrece", JSON.stringify(forms) === JSON.stringify(["VINTO-P1-12", "VINTO-P1-16"]) && !text0.includes(creds.draft_form_code) && text0.includes("Ficha candidata"), JSON.stringify(forms));
    await b.shot("o1-ejecucion-gambini.png");
    check("O3 WALLY (con asignación pero sin formulario vinculado): no se ofrece ningún formulario", await b.clickText(MACHINE_NO_FORM) && await b.waitFor("document.body.innerText.includes('El backend no publica formularios centrales para esta máquina')", "WALLY sin formularios", 15000) && (await b.js("document.querySelectorAll('[data-form]').length")) === 0);
    await b.clickText(MACHINE); await b.waitFor(`document.body.innerText.includes(${JSON.stringify(otNumbers[MACHINE])})`, "GAMBINI"); await sleep(800);
    check("O4 abrir P1-12 desde la navegación normal: ficha NO homologada, un pallet por captura, número oficial de pallet PENDIENTE y tres campos", await b.click('[data-form="VINTO-P1-12"]') && await b.waitFor("document.body.innerText.includes('Ficha NO homologada') && document.querySelectorAll('main input').length === 3 && document.querySelectorAll('main input[type=time]').length === 2", "pantalla P1-12", 15000) && (await b.text()).includes(otNumbers[MACHINE]) && (await b.text()).includes("Número oficial de pallet") && (await b.text()).includes("pendiente de definición") && !/PAL-\d{8}/.test(await b.text()));
    check("O5 un envío vacío se rechaza en el cliente sin POST", await b.clickText("Enviar registro trazable") && await b.waitFor("document.body.innerText.includes('Cantidad de jabas: es obligatorio.')", "validación", 8000) && posts(b).length === 0);
    await b.setField("Cantidad de jabas", "4,5"); await b.setField("Hora inicio del pallet", "08:15"); await b.setField("Hora fin del pallet", "09:05");
    check("O6 una cantidad no entera se rechaza en el cliente sin POST", await b.clickText("Enviar registro trazable") && await b.waitFor("document.body.innerText.includes('debe ser un número entero')", "jabas inválidas", 8000) && posts(b).length === 0);
    await b.setField("Cantidad de jabas", "40");
    await b.shot("o3-p112-lleno.png");
    check("O7 enviar P1-12", await b.clickText("Enviar registro trazable"));
    await b.waitFor("document.querySelector('[data-section=saved]') && document.body.innerText.includes('Verificada con una consulta posterior')", "P1-12 guardado y verificado", 30000);
    sent = JSON.parse((await cap(b))[0]);
    check("O8 un único POST = 201 y GET por id = 200; el payload solo lleva capture_id, form_code, assignment_id, device_key y los 3 valores (jabas como número)", posts(b).length === 1 && posts(b)[0].status === 201 && b.log.requests.some((r) => r.method === "GET" && /\/api\/captures\/[0-9a-f-]{36}$/.test(r.url) && r.status === 200) && JSON.stringify(Object.keys(sent).sort()) === JSON.stringify(["assignment_id", "capture_id", "device_key", "form_code", "values"]) && sent.form_code === "VINTO-P1-12" && JSON.stringify(sent.values) === JSON.stringify({ cantidad_jabas: 40, hora_inicio: "08:15", hora_fin: "09:05" }), JSON.stringify(sent.values));
    check("O9 tras guardar se muestra el identificador técnico de la captura y el número oficial de pallet sigue pendiente (sin código PAL- ni pesos)", (await b.text()).includes(sent.capture_id) && (await b.text()).includes("pendiente de definición") && !/PAL-\d{8}|Peso total calculado/.test(await b.text()));
    const row = q(`SELECT c.status||'|'||c.revision||'|'||m.code||'|'||f.code||'|'||c.created_by||'|'||c.operating_date||'|'||sh.code||'|'||ar.code||'|'||wo.number FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id JOIN vinto_config.shift_schedule sc ON sc.id = c.shift_schedule_id JOIN vinto_config.shift sh ON sh.id = sc.shift_id JOIN vinto_txn.assignment a ON a.id = c.assignment_id JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id JOIN vinto_master.article_version av ON av.id = l.article_version_id JOIN vinto_master.article ar ON ar.id = av.article_id WHERE c.id = '${sent.capture_id}'`)[0];
    check("O10 PostgreSQL: capture submitted, revisión 1, GAMBINI, VINTO-P1-12, el actor de la sesión, fecha operativa, turno de hipótesis, artículo y OT los derivó el backend", new RegExp(`^submitted\\|1\\|${MACHINE}\\|VINTO-P1-12\\|${users.operacion.user_id}\\|\\d{4}-\\d{2}-\\d{2}\\|FICT_CONV_(MANANA|TARDE|NOCHE)\\|${article}\\|${otNumbers[MACHINE]}$`).test(row), row);
    check("O11 PostgreSQL: tres detalles tipados (integer, time, time) y NINGÚN peso ni número de pallet guardado", q(`SELECT string_agg(f.key||'='||d.value_type||':'||coalesce(d.value_integer::text, d.value_time::text, d.value_text), '|' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${sent.capture_id}'`)[0] === "cantidad_jabas=integer:40|hora_inicio=time:08:15:00|hora_fin=time:09:05:00");
    check("O12 auditoría: el alta de la captura quedó registrada con el actor", Number(q(`SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'capture' AND actor_id = '${users.operacion.user_id}'`)[0]) >= 1);
    // P1-16 sigue funcionando en la misma sesión (sin confundirse con P1-12)
    await b.clickText("Volver"); await conv(b, "ejecucion"); await sleep(600);
    check("O13 P1-16 sigue funcionando en Conversión: se abre con sus propios campos (2 listas + 1 campo)", await b.click('[data-form="VINTO-P1-16"]') && await b.waitFor("document.querySelectorAll('main select').length === 2 && document.querySelectorAll('main input').length === 1", "pantalla P1-16", 15000));
    await b.setField("Tipo de merma", "carton"); await b.setField("Origen de la merma", "cola"); await b.setField("Peso real", "7,25");
    await b.clickText("Enviar registro trazable");
    await b.waitFor("document.querySelector('[data-section=saved]') && document.body.innerText.includes('Verificada con una consulta posterior')", "P1-16 guardado", 30000);
    sent116 = JSON.parse((await cap(b))[1]);
    check("O14 P1-16 se guardó como VINTO-P1-16 con sus tres valores y su propia fila en PostgreSQL", sent116.form_code === "VINTO-P1-16" && q(`SELECT f.code FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE c.id = '${sent116.capture_id}'`)[0] === "VINTO-P1-16" && q(`SELECT d.value_decimal::text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${sent116.capture_id}' AND f.key = 'peso_merma_kg'`)[0] === "7.25");
    await b.clickText("Volver"); await conv(b, "ejecucion");
    await nav(b, "Seguimiento"); await b.waitFor(`document.querySelector('[data-capture="${sent.capture_id}"]') && document.querySelector('[data-capture="${sent116.capture_id}"]')`, "historiales de P1-12 y P1-16", 20000);
    const historyRow = await b.js(`document.querySelector('[data-capture="${sent.capture_id}"]').innerText.replace(/\\s+/g, ' ')`);
    check("O15 Seguimiento muestra el pallet REAL desde PostgreSQL (parser específico): OT, línea/PV, máquina, turno, jabas y horas sin segundos", historyRow.includes(otNumbers[MACHINE]) && historyRow.includes("PV-M6A") && historyRow.includes(MACHINE) && historyRow.includes("(ficticio, prueba)") && /\b40\b/.test(historyRow) && historyRow.includes("08:15") && historyRow.includes("09:05") && !historyRow.includes("08:15:00"), historyRow.slice(0, 200));
    const histories = await b.js("[...document.querySelectorAll('[data-history]')].map((e) => [e.dataset.history, e.innerText.replace(/\\s+/g, ' ')])");
    const h112 = histories.find(([t]) => t.startsWith("Producción por pallet")), h116 = histories.find(([t]) => t.startsWith("Control de merma"));
    check("O16 los historiales de P1-12 y P1-16 no se mezclan: cada uno muestra solo sus capturas", !!h112 && !!h116 && h112[1].includes("08:15") && !h112[1].includes("Cartón") && h116[1].includes("Cartón") && !h116[1].includes("08:15") && histories.length === 2, JSON.stringify(histories.map(([t]) => t)));
    const orders = await b.js("document.querySelector('[data-conversion=\"seguimiento\"]').innerText");
    check("O17 Seguimiento lista las OT de Conversión y no las de Bobinas ni Rebobinado", orders.includes(otNumbers[MACHINE]) && !/COPASA|TUBETERA|MP1|MP3/.test(orders));
    await b.shot("o4-seguimiento-p112.png");
    const dump = await storageDump(b);
    check("O18 ningún dato central está en localStorage y el registro legacy sembrado se conserva sin mostrarse ni convertirse", !dump.includes(sent.capture_id) && !dump.includes(otNumbers[MACHINE]) && await legacyKept(b) && !(await b.text()).includes(MARKER), Object.keys(JSON.parse(dump)).join(","));
    check("O19 sin errores de JavaScript ni de CORS", b.log.exceptions.length === 0 && b.log.consoleErrors.filter((e) => !/401/.test(e)).length === 0, JSON.stringify([...b.log.exceptions, ...b.log.consoleErrors]).slice(0, 200));
    await logoutApp(b);
  });

  // ============================================================ 4. reintentos: sin duplicados (respuesta perdida / petición perdida)
  const faultRun = async (fault, label, jabas) => {
    let out = {};
    await browser(label, nextPort(), { fault }, async (b) => {
      await loginApp(b, "operacion");
      await nav(b, "Conversión"); await nav(b, "Ejecución"); await conv(b, "ejecucion"); await sleep(800);
      await b.click('[data-form="VINTO-P1-12"]'); await b.waitFor("document.querySelectorAll('main input').length === 3", "P1-12");
      await fillP112(b, { jabas, ini: "10:00", fin: "10:30" });
      await b.clickText("Enviar registro trazable");
      if (fault === "lose-request") {
        await b.waitFor("document.body.innerText.includes('El registro no se guardó')", "no guardado", 30000);
        check(`${label} con el intento pendiente los campos quedan bloqueados y se ofrece el reintento`, await b.js("[...document.querySelectorAll('main input')].every((e) => e.disabled)") && (await b.text()).includes("Reintentar envío"));
        await b.clickText("Reintentar envío");
      }
      await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación", 30000);
      out = { sent: (await cap(b)).map((x) => JSON.parse(x)), requests: [...b.log.requests] };
      await b.clickText("Volver"); await sleep(500);
      await logoutApp(b);
    });
    return out;
  };
  const lr = await faultRun("lose-response", "R1", "12");
  check("R1 respuesta perdida tras guardar: la reconciliación por GET encuentra la captura (1 POST, 1 fila, sin duplicar)", lr.sent.length === 1 && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${lr.sent[0].capture_id}'`)[0] === "1" && lr.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${lr.sent[0].capture_id}`) && r.status === 200));
  const lq = await faultRun("lose-request", "R2", "13");
  check("R2 petición perdida: GET 404 -> reintento con el MISMO capture_id y los MISMOS valores -> una sola captura con sus 3 detalles", lq.sent.length === 2 && JSON.stringify(lq.sent[0]) === JSON.stringify(lq.sent[1]) && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${lq.sent[0].capture_id}'`)[0] === "1" && q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${lq.sent[0].capture_id}'`)[0] === "3" && lq.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${lq.sent[0].capture_id}`) && r.status === 404));
  const opr = client(); await opr.login("operacion");
  const replay = await opr.call("POST", "/api/captures", sent);
  check("R3 reenviar el mismo payload (mismo capture_id) por la API devuelve 200 already_submitted y no crea otro pallet", replay.status === 200 && replay.json.created === false && replay.json.already_submitted === true && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${sent.capture_id}'`)[0] === "1");
  const conflict = await opr.call("POST", "/api/captures", { ...sent, values: { ...sent.values, cantidad_jabas: 41 } });
  check("R4 el mismo capture_id con otro contenido se rechaza (409 CAPTURE_IDEMPOTENCY_CONFLICT) y el valor guardado no cambia", conflict.status === 409 && conflict.json.code === "CAPTURE_IDEMPOTENCY_CONFLICT" && q(`SELECT d.value_integer::text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${sent.capture_id}' AND f.key = 'cantidad_jabas'`)[0] === "40");
  const cross = await opr.call("POST", "/api/captures", { ...sent116, assignment_id: sent.assignment_id, capture_id: sent.capture_id });
  check("R5 el capture_id de un pallet no puede reutilizarse para otro formulario (409) y no cambia el tipo de la captura", cross.status === 409 && cross.json.code === "CAPTURE_IDEMPOTENCY_CONFLICT" && q(`SELECT f.code FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id WHERE c.id = '${sent.capture_id}'`)[0] === "VINTO-P1-12");

  // ============================================================ 5. asignación vencida, formulario no vinculado / no publicado, alcance
  const wally = (await opr.call("GET", `/api/assignments/active?machine_code=${MACHINE_NO_FORM}`)).json.assignment, gambini = (await opr.call("GET", `/api/assignments/active?machine_code=${MACHINE}`)).json.assignment;
  const body = (assignment, form = "VINTO-P1-12", values = { cantidad_jabas: 5, hora_inicio: "01:00", hora_fin: "02:00" }) => ({ capture_id: crypto.randomUUID(), form_code: form, assignment_id: assignment.id, device_key: crypto.randomUUID(), values });
  const wrongMachine = await opr.call("POST", "/api/captures", body(wally));
  check("X1 un formulario NO vinculado a la máquina no se puede usar: P1-12 en WALLY = 409 FORM_NOT_AVAILABLE y nada se escribe", wrongMachine.status === 409 && wrongMachine.json.code === "FORM_NOT_AVAILABLE" && q(`SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = '${wally.id}'`)[0] === "0");
  const unpublished = await opr.call("POST", "/api/captures", body(gambini, creds.draft_form_code));
  check("X1b un formulario vinculado pero NO publicado no se acepta (409 FORM_NOT_AVAILABLE) y tampoco aparece en la disponibilidad del backend", unpublished.status === 409 && unpublished.json.code === "FORM_NOT_AVAILABLE" && !JSON.stringify((await opr.call("GET", "/api/production/machines")).json).includes(creds.draft_form_code));
  const countBefore = q("SELECT count(*) FROM vinto_txn.capture")[0];
  const shiftDate = (op) => qw(`SET session_replication_role = replica; UPDATE vinto_txn.assignment SET operating_date = operating_date ${op} 1 WHERE status = 'active' AND machine_id = (SELECT id FROM vinto_master.machine WHERE code = '${MACHINE}')`);
  await browser("stale-open", nextPort(), {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Conversión"); await nav(b, "Ejecución"); await conv(b, "ejecucion"); await sleep(800);
    await b.click('[data-form="VINTO-P1-12"]'); await b.waitFor("document.querySelectorAll('main input').length === 3", "P1-12");
    await fillP112(b, { jabas: "7", ini: "11:00", fin: "11:20" });
    shiftDate("-");
    await b.clickText("Enviar registro trazable");
    await b.waitFor("document.querySelector('[data-conversion=\"ejecucion\"]')", "regreso a Ejecución tras el rechazo", 25000);
    const sentStale = (await cap(b)).map((x) => JSON.parse(x));
    check("X2 asignación vencida con el formulario abierto: 409 ASSIGNMENT_STALE, se vuelve a Ejecución y NO se guarda ningún pallet", sentStale.length === 1 && posts(b)[0].status === 409 && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${sentStale[0].capture_id}'`)[0] === "0" && q("SELECT count(*) FROM vinto_txn.capture")[0] === countBefore);
    check("X2b la interfaz avisa de la asignación vencida con un mensaje claro", await b.waitFor("document.body.innerText.includes('otro turno o fecha operativa')", "aviso en Ejecución", 20000));
    await b.shot("x1-asignacion-vencida-al-enviar.png");
    await logoutApp(b);
  });
  const staleApi = await opr.call("GET", `/api/assignments/active?machine_code=${MACHINE}`);
  const stalePost = await opr.call("POST", "/api/captures", body(staleApi.json.assignment));
  check("X3 asignación VENCIDA: el backend la marca stale y el POST por API se rechaza con 409 ASSIGNMENT_STALE", staleApi.json.stale === true && stalePost.status === 409 && stalePost.json.code === "ASSIGNMENT_STALE");
  await browser("stale", nextPort(), {}, async (b) => {
    await loginApp(b, "operacion");
    await nav(b, "Conversión"); await nav(b, "Ejecución"); await conv(b, "ejecucion");
    await b.waitFor("document.body.innerText.includes('otro turno o fecha operativa')", "aviso de asignación vencida", 20000);
    const opened = await b.click('[data-form="VINTO-P1-12"]'); await sleep(800);
    check("X4 la interfaz muestra la asignación vencida y NO abre la captura", opened && !(await b.text()).includes("Ficha NO homologada") && posts(b).length === 0);
    await b.shot("x2-asignacion-vencida.png");
    await logoutApp(b);
  });
  shiftDate("+");
  check("X5 restaurada la fecha operativa, la asignación vuelve a estar vigente", (await opr.call("GET", `/api/assignments/active?machine_code=${MACHINE}`)).json.stale === false);
  await opr.call("POST", "/api/auth/logout");
  for (const who of ["operacion_solo_bobinas", "operacion_solo_rebobinado"]) {
    await browser(`scope-${who}`, nextPort(), {}, async (b) => {
      await loginApp(b, who);
      await nav(b, "Conversión"); await b.waitFor("!!document.querySelector('[data-conversion]')", "panel de Conversión", 20000);
      let disabledEverywhere = true;
      for (const m of ["Programación", "Ejecución", "Seguimiento"]) { await nav(b, m); await sleep(900); disabledEverywhere = disabledEverywhere && await b.js("!!document.querySelector('[data-conversion=\"disabled\"]')") && !(await b.js("document.querySelectorAll('[data-form]').length")); }
      check(`X6 ${who}: sin concesión de Conversión no puede capturar: la navegación la muestra NO habilitada en los tres módulos, sin formularios`, disabledEverywhere && (await b.text()).includes("Conversión no está habilitado"));
      await b.shot(`x3-sin-concesion-${who}.png`);
      await logoutApp(b);
    });
  }
  const noGrant = client(); await noGrant.login("operacion_solo_bobinas");
  const denied = await noGrant.call("POST", "/api/captures", body(gambini));
  check("X7 por API, un usuario sin concesión de Conversión no puede capturar en una asignación existente (404) y nada se escribe", denied.status === 404 && q("SELECT count(*) FROM vinto_txn.capture")[0] === countBefore);
  await noGrant.call("POST", "/api/auth/logout");

  // ============================================================ 6. disponibilidad por sector (regresión de Rebobinado: la completa es m4a-e2e.mjs)
  const reb = client(); await reb.login("operacion");
  const machinesApi = await reb.call("GET", "/api/production/machines");
  const sectorsApi = Object.fromEntries(machinesApi.json.sectors.map((s) => [s.code, s.machines.map((m) => `${m.code}:${m.forms.map((f) => f.code).join("+")}`)]));
  check("L1 cada sector publica SUS formularios: P1-12 y P1-16 solo en Conversión/GAMBINI; P1-10 y P1-29 solo en Rebobinado", sectorsApi.CONVERSION.join() === `${MACHINE}:VINTO-P1-12+VINTO-P1-16,${MACHINE_NO_FORM}:` && JSON.stringify(sectorsApi.REBOBINADO).includes("COPASA:VINTO-P1-10") && JSON.stringify(sectorsApi.REBOBINADO).includes("TUBETERA:VINTO-P1-29") && !/P1-12|P1-16/.test(JSON.stringify(sectorsApi.REBOBINADO)), JSON.stringify(sectorsApi));
  await reb.call("POST", "/api/auth/logout");

  // ============================================================ 7. móvil
  await browser("mob", nextPort(), { mobile: true }, async (b) => {
    await loginApp(b, "operacion");
    await b.clickText("Conversión"); await b.clickText("Ejecucion").then(async (ok) => { if (!ok) await b.clickText("ejecucion"); });
    await conv(b, "ejecucion"); await sleep(900);
    const o1 = await b.overflow(); await b.shot("m1-ejecucion-movil.png");
    await b.click('[data-form="VINTO-P1-12"]'); await b.waitFor("document.body.innerText.includes('Ficha NO homologada')", "P1-12 móvil", 15000);
    const o2 = await b.overflow(); await b.shot("m2-p112-movil.png");
    await b.clickText("Volver"); await conv(b, "ejecucion");
    await b.clickText("Seguimiento").then(async (ok) => { if (!ok) await b.clickText("seguimiento"); }); await conv(b, "seguimiento"); await sleep(1200);
    const o3 = await b.overflow(); await b.shot("m3-seguimiento-movil.png");
    check("M1 versión móvil (390 px): ejecución, P1-12 y seguimiento sin desborde horizontal de la página", o1 <= 0 && o2 <= 0 && o3 <= 0, `${o1}/${o2}/${o3}`);
    await logoutApp(b).catch(() => {});
  });
  await jefatura.call("POST", "/api/auth/logout"); await supervision.call("POST", "/api/auth/logout");
  const sessions = q(`SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()`)[0];
  check("Z1 sin sesiones activas de prueba tras los logouts", sessions === "0", `activas ${sessions}`);
  const totals = q(`SELECT f.code||'='||count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id JOIN vinto_config.form f ON f.id = fv.form_id GROUP BY f.code ORDER BY f.code`).join(",");
  check("Z2 totales en la base efímera: P1-12 = 3 (O, R1 y R2) y P1-16 = 1, sin duplicados y sin capturas de otros formularios", totals === "VINTO-P1-12=3,VINTO-P1-16=1", totals);
} else {
  // ============================================================ FASE disabled: configuración REAL (Conversión y Rebobinado concedidos pero NO operativos)
  const jef = client(); await jef.login("jefatura");
  const avail = await jef.call("GET", "/api/production/machines");
  check("D1 con la configuración real el backend NO expone Conversión ni Rebobinado aunque el usuario tenga la concesión (solo BOBINAS)", avail.status === 200 && JSON.stringify(avail.json.sectors.map((s) => s.code)) === JSON.stringify(["BOBINAS"]), JSON.stringify(avail.json.sectors?.map((s) => s.code)));
  const op = client(); await op.login("operacion");
  const apiBlocks = await op.call("POST", "/api/captures", { capture_id: crypto.randomUUID(), form_code: "VINTO-P1-12", assignment_id: crypto.randomUUID(), device_key: crypto.randomUUID(), values: {} });
  check("D2 con la política real P1-12 no se acepta (422 UNSUPPORTED_FORM) y las máquinas de Conversión se rechazan por alcance (422): ni asignación ni OT", apiBlocks.status === 422 && apiBlocks.json.code === "UNSUPPORTED_FORM" && (await op.call("GET", `/api/assignments/active?machine_code=${MACHINE}`)).status === 422 && (await jef.call("POST", "/api/work-orders", { machine_code: MACHINE, lines: [{ pv_reference: "PV", article_code: article, quantity: 1, due_date: "2026-11-01" }] })).status === 422);
  await op.call("POST", "/api/auth/logout"); await jef.call("POST", "/api/auth/logout");
  for (const who of ["jefatura", "operacion"]) {
    await browser(`dis-${who}`, nextPort(), { seedLegacy: true }, async (b) => {
      await loginApp(b, who);
      await b.clickText("Conversión"); await b.waitFor("!!document.querySelector('[data-conversion]')", "panel de Conversión", 20000);
      const seen = [];
      for (const m of ["Programación", "Ejecución", "Seguimiento"]) {
        await nav(b, m); await sleep(1000);
        const t = await b.text();
        seen.push(await b.js("!!document.querySelector('[data-conversion=\"disabled\"]')") && t.includes("Conversión no está habilitado") && !(await b.js("document.querySelectorAll('[data-form]').length")) && !/Crear OT inicial|Gambini|Sincro|OMET|Pañuelera|Wally|Producción diaria|OT-PRUEBA|LEGACY-M6A/i.test(t.replace(/Conversión no está habilitado[\s\S]*$/, "")) && !t.includes(MARKER));
      }
      check(`D3 ${who}: con Conversión no operativo la navegación lo muestra NO habilitado en Programación, Ejecución y Seguimiento, sin formularios, sin crear OT y sin datos demo ni registros legacy como respaldo`, seen.every(Boolean), JSON.stringify(seen));
      if (who === "operacion") await b.shot("d1-conversion-no-habilitado.png");
      check(`D4 ${who}: ningún POST a /api/captures, /api/work-orders ni /api/assignments desde la navegación bloqueada`, b.log.requests.filter((r) => r.method === "POST" && /\/api\/(captures|work-orders|assignments)/.test(r.url)).length === 0);
      check(`D5 ${who}: el registro legacy del navegador se CONSERVA intacto y no hay datos centrales en localStorage`, await legacyKept(b) && !(await storageDump(b)).includes("VINTO-P1-1"));
      if (who === "jefatura") {
        await b.clickText("Bobinas"); await b.waitFor("document.body.innerText.includes('Bobinas ·')", "Bobinas", 15000); await nav(b, "Programación"); await sleep(1500);
        check("D6 Bobinas sigue operativo con la configuración real: su programación central (MP1 / MP3) se muestra", await b.js("[...document.querySelectorAll('select')].some((s) => [...s.options].some((o) => o.value === 'MP1'))"));
      }
      await logoutApp(b);
    });
  }
  check("D7 con Conversión deshabilitado no se escribió ninguna captura ni OT en la base efímera", q("SELECT (SELECT count(*) FROM vinto_txn.capture)||'|'||(SELECT count(*) FROM vinto_txn.work_order)")[0] === "0|0");
  check("D8 sin sesiones activas de prueba tras los logouts", q("SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now()")[0] === "0");
}
writeFileSync(join(outDir, `resultados-m6b-${phase}.json`), JSON.stringify({ phase, database, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
