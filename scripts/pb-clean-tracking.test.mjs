// node --test scripts/pb-clean-tracking.test.mjs
// PB-CLEAN · regresión del saneamiento de Seguimiento de Bobinas y Calidad: sin datos ficticios, sin liberaciones simuladas, sin conteos locales presentados como centrales,
// sin ceros que representen un estado desconocido y sin reportes que parezcan operativos. La lógica de presentación del conteo se prueba en ejecución; el resto es regresión
// estática sobre el código fuente (el repositorio no renderiza React en pruebas Node). No valida reglas industriales ni sustituye una prueba de navegador.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import { captureCountView, CENTRAL_LABEL, LOCAL_LABEL, VALUE_UNKNOWN } from "../lib/vinto/capture-count-view.ts";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const page = read("app/page.tsx"), pending = read("components/vinto/tracking-pending.tsx"), counter = read("components/vinto/capture-count.tsx");
const trackingBody = page.slice(page.indexOf("function Tracking("), page.indexOf("function downloadRows("));

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

test("3 · un estado real desconocido no se muestra como cero ni como el conteo local: el valor principal es «—»", () => {
  assert.equal(VALUE_UNKNOWN, "—");
  const states = [{ status: "loading" }, { status: "failed", kind: "unavailable" }, { status: "failed", kind: "forbidden" }, { status: "failed", kind: "session" }];
  for (const state of states) {
    const view = captureCountView(state, "Bobinas", 7);
    assert.equal(view.value, "—", JSON.stringify(state));
    assert.equal(view.label, CENTRAL_LABEL);
    assert.notEqual(view.value, "0");
    assert.notEqual(view.value, "7");
  }
  // el conteo local solo aparece como dato secundario rotulado y aclarando que no representa la producción
  const failed = captureCountView({ status: "failed", kind: "unavailable" }, "Bobinas", 7);
  assert.match(failed.note, new RegExp(`${LOCAL_LABEL.replace(/[()]/g, "\\$&")}: 7`));
  assert.match(failed.note, /No representan la producción central de Bobinas ni se suman al conteo central/);
  assert.match(failed.note, /Consulta central no disponible/);
  assert.match(captureCountView({ status: "failed", kind: "forbidden" }, "Bobinas", 7).note, /Tu perfil no tiene acceso al conteo central/);
  assert.equal(captureCountView({ status: "loading" }, "Bobinas", 7).canRetry, false);
  // un cero central real sigue siendo un cero válido y el conteo local no se suma
  const zero = captureCountView({ status: "ready", count: 0 }, "Bobinas", 7);
  assert.deepEqual([zero.label, zero.value], [CENTRAL_LABEL, "0"]);
  assert.match(zero.note, /Registros locales \(este navegador\): 7\. No representan la producción central de Bobinas ni se suman al conteo central\. Sin sincronización automática/);
  assert.equal(zero.canRetry, true);
  assert.equal(captureCountView({ status: "ready", count: 12 }, "Bobinas", 3).value, "12");
  // rotulación consistente del dato secundario en TODOS los estados: local, no central, no sumado
  const all = [{ status: "loading" }, { status: "ready", count: 0 }, { status: "ready", count: 12 }, { status: "failed", kind: "unavailable" }, { status: "failed", kind: "forbidden" }, { status: "failed", kind: "session" }];
  for (const state of all) {
    const { note } = captureCountView(state, "Bobinas", 4);
    if (state.status === "loading") { assert.match(note, /Consultando registros centrales/); continue; }
    assert.match(note, /Registros locales \(este navegador\): 4\./, JSON.stringify(state));
    assert.match(note, /No representan la producción central/, JSON.stringify(state));
    assert.match(note, /ni se suman al conteo central/, JSON.stringify(state));
  }
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

test("5 · error, carga, falta de permisos y sesión perdida no generan datos demo de sustitución", () => {
  // el contenido de Seguimiento no tiene valor inicial ficticio: sin datos centrales se muestra el estado, nunca una OT, bobina o cifra de ejemplo
  assert.equal(/OT-PRUEBA|OT-2026-001|BOBINA-FICTICIA/.test(trackingBody + pending + counter), false);
  assert.match(counter, /if \(kind === "session"\) onSessionLost\(\)/);
  assert.match(counter, /status: "failed", kind/);
  assert.equal(/localCount\}/.test(counter), false, "el componente no pinta el conteo local como valor principal");
  assert.match(counter, /captureCountView\(current, front, localCount\)/);
  assert.equal(/localStorage|sessionStorage/.test(counter + pending), false);
  const failures = ["unavailable", "forbidden", "session"];
  for (const kind of failures) assert.equal(captureCountView({ status: "failed", kind }, "Bobinas", 5).value, "—");
});

test("6 · Seguimiento de Calidad no simula liberaciones ni usa OT o registros locales: muestra que el resumen no está disponible", () => {
  assert.match(page, /: <><QualityTrackingPending\/><QualityMachineControls scope=\{scope\} canCapture=\{canReadQualityInbox\} mode="tracking"[^\n]*\/><\/>\)\}<\/>\}/); // DEV-Q1: el resumen sigue «no disponible»; los controles por máquina candidatos son un panel aparte
  assert.equal((page.match(/<Tracking /g) ?? []).length, 1, "Tracking solo se usa para el Seguimiento central de Bobinas");
  assert.match(pending, /Resumen central todavía no disponible/);
  assert.match(pending, /no existe una fuente central de estados de liberación/);
  assert.match(pending, /no libera ni rechaza una bobina/);
  assert.equal(/records|ots=|asg=|localStorage|Liberada|Rechazada|<Metric/.test(pending), false);
  // el inbox y el historial centrales de Ejecución no cambian
  assert.match(page, /<QualityBobbinInbox resource=\{qualityInbox\.view\} refresh=\{qualityInbox\.refresh\}/);
  assert.match(page, /<QualityBobbinHistory item=\{qualityHistory\.item\}/);
  assert.match(page, /front === "Calidad" && canReadQualityInbox && activeModule === "ejecucion"/);
});

test("7 · los reportes inexistentes no aparecen como operativos", () => {
  assert.equal(/Se generan desde registros fuente|ya no se vuelven a llenar|derivado de Producción|suma de intervalos de pallets/.test(page), false);
  assert.match(trackingBody, /title="Reportes" note="Todavía no existen reportes centrales: solo están definidos por nombre y no se generan\."/);
  assert.match(trackingBody, /REPORT_DEFINITIONS\.map\(r => <div key=\{r\.id\}[^\n]*<Badge variant="outline">Pendiente<\/Badge>/);
  assert.equal(/emerald-300 bg-emerald-50/.test(trackingBody), false, "sin tarjetas verdes que simulen reportes derivados");
  assert.equal(/17 productos activos|MFRutaMaterialOP/.test(page), false, "sin cifras ni afirmaciones heredadas de la demo");
  assert.match(trackingBody, /note="Funcionalidad pendiente\."/);
  assert.match(trackingBody, /Descargas de registros locales \(este navegador\)/);
  assert.match(trackingBody, /no incluyen las capturas centrales \(F3, P1-06 y Calidad\)/);
});

test("8 · las capturas centrales F3, P1-06, P1-19 y P1-20 siguen conectadas", () => {
  for (const marker of ["<F6Capture ", "<F3BobbinCapture ", "<QualityHumidityCapture ", "<QualityPhysicalCapture ", "<QualityBobbinHistory "]) assert.ok(page.includes(marker), marker);
  assert.match(page, /const f6List = useResource<CentralCapture\[\]>\(candidateHistoryKey\("f6", scope, 0\)/);
  assert.match(page, /const qualityInbox = useResource<QualityBobbinInboxItem\[\]>\(qualityInboxKey\(scope\)/);
  assert.match(page, /<BobbinasProgramming /);
});

test("9 · Rebobinado y Conversión no se alteran y los datos locales históricos se conservan", () => {
  assert.match(page, /front === "Conversión" \? <ConversionCentral /);
  assert.match(page, /front === "Rebobinado" \? <RebobinadoCentral /);
  assert.match(page, /localStorage\.setItem\("vinto-p1-records"/);
  assert.match(page, /localStorage\.setItem\("vinto-ot"/);
  assert.match(page, /localStorage\.setItem\("vinto-asg"/);
  assert.equal(/localStorage\.(removeItem|clear)\("vinto-(p1-records|ot|asg)"\)|localStorage\.clear/.test(page), false, "no se borra ni migra el almacenamiento local");
});

test("10 · no se ofrece una descarga basada en datos imposibles de obtener (historial de tubetes)", () => {
  // Tracking recibe registros SIN F3 ni P1-06 y los registros F3 locales eran la única fuente del historial de tubetes: la descarga siempre saldría vacía.
  assert.match(page, /records=\{records\.filter\(r => r\.formId !== F6_FORM_ID && r\.formId !== F3_FORM_ID\)\}/);
  assert.equal(/downloadTubetes|Historial de tubetes|historial-uso-tubetes|tubetes\s*=/.test(page), false);
  assert.equal(/codigo_tubete/.test(trackingBody), false);
  // regla general: ningún botón de descarga filtra por un formulario que el propio Tracking excluye
  const excluded = ["F3_FORM_ID", "F6_FORM_ID", "form_3_registro_de_produccion_de_bobinas"];
  for (const id of excluded) assert.equal(new RegExp(String.raw`records\.filter\([^)]*formId === ${id}`).test(trackingBody), false, `Tracking no puede filtrar por ${id}`);
  assert.equal(/Descargas de registros locales[\s\S]*Historial/.test(trackingBody), false);
  // los datos locales no se borran ni se migran
  assert.match(page, /localStorage\.setItem\("vinto-p1-records"/);
});
