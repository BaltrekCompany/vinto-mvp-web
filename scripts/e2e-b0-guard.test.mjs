// node --test scripts/e2e-b0-guard.test.mjs
// E2E-B0 · guarda del aislamiento y la robustez del arnés de la validación integral de Bobinas y Calidad. Parte estática: el orquestador, el servidor de prueba y el recorrido no pueden apuntar a DEV/PROD, no
// modifican la configuración real de sectores ni de formularios centrales y conservan los casos E01..E11. Parte negativa (se ejecuta el arnés, sin Docker ni servicios del proyecto): H1 ninguna variable heredada ni
// manifiesto alterado redirige el recorrido (se rechaza ANTES de cualquier petición: un servidor señuelo no recibe nada); H2 el recorrido solo se adjunta al Chrome que lanzó (puerto dinámico validado) y no cierra
// navegadores ajenos; H3 la limpieza se verifica y un recurso propio pendiente da código distinto de cero sin matar recursos ajenos; H4 una corrida no puede parecer exitosa por resultados de otra.
// El recorrido completo (Docker + Chrome) se lanza con `node scripts/e2e/b0-run.mjs`.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const runner = read("scripts/e2e/b0-run.mjs"), driver = read("scripts/e2e/b0-e2e.mjs"), server = read("backend/tests/e2e_b0_server.py");
const strip = (text) => text.split("\n").filter((l) => !/^\s*(\/\/|#)/.test(l)).join("\n");
const DRIVER = join(root, "scripts/e2e/b0-e2e.mjs"), RUNNER = join(root, "scripts/e2e/b0-run.mjs");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const isWindows = process.platform === "win32";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clean = () => Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^E2E_/.test(k)));
const runNode = (args, env = {}, timeout = 60000) => spawnSync(process.execPath, args, { encoding: "utf8", timeout, env: { ...clean(), ...env } });

// servidor SEÑUELO: cuenta cualquier petición que reciba (HTTP). Si el arnés se redirigiera a él, `hits` dejaría de ser 0.
function decoy(handler) {
  const hits = [];
  const srv = http.createServer((req, res) => { hits.push(`${req.method} ${req.url}`); if (handler) return handler(req, res); res.writeHead(200, { "content-type": "application/json" }); res.end("{}"); });
  return new Promise((ok) => srv.listen(0, "127.0.0.1", () => ok({ srv, hits, port: srv.address().port, close: () => new Promise((d) => srv.close(() => d())) })));
}
const RUN_ID = "20261014T120000Z-0a1b2c3d";
const HEAD = spawnSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).stdout.trim();
const fixedManifest = (extra = {}) => ({ runId: RUN_ID, commit: HEAD, dirty: false, startedAt: "2026-10-14T12:00:00Z", api: "http://127.0.0.1:8190", web: "http://127.0.0.1:8796", container: "vinto-e2eb0-pg", pgPort: 55432, database: "vinto_e2eb0_unit_test", backendPid: 1, webPid: 2, ...extra });
function scenario(manifestExtra = {}, { credsDb = "vinto_e2eb0_unit_test", runDirName = RUN_ID, stale = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "e2eb0-guardtest-"));
  const runDir = join(dir, runDirName); mkdirSync(runDir);
  const creds = join(dir, "creds.json"), manifest = join(dir, "manifest.json");
  writeFileSync(creds, JSON.stringify({ database: credsDb, users: {}, articles: {} }));
  writeFileSync(manifest, JSON.stringify(fixedManifest(manifestExtra)));
  if (stale) writeFileSync(join(runDir, "resultados-e2e-b0.json"), JSON.stringify({ stale: true, runId: "otra" }));
  return { dir, runDir, creds, manifest, args: [DRIVER, creds, runDir, manifest] };
}

// ============================================================ estático
test("el orquestador usa un PostgreSQL exclusivo en un contenedor nuevo, en 127.0.0.1 y fuera de los puertos de desarrollo", () => {
  assert.match(runner, /CONTAINER = "vinto-e2eb0-pg", PG_PORT = 55432, API_PORT = 8190, WEB_PORT = 8796/);
  for (const forbidden of [5432, 8000, 8787]) assert.equal(new RegExp(`(PG_PORT|API_PORT|WEB_PORT) = ${forbidden}\\b`).test(runner), false, `puerto ${forbidden}`);
  assert.match(runner, /"--tmpfs", "\/var\/lib\/postgresql\/data"/); // sin volumen persistente
  assert.match(runner, /127\.0\.0\.1:\$\{PG_PORT\}:5432/);
  assert.equal(/--volume|"-v", "[^"]*:[^"]*"|volumes:/.test(runner), false, "sin volúmenes montados");
  assert.match(runner, /ya existe un contenedor \$\{CONTAINER\}; no se reutiliza ni se borra automáticamente/);
  assert.match(runner, /docker\("rm", "-f", "-v", CONTAINER\)/);
  assert.match(runner, /"--label", `\$\{RUN_LABEL\}=\$\{runId\}`/); // el contenedor queda ligado a la corrida
  assert.equal(/vinto-local|compose|postgres_data/.test(strip(runner)), false, "no toca el contenedor ni el volumen de desarrollo");
  assert.match(runner, /randomBytes\(18\)/); // credenciales efímeras
  assert.equal(/password\s*=\s*["'`][^"'`]+["'`]/.test(strip(runner)), false, "sin contraseñas literales");
});

test("el servidor de prueba usa la configuración REAL (no modifica sectores ni CENTRAL_FORM_CODES), exige base *_test exclusiva y escucha solo en 127.0.0.1", () => {
  const code = strip(server);
  assert.equal(/sectors\._OPERATIONAL\s*=|CENTRAL_FORM_CODES\s*=|validate_operational_sectors\(/.test(code), false, "no asigna la configuración real");
  assert.match(code, /tuple\(sectors\._OPERATIONAL\) != \("BOBINAS",\)/);
  assert.match(code, /capture_service\.CENTRAL_FORM_CODES != frozenset\(\{"VINTO-P1-06"\}\)/);
  assert.match(code, /FORBIDDEN_DATABASES = \{"vinto", "vinto_test", "postgres"\}/);
  assert.match(code, /parsed\.hostname != "127\.0\.0\.1" or parsed\.port in \(None, 5432\)/);
  assert.match(code, /host="127\.0\.0\.1"/);
  assert.equal(/host="0\.0\.0\.0"/.test(code), false);
  assert.match(code, /DEV_PORTS = \{8000\}/);
  assert.match(code, /connect\(database\)/);
  assert.equal(/install_(rebobinado|p110|grouped|p129)|install_tubetera/.test(code), false, "sin fixtures de otros sectores ni formularios sintéticos");
  assert.match(code, /drop_database\(name\)/);
});

test("el recorrido fija sus destinos, valida el manifiesto y la identidad de la base antes de operar, y solo escribe en el directorio de su corrida", () => {
  const code = strip(driver);
  assert.match(code, /const FIXED = Object\.freeze\(\{ api: "http:\/\/127\.0\.0\.1:8190", web: "http:\/\/127\.0\.0\.1:8796", container: "vinto-e2eb0-pg", pgPort: 55432 \}\)/);
  assert.equal(/process\.env\.E2E_(API|WEB|PG_CONTAINER|CHROME)\s*\?\?/.test(code), false, "ningún destino se toma del entorno");
  assert.match(code, /apiUrl\.port === "8000" \|\| webUrl\.port === "8787" \|\| apiUrl\.port === "5432"/);
  assert.match(code, /apiUrl\.hostname !== "127\.0\.0\.1" \|\| webUrl\.hostname !== "127\.0\.0\.1"/);
  assert.match(code, /\^vinto-e2eb0-/);
  assert.match(code, /FORBIDDEN_DB = \["vinto", "vinto_test", "postgres"\]/);
  assert.match(code, /FORBIDDEN_DB\.includes\(manifest\.database\)/);
  assert.match(code, /SELECT current_database\(\)/);
  assert.match(code, /BEGIN READ ONLY/);
  assert.equal(/INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER/.test(code), false, "el recorrido no escribe por SQL");
  assert.match(code, /port === "8000"/); // el navegador aborta si llama al puerto de DEV
  assert.match(code, /Z3 aislamiento/);
  // identidad de los servicios antes de cualquier operación de negocio
  const firstBusiness = code.indexOf("await jefatura.login");
  for (const marker of ["S0 la base del recorrido", "S0a la corrida está identificada", "S0b identidad de los servicios", "S0d la API sirve EXACTAMENTE la base de esta corrida"]) { const at = code.indexOf(marker); assert.ok(at > 0 && at < firstBusiness, `${marker} debe preceder a la primera operación de negocio`); }
  assert.ok(code.indexOf("abort(`la variable heredada") < code.indexOf("JSON.parse(readFileSync(manifestPath"), "las variables heredadas se rechazan antes de leer nada");
});

test("el recorrido conserva los casos E01 a E11, las comprobaciones de robustez y el cierre sin simular resultados", () => {
  for (let n = 1; n <= 11; n++) assert.match(driver, new RegExp(`"E${String(n).padStart(2, "0")}\\.`), `caso E${n}`);
  for (const id of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "Z1", "Z2", "Z3", "Z4", "Z5"]) assert.match(driver, new RegExp(`"${id} `), id);
  assert.match(driver, /kind = "browser"/); // distingue navegador, HTTP, SQL y estático
  assert.equal(/check\([^)]*,\s*true\s*[,)]/.test(strip(driver)), false, "ninguna comprobación se marca PASS incondicionalmente");
  assert.match(driver, /process\.exit\(fails\.length \? 1 : 0\)/);
});

test("el recorrido de Calidad no ofrece ni sondea acciones de liberación o rechazo como funcionalidad existente", () => {
  assert.match(driver, /E09\.9 el contrato OpenAPI no contiene rutas de liberación, rechazo ni decisión de Calidad/);
  assert.match(driver, /E09\.10 sondeo directo/);
  assert.match(driver, /E09\.2 PostgreSQL: tras todas las capturas de Calidad, ninguna bobina fue liberada ni rechazada/);
  assert.equal(/\/release|\/reject/.test(strip(driver).replace(/for \(const verb of \[[^\]]*\]\)[^\n]*/, "")), false);
});

// ============================================================ H1 · destinos fijos: rechazo previo a cualquier petición
test("H1 · una variable heredada que intenta redirigir API, frontend, contenedor o Chrome aborta antes de cualquier petición (el servidor señuelo no recibe nada)", async () => {
  const d = await decoy();
  try {
    const sc = scenario();
    for (const env of [{ E2E_API: `http://127.0.0.1:${d.port}` }, { E2E_WEB: `http://127.0.0.1:${d.port}` }, { E2E_PG_CONTAINER: "otro-contenedor" }, { E2E_PG_CONTAINER: "vinto-e2eb0-otro" }, { E2E_CHROME: "C:\\otro\\chrome.exe" }]) {
      const r = runNode(sc.args, env);
      assert.equal(r.status, 2, JSON.stringify(env));
      assert.match(r.stderr, /E2E ABORTADO: la variable heredada E2E_(API|WEB|PG_CONTAINER|CHROME)/, JSON.stringify(env));
      assert.equal(r.stdout.includes("PASS") || r.stdout.includes("FAIL"), false, "no llegó a ejecutar ninguna comprobación");
    }
    assert.deepEqual(d.hits, [], "ninguna petición llegó al servicio señuelo");
    assert.equal(existsSync(join(sc.runDir, "resultados-e2e-b0.json")), false);
    rmSync(sc.dir, { recursive: true, force: true });
  } finally { await d.close(); }
});

test("H1 · el valor fijado por el propio orquestador no se rechaza como variable heredada, pero un manifiesto con destinos distintos sí, también antes de cualquier petición", async () => {
  const d = await decoy();
  try {
    const cases = [
      [{ api: `http://127.0.0.1:${d.port}` }, /no coincide con los destinos fijos/], [{ web: "http://127.0.0.1:8787" }, /no coincide con los destinos fijos/], [{ container: "vinto-local-postgres-1" }, /no coincide con los destinos fijos/],
      [{ pgPort: 5432 }, /no coincide con los destinos fijos/], [{ runId: "corrida-manual" }, /identificador de corrida válido/], [{ commit: "abc" }, /SHA probado/],
      [{ database: "vinto" }, /no es una base efímera/], [{ database: "vinto_test" }, /no es una base efímera/], [{ database: "produccion" }, /no es una base efímera/],
      [{ backendPid: null }, /no identifica los procesos/], [{ commit: "0".repeat(40) }, /el código cambió/],
    ];
    for (const [extra, pattern] of cases) {
      const sc = scenario(extra);
      const r = runNode(sc.args, { E2E_API: "http://127.0.0.1:8190", E2E_WEB: "http://127.0.0.1:8796", E2E_PG_CONTAINER: "vinto-e2eb0-pg" });
      assert.equal(r.status, 2, JSON.stringify(extra));
      assert.match(r.stderr, pattern, JSON.stringify(extra));
      rmSync(sc.dir, { recursive: true, force: true });
    }
    const mismatch = scenario({}, { credsDb: "vinto_e2eb0_otra_test" });
    const r = runNode(mismatch.args);
    assert.equal(r.status, 2); assert.match(r.stderr, /la base de las credenciales no es la declarada en el manifiesto/);
    rmSync(mismatch.dir, { recursive: true, force: true });
    const noManifest = runNode([DRIVER]);
    assert.equal(noManifest.status, 2); assert.match(noManifest.stderr, /solo se ejecuta desde scripts\/e2e\/b0-run\.mjs/);
    assert.deepEqual(d.hits, []);
  } finally { await d.close(); }
});

test("H1 · el orquestador tampoco admite destinos heredados y aborta antes de usar Docker o crear nada", () => {
  const before = existsSync(join(root, "e2e-b0-evidence")) ? readdirSync(join(root, "e2e-b0-evidence")).length : -1;
  for (const env of [{ E2E_API: "http://127.0.0.1:9999" }, { E2E_WEB: "http://127.0.0.1:9998" }, { E2E_PG_CONTAINER: "vinto-local-postgres-1" }, { E2E_CHROME: "x" }]) {
    const r = runNode([RUNNER, join(tmpdir(), "e2eb0-no-debe-crearse")], env);
    assert.equal(r.status, 2, JSON.stringify(env));
    assert.match(r.stderr, /la variable heredada E2E_(API|WEB|PG_CONTAINER|CHROME) no se admite/);
  }
  assert.equal(existsSync(join(tmpdir(), "e2eb0-no-debe-crearse")), false, "no se creó ningún directorio");
  assert.equal(existsSync(join(root, "e2e-b0-evidence")) ? readdirSync(join(root, "e2e-b0-evidence")).length : -1, before);
});

// ============================================================ H2 · adjunto CDP solo al Chrome propio
test("H2 · el depurador usa puerto dinámico, DevToolsActivePort del perfil propio y valida la identidad del Chrome lanzado (nada de puertos fijos)", () => {
  const code = strip(driver);
  assert.match(code, /"--remote-debugging-port=0"/);
  assert.equal(/remote-debugging-port=\$\{|let port = \d+|nextPort|9[0-9]{3}\b/.test(code), false, "sin puertos de depuración fijos ni contadores");
  assert.match(code, /DevToolsActivePort/);
  assert.match(code, /webSocketDebuggerUrl\)\.endsWith\(dtp\.path\)/);
  assert.match(code, /ownsPort\(dtp\.port, chrome\.pid\)/);
  assert.match(code, /mkdtempSync\(join\(tmpdir\(\), `e2eb0-\$\{manifest\.runId\}-\$\{label\}-`\)\)/); // perfil único por caso
  assert.match(code, /taskkill", \["\/PID", String\(chrome\.pid\)/); // solo cierra el PID propio
  assert.equal(/taskkill[^\n]*(IM|\/FI|chrome\.exe)/.test(code), false, "nunca cierra Chrome por nombre");
});

test("H2 · colisión: señuelos CDP en el rango antiguo (9500-9519) y un Chrome AJENO abierto; el recorrido se adjunta solo a su propio Chrome y no cierra el ajeno", { skip: !isWindows || !existsSync(CHROME) ? "requiere Windows y Chrome instalado" : false, timeout: 120000 }, async () => {
  const decoys = [];
  for (let port = 9500; port < 9520; port++) { try { const hits = []; const srv = http.createServer((req, res) => { hits.push(req.url); res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify([{ type: "page", webSocketDebuggerUrl: `ws://127.0.0.1:${port}/devtools/page/decoy` }])); }); await new Promise((ok, no) => { srv.once("error", no); srv.listen(port, "127.0.0.1", ok); }); decoys.push({ port, srv, hits }); } catch { /* puerto ocupado por otro: se ignora, no es nuestro */ } }
  const foreignProfile = mkdtempSync(join(tmpdir(), "e2eb0-foreign-chrome-"));
  const foreign = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${foreignProfile}`, "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  const before = readdirSync(tmpdir()).filter((e) => e.startsWith("e2eb0-selftest-") || e.includes("-selftest-"));
  try {
    let foreignPort = null;
    for (let i = 0; i < 100 && !foreignPort; i++) { try { foreignPort = Number(readFileSync(join(foreignProfile, "DevToolsActivePort"), "utf8").split("\n")[0]); } catch { await sleep(100); } }
    assert.ok(foreignPort, "el Chrome ajeno publicó su puerto");
    await sleep(2000); // el Chrome ajeno termina de abrir sus propios destinos internos antes de tomar la referencia
    const pageIds = async () => (await (await fetch(`http://127.0.0.1:${foreignPort}/json`)).json()).filter((t) => t.type === "page").map((t) => t.id);
    const foreignPagesBefore = await pageIds();
    assert.ok(foreignPagesBefore.length >= 1);
    const r = runNode([DRIVER, "--self-test-cdp"], {}, 90000);
    assert.equal(r.status, 0, r.stderr + r.stdout);
    const observed = JSON.parse(r.stdout.split("\n").find((l) => l.startsWith("CDP_SELFTEST ")).slice("CDP_SELFTEST ".length));
    assert.notEqual(observed.port, foreignPort, "no se adjuntó al Chrome ajeno");
    assert.equal(decoys.some((x) => x.port === observed.port), false, "no se adjuntó a un señuelo del rango antiguo");
    assert.match(observed.browserPath, /^\/devtools\/browser\/[0-9a-f-]+$/);
    assert.match(observed.userAgent, /Chrome\//);
    assert.deepEqual(decoys.flatMap((x) => x.hits), [], "ningún señuelo recibió una sola petición");
    const foreignPagesAfter = await pageIds();
    assert.deepEqual(foreignPagesAfter, foreignPagesBefore, "el Chrome ajeno sigue vivo con exactamente las mismas pestañas (no se cerró ni se abrió ninguna)");
    assert.equal(foreign.exitCode, null, "el Chrome ajeno no fue cerrado");
    assert.deepEqual(readdirSync(tmpdir()).filter((e) => e.includes("-selftest-")).sort(), before.sort(), "el perfil temporal del Chrome propio se eliminó");
  } finally {
    spawnSync("taskkill", ["/PID", String(foreign.pid), "/T", "/F"], { stdio: "ignore" }); await sleep(800);
    try { rmSync(foreignProfile, { recursive: true, force: true }); } catch { /* temporal */ }
    for (const x of decoys) await new Promise((d) => x.srv.close(() => d()));
  }
});

// ============================================================ H3 · la limpieza forma parte del resultado
test("H3 · el orquestador verifica la limpieza (contenedor, procesos propios, puertos y directorios) y un pendiente da código 3 sin eliminar nada ajeno", { skip: !isWindows ? "requiere Windows (PowerShell/Get-CimInstance)" : false, timeout: 120000 }, async () => {
  assert.match(runner, /if \(exitCode === 0\) exitCode = 3/);
  assert.match(runner, /LIMPIEZA PENDIENTE/);
  assert.match(runner, /cleanup = \{ ok: pending\.length === 0, pending \}/);
  const runId = "20261014T130000Z-9f8e7d6c";
  const work = mkdtempSync(join(tmpdir(), `e2eb0-${runId}-`));
  const d = await decoy(); // un puerto «reservado» ocupado por un servicio AJENO
  const alien = spawn(process.execPath, ["-e", "setInterval(() => {}, 1e6)", runId], { stdio: "ignore" }); // un proceso con el identificador de la corrida que sigue vivo
  try {
    await sleep(1500);
    const spec = join(tmpdir(), `e2eb0-spec-${Date.now()}.json`);
    writeFileSync(spec, JSON.stringify({ container: null, ports: [d.port], runId, work }));
    const dirty = runNode([RUNNER, "--self-test-cleanup", spec], {}, 90000);
    assert.equal(dirty.status, 3, dirty.stdout + dirty.stderr);
    const pending = JSON.parse(dirty.stdout.split("\n").find((l) => l.startsWith("CLEANUP_SELFTEST ")).slice("CLEANUP_SELFTEST ".length)).pending;
    assert.ok(pending.some((p) => p.resource === "puerto" && p.id === d.port), "informa el puerto ocupado");
    assert.ok(pending.some((p) => p.resource === "proceso" && p.id === alien.pid), "informa el proceso propio pendiente");
    assert.ok(pending.some((p) => p.resource === "directorio temporal" && p.id === work), "informa el directorio temporal pendiente");
    // la verificación solo informa: no mata procesos, no cierra puertos ni borra directorios
    assert.doesNotThrow(() => process.kill(alien.pid, 0), "el proceso no fue eliminado");
    assert.ok(existsSync(work), "el directorio no fue eliminado");
    assert.equal((await fetch(`http://127.0.0.1:${d.port}/`)).status, 200, "el servicio ajeno sigue atendiendo");
    // al liberar todo, la verificación es limpia
    spawnSync("taskkill", ["/PID", String(alien.pid), "/T", "/F"], { stdio: "ignore" }); await d.close(); rmSync(work, { recursive: true, force: true }); await sleep(1500);
    const ok = runNode([RUNNER, "--self-test-cleanup", spec], {}, 90000);
    assert.equal(ok.status, 0, ok.stdout + ok.stderr);
    assert.deepEqual(JSON.parse(ok.stdout.split("\n").find((l) => l.startsWith("CLEANUP_SELFTEST ")).slice("CLEANUP_SELFTEST ".length)).pending, []);
    rmSync(spec, { force: true });
  } finally { spawnSync("taskkill", ["/PID", String(alien.pid), "/T", "/F"], { stdio: "ignore" }); await d.close().catch(() => {}); rmSync(work, { recursive: true, force: true }); }
});

// ============================================================ H4 · resultados de la corrida
test("H4 · cada corrida usa su propio directorio y un directorio con resultados anteriores se rechaza sin tocarlos", async () => {
  assert.match(runner, /mkdirSync\(runDir\); \/\/ sin recursive: falla si existe/);
  assert.match(runner, /el directorio de evidencias \$\{runDir\} ya existe; cada corrida usa uno propio/);
  assert.match(driver, /\{ flag: "wx" \}/); // nunca sobrescribe
  const d = await decoy();
  try {
    const stale = scenario({}, { stale: true });
    const staleFile = join(stale.runDir, "resultados-e2e-b0.json"), snapshot = readFileSync(staleFile, "utf8");
    const r = runNode(stale.args);
    assert.equal(r.status, 2); assert.match(r.stderr, /ya contiene resultados anteriores incompatibles; no se sobrescriben/);
    assert.equal(readFileSync(staleFile, "utf8"), snapshot, "el archivo anterior no se modificó ni se borró");
    const foreignDir = scenario({}, { runDirName: "evidencias-manuales" });
    const r2 = runNode(foreignDir.args);
    assert.equal(r2.status, 2); assert.match(r2.stderr, /no corresponde al identificador de esta corrida/);
    assert.deepEqual(d.hits, []);
    rmSync(stale.dir, { recursive: true, force: true }); rmSync(foreignDir.dir, { recursive: true, force: true });
  } finally { await d.close(); }
});

test("H4 · el orquestador solo da por válidos unos resultados de ESTA corrida y de ESTE SHA con conteos coherentes y sin fallos", () => {
  const dir = mkdtempSync(join(tmpdir(), "e2eb0-resultstest-"));
  const spec = { file: join(dir, "resultados-e2e-b0.json"), runId: RUN_ID, commit: HEAD, database: "vinto_e2eb0_unit_test" };
  const specFile = join(dir, "spec.json"); writeFileSync(specFile, JSON.stringify(spec));
  const good = { runId: RUN_ID, commit: HEAD, database: "vinto_e2eb0_unit_test", total: 2, pass: 2, fail: 0, results: [{ ok: true }, { ok: true }] };
  const verdict = (data) => { if (data === null) rmSync(spec.file, { force: true }); else writeFileSync(spec.file, typeof data === "string" ? data : JSON.stringify(data)); const r = runNode([RUNNER, "--self-test-results", specFile]); return { status: r.status, v: JSON.parse(r.stdout.split("\n").find((l) => l.startsWith("RESULTS_SELFTEST ")).slice("RESULTS_SELFTEST ".length)) }; };
  assert.deepEqual([verdict(good).status, verdict(good).v.ok], [0, true]);
  for (const [data, fragment] of [
    [null, /no existe resultados-e2e-b0\.json/], ["no es json", /no es JSON válido/], [{ ...good, runId: "20261013T000000Z-deadbeef" }, /otra corrida/], [{ ...good, commit: "0".repeat(40) }, /otro SHA/],
    [{ ...good, database: "vinto_e2eb0_otra_test" }, /otra base/], [{ ...good, total: 3 }, /conteos/], [{ ...good, pass: 1 }, /conteos/], [{ ...good, results: [] , total: 0, pass: 0, fail: 0 }, /no contienen comprobaciones/],
    [{ ...good, total: 2, pass: 1, fail: 1, results: [{ ok: true }, { ok: false }] }, /comprobaciones fallidas/],
  ]) { const out = verdict(data); assert.equal(out.status, 1, JSON.stringify(data)); assert.equal(out.v.ok, false); assert.match(out.v.reason, fragment, JSON.stringify(data)); }
  rmSync(dir, { recursive: true, force: true });
  // el resumen final solo es «passed» si el recorrido, sus resultados y la limpieza fueron correctos
  assert.match(runner, /status: exitCode === 0 \? "passed" : "failed"/);
  assert.match(runner, /if \(exitCode === 0 && !verdict\.ok\)/);
  assert.match(driver, /runId: manifest\.runId, commit: manifest\.commit/);
});
