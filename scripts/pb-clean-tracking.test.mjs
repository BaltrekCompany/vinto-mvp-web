// node --test scripts/pb-clean-tracking.test.mjs
// PB-CLEAN (actualizado en INT-02A) · regresión del saneamiento de Seguimiento de Bobinas y Calidad: sin datos ficticios, sin liberaciones simuladas, sin conteos locales presentados como indicadores,
// sin ceros que representen un estado desconocido y sin reportes que parezcan operativos. La lógica de presentación del conteo se prueba en ejecución; el resto es regresión estática sobre el código fuente
// (el repositorio no renderiza React en pruebas Node). No valida reglas industriales ni sustituye una prueba de navegador.
//
// CAMBIO DE CONTRATO (INT-02A): antes Seguimiento mostraba, como dato secundario rotulado, el conteo y las descargas de los registros LOCALES del navegador (vinto-p1-records). Ahora la operación es
// exclusivamente central: Seguimiento ya no lee, muestra, descarga ni menciona esos registros (siguen intactos en el navegador, sin visor), y la pantalla ya no escribe en localStorage.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { captureCountView, CENTRAL_LABEL, VALUE_UNKNOWN } from "../lib/vinto/capture-count-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const page = read("app/page.tsx"), pending = read("components/vinto/tracking-pending.tsx"), counter = read("components/vinto/capture-count.tsx");
const trackingBody = page.slice(page.indexOf("function Tracking("), page.indexOf("// ====", page.indexOf("function Tracking(")));

test("1 · no se representa la bobina ficticia BM-2609-001 en el código de la aplicación", () => {
  for (const file of ["app/page.tsx", "components/vinto/tracking-pending.tsx", "components/vinto/capture-count.tsx", "lib/vinto/capture-count-view.ts"]) assert.equal(/BM-2609-001/.test(read(file)), false, file);
});

test("2 · no hay métricas de liberaciones originadas en estado local: ni tipo Release, ni estado `releases`, ni ReleaseCards, ni acciones Liberar/Rechazar", () => {
  assert.equal(/type Release\b|\breleases\b|setReleases|ReleaseCards|Liberada|Rechazada/.test(page), false);
  assert.equal(/Liberar|Rechazar/.test(page), false);
  assert.equal(/"quality\.release"/.test(page), false);
  assert.equal(/<Metric label="Bobinas liberadas"/.test(page), false);
  assert.match(trackingBody, /<PendingMetric label="Bobinas liberadas" note="Sin fuente central/);
});

test("3 · un estado real desconocido no se muestra como cero: el valor principal es «—» y ningún conteo local se menciona ni se suma", () => {
  assert.equal(VALUE_UNKNOWN, "—");
  const states = [{ status: "loading" }, { status: "failed", kind: "unavailable" }, { status: "failed", kind: "forbidden" }, { status: "failed", kind: "session" }];
  for (const state of states) {
    const view = captureCountView(state, "Bobinas");
    assert.equal(view.value, "—", JSON.stringify(state));
    assert.equal(view.label, CENTRAL_LABEL);
    assert.notEqual(view.value, "0");
  }
  assert.match(captureCountView({ status: "failed", kind: "unavailable" }, "Bobinas").note, /Consulta central no disponible/);
  assert.match(captureCountView({ status: "failed", kind: "forbidden" }, "Bobinas").note, /Tu perfil no tiene acceso al conteo central/);
  assert.equal(captureCountView({ status: "loading" }, "Bobinas").canRetry, false);
  // un cero central real sigue siendo un cero válido
  const zero = captureCountView({ status: "ready", count: 0 }, "Bobinas");
  assert.deepEqual([zero.label, zero.value, zero.canRetry], [CENTRAL_LABEL, "0", true]);
  assert.match(zero.note, /Capturas centrales de Bobinas \(PostgreSQL\)\. Sin sincronización automática/);
  assert.equal(captureCountView({ status: "ready", count: 12 }, "Bobinas").value, "12");
  // INT-02A: ninguna nota menciona registros locales del navegador
  for (const state of [...states, { status: "ready", count: 0 }, { status: "ready", count: 12 }]) assert.equal(/local|navegador/i.test(captureCountView(state, "Bobinas").note), false, JSON.stringify(state));
});

test("4 · las OT y asignaciones centrales de Bobinas siguen visibles y solo se muestran cuando ambas cargaron", () => {
  assert.match(page, /<Tracking front=\{front\} ots=\{workOrders\.view\.data\.map\(toDisplayOt\)\} asg=\{centralAssignments\.view\.data\.map\(toDisplayAssignment\)\}/);
  assert.match(page, /workOrders\.view\.status === "ready" && centralAssignments\.view\.status === "ready"/);
  assert.match(page, /<CentralStatus state=\{workOrders\.view\.status !== "ready" \? workOrders\.view : centralAssignments\.view\} onRetry=\{refreshCentral\}\/>/);
  assert.match(trackingBody, /<Metric label="OT visibles" value=\{visible\.length\}\/>/);
  assert.match(trackingBody, /<th className="p-3">Asignación<\/th>/);
  assert.match(page, /<CentralCaptures resource=\{f6List\.view\} refresh=\{f6List\.refresh\}\/>/); // la lista central de P1-06 se conserva
  assert.equal(/<th className="p-3">Capturas<\/th>/.test(trackingBody), false, "la columna de capturas locales por OT se retira");
});

test("5 · error, carga, falta de permisos y sesión perdida no generan datos demo ni locales de sustitución", () => {
  assert.equal(/OT-PRUEBA|OT-2026-001|BOBINA-FICTICIA/.test(trackingBody + pending + counter), false);
  assert.match(counter, /if \(kind === "session"\) onSessionLost\(\)/);
  assert.match(counter, /status: "failed", kind/);
  assert.equal(/localCount/.test(counter), false, "el componente ya no recibe ni pinta ningún conteo local");
  assert.match(counter, /captureCountView\(current, front\)/);
  assert.equal(/localStorage|sessionStorage/.test(counter + pending), false);
  assert.match(trackingBody, /<CaptureCount front=\{front\} userKey=\{userKey\} onSessionLost=\{onSessionLost\}\/>/);
  for (const kind of ["unavailable", "forbidden", "session"]) assert.equal(captureCountView({ status: "failed", kind }, "Bobinas").value, "—");
});

test("6 · Seguimiento de Calidad no simula liberaciones ni usa OT o registros locales: muestra que el resumen no está disponible", () => {
  assert.match(page, /: <><QualityTrackingPending\/><QualityMachineControls scope=\{scope\} canCapture=\{canReadQualityInbox\} mode="tracking"[^\n]*\/><\/>\)\}<\/>\}/);
  assert.equal((page.match(/<Tracking /g) ?? []).length, 1, "Tracking solo se usa para el Seguimiento central de Bobinas");
  assert.match(pending, /Resumen central todavía no disponible/);
  assert.match(pending, /no existe una fuente central de estados de liberación/);
  assert.match(pending, /no libera ni rechaza una bobina/);
  assert.equal(/records|ots=|asg=|localStorage|Liberada|Rechazada|<Metric/.test(pending), false);
  assert.match(page, /<QualityBobbinInbox resource=\{qualityInbox\.view\} refresh=\{qualityInbox\.refresh\}/);
  assert.match(page, /<QualityBobbinHistory item=\{qualityHistory\.item\}/);
  assert.match(page, /front === "Calidad" && canReadQualityInbox && activeModule === "ejecucion"/);
});

test("7 · los reportes inexistentes no aparecen como operativos y Seguimiento no ofrece descargas de registros locales", () => {
  assert.equal(/Se generan desde registros fuente|ya no se vuelven a llenar|derivado de Producción|suma de intervalos de pallets/.test(page), false);
  assert.match(trackingBody, /title="Reportes" note="Todavía no existen reportes centrales: solo están definidos por nombre y no se generan\."/);
  assert.match(trackingBody, /REPORT_DEFINITIONS\.map\(r => <div key=\{r\.id\}[^\n]*<Badge variant="outline">Pendiente<\/Badge>/);
  assert.equal(/emerald-300 bg-emerald-50/.test(trackingBody), false, "sin tarjetas verdes que simulen reportes derivados");
  assert.equal(/17 productos activos|MFRutaMaterialOP/.test(page), false, "sin cifras ni afirmaciones heredadas de la demo");
  assert.match(trackingBody, /note="Funcionalidad pendiente\."/);
  // INT-02A: el panel de «Descargas de registros locales (este navegador)» se retira
  assert.equal(/Descargas de registros locales|downloadRecords|downloadRows|registros-locales|Resumen OT–producto \(local\)/.test(page), false);
});

test("8 · las capturas centrales F3, P1-06, P1-19 y P1-20 siguen conectadas", () => {
  for (const marker of ["<F6Capture ", "<F3BobbinCapture ", "<QualityHumidityCapture ", "<QualityPhysicalCapture ", "<QualityBobbinHistory "]) assert.ok(page.includes(marker), marker);
  assert.match(page, /const f6List = useResource<CentralCapture\[\]>\(candidateHistoryKey\("f6", scope, 0\)/);
  assert.match(page, /const qualityInbox = useResource<QualityBobbinInboxItem\[\]>\(qualityInboxKey\(scope\)/);
  assert.match(page, /<BobbinasProgramming /);
});

test("9 · Rebobinado y Conversión solo usan sus shells centrales y la pantalla ya no escribe ni borra los datos locales históricos", () => {
  assert.match(page, /front === "Conversión" \? <ConversionCentral /);
  assert.match(page, /front === "Rebobinado" \? <RebobinadoCentral /);
  // INT-02A: ninguna escritura ni lectura de las claves legacy; los bytes históricos quedan intactos (sin setItem, removeItem, clear ni getItem desde la aplicación)
  assert.equal(/localStorage|sessionStorage/.test(page.replace(/\/\/.*$/gm, "")), false);
  assert.equal(/vinto-p1-records|vinto-ot|vinto-asg/.test(page.replace(/\/\/.*$/gm, "")), false);
});

test("10 · no queda ninguna ruta que lea registros locales para Seguimiento (historial de tubetes, resúmenes por OT)", () => {
  assert.equal(/records=\{/.test(page), false, "Tracking no recibe registros locales");
  assert.equal(/downloadTubetes|Historial de tubetes|historial-uso-tubetes|tubetes\s*=/.test(page), false);
  assert.equal(/codigo_tubete/.test(trackingBody), false);
  assert.equal(/setRecords|useState<CaptureRecord/.test(page), false);
});
