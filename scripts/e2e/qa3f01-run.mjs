// node scripts/e2e/qa3f01-run.mjs <evidence-dir>
// QA-3F-01 · orquestador local y AISLADO de la integración E2E de los TRES frentes (Bobinas, Rebobinado, Conversión) y Calidad en UNA sola instancia
// y base de datos. Derivado de scripts/e2e/b0-run.mjs (mismas salvaguardas de aislamiento); añade una SEGUNDA fase con la misma infraestructura.
// Levanta, solo para la prueba y solo en 127.0.0.1:
//   1. un PostgreSQL 17 EXCLUSIVO en un contenedor NUEVO `vinto-qa3f01-pg` (datos en tmpfs, sin volumen, puerto 55440; nunca el 5432 de desarrollo
//      ni el contenedor `vinto-local-postgres-1` del stack de desarrollo), etiquetado con el identificador de la corrida;
//   2. el frontend REAL (SIN ruta de QA) construido UNA vez con NEXT_PUBLIC_API_URL=http://127.0.0.1:8192 y servido en el puerto 8799;
//   3. FASE A «habilitada»: el backend REAL (backend/tests/e2e_qa3f01_server.py, E2E_3F=on) sobre una base efímera `*_test` nueva, con los tres
//      sectores y VINTO-P1-06/P1-10/P1-16 habilitados SOLO en ese proceso; corre scripts/e2e/qa3f01-e2e.mjs <enabled>;
//   4. FASE B «política cerrada»: el MISMO backend (E2E_3F=off) sobre OTRA base efímera `*_test` nueva (nunca la de la fase A), con la
//      configuración REAL (solo BOBINAS operativo); corre scripts/e2e/qa3f01-e2e.mjs <closed>.
// Cada corrida tiene un identificador único (`<fecha>-<aleatorio>`), su PROPIO subdirectorio de evidencias `<evidence-dir>/<runId>/` y queda
// vinculada al SHA probado. Al terminar (también si falla) detiene los procesos, ELIMINA el contenedor y VERIFICA la limpieza; si algo propio
// queda pendiente, el código de salida es 3. No toca recursos ajenos (contenedor ni volumen `vinto-local-*`, ni otros procesos, ni DEV/PROD).
import { execFileSync, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CONTAINER = "vinto-qa3f01-pg", PG_PORT = 55440, API_PORT = 8192, WEB_PORT = 8799, RUN_LABEL = "vinto.qa3f01.run";
const PORTS = [PG_PORT, API_PORT, WEB_PORT];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log(`[qa-3f-01] ${m}`);
const die = (m) => { console.error(`E2E ABORTADO: ${m}`); process.exit(2); };
const docker = (...args) => execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
const portFree = (port) => new Promise((ok) => { const s = net.connect({ port, host: "127.0.0.1" }); s.on("connect", () => { s.destroy(); ok(false); }); s.on("error", () => ok(true)); });
const kill = (child) => { if (child?.pid) try { execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* ya terminó */ } };
const waitFor = async (what, test, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await test()) return; } catch { /* aún no */ } await sleep(1000); } throw new Error(`tiempo agotado esperando ${what}`); };
const psJson = (script) => JSON.parse(execFileSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], { encoding: "utf8" }).trim() || "[]");

// ---------------------------------------------------------------- limpieza propia (igual criterio que b0-run.mjs)
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
    for (const entry of readdirSync(tmpdir()).filter((e) => e.startsWith(`qa3f01-${runId}`))) pending.push({ resource: "directorio temporal", id: join(tmpdir(), entry) });
    return pending;
  });
}

function validateResults(file, { runId, commit, database }) {
  if (!existsSync(file)) return { ok: false, reason: `no existe ${file} (el recorrido no llegó a escribirlos)` };
  let data; try { data = JSON.parse(readFileSync(file, "utf8")); } catch { return { ok: false, reason: `${file} no es JSON válido` }; }
  if (data.runId !== runId) return { ok: false, reason: `los resultados pertenecen a otra corrida (${data.runId})` };
  if (data.commit !== commit) return { ok: false, reason: `los resultados pertenecen a otro SHA (${data.commit})` };
  if (database !== undefined && data.database !== database) return { ok: false, reason: "los resultados pertenecen a otra base" };
  if (!Array.isArray(data.results) || data.total !== data.results.length || data.fail !== data.results.filter((r) => !r.ok).length || data.pass !== data.total - data.fail) return { ok: false, reason: "los conteos de los resultados no coinciden con sus comprobaciones" };
  if (data.total === 0) return { ok: false, reason: "los resultados no contienen comprobaciones" };
  return { ok: data.fail === 0, reason: data.fail === 0 ? "ok" : `${data.fail} comprobaciones fallidas`, total: data.total, pass: data.pass, fail: data.fail };
}

// ---------------------------------------------------------------- precondiciones
const evidenceBase = resolve(process.argv[2] ?? join(root, "qa3f01-evidence"));
for (const name of ["E2E_API", "E2E_WEB", "E2E_PG_CONTAINER", "E2E_CHROME", "E2E_3F"]) if (process.env[name] !== undefined) die(`la variable heredada ${name} no se admite: los destinos de QA-3F-01 son fijos`);
const PYTHON = process.env.E2E_PYTHON ?? join(root, "backend", ".venv", "Scripts", "python.exe");
if (!existsSync(PYTHON)) die(`no existe el intérprete de Python del backend: ${PYTHON}`);
try { docker("info", "--format", "{{.ServerVersion}}"); } catch { die("el motor de Docker no está disponible"); }
if (docker("ps", "-a", "--filter", `name=^${CONTAINER}$`, "--format", "{{.Names}}")) die(`ya existe un contenedor ${CONTAINER}; no se reutiliza ni se borra automáticamente`);
for (const port of PORTS) if (!(await portFree(port))) die(`el puerto ${port} está ocupado`);
const runId = `${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z")}-${randomBytes(4).toString("hex")}`;
const runDir = join(evidenceBase, runId);
if (existsSync(runDir)) die(`el directorio de evidencias ${runDir} ya existe; cada corrida usa uno propio y no se reutiliza`);
mkdirSync(evidenceBase, { recursive: true });
mkdirSync(runDir);
const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
const dirty = execFileSync("git", ["status", "--porcelain"], { cwd: root, encoding: "utf8" }).trim().length > 0;
const startedAt = new Date().toISOString();
const work = mkdtempSync(join(tmpdir(), `qa3f01-${runId}-`));
const manifestPath = (phase) => join(work, `manifest-${phase}.json`);
const credsPath = (phase) => join(work, `creds-${phase}.json`);
const password = randomBytes(18).toString("base64url");
const summaryPath = join(runDir, "corrida.json");
const summary = { runId, commit, dirty, startedAt, status: "running", note: "Una corrida es válida solo si status = passed; resultados de otra corrida no la hacen exitosa." };
writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
let exitCode = 1, createdContainer = false, webChild = null;
const phases = {};
const versions = {};

async function runPhase(phase) {
  log(`FASE ${phase === "enabled" ? "A: HABILITADA (Bobinas + Rebobinado + Conversión)" : "B: POLÍTICA CERRADA (configuración real)"}`);
  const url = `postgresql://qa3f01:${password}@127.0.0.1:${PG_PORT}/postgres`, origin = `http://127.0.0.1:${WEB_PORT}`;
  const childEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^E2E_(API|WEB|PG_CONTAINER|CHROME|3F)$/.test(k)));
  const backend = spawn(PYTHON, ["-B", join("tests", "e2e_qa3f01_server.py")], {
    cwd: join(root, "backend"), stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
    env: {
      ...childEnv, PYTHONPATH: ".", PYTHONUNBUFFERED: "1", APP_ENV: "local", TEST_DATABASE_URL: url, DATABASE_URL: url,
      CORS_ORIGINS: JSON.stringify([origin]), E2E_PORT: String(API_PORT), E2E_ORIGIN: origin, E2E_OUT: credsPath(phase), E2E_3F: phase === "enabled" ? "on" : "off",
    },
  });
  let backendOut = ""; for (const s of [backend.stdout, backend.stderr]) s.on("data", (d) => { backendOut += d; });
  try {
    await waitFor(`el backend de prueba (fase ${phase})`, () => { if (/E2E ABORTADO|Traceback/.test(backendOut)) throw new Error(backendOut.slice(-600).replaceAll(password, "***")); return backendOut.includes("E2E LISTO"); }, 120000);
    const credsPublic = JSON.parse(readFileSync(credsPath(phase), "utf8"));
    const database = credsPublic.database;
    const manifest = { runId, commit, dirty, startedAt, phase, api: `http://127.0.0.1:${API_PORT}`, web: origin, container: CONTAINER, pgPort: PG_PORT, database, backendPid: backend.pid, webPid: webChild.pid };
    writeFileSync(manifestPath(phase), JSON.stringify(manifest, null, 2));
    writeFileSync(join(runDir, `entorno-qa3f01-${phase}.json`), JSON.stringify({ ...versions, runId, commit, dirty, phase, database, api: manifest.api, web: manifest.web, postgresContainer: CONTAINER, postgresPort: PG_PORT }, null, 2));
    log(`recorrido QA-3F-01 (navegador + HTTP + SQL), fase ${phase}, base ${database}`);
    const driver = spawn(process.execPath, [join(root, "scripts", "e2e", "qa3f01-e2e.mjs"), credsPath(phase), runDir, manifestPath(phase), phase], { cwd: root, stdio: "inherit", env: childEnv });
    const driverExit = await new Promise((ok) => driver.on("exit", (code) => ok(code ?? 1)));
    const verdict = validateResults(join(runDir, `resultados-qa3f01-${phase}.json`), { runId, commit, database });
    let code = driverExit;
    if (driverExit === 0 && !verdict.ok) { log(`fase ${phase}: código 0 pero resultados inválidos: ${verdict.reason}`); code = 1; }
    if (driverExit !== 0 && verdict.ok) log(`fase ${phase}: código de error aunque los resultados no tienen fallos`);
    phases[phase] = { database, exitCode: code, verdict };
    return code;
  } finally {
    // taskkill /F termina el proceso de inmediato (no entrega SIGTERM de forma que Python pueda interceptarlo en Windows), así que su bloque
    // `finally` (DROP de sus bases efímeras, "E2E LIMPIO") no llega a ejecutarse de forma fiable; no se espera esa confirmación. La garantía real
    // de limpieza es eliminar el CONTENEDOR completo al final de la corrida (abajo), que borra todas las bases efímeras sin depender de ello.
    kill(backend);
    await sleep(1000);
  }
}

try {
  log(`corrida ${runId} sobre ${commit.slice(0, 7)}${dirty ? " (árbol con cambios)" : ""}; evidencias en ${runDir}`);
  log("PostgreSQL exclusivo de QA-3F-01 (contenedor nuevo, tmpfs, 127.0.0.1:" + PG_PORT + ")");
  docker("run", "-d", "--name", CONTAINER, "--label", `${RUN_LABEL}=${runId}`, "-e", "POSTGRES_USER=qa3f01", "-e", `POSTGRES_PASSWORD=${password}`, "-e", "POSTGRES_DB=postgres", "-p", `127.0.0.1:${PG_PORT}:5432`, "--tmpfs", "/var/lib/postgresql/data", "postgres:17");
  createdContainer = true;
  await waitFor("PostgreSQL", () => { docker("exec", CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", "qa3f01"); return true; }, 60000);
  versions.postgres = docker("exec", CONTAINER, "psql", "-U", "qa3f01", "-d", "postgres", "-Atc", "show server_version");

  const origin = `http://127.0.0.1:${WEB_PORT}`;
  const childEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^E2E_(API|WEB|PG_CONTAINER|CHROME|3F)$/.test(k)));
  log("frontend real (build con NEXT_PUBLIC_API_URL de QA-3F-01) en 127.0.0.1:" + WEB_PORT);
  execFileSync(process.execPath, [join(root, "scripts", "run-framework.mjs"), "build"], { cwd: root, stdio: "ignore", env: { ...childEnv, NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API_PORT}` } });
  webChild = spawn(process.execPath, ["--import", "./scripts/sites-env.mjs", "./node_modules/wrangler/bin/wrangler.js", "dev", "--config", "dist/server/wrangler.json", "--local", "--persist-to", join(work, "wrangler"), "--ip", "127.0.0.1", "--port", String(WEB_PORT), "--inspector-port", "0"], { cwd: root, stdio: "ignore", windowsHide: true, env: childEnv });
  await waitFor("el frontend", async () => (await fetch(`${origin}/`)).status === 200, 120000);
  versions.node = process.version;
  versions.python = execFileSync(PYTHON, ["--version"], { encoding: "utf8" }).trim();
  versions.chrome = (() => { try { return execFileSync("powershell", ["-NoProfile", "-Command", "(Get-Item 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe').VersionInfo.ProductVersion"], { encoding: "utf8" }).trim(); } catch { return "desconocida"; } })();

  const codeA = await runPhase("enabled");
  const codeB = await runPhase("closed");
  exitCode = codeA === 0 && codeB === 0 ? 0 : 1;
} catch (error) {
  console.error("QA-3F-01 falló antes de completar el recorrido:", String(error.message).replaceAll(password, "***"));
  exitCode = 2;
  phases.error = String(error.message).split("\n")[0].replaceAll(password, "***");
} finally {
  kill(webChild);
  await sleep(1500);
  if (createdContainer) { try { docker("rm", "-f", "-v", CONTAINER); log("contenedor de PostgreSQL de QA-3F-01 eliminado (con todas sus bases efímeras)"); } catch (e) { console.error("No se pudo eliminar el contenedor:", e.message); } }
  try { rmSync(work, { recursive: true, force: true }); } catch { /* se informa abajo si queda */ }
  const pending = await verifyCleanup({ container: CONTAINER, ports: PORTS, runId, work });
  const cleanup = { ok: pending.length === 0, pending };
  if (pending.length) { for (const p of pending) console.error(`LIMPIEZA PENDIENTE: ${p.resource} ${p.id}${p.detail ? " (" + p.detail + ")" : ""}`); if (exitCode === 0) exitCode = 3; }
  else log("limpieza verificada: sin contenedor, procesos, puertos ni directorios temporales propios pendientes");
  const finalSummary = { ...summary, finishedAt: new Date().toISOString(), status: exitCode === 0 ? "passed" : "failed", exitCode, phases, cleanup };
  writeFileSync(summaryPath, JSON.stringify(finalSummary, null, 2));
  log(`corrida ${runId}: ${finalSummary.status.toUpperCase()} (código ${exitCode})`);
}
process.exit(exitCode);
