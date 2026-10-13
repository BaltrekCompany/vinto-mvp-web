// node scripts/e2e/p129-e2e.mjs <creds.json> <evidence-dir>
// M3-B · recorrido E2E de la ficha CANDIDATA VINTO-P1-29 «Producción Tubetera» en un entorno AISLADO: OT -> asignación -> formulario P1-29 (componente React REAL) -> varias filas de rodelas y
// formatos -> POST -> PostgreSQL efímero -> GET -> listado filtrado -> idempotencia -> reconciliación -> logout. Requiere el backend de prueba (backend/tests/e2e_p110_server.py, puerto 8190, que instala la
// máquina TUBETERA ficticia y la definición candidata) y el frontend de QA con el harness temporal scripts/e2e/harness-p129-page.tsx.txt (puerto 8796). TODOS los datos son FICTICIOS. NO es una ruta ni una
// prueba del producto.
//
// SALVAGUARDAS: aborta si la API o el frontend son los de DEV (8000 / 8787), si la base no termina en `_test`, si no es `current_database()`, si el backend no sirve esa base o si el navegador llama al
// puerto 8000. Las lecturas de PostgreSQL son SELECT en transacciones de solo lectura (también sobre DEV, solo para comprobar que no cambió).
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [credsPath, outDir] = process.argv.slice(2);
const API = process.env.E2E_API ?? "http://127.0.0.1:8190", WEB = process.env.E2E_WEB ?? "http://127.0.0.1:8796";
const PG_CONTAINER = process.env.E2E_PG_CONTAINER ?? "vinto-local-postgres-1";
const CODE = "VINTO-P1-29";
const MACHINE_UNDER_TEST = "TUBETERA";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const creds = JSON.parse(readFileSync(credsPath, "utf8"));
const { database, users } = creds;
const MACHINE = MACHINE_UNDER_TEST;
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
// selectores de la interfaz de grupos (data-group = título del grupo)
const G = { rodelas: '[data-group="Rodelas de papel kraft"]', formatos: '[data-group="Formatos de tubete"]' };
const TITLE = { rodelas: "Rodelas de papel kraft", formatos: "Formatos de tubete" };
const cellAt = (group, row, i) => `(document.querySelectorAll('${G[group]} li[data-row="${row}"] input, ${G[group]} li[data-row="${row}"] textarea'))[${i}]`;
const setCell = (b, group, row, i, value) => b.js(`(() => { const el = ${cellAt(group, row, i)}; if (!el) return false; const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const setSimple = (b, i, value) => b.js(`(() => { const el = (document.querySelectorAll('main input'))[${i}]; if (!el) return false; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
const addRowBtn = (group) => `${G[group]} button`; // el primer botón del grupo es «Agregar fila»
const counter = (b, group) => b.js(`document.querySelector('${G[group]} [data-testid="group-count"]').innerText`);
const rowCount = (b, group) => b.js(`document.querySelectorAll('${G[group]} li[data-row]').length`);
const isDisabled = (b, selector) => b.js(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); return !!el && el.disabled; })()`);
const removeBtn = (group, row) => `${G[group]} button[aria-label="Eliminar fila ${row} de ${TITLE[group]}"]`;
const capturePosts = (b) => b.js("window.__posts ?? []");
const posts = (b) => b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/captures"));
const text = (b) => b.js("document.body.innerText");
const dbRows = (id) => q(`SELECT g.code||'|'||r.row_number||'|'||coalesce((SELECT string_agg(f.key||'='||coalesce(d.value_text, d.value_decimal::text, d.value_integer::text), ',' ORDER BY f.display_order) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.group_row_id = r.id), '') FROM vinto_txn.capture_group_row r JOIN vinto_config.field_group g ON g.id = r.field_group_id WHERE r.capture_id = '${id}' ORDER BY g.display_order, r.row_number`);

// ================================================================ 1. preparación por API (OT -> asignación)
const jefatura = client(), supervision = client(), operacion = client();
const article = creds.article_code;
check("P1 login JEFATURA / SUPERVISION de prueba", (await jefatura.login("jefatura")).status === 200 && (await supervision.login("supervision")).status === 200);
const me = await operacion.login("operacion");
check("P2 el backend sirve la base efímera (el usuario de prueba solo existe allí)", me.status === 200 && me.json.user.id === users.operacion.user_id && q(`SELECT count(*) FROM vinto_master.user WHERE id = '${users.operacion.user_id}'`)[0] === "1");
await operacion.call("POST", "/api/auth/logout");
check("P3 la máquina de prueba es la TUBETERA ficticia del sector REBOBINADO de prueba", q(`SELECT m.code||'|'||m.name||'|'||s.code FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = '${MACHINE}'`)[0] === `${MACHINE}|Tubetera (prueba)|REBOBINADO`);
const order = await jefatura.call("POST", "/api/work-orders", { machine_code: MACHINE, lines: [{ pv_reference: "PV-E2E-T", article_code: article, quantity: 10, due_date: "2026-11-01" }] });
const published = await jefatura.call("POST", `/api/work-orders/${order.json.id}/publish`);
const activated = await supervision.call("POST", "/api/assignments/activate", { work_order_id: published.json.id, baseline_line_id: published.json.baseline.lines[0].id });
check("P4 OT creada y asignación activa en la TUBETERA de prueba (turno ficticio)", order.status === 201 && activated.status === 201 && activated.json.assignment.machine.code === MACHINE && activated.json.assignment.shift.code.startsWith("FICT_"), `OT ${order.status}, asignación ${activated.status}`);
const assignment = activated.json.assignment;

// ================================================================ 2. componente React real: un lote, dos rodelas, dos formatos
const LOTE = { fecha: "2026-01-15", lote: "LOTE-FICTICIO-E2E", pegamento: "12,5 (texto de ejemplo)", fardo: "100,0 (texto de ejemplo)", mrp: "MRP-FICTICIO-E2E", obs: "dato ficticio E2E" };
const RODELAS = [["RODELA-FICTICIA-A", "10,250"], ["RODELA-FICTICIA-B", "8.100"]];
// formatos: tipo, producidos, observados(textarea), merma, int, ext, hojas, espesor, peso
const FORMATOS = [["FORMATO-FICTICIO-1", "120 (texto)", "3 observados", "0,500", "38.10", "42.00", "4", "1.800", "6,750"], ["FORMATO-FICTICIO-2", "80", "", "0.250", "30.00", "34.00", "3", "1.500", "4.125"]];
const EXPECTED = {
  rodelas: [{ rodela_papel_kraft_identificacion: "RODELA-FICTICIA-A", rodela_papel_kraft_peso_kg: "10.250" }, { rodela_papel_kraft_identificacion: "RODELA-FICTICIA-B", rodela_papel_kraft_peso_kg: "8.100" }],
  formatos: [
    { formato_tipo_de_tubete: "FORMATO-FICTICIO-1", cantidad_tubetes_producidos_por_formato: "120 (texto)", cantidad_tubetes_observados_por_formato: "3 observados", merma_kg_por_formato: "0.500", diametro_interno_mm_por_formato: "38.10", diametro_externo_mm_por_formato: "42.00", cantidad_de_hojas_por_formato: "4", espesor_mm_por_formato: "1.800", peso_kg_por_formato: "6.750" },
    { formato_tipo_de_tubete: "FORMATO-FICTICIO-2", cantidad_tubetes_producidos_por_formato: "80", merma_kg_por_formato: "0.250", diametro_interno_mm_por_formato: "30.00", diametro_externo_mm_por_formato: "34.00", cantidad_de_hojas_por_formato: "3", espesor_mm_por_formato: "1.500", peso_kg_por_formato: "4.125" },
  ],
};
async function fillForm(b, lote) {
  for (const [i, v] of [LOTE.fecha, lote, LOTE.pegamento, LOTE.fardo, LOTE.mrp].entries()) await setSimple(b, i, v);
  await b.js(`(() => { const t = document.querySelector('main textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, ${JSON.stringify(LOTE.obs)}); t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  for (const [r, cells] of RODELAS.entries()) for (const [i, v] of cells.entries()) await setCell(b, "rodelas", r + 1, i, v);
  for (const [r, cells] of FORMATOS.entries()) for (const [i, v] of cells.entries()) await setCell(b, "formatos", r + 1, i, v);
}
const dbSimple = (id) => q(`SELECT f.key||'='||coalesce(d.value_text, d.value_date::text) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = '${id}' AND d.group_row_id IS NULL ORDER BY f.display_order`);
const EXPECTED_DB_ROWS = ["rodelas|1|rodela_papel_kraft_identificacion=RODELA-FICTICIA-A,rodela_papel_kraft_peso_kg=10.250", "rodelas|2|rodela_papel_kraft_identificacion=RODELA-FICTICIA-B,rodela_papel_kraft_peso_kg=8.100",
  "formatos|1|formato_tipo_de_tubete=FORMATO-FICTICIO-1,cantidad_tubetes_producidos_por_formato=120 (texto),cantidad_tubetes_observados_por_formato=3 observados,merma_kg_por_formato=0.500,diametro_interno_mm_por_formato=38.10,diametro_externo_mm_por_formato=42.00,cantidad_de_hojas_por_formato=4,espesor_mm_por_formato=1.800,peso_kg_por_formato=6.750",
  "formatos|2|formato_tipo_de_tubete=FORMATO-FICTICIO-2,cantidad_tubetes_producidos_por_formato=80,merma_kg_por_formato=0.250,diametro_interno_mm_por_formato=30.00,diametro_externo_mm_por_formato=34.00,cantidad_de_hojas_por_formato=3,espesor_mm_por_formato=1.500,peso_kg_por_formato=4.125"];
let sent = null;
await browser("a", 9391, async (b) => {
  await b.goto(`${WEB}/qa-harness`);
  await loginUi(b, "operacion");
  await b.waitFor("document.body.innerText.includes('Producción Tubetera') && document.querySelectorAll('main input').length > 5", "formulario P1-29", 30000);
  const plain = await text(b);
  check("A1 la pantalla indica «Ficha candidata — No homologada» y muestra el contexto de la asignación", plain.includes("Ficha candidata — No homologada") && plain.includes(order.json.number) && plain.includes(MACHINE) && plain.includes(assignment.shift.name) && plain.includes(assignment.operating_date));
  check("A2 operador, turno y visto bueno quedan como contexto pendiente (no editable, sin firma ficticia); la sesión se muestra como identificación, no como operador ni visto bueno", plain.includes("Visto bueno del responsable") && (plain.match(/— pendiente de definición —/g) ?? []).length === 2 && plain.includes("no es el operador ni el visto bueno del responsable") && plain.includes("Decisiones pendientes de VINTO"));
  check("A3 estado inicial: cada grupo con 1 fila (mínimo de prueba) y sin poder eliminar por debajo del mínimo", (await counter(b, "rodelas")).startsWith("1 fila") && (await counter(b, "formatos")).startsWith("1 fila") && await isDisabled(b, removeBtn("rodelas", 1)) && await isDisabled(b, removeBtn("formatos", 1)));
  await b.shot("a1-formulario-inicial.png");
  check("A4 agregar una segunda fila en rodelas y en formatos", await b.click(addRowBtn("rodelas")) && await b.click(addRowBtn("formatos")) && (await rowCount(b, "rodelas")) === 2 && (await rowCount(b, "formatos")) === 2);
  await fillForm(b, LOTE.lote);
  await b.shot("a2-formulario-lleno.png");
  const before = q("SELECT count(*) FROM vinto_txn.capture")[0];
  check("A5 enviar", await b.clickText("Enviar registro trazable"));
  await b.waitFor("document.querySelector('[data-section=saved]') && document.querySelector('[data-readback]')?.dataset.readback === 'ok'", "captura guardada y verificada", 30000);
  await b.shot("a3-guardado-y-verificado.png");
  const sentPosts = posts(b);
  check("A6 un único POST /api/captures = 201 y una consulta posterior GET por id = 200", sentPosts.length === 1 && sentPosts[0].status === 201 && b.log.requests.some((r) => r.method === "GET" && /\/api\/captures\/[0-9a-f-]{36}$/.test(r.url) && r.status === 200));
  sent = JSON.parse((await capturePosts(b))[0]);
  check("A7 el payload usa values._groups con las filas en orden, decimales como texto con punto (la coma se normaliza) y las cantidades como texto", JSON.stringify(sent.values._groups) === JSON.stringify(EXPECTED) && sent.values.fecha_de_produccion === "2026-01-15" && sent.values.pegamento_total_kg === "12,5 (texto de ejemplo)" && sent.form_code === CODE);
  check("A8 el payload NO lleva ids de fila, contexto del servidor ni los campos automáticos pendientes", !JSON.stringify(sent).match(/rowKey|row_number|group_row|field_group|"operador"|"turno"|"visto_bueno_responsable"|"maquina"|"responsable"|"firma"/) && JSON.stringify(Object.keys(sent).sort()) === JSON.stringify(["assignment_id", "capture_id", "device_key", "form_code", "values"]));
  const stored = dbRows(sent.capture_id);
  check("A9 PostgreSQL: filas de rodelas y formatos en su orden con los valores EXACTOS (decimales con su escala, cantidades como texto)", JSON.stringify(stored) === JSON.stringify(EXPECTED_DB_ROWS), stored.join(" ; ").slice(0, 400));
  const simple = dbSimple(sent.capture_id);
  check("A10 PostgreSQL: campos simples (la fecha de producción es la tecleada, no la fecha operativa)", JSON.stringify(simple) === JSON.stringify(["fecha_de_produccion=2026-01-15", `lote_de_produccion=${LOTE.lote}`, `pegamento_total_kg=${LOTE.pegamento}`, `peso_fardo=${LOTE.fardo}`, `numero_mrp_del_sistema=${LOTE.mrp}`, `observaciones=${LOTE.obs}`]) && assignment.operating_date !== "2026-01-15", simple.join(" ; "));
  const head = q(`SELECT c.status||'|'||c.revision||'|'||m.code||'|'||c.assignment_id||'|'||c.created_by FROM vinto_txn.capture c JOIN vinto_master.machine m ON m.id = c.machine_id WHERE c.id = '${sent.capture_id}'`)[0];
  check("A11 capture: submitted, revision = 1, máquina y asignación derivadas por el servidor y autor", head === `submitted|1|${MACHINE}|${assignment.id}|${users.operacion.user_id}`, head);
  check("A12 detalles: 6 simples + 4 de rodelas + 17 de formatos, los de fila ligados a su fila y grupo; sin duplicados", q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent.capture_id}' AND group_row_id IS NULL`)[0] === "6" && q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent.capture_id}' AND group_row_id IS NOT NULL AND field_group_id IS NOT NULL`)[0] === "21" && Number(q("SELECT count(*) FROM vinto_txn.capture")[0]) === Number(before) + 1);
  check("A13 auditoría: la alta de las filas quedó registrada con el actor", Number(q(`SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'capture_group_row' AND actor_id = '${users.operacion.user_id}'`)[0]) >= 4);
  const read = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures/${sent.capture_id}', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A14 GET por id reconstruye campos simples y ambos grupos en el orden original", read.status === 200 && read.body.form.code === CODE && JSON.stringify(read.body.values._groups) === JSON.stringify(EXPECTED) && read.body.values.fecha_de_produccion === "2026-01-15");
  const listed = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures?form_code=${CODE}', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A15 el listado filtrado por form_code devuelve P1-29 con sus filas", listed.status === 200 && listed.body.every((c) => c.form.code === CODE) && listed.body.some((c) => c.id === sent.capture_id && c.values._groups.formatos.length === 2));
  const historic = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/captures', { credentials: 'include' }).then(async (r) => JSON.stringify({ status: r.status, body: await r.json() }))`));
  check("A16 el listado histórico (F6) NO incluye P1-29", historic.status === 200 && historic.body.every((c) => c.form.code === "VINTO-P1-06") && !historic.body.some((c) => c.id === sent.capture_id));
  const storage = JSON.parse(await b.js("JSON.stringify({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })"));
  check("A17 el navegador solo guarda vinto-device-key (nada del lote ni de las filas)", JSON.stringify(storage.local) === JSON.stringify(["vinto-device-key"]) && storage.session.length === 0);
  check("A18 sin errores de JavaScript/CORS en el navegador", b.log.exceptions.length === 0 && b.log.consoleErrors.filter((e) => !/401/.test(e)).length === 0, JSON.stringify([...b.log.exceptions, ...b.log.consoleErrors]).slice(0, 300));
  await b.js("document.querySelector('#qa-logout').click()"); await b.waitFor("!!document.querySelector('#qa-user')", "ingreso tras logout", 15000);
  const lo = b.log.requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/auth/logout"));
  const after = JSON.parse(await b.js(`fetch(${JSON.stringify(API)} + '/api/auth/me', { credentials: 'include' }).then((r) => JSON.stringify({ status: r.status }))`));
  check("A19 logout = 204 y /api/auth/me = 401", lo.length === 1 && lo[0].status === 204 && after.status === 401);
});

// ================================================================ 3. idempotencia, conflictos, validación, permisos y alcance sobre la captura A (API)
const op = client(); await op.login("operacion");
const countsA = () => `${q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${sent.capture_id}'`)[0]}|${q(`SELECT count(*) FROM vinto_txn.capture_group_row WHERE capture_id = '${sent.capture_id}'`)[0]}|${q(`SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = '${sent.capture_id}'`)[0]}`;
const before = countsA();
const replay = await op.call("POST", "/api/captures", sent);
check("B1 reintento idéntico = 200 already_submitted, sin crear filas ni detalles", replay.status === 200 && replay.json.already_submitted === true && countsA() === before, `${before} -> ${countsA()}`);
const variants = {
  "una celda de una fila de formatos": (v) => { v.values._groups.formatos[1].merma_kg_por_formato = "0.251"; },
  "el orden de las rodelas": (v) => { v.values._groups.rodelas.reverse(); },
  "una rodela de más": (v) => { v.values._groups.rodelas.push({ rodela_papel_kraft_identificacion: "R-3", rodela_papel_kraft_peso_kg: "1" }); },
  "un formato de menos": (v) => { v.values._groups.formatos.pop(); },
  "la fecha de producción": (v) => { v.values.fecha_de_produccion = "2026-01-16"; },
};
for (const [name, mutate] of Object.entries(variants)) {
  const body = structuredClone(sent); mutate(body);
  const r = await op.call("POST", "/api/captures", body);
  check(`B2 mismo capture_id con ${name} distinto = 409 CAPTURE_IDEMPOTENCY_CONFLICT`, r.status === 409 && r.json.code === "CAPTURE_IDEMPOTENCY_CONFLICT" && countsA() === before);
}
check("B3 el contenido original no cambió tras los conflictos", JSON.stringify(dbRows(sent.capture_id)) === JSON.stringify(EXPECTED_DB_ROWS));
const nuevo = (mutate) => { const body = structuredClone(sent); body.capture_id = crypto.randomUUID(); mutate(body); return body; };
const totalBefore = q("SELECT count(*) FROM vinto_txn.capture")[0];
const invalid = [
  ["decimal inválido", (b) => { b.values._groups.formatos[0].espesor_mm_por_formato = "secreto-1e3"; }, /_groups\.formatos\[1\]\.espesor_mm_por_formato/],
  ["cantidad como número JSON (declarada texto)", (b) => { b.values._groups.formatos[0].cantidad_de_hojas_por_formato = 4; }, /cantidad_de_hojas_por_formato: debe ser texto/],
  ["falta un obligatorio de fila", (b) => { delete b.values._groups.rodelas[1].rodela_papel_kraft_peso_kg; }, /_groups\.rodelas\[2\]\.rodela_papel_kraft_peso_kg: obligatorio/],
  ["sin rodelas (mínimo de prueba)", (b) => { delete b.values._groups.rodelas; }, /_groups\.rodelas: se requieren al menos 1 filas/],
  ["campos automáticos pendientes enviados", (b) => { Object.assign(b.values, { operador: "x", turno: "DIA", visto_bueno_responsable: "ok" }); }, /operador: campo desconocido/],
  ["ids internos de fila", (b) => { Object.assign(b.values._groups.formatos[0], { id: "x", row_number: 9, group_row_id: "y" }); }, /_groups\.formatos\[1\]\.id: campo desconocido/],
  ["grupo no declarado", (b) => { b.values._groups.otros = [{ x: 1 }]; }, /_groups\.otros: grupo no declarado/],
];
for (const [name, mutate, pattern] of invalid) {
  const r = await op.call("POST", "/api/captures", nuevo(mutate));
  check(`B4 422 seguro: ${name}`, r.status === 422 && r.json.code === "CAPTURE_VALIDATION" && pattern.test(r.text) && !r.text.includes("secreto") && !/SELECT/.test(r.text));
}
check("B5 nada se escribió con las capturas inválidas", q("SELECT count(*) FROM vinto_txn.capture")[0] === totalBefore);
const jef = await jefatura.call("GET", `/api/captures/${sent.capture_id}`);
const anon = await client().call("GET", `/api/captures/${sent.capture_id}`);
const soloBobinas = client(); await soloBobinas.login("operacion_solo_bobinas");
const sbGet = await soloBobinas.call("GET", `/api/captures/${sent.capture_id}`);
const sbList = await soloBobinas.call("GET", `/api/captures?form_code=${CODE}`);
const sbPost = await soloBobinas.call("POST", "/api/captures", nuevo(() => {}));
check("B7 permisos y alcance: sin sesión 401, JEFATURA 403, sin concesión de Rebobinado GET por id 404, listado vacío y POST 404", anon.status === 401 && jef.status === 403 && sbGet.status === 404 && sbList.status === 200 && sbList.json.length === 0 && sbPost.status === 404, `${anon.status}/${jef.status}/${sbGet.status}/${sbPost.status}`);
await op.call("POST", "/api/auth/logout"); await soloBobinas.call("POST", "/api/auth/logout");

// ================================================================ 4. validación local, reconciliación y bloqueo de filas con un intento pendiente
await browser("v", 9392, async (b) => {
  await b.goto(`${WEB}/qa-harness`); await loginUi(b, "operacion");
  await b.waitFor("document.body.innerText.includes('Producción Tubetera') && document.querySelectorAll('main input').length > 5", "formulario", 30000);
  await setCell(b, "rodelas", 1, 0, "solo identificación");
  const countBefore = q("SELECT count(*) FROM vinto_txn.capture")[0];
  await b.clickText("Enviar registro trazable");
  await b.waitFor("document.body.innerText.includes('Peso de la rodela: es obligatorio.')", "errores de fila", 10000);
  await b.shot("v1-errores-por-fila.png");
  const t = await text(b);
  check("V1 errores asociados a la fila y al campo (rodelas fila 1, formatos fila 1) y a los campos del lote, sin ningún POST", t.includes("Peso de la rodela: es obligatorio.") && t.includes("Tipo de tubete: es obligatorio.") && t.includes("Fecha de producción: es obligatorio.") && posts(b).length === 0 && q("SELECT count(*) FROM vinto_txn.capture")[0] === countBefore);
  await b.js("document.querySelector('#qa-logout').click()"); await b.waitFor("!!document.querySelector('#qa-user')", "ingreso tras logout", 15000);
});

async function faultRun(mode, label, port, lote, expectRetry) {
  let result = {};
  await browser(label, port, async (b) => {
    await b.goto(`${WEB}/qa-harness?mode=${mode}`); await loginUi(b, "operacion");
    await b.waitFor("document.body.innerText.includes('Producción Tubetera') && document.querySelectorAll('main input').length > 5", "formulario", 30000);
    await b.click(addRowBtn("rodelas")); await b.click(addRowBtn("formatos"));
    await fillForm(b, lote);
    await b.clickText("Enviar registro trazable");
    if (!expectRetry) await b.waitFor("!!document.querySelector('[data-section=saved]')", "confirmación tras respuesta perdida", 30000);
    else {
      await b.waitFor("document.body.innerText.includes('El registro no se guardó')", "aviso de no guardado", 30000);
      const locked = (await isDisabled(b, addRowBtn("rodelas"))) && (await isDisabled(b, removeBtn("rodelas", 1))) && (await isDisabled(b, addRowBtn("formatos"))) && (await isDisabled(b, removeBtn("formatos", 2))) && await b.js("[...document.querySelectorAll('main input, main textarea')].every((e) => e.disabled)");
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
const lostResponse = await faultRun("lose-response", "C1", 9393, "LOTE-C1", false);
const idC = lostResponse.sent[0].capture_id;
check("C1 respuesta perdida tras guardar: el GET por el mismo id encuentra la captura con TODAS sus filas (1 POST, sin duplicar)", lostResponse.sent.length === 1 && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${idC}'`)[0] === "1" && dbRows(idC).length === 4 && lostResponse.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${idC}`) && r.status === 200));
const lostRequest = await faultRun("lose-request", "C2", 9394, "LOTE-C2", true);
const idD = lostRequest.sent[0].capture_id;
check("C2 petición perdida antes de llegar: GET 404 -> reintento con el MISMO capture_id y las MISMAS filas (2 envíos idénticos) -> una sola captura con sus 4 filas", lostRequest.sent.length === 2 && JSON.stringify(lostRequest.sent[0]) === JSON.stringify(lostRequest.sent[1]) && q(`SELECT count(*) FROM vinto_txn.capture WHERE id = '${idD}'`)[0] === "1" && dbRows(idD).length === 4
  && lostRequest.requests.some((r) => r.method === "GET" && r.url.endsWith(`/api/captures/${idD}`) && r.status === 404));

// ================================================================ 5. resumen y no-escritura en DEV
check("Z1 en la base efímera hay exactamente 3 capturas P1-29 (A, C1 y C2), sin duplicados", q(`SELECT count(*) FROM vinto_txn.capture WHERE form_version_id IN (SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = '${CODE}')`)[0] === "3");
check("Z2 sin sesiones activas de prueba tras los logouts", q(`SELECT count(*) FROM vinto_auth.session WHERE revoked_at IS NULL AND expires_at > now() AND user_id = '${users.operacion.user_id}'`)[0] === "0");
const devAfter = psql("vinto", DEV_SQL)[0];
check("Z3 DEV intacto: capturas | filas de grupo | auditoría | sesiones | auth_event | concesiones idénticos antes y después (solo SELECT)", devBefore === devAfter, `${devBefore} -> ${devAfter}`);
writeFileSync(join(outDir, "resultados-e2e-p129.json"), JSON.stringify({ database, devBefore, devAfter, results }, null, 2));
const fails = results.filter((r) => !r.ok);
console.log(`\nTOTAL ${results.length} · PASS ${results.length - fails.length} · FAIL ${fails.length}`);
process.exit(fails.length ? 1 : 0);
