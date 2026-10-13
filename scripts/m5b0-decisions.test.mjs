// node --test scripts/m5b0-decisions.test.mjs
// M5-B0 · integridad del paquete documental de decisiones: ninguna de las 38 preguntas de origen (M4-B1 §7: 20; M5-A §6: 18) se pierde, los IDs son únicos, todas las decisiones
// siguen «Pendiente» (nada aprobado sin evidencia) y la agenda solo cita IDs que existen. Solo lee documentos; no valida reglas industriales.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { test } from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const decisions = read("docs/M5-B0-decisiones-VINTO.md");
const agenda = read("docs/M5-B0-agenda-homologacion.md");
const rows = decisions.split("\n").filter((l) => /^\| (H[123]|P)-\d+ \|/.test(l)).map((l) => l.split("|").slice(1, -1).map((c) => c.trim()));
const ids = rows.map((r) => r[0]);
const expand = (text) => {
  const found = new Set();
  for (const m of text.matchAll(/\b(H[123]|P)-(\d+)(?:\s*…\s*(?:(H[123]|P)-)?(\d+))?/g)) {
    const from = Number(m[2]), to = m[4] ? Number(m[4]) : from;
    for (let n = from; n <= to; n++) found.add(`${m[1]}-${String(n).padStart(2, "0")}`);
  }
  return found;
};

test("47 unique decisions with stable IDs, split by class", () => {
  assert.equal(rows.length, 47);
  assert.equal(new Set(ids).size, 47);
  const count = (prefix) => ids.filter((id) => id.startsWith(prefix)).length;
  assert.deepEqual([count("H1-"), count("H2-"), count("H3-"), count("P-")], [22, 18, 3, 4]);
});

test("every decision starts as Pendiente (no approval without evidence) and has all the required columns", () => {
  for (const row of rows) {
    assert.equal(row.length, 12, row[0]);
    assert.equal(row[6], "Pendiente", `${row[0]} debe seguir Pendiente`);
    assert.ok(row.every((cell) => cell.length > 0), `${row[0]} tiene celdas vacías`);
  }
  assert.equal(/\|\s*Aprobado\s*\|/.test(decisions.split("## 4.")[0].split("## 3.")[1]), false);
});

test("all 38 source questions are traced to existing decisions (none lost)", () => {
  const m4 = read("docs/M4-B1-homologacion-rebobinado.md").split("## 7.")[1].split("## 8.")[0];
  const m4Numbers = [...m4.matchAll(/^(\d+)\. /gm)].map((m) => Number(m[1]));
  assert.deepEqual(m4Numbers, Array.from({ length: 20 }, (_, i) => i + 1));
  const m5 = read("docs/M5-A-p107-genealogia.md").split("## 6.")[1].split("## 7.")[0];
  const m5Numbers = [...m5.matchAll(/^\| (\d+) \|/gm)].map((m) => Number(m[1]));
  assert.deepEqual(m5Numbers, Array.from({ length: 18 }, (_, i) => i + 1));

  const trace = decisions.split("## 4.")[1].split("## 5.")[0];
  const [m4Line, m5Line] = [trace.match(/\*\*M4-B1 §7\*\* → decisión: (.*)/)[1], trace.match(/\*\*M5-A §6\*\* → decisión: (.*)/)[1]];
  const mapped = (line) => new Map(line.split("·").map((part) => [Number(part.match(/[P#](\d+)→/)[1]), [...expand(part.split("→")[1])]]));
  const m4Map = mapped(m4Line), m5Map = mapped(m5Line);
  assert.deepEqual([...m4Map.keys()], m4Numbers);
  assert.deepEqual([...m5Map.keys()], m5Numbers);
  for (const targets of [...m4Map.values(), ...m5Map.values()]) {
    assert.ok(targets.length >= 1);
    for (const id of targets) assert.ok(ids.includes(id), `${id} no existe`);
  }
  // cada decisión no derivada está cubierta por alguna pregunta de origen
  const covered = new Set([...m4Map.values(), ...m5Map.values()].flat());
  const derived = rows.filter((r) => /derivada/.test(r.join(" "))).map((r) => r[0]);
  for (const id of ids) assert.ok(covered.has(id) || derived.includes(id), `${id} sin origen ni marca «derivada»`);
});

test("the agenda and the phase dependencies only cite existing decision IDs", () => {
  for (const text of [agenda, decisions.split("## 5.")[1].split("## 6.")[0]]) for (const id of expand(text)) assert.ok(ids.includes(id), `${id} no existe`);
});

test("the package keeps M1-B2-c1 as pending evidence, the article_version_spec fingerprint item pending and the checklist in NO GO", () => {
  assert.match(decisions, /M1-B2-c1[^\n]*no está disponible/);
  assert.match(decisions, /article_version_spec/);
  assert.match(decisions, /\*\*Decisión actual: NO GO\*\*/);
  assert.equal(/\bGO\b(?! \/)(?!\*\*)/.test(decisions.split("## 7.")[1].replace(/NO GO/g, "").replace(/\| GO \(/g, "|")), false);
});

// ---- gates: preparación frente a autorización de implementación; H2-10 nunca opcional --------------------------------------------------------------------------------------
const phases = decisions.split("## 5.")[1].split("## 6.")[0];
const phaseRow = (name) => phases.split("\n").find((l) => l.startsWith(`| **${name}**`));
const bullet = (heading) => agenda.split("\n").find((l) => l.includes(heading));

test("the agenda's complete sets cover EVERY decision that the §5 dependency matrix requires for M4-B2 and M5-B", () => {
  const m4b2 = expand(phaseRow("M4-B2")), m5b = expand(phaseRow("M5-B"));
  assert.ok(m4b2.size > 15 && m5b.size > 20);
  const completeM4 = expand(bullet("Conjunto completo para iniciar M4-B2")), completeM5 = expand(bullet("Conjunto completo para iniciar M5-B"));
  for (const id of ["H1-12", "H1-14", "H1-20", "H1-22"]) assert.ok(completeM4.has(id), `${id} falta en el conjunto completo de M4-B2`);
  for (const id of ["H2-06", "H2-09", "H2-14", "H2-15", "H2-16", "H2-17", "H2-18"]) assert.ok(completeM5.has(id), `${id} falta en el conjunto completo de M5-B`);
  for (const id of m4b2) assert.ok(completeM4.has(id), `M4-B2 §5 exige ${id} y la agenda no lo incluye`);
  for (const id of m5b) assert.ok(completeM5.has(id), `M5-B §5 exige ${id} y la agenda no lo incluye`);
});

test("agenda minimums are preparation only: they never authorize definitive contracts, catalog promotion or enabling Rebobinado", () => {
  assert.match(agenda, /## Alcance de las decisiones «mínimas» de cada sesión/);
  assert.match(agenda, /análisis y preparación técnica no operativa/);
  assert.match(agenda, /\*\*NO autorizan\*\* implementar contratos definitivos, promover catálogos[^.]*activar Rebobinado/);
  assert.match(agenda, /condiciones explícitas de la §5/);
  assert.equal(agenda.split("\n").filter((l) => /^- \*Mínimo de la reunión/.test(l)).length, 2);
  assert.equal(/se puede iniciar M[45]-B[23]\b/.test(agenda), false); // la forma antigua («con los mínimos… se puede iniciar M4-B2») no debe volver
  assert.match(agenda, /M4-B2 completo solo inicia cuando el conjunto completo anterior está Aprobado con evidencia/);
  assert.match(agenda, /M5-B completo solo inicia con el conjunto completo anterior Aprobado con evidencia/);
  assert.match(decisions, /Los mínimos de la agenda solo permiten análisis y preparación técnica no operativa/);
});

test("H2-10 (liberación de Calidad de la madre) is always required; only H2-11 is conditional", () => {
  const row = (id) => rows.find((r) => r[0] === id);
  assert.match(row("H2-10")[10], /M5-B \(siempre\)/);
  assert.equal(/\bsi se exige\b/.test(row("H2-10")[10]), false);
  assert.match(row("H2-11")[10], /solo si/);
  assert.match(phaseRow("M5-B"), /\*\*H2-10 siempre debe estar aprobada\*\*/);
  assert.match(phaseRow("M5-B"), /\*\*H2-11 es condicional\*\*/);
  assert.equal(/H2-10\/H2-11 solo/.test(decisions), false);
  assert.match(phaseRow("M4-B3"), /\*\*H2-10 resuelta siempre\*\*/);
  assert.ok(expand(bullet("Conjunto completo para iniciar M5-B")).has("H2-10"));
  assert.match(agenda, /\*\*H2-10 siempre se resuelve\*\*/);
  assert.match(agenda, /\*\*H2-11 solo\*\* si H2-10 exige liberación/);
});
