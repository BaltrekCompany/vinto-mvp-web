// node --test scripts/mf09a-p1-01-titulo.test.mjs
// MF-09A · ajuste visual detectado en el QA de MF-09: el título y el subtítulo de P1-01 llevaban «MP3» fijo aunque la asignación fuera de MP1. Ahora salen de la máquina del contexto de la asignación (ya validado por el
// backend); sin máquina no se muestra ninguna. Renderiza la pantalla real (React + react-dom/server, sin navegador ni red); los componentes TSX se empaquetan en memoria con Vite (alias "@/").
import assert from "node:assert/strict";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "vite";

const root = resolve(import.meta.dirname, "..").split(String.fromCharCode(92)).join("/");
const workDir = join(root, `.tmp-mf09a-titulo-${process.pid}`);
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

let React, server, ui;
before(async () => {
  mkdirSync(workDir, { recursive: true });
  [React, server] = [await import("react"), await import("react-dom/server")];
  const rel = `.tmp-mf09a-titulo-${process.pid}/entry.ts`;
  writeFileSync(join(root, rel), ['export { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";', 'export { CandidateHistory } from "@/components/vinto/candidate-history";', 'export { BOBINAS_CANDIDATES } from "@/lib/vinto/bobinas-candidates";'].join("\n"));
  ui = await bundle(rel, "ui");
});
after(() => rmSync(workDir, { recursive: true, force: true }));

const noop = () => {};
const ctx = (machine, assignmentId = "44444444-4444-4444-8444-444444444444") => ({ assignmentId, workOrderId: "22222222-2222-4222-8222-222222222222", otId: "OT-2026-0001", lineId: "L1", pv: "PV-1", productCode: "M1-1024", productName: "BOBINA 1024", machine, shift: "Día", date: "2026-10-06" });
const screen = (screen, context) => server.renderToStaticMarkup(React.createElement(ui.CandidateFormCapture, { candidate: ui.BOBINAS_CANDIDATES[screen], context, online: true, attempt: null, setAttempt: noop, back: noop, onAssignmentChanged: noop, onSessionLost: noop }));
const textOf = (html) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("P1-01 muestra la máquina REAL de la asignación en el subtítulo y en el título (MP1 y MP3) y se actualiza al cambiar de máquina", () => {
  for (const machine of ["MP1", "MP3"]) {
    const html = screen("p101", ctx(machine)), text = textOf(html);
    assert.match(html, new RegExp(`>Operación e inspección · Bobinas ${machine}<`), `${machine}: subtítulo`);
    assert.match(html, new RegExp(`<h1[^>]*>Operación e inspección de máquina ${machine}</h1>`), `${machine}: título`);
    const other = machine === "MP1" ? "MP3" : "MP1";
    assert.equal(text.includes(`Operación e inspección de máquina ${other}`), false, `${machine}: no queda el texto de ${other}`);
    assert.equal(text.includes(`Bobinas ${other}`), false);
    assert.ok(text.includes(machine), "el contexto de la asignación sigue mostrando la máquina");
  }
  // el mismo componente con otra asignación cambia los textos (no hay texto fijo ni estado editable)
  assert.match(screen("p101", ctx("MP3")), /Operación e inspección de máquina MP3/);
  assert.match(screen("p101", ctx("MP1", "55555555-5555-4555-8555-555555555555")), /Operación e inspección de máquina MP1/);
});

test("sin máquina en el contexto no se muestra ninguna máquina (ni un MP3 por defecto)", () => {
  for (const machine of [undefined, "", "   "]) {
    const html = screen("p101", ctx(machine)), text = textOf(html);
    assert.match(html, /<h1[^>]*>Operación e inspección de máquina<\/h1>/);
    assert.match(html, />Operación e inspección · Bobinas<\//);
    assert.equal(/Operación e inspección de máquina MP\d/.test(text) || /Bobinas MP\d/.test(text), false);
  }
});

test("los 70 campos (MF-12A: P1-01 v4) y las 7 secciones de P1-01 siguen y los demás formularios no cambian de título", () => {
  const html = screen("p101", ctx("MP1"));
  assert.equal(html.split("<input").length - 1, 70);
  for (const title of ["Materia prima, tanques y pulpeo", "Caudales, mezclas y consistencias", "Químicos", "Secador, presiones y temperaturas", "Prensa, aceite, vacío y filtros", "Limpieza y cambios de cuchillas", "Novedades"]) assert.ok(textOf(html).includes(title), title);
  const { BOBINAS_CANDIDATES: c } = ui;
  assert.deepEqual([c.p101.code, c.p101.title, c.p101.kicker], ["VINTO-P1-01", "Operación e inspección de máquina", "Operación e inspección · Bobinas"], "sin máquina fija; el código técnico no cambia");
  assert.deepEqual([c.p102.title, c.p102.kicker, c.p102.titleFor], ["Parámetros de operación de máquina MP1", "Parámetros · Bobinas MP1", undefined], "P1-02 es solo de MP1 y no cambia");
  for (const other of ["p104", "p105", "p131"]) assert.equal(c[other].titleFor, undefined, other);
  assert.match(screen("p102", ctx("MP1")), /Parámetros de operación de máquina MP1/);
});

test("el historial no inventa una máquina: título genérico de P1-01 (reúne capturas de MP1 y MP3)", () => {
  const html = server.renderToStaticMarkup(React.createElement(ui.CandidateHistory, { candidate: ui.BOBINAS_CANDIDATES.p101, resource: { status: "ready", data: [], refreshing: false }, refresh: noop }));
  assert.match(textOf(html), /Operación e inspección de máquina \(P1-01\) · registros centrales/);
});
