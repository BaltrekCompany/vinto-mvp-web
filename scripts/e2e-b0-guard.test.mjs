// node --test scripts/e2e-b0-guard.test.mjs
// E2E-B0 · guarda estática del aislamiento de la validación integral de Bobinas y Calidad: el orquestador, el servidor de prueba y el recorrido no pueden apuntar a DEV/PROD, no modifican la
// configuración real de sectores ni de formularios centrales, y el recorrido conserva los casos E01..E11 y las salvaguardas. No ejecuta el recorrido (eso requiere Docker y Chrome: `node scripts/e2e/b0-run.mjs`).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const runner = read("scripts/e2e/b0-run.mjs"), driver = read("scripts/e2e/b0-e2e.mjs"), server = read("backend/tests/e2e_b0_server.py");
const strip = (text) => text.split("\n").filter((l) => !/^\s*(\/\/|#)/.test(l)).join("\n");

test("el orquestador usa un PostgreSQL exclusivo en un contenedor nuevo, en 127.0.0.1 y fuera de los puertos de desarrollo", () => {
  assert.match(runner, /CONTAINER = "vinto-e2eb0-pg", PG_PORT = 55432, API_PORT = 8190, WEB_PORT = 8796/);
  for (const forbidden of [5432, 8000, 8787]) assert.equal(new RegExp(`(PG_PORT|API_PORT|WEB_PORT) = ${forbidden}\\b`).test(runner), false, `puerto ${forbidden}`);
  assert.match(runner, /"--tmpfs", "\/var\/lib\/postgresql\/data"/); // sin volumen persistente
  assert.match(runner, /127\.0\.0\.1:\$\{PG_PORT\}:5432/);
  assert.equal(/--volume|"-v", "[^"]*:[^"]*"|volumes:/.test(runner), false, "sin volúmenes montados");
  assert.match(runner, /ya existe un contenedor \$\{CONTAINER\}; no se reutiliza ni se borra automáticamente/);
  assert.match(runner, /docker\("rm", "-f", "-v", CONTAINER\)/);
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
  assert.match(code, /connect\(database\)/); // conexión protegida por connect_test_database (current_database())
  assert.equal(/install_(rebobinado|p110|grouped|p129)|install_tubetera/.test(code), false, "sin fixtures de otros sectores ni formularios sintéticos");
  assert.match(code, /drop_database\(name\)/);
});

test("el recorrido aborta si la API o el frontend son los de DEV, si el contenedor no es el de E2E-B0 o si la base no es efímera, y solo escribe en el directorio de evidencias", () => {
  assert.match(driver, /apiUrl\.port === "8000" \|\| webUrl\.port === "8787" \|\| apiUrl\.port === "5432"/);
  assert.match(driver, /apiUrl\.hostname !== "127\.0\.0\.1" \|\| webUrl\.hostname !== "127\.0\.0\.1"/);
  assert.match(driver, /\^vinto-e2eb0-/);
  assert.match(driver, /\["vinto", "vinto_test", "postgres"\]\.includes\(database\)/);
  assert.match(driver, /SELECT current_database\(\)/);
  assert.match(driver, /BEGIN READ ONLY/);
  assert.equal(/INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER/.test(strip(driver).replace(/UPDATE\b[^\n]*audit/gi, "")), false, "el recorrido no escribe por SQL");
  assert.match(driver, /port === "8000"/); // el navegador aborta si llama al puerto de DEV (copiado del arnés de M4-A)
  assert.match(driver, /Z3 aislamiento/);
});

test("el recorrido conserva los casos E01 a E11, las comprobaciones de robustez y el cierre sin simular resultados", () => {
  for (let n = 1; n <= 11; n++) assert.match(driver, new RegExp(`"E${String(n).padStart(2, "0")}\\.`), `caso E${n}`);
  for (const id of ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "Z1", "Z2", "Z3", "Z4", "Z5"]) assert.match(driver, new RegExp(`"${id} `), id);
  assert.match(driver, /kind = "browser"/); // distingue navegador, HTTP, SQL y estático
  assert.equal(/check\([^)]*,\s*true\s*[,)]/.test(strip(driver).replace(/check\("S0 [^\n]*/, "")), false, "ninguna comprobación se marca PASS incondicionalmente");
  assert.match(driver, /process\.exit\(fails\.length \? 1 : 0\)/);
});

test("el recorrido de Calidad no ofrece ni sondea acciones de liberación o rechazo como funcionalidad existente", () => {
  assert.match(driver, /E09\.9 el contrato OpenAPI no contiene rutas de liberación, rechazo ni decisión de Calidad/);
  assert.match(driver, /E09\.10 sondeo directo/);
  assert.match(driver, /E09\.2 PostgreSQL: tras todas las capturas de Calidad, ninguna bobina fue liberada ni rechazada/);
  assert.equal(/\/release|\/reject/.test(strip(driver).replace(/for \(const verb of \[[^\]]*\]\)[^\n]*/, "")), false);
});
