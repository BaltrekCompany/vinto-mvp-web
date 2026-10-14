// node scripts/e2e/b0-run.mjs <evidence-dir>
// E2E-B0 · orquestador local y AISLADO de la validación integral de Bobinas y Calidad. Levanta, solo para la prueba y solo en 127.0.0.1:
//   1. un PostgreSQL 17 EXCLUSIVO en un contenedor nuevo `vinto-e2eb0-pg` (datos en tmpfs, sin volumen, puerto 55432; nunca el 5432 de desarrollo);
//   2. el backend REAL (backend/tests/e2e_b0_server.py) sobre una base efímera `*_test` en ese PostgreSQL, puerto 8190, con la configuración real del producto;
//   3. el frontend REAL construido con NEXT_PUBLIC_API_URL=http://127.0.0.1:8190 y servido en el puerto 8796 (nunca 8787);
//   4. el recorrido de navegador y HTTP/SQL de scripts/e2e/b0-e2e.mjs.
// Al terminar (también si falla) detiene los procesos y ELIMINA el contenedor (y con él todas las bases creadas). No toca el contenedor ni el volumen de desarrollo `vinto-local-*`.
// Rechaza la ejecución si el contenedor, algún puerto o la ruta de Python ya existen/están ocupados. Las credenciales de prueba son efímeras, viven en el directorio temporal y se borran.
import { execFileSync, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const evidenceDir = resolve(process.argv[2] ?? join(root, "e2e-b0-evidence"));
const CONTAINER = "vinto-e2eb0-pg", PG_PORT = 55432, API_PORT = 8190, WEB_PORT = 8796;
const PYTHON = process.env.E2E_PYTHON ?? join(root, "backend", ".venv", "Scripts", "python.exe");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log(`[e2e-b0] ${m}`);
const die = (m) => { console.error(`E2E ABORTADO: ${m}`); process.exit(2); };
const docker = (...args) => execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, MSYS_NO_PATHCONV: "1" } }).trim();
const portFree = (port) => new Promise((ok) => { const s = net.connect({ port, host: "127.0.0.1" }); s.on("connect", () => { s.destroy(); ok(false); }); s.on("error", () => ok(true)); });
const kill = (child) => { if (child?.pid) try { execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" }); } catch { /* ya terminó */ } };
const waitFor = async (what, test, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await test()) return; } catch { /* aún no */ } await sleep(1000); } throw new Error(`tiempo agotado esperando ${what}`); };

// ---- precondiciones
if (!existsSync(PYTHON)) die(`no existe el intérprete de Python del backend: ${PYTHON}`);
try { docker("info", "--format", "{{.ServerVersion}}"); } catch { die("el motor de Docker no está disponible"); }
if (docker("ps", "-a", "--filter", `name=^${CONTAINER}$`, "--format", "{{.Names}}")) die(`ya existe un contenedor ${CONTAINER}; no se reutiliza ni se borra automáticamente`);
for (const port of [PG_PORT, API_PORT, WEB_PORT]) if (!(await portFree(port))) die(`el puerto ${port} está ocupado`);
mkdirSync(evidenceDir, { recursive: true });
const work = mkdtempSync(join(tmpdir(), "e2eb0-"));
const credsPath = join(work, "creds.json"), password = randomBytes(18).toString("base64url");
const children = [];
let exitCode = 1, createdContainer = false;
const versions = {};
try {
  log("PostgreSQL exclusivo de E2E-B0 (contenedor nuevo, tmpfs, 127.0.0.1:" + PG_PORT + ")");
  docker("run", "-d", "--name", CONTAINER, "-e", "POSTGRES_USER=e2eb0", "-e", `POSTGRES_PASSWORD=${password}`, "-e", "POSTGRES_DB=postgres", "-p", `127.0.0.1:${PG_PORT}:5432`, "--tmpfs", "/var/lib/postgresql/data", "postgres:17");
  createdContainer = true;
  await waitFor("PostgreSQL", () => { docker("exec", CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", "e2eb0"); return true; }, 60000);
  versions.postgres = docker("exec", CONTAINER, "psql", "-U", "e2eb0", "-d", "postgres", "-Atc", "show server_version");
  const url = `postgresql://e2eb0:${password}@127.0.0.1:${PG_PORT}/postgres`, origin = `http://127.0.0.1:${WEB_PORT}`;

  log("backend real sobre una base efímera *_test");
  const backendLog = join(work, "backend.log");
  const backend = spawn(PYTHON, ["-B", join("tests", "e2e_b0_server.py")], {
    cwd: join(root, "backend"), stdio: ["ignore", "pipe", "pipe"], windowsHide: true,
    env: { ...process.env, PYTHONPATH: ".", PYTHONUNBUFFERED: "1", APP_ENV: "local", TEST_DATABASE_URL: url, DATABASE_URL: url, CORS_ORIGINS: JSON.stringify([origin]), E2E_PORT: String(API_PORT), E2E_ORIGIN: origin, E2E_OUT: credsPath },
  });
  children.push(backend);
  let backendOut = ""; for (const s of [backend.stdout, backend.stderr]) s.on("data", (d) => { backendOut += d; });
  await waitFor("el backend de prueba", () => { if (/E2E ABORTADO|Traceback/.test(backendOut)) throw new Error(backendOut.slice(-600)); return backendOut.includes("E2E LISTO"); }, 120000);
  writeFileSync(backendLog, backendOut.replace(password, "***"));
  versions.python = execFileSync(PYTHON, ["--version"], { encoding: "utf8" }).trim();

  log("frontend real (build con NEXT_PUBLIC_API_URL de E2E-B0) en 127.0.0.1:" + WEB_PORT);
  execFileSync(process.execPath, [join(root, "scripts", "run-framework.mjs"), "build"], { cwd: root, stdio: "ignore", env: { ...process.env, NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API_PORT}` } });
  const web = spawn(process.execPath, ["--import", "./scripts/sites-env.mjs", "./node_modules/wrangler/bin/wrangler.js", "dev", "--config", "dist/server/wrangler.json", "--local", "--persist-to", join(work, "wrangler"), "--ip", "127.0.0.1", "--port", String(WEB_PORT), "--inspector-port", "0"], { cwd: root, stdio: "ignore", windowsHide: true });
  children.push(web);
  await waitFor("el frontend", async () => (await fetch(`${origin}/`)).status === 200, 120000);
  versions.node = process.version;
  versions.chrome = (() => { try { return execFileSync("powershell", ["-NoProfile", "-Command", "(Get-Item 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe').VersionInfo.ProductVersion"], { encoding: "utf8" }).trim(); } catch { return "desconocida"; } })();
  versions.commit = (() => { try { return execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim(); } catch { return "desconocido"; } })();
  const credsPublic = JSON.parse(readFileSync(credsPath, "utf8"));
  writeFileSync(join(evidenceDir, "entorno-e2e-b0.json"), JSON.stringify({ ...versions, database: credsPublic.database, api: `http://127.0.0.1:${API_PORT}`, web: origin, postgresContainer: CONTAINER, postgresPort: PG_PORT }, null, 2));

  log("recorrido E2E-B0 (navegador + HTTP + SQL)");
  const driver = spawn(process.execPath, [join(root, "scripts", "e2e", "b0-e2e.mjs"), credsPath, evidenceDir], { cwd: root, stdio: "inherit" });
  exitCode = await new Promise((ok) => driver.on("exit", (code) => ok(code ?? 1)));
} catch (error) {
  console.error("E2E-B0 falló antes de completar el recorrido:", error.message);
  exitCode = 2;
} finally {
  for (const child of children.reverse()) kill(child);
  await sleep(1500);
  if (createdContainer) { try { docker("rm", "-f", "-v", CONTAINER); log("contenedor de PostgreSQL de E2E-B0 eliminado (con todas sus bases efímeras)"); } catch (e) { console.error("No se pudo eliminar el contenedor:", e.message); exitCode = exitCode || 3; } }
  try { rmSync(work, { recursive: true, force: true }); } catch { /* temporal */ }
  const leftovers = docker("ps", "-a", "--filter", `name=${CONTAINER}`, "--format", "{{.Names}}");
  log(`limpieza: contenedores restantes de E2E-B0 = ${leftovers ? leftovers : "ninguno"}; puertos libres = ${(await Promise.all([PG_PORT, API_PORT, WEB_PORT].map(portFree))).every(Boolean)}`);
}
process.exit(exitCode);
