// node --experimental-strip-types --test scripts/rbe03-ui.test.mjs
// RBE-03: reglas puras y render SSR de la interfaz. Sin red, datos demo ni DOM interactivo.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "vite";

import {
  buildRewindingExportDraftPayload,
  buildRewindingExportPackagePayload,
  formatRewindingExportCuts,
  formatRewindingExportFormat,
  parseRewindingExportChild,
  parseRewindingExportDraft,
  parseRewindingExportDraftSummaryList,
  parseRewindingExportPreview,
  parseRewindingWorkOrderClassification,
  parseRewindingWorkOrderOptionList,
  rewindingExportChildLabel,
  rewindingExportContextDifferences,
  validateRewindingExportPackage,
} from "../lib/vinto/rewinding-export.ts";

const root = resolve(import.meta.dirname, "..").split(String.fromCharCode(92)).join("/");
const workDir = join(root, ".tmp-rbe03-" + process.pid);
const noop = () => {};
const UUID = {
  mother: "11111111-1111-4111-8111-111111111111",
  motherBobbin: "22222222-2222-4222-8222-222222222222",
  article: "33333333-3333-4333-8333-333333333333",
  workOrder: "44444444-4444-4444-8444-444444444444",
  child1: "55555555-5555-4555-8555-555555555555",
  child2: "66666666-6666-4666-8666-666666666666",
  child3: "77777777-7777-4777-8777-777777777777",
  package: "88888888-8888-4888-8888-888888888888",
  operator: "99999999-9999-4999-8999-999999999999",
};

const mother = (overrides = {}) => ({
  mother_capture_id: UUID.mother,
  mother_bobbin_id: UUID.motherBobbin,
  mother_label: "3987",
  pv_reference: "PV-2026-0158",
  article_id: UUID.article,
  article_code: "30120",
  article_description: "Bobina Tissue 20 g",
  machine: { code: "COPASA", name: "Copasa" },
  work_order: { id: UUID.workOrder, number: "OT-2026-0045" },
  operating_date: "2026-11-26",
  destination: "Perú",
  formato_1: "120",
  formato_2: "120",
  formato_3: "0",
  diametro: "1.20",
  tubete: "110 mm",
  ayudante: null,
  operator: { user_id: UUID.operator, display_name: "Operador fuente" },
  ...overrides,
});
const child = (id, position, overrides = {}) => ({
  bobbin_id: id, mother_capture_id: UUID.mother, position, weight_kg: "317.00", quality_status: "released", ...overrides,
});
const packageRow = (id, childId, slot = "A") => ({
  id, package_number: 1, mother_capture_id: UUID.mother, mother_label_snapshot: "3987",
  mother: mother(), children: [{ bobbin_id: childId, package_slot: slot, position: 1, weight_kg: "317.00" }],
});

test("Formato y Cortes conservan literalmente los decimales de P1-07; no convierten Cortes a códigos industriales", () => {
  const m = mother({ formato_1: "120.00", formato_2: "120.0", formato_3: "0" });
  assert.equal(formatRewindingExportFormat(m), "120.00 + 120.0");
  assert.equal(formatRewindingExportCuts(m), "0");
  assert.notEqual(formatRewindingExportCuts(m), "0-C");
  assert.equal(formatRewindingExportFormat(mother({ formato_2: null })), "120");
  assert.equal(formatRewindingExportCuts(mother({ formato_3: null })), "—");
});

test("el contexto de un reporte no mezcla PV, artículo, máquina, destino ni Formato; Cortes es por paquete", () => {
  const base = mother();
  assert.deepEqual(rewindingExportContextDifferences(base, mother({ mother_capture_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" })), []);
  assert.deepEqual(rewindingExportContextDifferences(base, mother({ destination: " Perú " })), []);
  assert.deepEqual(rewindingExportContextDifferences(base, mother({ machine: { code: "BELOIT", name: "Beloit" } })), ["máquina"]);
  assert.deepEqual(rewindingExportContextDifferences(base, mother({ formato_3: "6" })), []);
  assert.deepEqual(rewindingExportContextDifferences(base, mother({ formato_2: null })), ["Formato"]);
  assert.deepEqual(rewindingExportContextDifferences(base, mother({ pv_reference: "PV-OTRO", destination: "Chile" })), ["PV", "destino"]);
});

test("el selector muestra posición y peso de la cría, sin inventar códigos", () => {
  const c = { position: 13, weight_kg: "306.50" };
  assert.equal(rewindingExportChildLabel(c), "Cría 13 - 306.50 kg");
});

test("el parser de crías acepta solo released, posición real y peso decimal positivo", () => {
  const valid = child(UUID.child1, 1);
  assert.deepEqual(parseRewindingExportChild(valid), valid);
  assert.equal(parseRewindingExportChild({ ...valid, quality_status: "pending" }), null);
  assert.equal(parseRewindingExportChild({ ...valid, quality_status: "rejected" }), null);
  assert.equal(parseRewindingExportChild({ ...valid, position: 12 }), null);
  assert.equal(parseRewindingExportChild({ ...valid, weight_kg: "0" }), null);
  assert.equal(parseRewindingExportChild({ ...valid, weight_kg: "317 kg" }), null);
});

test("la Cría A es obligatoria y una cría no puede repetirse dentro del mismo reporte", () => {
  const m = mother();
  const available = [child(UUID.child1, 1), child(UUID.child2, 2), child(UUID.child3, 3)];
  const existing = [packageRow(UUID.package, UUID.child1)];
  assert.ok(validateRewindingExportPackage({
    mother: m, availableChildren: available, selection: { B: UUID.child2 }, existingPackages: [],
  }).some(error => error.includes("Cría A")));
  assert.ok(validateRewindingExportPackage({
    mother: m, availableChildren: available, selection: { A: UUID.child1, B: UUID.child1 }, existingPackages: [],
  }).some(error => error.includes("repetir")));
  assert.ok(validateRewindingExportPackage({
    mother: m, availableChildren: available, selection: { A: UUID.child1 }, existingPackages: existing,
  }).some(error => error.includes("otro paquete")));
});

test("la misma madre puede repetirse en paquetes distintos y las crías nuevas pasan la validación", () => {
  const m = mother();
  const available = [child(UUID.child1, 1), child(UUID.child2, 2), child(UUID.child3, 3)];
  const existing = [packageRow(UUID.package, UUID.child1)];
  const errors = validateRewindingExportPackage({
    mother: m, availableChildren: available, selection: { A: UUID.child2, B: UUID.child3 }, existingPackages: existing,
  });
  assert.deepEqual(errors, []);
  const payload = buildRewindingExportPackagePayload({
    mother: m, availableChildren: available, selection: { A: UUID.child2, B: UUID.child3 },
  });
  assert.deepEqual(payload, { mother_capture_id: UUID.mother, children: [{ package_slot: "A", child_bobbin_id: UUID.child2 }, { package_slot: "B", child_bobbin_id: UUID.child3 }] });
});

test("conserva las posiciones no consecutivas de las crías", () => {
  const m = mother();
  const available = [child(UUID.child1, 1), child(UUID.child3, 3)];
  assert.deepEqual(buildRewindingExportPackagePayload({ mother: m, availableChildren: available, selection: { A: UUID.child1, E: UUID.child3 } }), { mother_capture_id: UUID.mother, children: [{ package_slot: "A", child_bobbin_id: UUID.child1 }, { package_slot: "E", child_bobbin_id: UUID.child3 }] });
});

test("la selección rechaza crías que pertenecen a otra madre o que ya no están disponibles", () => {
  const m = mother();
  const wrong = child(UUID.child1, 1, { mother_capture_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" });
  const errors = validateRewindingExportPackage({
    mother: m, availableChildren: [wrong], selection: { A: UUID.child1 }, existingPackages: [],
  });
  assert.ok(errors.some(error => error.includes("no pertenece")));
  assert.ok(validateRewindingExportPackage({
    mother: m, availableChildren: [], selection: { A: UUID.child1 }, existingPackages: [],
  }).some(error => error.includes("no está disponible")));
});

test("los datos manuales se recortan solo en los identificadores de camión/orden; observaciones se conservan", () => {
  assert.deepEqual(buildRewindingExportDraftPayload({
    pv_reference: "PV-1", article_id: UUID.article, truck_number: "  CAM-018  ",
    order_number: "  2026-0045 ", observations: "  Inspección final  ",
  }), {
    pv_reference: "PV-1", article_id: UUID.article, truck_number: "CAM-018",
    order_number: "2026-0045", observations: "  Inspección final  ",
  });
});

test("el parser de borradores rechaza una forma parcial y acepta un borrador real vacío", () => {
  const draft = {
    id: UUID.package, status: "draft", created_at: "2026-11-27T10:00:00-05:00",
    pv_reference: "PV-2026-0158", article: { id: UUID.article, code: "30120", description: "Bobina Tissue 20 g" },
    truck_number: "", order_number: "", observations: "", packages: [],
  };
  assert.ok(parseRewindingExportDraft(draft));
  assert.equal(parseRewindingExportDraft({ ...draft, status: "generated" }), null);
  assert.equal(parseRewindingExportDraftSummaryList({ items: [{
    id: UUID.package, created_at: draft.created_at, pv_reference: draft.pv_reference,
    article_code: "30120", machine_code: null, package_count: 0,
  } ] })?.length, 1);
});

test("la vista previa diferencia warnings informativos de validaciones bloqueantes", () => {
  const preview = {
    valid: false, package_count: 1, child_count: 2,
    warnings: [{ code: "SOURCE_TIME_INVERTED", message: "Hora de origen invertida." }],
    blocking_errors: [{ code: "V02", message: "Falta número de camión." }],
  };
  assert.deepEqual(parseRewindingExportPreview(preview), preview);
  assert.equal(parseRewindingExportPreview({ ...preview, valid: true }), null);
});

test("la lista de clasificación incluye OTs cerradas y no infiere QA por estado", () => {
  const items = parseRewindingWorkOrderOptionList({ items: [{
    id: UUID.workOrder, number: "OT-2026-0045", status: "closed", machine_code: "COPASA",
  }] });
  assert.equal(items?.[0]?.status, "closed");
  assert.equal(parseRewindingWorkOrderOptionList({ items: [{
    id: UUID.workOrder, number: "OT-2026-0045", status: "archived", machine_code: "COPASA",
  }] }), null);
});

test("la clasificación de OT distingue desconocida de production_confirmed y QA", () => {
  assert.deepEqual(parseRewindingWorkOrderClassification({
    work_order_id: UUID.workOrder, classification: null, sequence_no: null, recorded_at: null, reason: null, recorded_by: null,
  }), { work_order_id: UUID.workOrder, classification: null, sequence_no: null, recorded_at: null, reason: null, recorded_by: null });
  assert.equal(parseRewindingWorkOrderClassification({
    work_order_id: UUID.workOrder, classification: "qa", sequence_no: 1,
    recorded_at: "2026-11-27T10:00:00Z", reason: "Datos de ensayo revisados.",
    recorded_by: { id: UUID.operator, display_name: "Jefatura" },
  })?.classification, "qa");
  assert.equal(parseRewindingWorkOrderClassification({
    work_order_id: UUID.workOrder, classification: "unknown", sequence_no: null, recorded_at: null, reason: null, recorded_by: null,
  }), null);
});

const aliasPlugin = {
  name: "at-alias",
  enforce: "pre",
  resolveId(source) {
    if (!source.startsWith("@/")) return null;
    const base = root + "/" + source.slice(2);
    for (const candidate of [base + ".tsx", base + ".ts", base + "/index.tsx", base + "/index.ts"]) {
      if (existsSync(candidate)) return candidate;
    }
    return null;
  },
};
let React, server, ui;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  React = await import("react");
  server = await import("react-dom/server");
  const entry = join(workDir, "entry.ts");
  writeFileSync(entry, [
    'export { RewindingExportWorkspace } from "@/components/vinto/rewinding-export-workspace";',
    'export { RewindingWorkOrderClassificationPanel } from "@/components/vinto/rewinding-work-order-classification";',
  ].join("\n"));
  const output = await build({
    configFile: false, root, logLevel: "error", mode: "production", plugins: [aliasPlugin],
    oxc: { jsx: { runtime: "automatic" } },
    build: { write: false, ssr: entry, minify: false, target: "node22", rollupOptions: { output: { format: "es" } } },
  });
  const bundle = (Array.isArray(output) ? output[0] : output).output.find(item => item.type === "chunk");
  const file = join(workDir, "ui.mjs");
  writeFileSync(file, bundle.code);
  ui = await import(pathToFileURL(file).href);
});
after(() => rmSync(workDir, { recursive: true, force: true }));

test("la interfaz no aparece si la sesión no tiene permisos RBE", () => {
  const html = server.renderToStaticMarkup(React.createElement(ui.RewindingExportWorkspace, {
    scope: "user:" + UUID.operator, canCreate: false, canReadOwn: false, onSessionLost: noop,
  }));
  assert.equal(html, "");
});

test("la interfaz autorizada muestra carga del servidor y no rellena opciones con datos demo", () => {
  const html = server.renderToStaticMarkup(React.createElement(ui.RewindingExportWorkspace, {
    scope: "user:" + UUID.operator, canCreate: true, canReadOwn: true, onSessionLost: noop,
  }));
  assert.ok(html.includes("Reporte de Bobinas Refiladas para Exportación"));
  assert.ok(html.includes("Consultando PV con crías elegibles"));
  assert.ok(html.includes("Consultando borradores"));
  assert.ok(html.includes("Fecha (automática)"));
  assert.ok(html.includes("Se asigna al generar el reporte"));
  assert.equal(html.includes("PV-2026-0158"), false);
  assert.equal(html.includes("Cría 1 - 317 kg"), false);
});

test("el panel de clasificación de Jefatura carga las OTs del servidor, incluidas las cerradas", () => {
  const html = server.renderToStaticMarkup(React.createElement(ui.RewindingWorkOrderClassificationPanel, {
    scope: "user:" + UUID.operator, onSessionLost: noop,
  }));
  assert.ok(html.includes("Clasificación de órdenes para RBE"));
  assert.ok(html.includes("Consultando OTs de Rebobinado, incluidas las cerradas"));
  assert.equal(html.includes("OT-2026-0045"), false);
});

test("la interfaz no utiliza almacenamiento offline/local del navegador", () => {
  const workspace = readFileSync(join(root, "components/vinto/rewinding-export-workspace.tsx"), "utf8");
  const classification = readFileSync(join(root, "components/vinto/rewinding-work-order-classification.tsx"), "utf8");
  for (const source of [workspace, classification]) {
    assert.equal(/localStorage|sessionStorage|indexedDB|navigator\.onLine/.test(source), false);
  }
});
