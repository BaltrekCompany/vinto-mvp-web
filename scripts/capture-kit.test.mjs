// node --test scripts/capture-kit.test.mjs
// Capturas simples reutilizables (M2-B1): renderiza los COMPONENTES reales (React + react-dom/server) del kit, de F6 y de la vista previa de P1-10, sin navegador ni red.
// Los componentes TSX se empaquetan en memoria con Vite (alias "@/") a un directorio temporal dentro del repositorio (para resolver react desde node_modules) que se borra al terminar.
// Los efectos no se ejecutan en el render del servidor: la lógica de envío de F6 está en lib/vinto/captures.ts (scripts/captures.test.mjs).
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").replace(/\\/g, "/");
const workDir = join(root, `.tmp-capture-kit-test-${process.pid}`);

const aliasPlugin = {
  name: "at-alias", enforce: "pre",
  resolveId(source) {
    if (!source.startsWith("@/")) return null;
    const base = `${root}/${source.slice(2)}`;
    for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) if (existsSync(candidate)) return candidate;
    return null;
  },
};

async function bundle(entry, name) {
  const output = await build({
    configFile: false, root, logLevel: "error", mode: "production", plugins: [aliasPlugin], oxc: { jsx: { runtime: "automatic" } },
    build: { write: false, ssr: join(root, entry), minify: false, target: "node22", rollupOptions: { output: { format: "es" } } },
  });
  const chunk = (Array.isArray(output) ? output[0] : output).output.find((item) => item.type === "chunk");
  const file = join(workDir, `${name}.mjs`);
  writeFileSync(file, chunk.code);
  return import(pathToFileURL(file).href);
}

let kit, f6, preview, React, server;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  [kit, f6, preview] = await Promise.all([
    bundle("components/vinto/capture-kit.tsx", "kit"), bundle("components/vinto/f6-capture.tsx", "f6"), bundle("components/vinto/p1-10-preview.tsx", "preview"),
  ]);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const html = (Component, props) => server.renderToStaticMarkup(React.createElement(Component, props));
const text = (markup) => markup.replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
const count = (haystack, needle) => haystack.split(needle).length - 1;
const noop = () => {};
const DISABLED = /\sdisabled(=""|\s|>)/; // the attribute, not the Tailwind `disabled:` variants in class names
const disabledTags = (markup, tag) => (markup.match(new RegExp("<" + tag + "[ ][^>]*>", "g")) ?? []).filter((t) => DISABLED.test(t)).length; // tags with attributes (React always emits a space)
const CONTEXT = { assignmentId: "44444444-4444-4444-8444-444444444444", workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1",
  productCode: "M1-1024", productName: "BOBINA 1024", machine: "MP1", shift: "Día", date: "2026-10-06" };
const DRAFT = { cantidad_fardos: "2", punto_merma: "recorte_maquina", tipo_producto: "hoja_doble", peso_kg: "125.50", observaciones: "x" };
const F6_PROPS = { context: CONTEXT, online: true, attempt: null, setAttempt: noop, back: noop, onSubmitted: noop, onAssignmentChanged: noop, onSessionLost: noop };
const read = (path) => readFileSync(join(root, path), "utf8").replace(/\r\n/g, "\n");
const code = (source) => source.replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");

// ---- kit ------------------------------------------------------------------------------------------------------------------------

test("kit: context items come from the assignment context only", () => {
  assert.deepEqual(kit.contextItems(CONTEXT), [
    { label: "OT", value: "OT-2026-0001" }, { label: "Línea / PV", value: "L1 / PV-1" }, { label: "Producto", value: "BOBINA 1024" },
    { label: "Máquina", value: "MP1" }, { label: "Turno / fecha", value: "Día · 2026-10-06" },
  ]);
  const strip = text(html(kit.ContextStrip, { items: kit.contextItems(CONTEXT) }));
  for (const piece of ["OT", "OT-2026-0001", "L1 / PV-1", "BOBINA 1024", "MP1", "Día · 2026-10-06"]) assert.ok(strip.includes(piece), piece);
});

test("kit: shell has the back control, the kicker and the title", () => {
  const markup = html(kit.CaptureShell, { kicker: "Cierre", title: "Mi formulario", onBack: noop, children: React.createElement("p", null, "contenido") });
  const plain = text(markup);
  assert.ok(plain.includes("Volver") && plain.includes("Cierre") && plain.includes("Mi formulario") && plain.includes("contenido"));
  assert.equal(count(markup, "<h1"), 1);
});

test("kit: fields mark required, honour disabled, suffix and inputMode (the value stays text)", () => {
  const field = (props) => html(kit.TextField, { label: "Peso", value: "1,5", onChange: noop, ...props });
  assert.ok(text(field({ required: true })).includes("Peso *"));
  assert.ok(!text(field({})).includes("Peso *"));
  assert.match(field({ inputMode: "decimal", suffix: "kg" }), /inputMode="decimal"/);
  assert.ok(text(field({ suffix: "kg" })).includes("kg"));
  assert.equal(disabledTags(field({ disabled: true }), "input"), 1);
  assert.equal(disabledTags(field({}), "input"), 0);
  assert.match(field({}), /type="text"/); // never type=number: decimals are typed as text and validated by the form
  assert.ok(text(field({ hint: "ayuda" })).includes("ayuda"));
  const area = html(kit.TextAreaField, { label: "Notas", value: "n", onChange: noop, disabled: true });
  assert.equal(disabledTags(area, "textarea"), 1);
  const choice = html(kit.ChoiceField, { label: "Tipo", value: "a", onChange: noop, options: [{ value: "a", label: "A" }, { value: "b", label: "B" }] });
  assert.ok(text(choice).includes("Tipo *") && count(choice, "<option") === 3);
  assert.match(choice, /<option value="a" selected/);
});

test("kit: notice and submit bar states", () => {
  assert.equal(html(kit.CaptureNotice, { text: null }), "");
  assert.match(html(kit.CaptureNotice, { text: "Error" }), /role="alert"/);
  const bar = (props) => html(kit.SubmitBar, { onSend: noop, sending: false, retry: false, ...props });
  assert.ok(text(bar({})).includes("Enviar registro trazable") && disabledTags(bar({}), "button") === 0);
  assert.ok(text(bar({ retry: true })).includes("Reintentar envío"));
  assert.ok(text(bar({ sending: true })).includes("Enviando…") && disabledTags(bar({ sending: true }), "button") === 1);
  assert.ok(text(bar({ label: "Guardar" })).includes("Guardar"));
});

test("kit: layout is mobile-first (one column, md breakpoints, no fixed widths) and has no business logic", () => {
  const source = code(read("components/vinto/capture-kit.tsx"));
  assert.equal(/(?:min-|max-)?w-\[\d+px\]/.test(source), false);
  assert.ok(source.includes("md:grid-cols-2") && source.includes("md:grid-cols-5"));
  assert.equal(/fetch\(|localStorage|sessionStorage|captures-api|central-http|requestJson|document\.cookie/.test(source), false);
});

// ---- F6 sin cambios de comportamiento -------------------------------------------------------------------------------------------

test("F6 renders the same fields, labels, context and submit action as before the extraction", () => {
  const markup = html(f6.F6Capture, F6_PROPS), plain = text(markup);
  for (const piece of ["Cierre de fardos", "Registro de control de fardos", "Control de fardos", "Línea genérica para bobina rechazada o recorte de máquina.", "Cantidad de fardos *", "Punto de merma *",
    "Tipo de producto *", "Peso real total *", "kg", "Observaciones", "Seleccionar…", "Bobina rechazada", "Recorte de máquina", "Servilleta", "Hoja doble", "Hoja simple",
    "OT-2026-0001", "L1 / PV-1", "BOBINA 1024", "MP1", "Día · 2026-10-06", "Enviar registro trazable", "Volver"]) assert.ok(plain.includes(piece), piece);
  assert.equal(count(markup, "<input"), 2);
  assert.equal(count(markup, "<select"), 2);
  assert.equal(count(markup, "<textarea"), 1);
  assert.match(markup, /inputMode="numeric"/);
  assert.match(markup, /inputMode="decimal"/);
  assert.equal(disabledTags(markup, "input") + disabledTags(markup, "select") + disabledTags(markup, "textarea") + disabledTags(markup, "button"), 0);
  assert.equal(/role="alert"/.test(markup), false);
});

test("F6 with a pending attempt locks the fields, keeps the draft and offers the retry with the uncertain notice", () => {
  const attempt = { captureId: "99999999-9999-4999-8999-999999999999", payload: { capture_id: "99999999-9999-4999-8999-999999999999" }, draft: DRAFT };
  const markup = html(f6.F6Capture, { ...F6_PROPS, attempt }), plain = text(markup);
  assert.ok(plain.includes("Reintentar envío") && plain.includes("No se pudo confirmar el envío."));
  assert.match(markup, /role="alert"/);
  assert.equal(disabledTags(markup, "input") + disabledTags(markup, "select") + disabledTags(markup, "textarea"), 5); // 2 inputs + 2 selects + 1 textarea
  assert.equal(disabledTags(markup, "button"), 0); // the retry button stays enabled
  assert.match(markup, /value="125.50"/); // the exact draft text (no float round trip)
  assert.match(markup, /value="2"/);
});

test("F6 source keeps its guarantees: central API only, double-submit guard, same attempt on retry", () => {
  const source = code(read("components/vinto/f6-capture.tsx"));
  assert.ok(source.includes("if (busy.current) return"));
  assert.ok(source.includes("createAttempt(draft, context.assignmentId, getDeviceKey())"));
  assert.ok(source.includes("submitAttempt(current, { post: submitCapture, get: id => getCapture(id) })"));
  assert.ok(source.includes("setAttempt(current)") && source.includes("setAttempt(null)"));
  assert.equal(/localStorage|sessionStorage|vinto-p1-records|document\.cookie|Authorization/.test(source), false);
});

// ---- vista previa P1-10 -----------------------------------------------------------------------------------------------------------

test("P1-10 preview shows the manual and the contextual fields from the existing definition, separated", () => {
  const markup = html(preview.P110Preview, { onBack: noop }), plain = text(markup);
  assert.ok(plain.includes("Registro de fardos"));
  for (const label of ["Código / número de producto *", "Número de fardo *", "Peso fardo *", "Observaciones"]) assert.ok(plain.includes(label), label);
  assert.equal(plain.includes("Observaciones *"), false);
  for (const label of ["Fecha · automático", "Máquina · automático", "Responsable · automático", "Firma · automático"]) assert.ok(plain.includes(label), label);
  assert.equal(count(markup, "<input"), 3);
  assert.equal(count(markup, "<textarea"), 1);
  const contextual = markup.slice(markup.indexOf('data-section="contextual"'), markup.indexOf("Campos de captura manual"));
  assert.equal(/<(input|select|textarea)/.test(contextual), false); // contextual values are NOT editable
});

test("P1-10 preview is clearly marked as a non-recording preview with fictitious data", () => {
  const plain = text(html(preview.P110Preview, { onBack: noop }));
  assert.ok(plain.includes("VISTA PREVIA — NO REGISTRA CAPTURAS") && plain.includes("DATOS FICTICIOS DE DEMOSTRACIÓN"));
  assert.ok(plain.includes("Rebobinado no es un sector operativo"));
  assert.ok(plain.includes("(ejemplo)"));
});

test("P1-10 preview lists every pending business rule and invents none", () => {
  const plain = text(html(preview.P110Preview, { onBack: noop }));
  for (const piece of ["Correlativo de fardo", "No hay numerador ni formato confirmados", "Peso del fardo", "Tipo declarado: texto", "Máquinas permitidas", "«Todas las rebobinadoras» frente a COPASA",
    "Responsable", "No se asume que sea el operador que captura", "Firma / aprobación", "No se simula ninguna firma digital", "Habilitación", "Por confirmar: fecha operativa o fecha calendario",
    "Sin correlativo, formato ni unicidad confirmados."]) assert.ok(plain.includes(piece), piece);
  assert.equal(count(plain, "Ninguna de estas reglas está implementada ni asumida"), 1);
});

test("P1-10 preview cannot submit: disabled action, no form, no submit button, no handlers that send", () => {
  const markup = html(preview.P110Preview, { onBack: noop });
  const submit = (markup.match(/<button[^>]*data-testid="preview-submit"[^>]*>/) ?? [""])[0];
  assert.ok(DISABLED.test(submit), submit);
  assert.equal(count(markup, "<form"), 0);
  assert.equal(/type="submit"/.test(markup), false);
  const buttons = markup.match(/<button[^>]*>/g) ?? [];
  assert.equal(buttons.filter((tag) => !DISABLED.test(tag)).length, 1); // only "Volver" is enabled
  assert.ok(text(markup).includes("Envío no habilitado (vista previa)"));
});

test("P1-10 preview: rendering performs no network call and touches no storage", () => {
  const original = globalThis.fetch;
  let touched = 0;
  globalThis.fetch = () => { touched++; throw new Error("network"); };
  try { html(preview.P110Preview, { onBack: noop }); } finally { globalThis.fetch = original; }
  assert.equal(touched, 0);
});

test("P1-10 preview source is isolated: no HTTP/storage/device imports and no route or policy wiring", () => {
  for (const file of ["components/vinto/p1-10-preview.tsx", "lib/vinto/p1-10-preview.ts"]) {
    const source = code(read(file));
    assert.equal(/fetch\(|localStorage|sessionStorage|document\.cookie|captures-api|central-http|requestJson|submitCapture|getDeviceKey|lib\/vinto\/device|capture_id|\/api\//.test(source), false, file);
  }
  assert.equal(/p1-10-preview|P110Preview/.test(read("app/page.tsx")), false); // not linked from the application
  assert.equal(["app/p1-10", "app/preview", "app/qa-harness", "app/__qa"].some((dir) => existsSync(join(root, dir))), false); // no public preview route in the PR
});

test("P1-10 stays out of production: not in the backend policy, not in the seed bundle, no Rebobinado enabled", () => {
  const service = read("backend/app/capture_service.py");
  assert.match(service, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  assert.equal(/CENTRAL_FORM_CODES[^\n]*P1-10/.test(service), false);
  for (const name of ["forms.json", "form_versions.json", "field_definitions.json", "form_version_machines.json"]) {
    const file = join(root, "backend/seed_data", name);
    if (existsSync(file)) assert.equal(readFileSync(file, "utf8").includes("VINTO-P1-10"), false, name);
  }
  assert.match(read("backend/app/sectors.py"), /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
});

test("P1-10 preview spec follows the definition: 4 manual + 4 contextual fields, nothing hidden", async () => {
  const lib = await bundle("lib/vinto/p1-10-preview.ts", "lib");
  const spec = lib.previewSpec();
  assert.deepEqual(spec.manual.map((f) => f.key), ["codigo_numero_de_producto", "numero_de_fardo", "peso_fardo", "observaciones"]);
  assert.deepEqual(spec.contextual.map((f) => f.key), ["fecha", "maquina", "responsable", "firma"]);
  assert.deepEqual(spec.manual.map((f) => f.required), [true, true, true, false]);
  assert.equal(spec.manual.find((f) => f.key === "peso_fardo").declaredType, "text"); // the preview does not turn it into a decimal contract
  assert.equal(spec.manual.find((f) => f.key === "peso_fardo").unit, "kg");
  assert.deepEqual(spec.allowedMachineIds, ["copasa"]);
  assert.ok(spec.contextual.every((f) => f.origin && f.pending));
  assert.equal(lib.PENDING_RULES.length, 7);
  assert.ok(Object.values(lib.DEMO_DRAFT).every((v) => /ejemplo/i.test(v)));
});
