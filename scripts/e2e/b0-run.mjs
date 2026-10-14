// node scripts/e2e/b0-run.mjs <evidence-dir>
// E2E-B0 · orquestador local y AISLADO de la validación integral de Bobinas y Calidad. Levanta, solo para la prueba y solo en 127.0.0.1:
//   1. un PostgreSQL 17 EXCLUSIVO en un contenedor nuevo `vinto-e2eb0-pg` (datos en tmpfs, sin volumen, puerto 55432; nunca el 5432 de desarrollo), etiquetado con el identificador de la corrida;
//   2. el backend REAL (backend/tests/e2e_b0_server.py) sobre una base efímera `*_test` en ese PostgreSQL, puerto 8190, con la configuración real del producto;
//   3. el frontend REAL construido con NEXT_PUBLIC_API_URL=http://127.0.0.1:8190 y servido en el puerto 8796 (nunca 8787);
//   4. el recorrido de navegador y HTTP/SQL de scripts/e2e/b0-e2e.mjs, que solo recibe los destinos por el manifiesto de la corrida (nunca por variables de entorno).
// Cada corrida tiene un identificador único (`<fecha>-<aleatorio>`), su PROPIO subdirectorio de evidencias `<evidence-dir>/<runId>/` y queda vinculada al SHA probado: una corrida fallida no puede parecer
// exitosa por resultados de una ejecución anterior. Al terminar (también si falla) detiene los procesos, ELIMINA el contenedor y VERIFICA la limpieza; si algo propio queda pendiente, el código de salida es 3
// y el recurso pendiente se registra en `corrida.json`. No toca recursos ajenos (contenedor ni volumen `vinto-local-*`, ni otros procesos).
//
// Autopruebas sin servicios (usadas por scripts/e2e-b0-guard.test.mjs):
//   node scripts/e2e/b0-run.mjs --self-test-cleanup <spec.json>   verifica la limpieza de un conjunto de recursos dado (puertos, runId, directorio) y lista los pendientes
//   node scripts/e2e/b0-run.mjs --self-test-results <spec.json>   valida un `resultados-e2e-b0.json` frente a un runId y un SHA
import { execFileSync, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CONTAINER = "vinto-e2eb0-pg", PG_PORT = 55432, API_PORT = 8190, WEB_PORT = 8796, RUN_LABEL = "vinto.e2eb0.run";
const PORTS = [PG_PORT, API_PORT, WEB_PORT];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log(`[e2e-b0] ${m}`);
const die = (m) => { console.error(`E2E ABORTADO: ${m}`); process.exit(2); };
const docker = (...args) => execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
const portFree = (port) => new Promise((ok) => { const s = net.connect({ port, host: "127.0.0.1" }); s.on("connect", () => { s.destroy(); ok(false); }); s.on("error", () => ok(true)); });
const kill = (child) => { if (child?.pid) try { execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* ya terminó */ } };
const waitFor = async (what, test, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await test()) return; } catch { /* aún no */ } await sleep(1000); } throw new Error(`tiempo agotado esperando ${what}`); };
const psJson = (script) => JSON.parse(execFileSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], { encoding: "utf8" }).trim() || "[]");

// ---------------------------------------------------------------- H3: la limpieza forma parte del resultado
// Devuelve la lista de recursos PROPIOS de la corrida que siguen presentes. «Propio» = el contenedor con su nombre exacto o su etiqueta de corrida, los puertos reservados, los procesos cuya línea de
// comandos contiene el identificador de la corrida y los directorios temporales con ese identificador. Nunca elimina nada: solo informa.
function verifyCleanup({ container, ports, runId, work }) {
  const pending = [];
  if (container) {
    try {
      if (docker("ps", "-a", "--filter", `name=^${container}$`, "--format", "{{.Names}}")) pending.push({ resource: "contenedor", id: container });
      for (const name of docker("ps", "-a", "--filter", `label=${RUN_LABEL}=${runId}`, "--format", "{{.Names}}").split("\n").filter(Boolean)) if (name !== container) pending.push({ resource: "contenedor", id: name });
    } catch (error) { pending.push({ resource: "docker", id: container, detail: `no verificable: ${String(error.message).split("\n")[0]}` }); }
  }
  return Promise.all((ports ?? []).map(async (port) => ((await portFree(port)) ? null : { resource: "puerto", id: port }))).then((busy) => {
    pending.push(...busy.filter(Boolean));
    try {
      const own = psJson(`$r = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.Contains('${runId}') } | ForEach-Object { [pscustomobject]@{ pid = $_.ProcessId; name = $_.Name } }); ConvertTo-Json -InputObject $r -Compress`);
      for (const p of [own].flat().filter(Boolean)) pending.push({ resource: "proceso", id: p.pid, detail: p.name });
    } catch (error) { pending.push({ resource: "procesos", id: runId, detail: `no verificable: ${String(error.message).split("\n")[0]}` }); }
    if (work && existsSync(work)) pending.push({ resource: "directorio temporal", id: work });
    for (const entry of readdirSync(tmpdir()).filter((e) => e.startsWith(`e2eb0-${runId}`))) pending.push({ resource: "directorio temporal", id: join(tmpdir(), entry) });
    return pending;
  });
}

// ---------------------------------------------------------------- H4: los resultados deben pertenecer a ESTA corrida y a ESTE SHA
function validateResults(file, { runId, commit, database }) {
  if (!existsSync(file)) return { ok: false, reason: "no existe resultados-e2e-b0.json en el directorio de la corrida (el recorrido no llegó a escribirlos)" };
  let data; try { data = JSON.parse(readFileSync(file, "utf8")); } catch { return { ok: false, reason: "resultados-e2e-b0.json no es JSON válido" }; }
  if (data.runId !== runId) return { ok: false, reason: `los resultados pertenecen a otra corrida (${data.runId})` };
  if (data.commit !== commit) return { ok: false, reason: `los resultados pertenecen a otro SHA (${data.commit})` };
  if (database !== undefined && data.database !== database) return { ok: false, reason: "los resultados pertenecen a otra base" };
  if (!Array.isArray(data.results) || data.total !== data.results.length || data.fail !== data.results.filter((r) => !r.ok).length || data.pass !== data.total - data.fail) return { ok: false, reason: "los conteos de los resultados no coinciden con sus comprobaciones" };
  if (data.total === 0) return { ok: false, reason: "los resultados no contienen comprobaciones" };
  return { ok: data.fail === 0, reason: data.fail === 0 ? "ok" : `${data.fail} comprobaciones fallidas`, total: data.total, pass: data.pass, fail: data.fail };
}

// ---------------------------------------------------------------- autopruebas (sin Docker, sin servicios)
if (process.argv[2] === "--self-test-cleanup") {
  const spec = JSON.parse(readFileSync(process.argv[3], "utf8"));
  const pending = await verifyCleanup(spec);
  console.log("CLEANUP_SELFTEST " + JSON.stringify({ pending }));
  process.exit(pending.length ? 3 : 0);
}
if (process.argv[2] === "--self-test-results") {
  const spec = JSON.parse(readFileSync(process.argv[3], "utf8"));
  const verdict = validateResults(spec.file, spec);
  console.log("RESULTS_SELFTEST " + JSON.stringify(verdict));
  process.exit(verdict.ok ? 0 : 1);
}

// ---------------------------------------------------------------- precondiciones
const evidenceBase = resolve(process.argv[2] ?? join(root, "e2e-b0-evidence"));
for (const name of ["E2E_API", "E2E_WEB", "E2E_PG_CONTAINER", "E2E_CHROME"]) if (process.env[name] !== undefined) die(`la variable heredada ${name} no se admite: los destinos de E2E-B0 son fijos`);
const PYTHON = process.env.E2E_PYTHON ?? join(root, "backend", ".venv", "Scripts", "python.exe");
if (!existsSync(PYTHON)) die(`no existe el intérprete de Python del backend: ${PYTHON}`);
try { docker("info", "--format", "{{.ServerVersion}}"); } catch { die("el motor de Docker no está disponible"); }
if (docker("ps", "-a", "--filter", `name=^${CONTAINER}$`, "--format", "{{.Names}}")) die(`ya existe un contenedor ${CONTAINER}; no se reutiliza ni se borra automáticamente`);
for (const port of PORTS) if (!(await portFree(port))) die(`el puerto ${port} está ocupado`);
const runId = `${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z")}-${randomBytes(4).toString("hex")}`;
const runDir = join(evidenceBase, runId);
if (existsSync(runDir)) die(`el directorio de evidencias ${runDir} ya existe; cada corrida usa uno propio y no se reutiliza`);
mkdirSync(evidenceBase, { recursive: true });
mkdirSync(runDir); // sin recursive: falla si existe
const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
const dirty = execFileSync("git", ["status", "--porcelain"], { cwd: root, encoding: "utf8" }).trim().length > 0;
const startedAt = new Date().toISOString();
const work = mkdtempSync(join(tmpdir(), `e2eb0-${runId}-`));
const credsPath = join(work, "creds.json"), manifestPath = join(work, "manifest.json"), password = randomBytes(18).toString("base64url");
const summaryPath = join(runDir, "corrida.json");
const summary = { runId, commit, dirty, startedAt, status: "running", note: "Una corrida es válida solo si status = passed; resultados-e2e-b0.json de otra corrida no la hace exitosa." };
writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
const children = [];
let exitCode = 1, createdContainer = false, verdict = { ok: false, reason: "el recorrido no se ejecutó" }, database = null;
const versions = {};
try {
  log(`corrida ${runId} sobre ${commit.slice(0, 7)}${dirty ? " (árbol con cambios)" : ""}; evidencias en ${runDir}`);
  log("PostgreSQL exclusivo de E2E-B0 (contenedor nuevo, tmpfs, 127.0.0.1:" + PG_PORT + ")");
  docker("run", "-d", "--name", CONTAINER, "--label", `${RUN_LABEL}=${runId}`, "-e", "POSTGRES_USER=e2eb0", "-e", `POSTGRES_PASSWORD=${password}`, "-e", "POSTGRES_DB=postgres", "-p", `127.0.0.1:${PG_PORT}:5432`, "--tmpfs", "/var/lib/postgresql/data", "postgres:17");
  createdContainer = true;
  await waitFor("PostgreSQL", () => { docker("exec", CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", "e2eb0"); return true; }, 60000);
  versions.postgres = docker("exec", CONTAINER, "psql", "-U", "e2eb0", "-d", "postgres", "-Atc", "show server_version");
  const url = `postgresql://e2eb0:${password}@127.0.0.1:${PG_PORT}/postgres`, origin = `http://127.0.0.1:${WEB_PORT}`;
  const childEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^E2E_(API|WEB|PG_CONTAINER|CHROME)$/.test(k)));

  log("backend real sobre una base efímera *_test");
  const backend = spawn(PYTHON, ["-B", join("tests", "e2e_b0_server.py"), `--e2e-run=${runId}`], {
    cwd: join(root, "backend"), stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
    env: { ...childEnv, PYTHONPATH: ".", PYTHONUNBUFFERED: "1", APP_ENV: "local", TEST_DATABASE_URL: url, DATABASE_URL: url, CORS_ORIGINS: JSON.stringify([origin]), E2E_PORT: String(API_PORT), E2E_ORIGIN: origin, E2E_OUT: credsPath },
  });
  children.push(backend);
  let backendOut = ""; for (const s of [backend.stdout, backend.stderr]) s.on("data", (d) => { backendOut += d; });
  await waitFor("el backend de prueba", () => { if (/E2E ABORTADO|Traceback/.test(backendOut)) throw new Error(backendOut.slice(-600).replaceAll(password, "***")); return backendOut.includes("E2E LISTO"); }, 120000);
  versions.python = execFileSync(PYTHON, ["--version"], { encoding: "utf8" }).trim();

  log("frontend real (build con NEXT_PUBLIC_API_URL de E2E-B0) en 127.0.0.1:" + WEB_PORT);
  execFileSync(process.execPath, [join(root, "scripts", "run-framework.mjs"), "build"], { cwd: root, stdio: "ignore", env: { ...childEnv, NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API_PORT}` } });
  const web = spawn(process.execPath, ["--import", "./scripts/sites-env.mjs", "./node_modules/wrangler/bin/wrangler.js", "dev", "--config", "dist/server/wrangler.json", "--local", "--persist-to", join(work, "wrangler"), "--ip", "127.0.0.1", "--port", String(WEB_PORT), "--inspector-port", "0"], { cwd: root, stdio: "ignore", windowsHide: true, env: childEnv });
  children.push(web);
  await waitFor("el frontend", async () => (await fetch(`${origin}/`)).status === 200, 120000);
  versions.node = process.version;
  versions.chrome = (() => { try { return execFileSync("powershell", ["-NoProfile", "-Command", "(Get-Item 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe').VersionInfo.ProductVersion"], { encoding: "utf8" }).trim(); } catch { return "desconocida"; } })();
  const credsPublic = JSON.parse(readFileSync(credsPath, "utf8"));
  database = credsPublic.database;
  const manifest = { runId, commit, dirty, startedAt, api: `http://127.0.0.1:${API_PORT}`, web: origin, container: CONTAINER, pgPort: PG_PORT, database, backendPid: backend.pid, webPid: web.pid };
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  writeFileSync(join(runDir, "entorno-e2e-b0.json"), JSON.stringify({ ...versions, runId, commit, dirty, database, api: manifest.api, web: manifest.web, postgresContainer: CONTAINER, postgresPort: PG_PORT }, null, 2));

  log("recorrido E2E-B0 (navegador + HTTP + SQL)");
  const driver = spawn(process.execPath, [join(root, "scripts", "e2e", "b0-e2e.mjs"), credsPath, runDir, manifestPath], { cwd: root, stdio: "inherit", env: childEnv });
  exitCode = await new Promise((ok) => driver.on("exit", (code) => ok(code ?? 1)));
  verdict = validateResults(join(runDir, "resultados-e2e-b0.json"), { runId, commit, database });
  if (exitCode === 0 && !verdict.ok) { log(`el recorrido terminó con código 0 pero sus resultados no son válidos: ${verdict.reason}`); exitCode = 1; }
  if (exitCode !== 0 && verdict.ok) { log("el recorrido terminó con error aunque sus resultados no tienen fallos"); }
} catch (error) {
  console.error("E2E-B0 falló antes de completar el recorrido:", String(error.message).replaceAll(password, "***"));
  exitCode = 2;
  verdict = { ok: false, reason: `la corrida se interrumpió: ${String(error.message).split("\n")[0].replaceAll(password, "***")}` };
} finally {
  for (const child of [...children].reverse()) kill(child);
  await sleep(1500);
  if (createdContainer) { try { docker("rm", "-f", "-v", CONTAINER); log("contenedor de PostgreSQL de E2E-B0 eliminado (con todas sus bases efímeras)"); } catch (e) { console.error("No se pudo eliminar el contenedor:", e.message); } }
  try { rmSync(work, { recursive: true, force: true }); } catch { /* se informa abajo si queda */ }
  const pending = await verifyCleanup({ container: CONTAINER, ports: PORTS, runId, work });
  const cleanup = { ok: pending.length === 0, pending };
  if (pending.length) { for (const p of pending) console.error(`LIMPIEZA PENDIENTE: ${p.resource} ${p.id}${p.detail ? " (" + p.detail + ")" : ""}`); if (exitCode === 0) exitCode = 3; }
  else log("limpieza verificada: sin contenedor, procesos, puertos ni directorios temporales propios pendientes");
  const finalSummary = { ...summary, finishedAt: new Date().toISOString(), status: exitCode === 0 ? "passed" : "failed", exitCode, results: verdict, cleanup, database };
  writeFileSync(summaryPath, JSON.stringify(finalSummary, null, 2));
  log(`corrida ${runId}: ${finalSummary.status.toUpperCase()} (código ${exitCode})`);
}
process.exit(exitCode);
