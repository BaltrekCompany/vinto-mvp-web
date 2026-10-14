// node --test scripts/m7a-decisions.test.mjs
// M7-A · integridad del paquete documental de homologación de Conversión: las 36 decisiones (11 C + 11 P + 8 N + 6 B) conservan su identificador y su procedencia, la clave única es (frente, ID) con prefijos
// `CV:` y `RB:`, todas siguen «Pendiente» (nada aprobado sin evidencia), las referencias existen (también hacia M5-B0) y los conteos PF / OP / LT no duplican decisiones. Solo lee documentos; no valida reglas
// industriales ni aprueba nada: un E2E que pasa no es evidencia de aprobación.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const matrixDoc = read("docs/M7-A-conversion-decisiones-VINTO.md"), indexDoc = read("docs/M7-A-homologacion-indice.md"), agendaDoc = read("docs/M7-A-agenda-y-registro-conversion.md");
const m5b0 = read("docs/M5-B0-decisiones-VINTO.md"), acta = read("docs/M5-B0-acta-homologacion.md");
const SOURCES = { C: "docs/M6-A-conversion-central-p116.md", P: "docs/M6-B-conversion-p112.md", N: "docs/M6-C-conversion-p113.md", B: "docs/M6-D-conversion-p111.md" };

const cells = (line) => line.split(/(?<!\\)\|/).slice(1, -1).map((c) => c.trim());
const section = (text, from, to) => text.split(from)[1].split(to)[0];
const rowsOf = (text, prefix) => text.split("\n").filter((l) => l.startsWith(prefix)).map(cells);
const main = rowsOf(section(matrixDoc, "## 2. Matriz de decisiones", "## 3. Clasificación"), "| CV:");
const meta = rowsOf(section(matrixDoc, "## 3. Clasificación", "## 4. Procedencia"), "| CV:");
const registry = rowsOf(section(agendaDoc, "## 3. Formato breve de registro", "## 4. Resumen"), "| CV:");
const ids = main.map((r) => r[0]);
const rb = new Set(m5b0.split("\n").filter((l) => /^\| (H[123]|P)-\d+ \|/.test(l)).map((l) => cells(l)[0]));
const refs = (text, prefix) => [...text.matchAll(new RegExp(`${prefix}:([A-Z0-9]+-\\d+)`, "g"))].map((m) => m[1]);
const cvIds = new Set(ids.map((id) => id.slice(3)));

test("36 unique composite keys (frente, ID): 11 C + 11 P + 8 N + 6 B, contiguous and in the same order in the matrix, the classification and the registry", () => {
  assert.equal(main.length, 36);
  assert.equal(new Set(ids).size, 36);
  assert.ok(ids.every((id) => /^CV:[CPNB]-\d+$/.test(id)), "todas las claves llevan el prefijo CV:");
  const count = (letter) => ids.filter((id) => id.startsWith(`CV:${letter}-`)).length;
  assert.deepEqual([count("C"), count("P"), count("N"), count("B")], [11, 11, 8, 6]);
  for (const [letter, n] of [["C", 11], ["P", 11], ["N", 8], ["B", 6]]) assert.deepEqual(ids.filter((id) => id.startsWith(`CV:${letter}-`)).map((id) => Number(id.split("-")[1])), Array.from({ length: n }, (_, i) => i + 1));
  assert.deepEqual(meta.map((r) => r[0]), ids);
  assert.deepEqual(registry.map((r) => r[0]), ids);
});

test("every decision keeps the identifier and provenance of its source (M6-A §7, M6-B §7, M6-C §10, M6-D §10): none lost, none invented", () => {
  for (const [letter, file] of Object.entries(SOURCES)) {
    const text = read(file);
    const sourceIds = text.split("\n").filter((l) => new RegExp(`^\\| ${letter}-\\d+ \\|`).test(l)).map((l) => cells(l)[0]).sort();
    const mine = ids.filter((id) => id.startsWith(`CV:${letter}-`)).map((id) => id.slice(3)).sort();
    assert.deepEqual(mine, sourceIds, `${letter}: los IDs deben coincidir con ${file}`);
    const docName = file.match(/M6-[A-D]/)[0];
    for (const row of main.filter((r) => r[0].startsWith(`CV:${letter}-`))) assert.ok(row[4].includes(docName), `${row[0]} debe citar ${docName} como fuente`);
    assert.equal((text.match(/M7-A-conversion-decisiones-VINTO\.md/g) ?? []).length, 1, `${file} tiene exactamente un enlace de navegación al paquete M7-A`);
  }
});

test("every decision is Pendiente with all the required columns and no approval or invented answer", () => {
  const roles = new Set(["JP", "CAL", "DB", "TI", "DIR"]);
  for (const row of main) {
    assert.equal(row.length, 9, row[0]);
    assert.equal(row[6], "Pendiente", `${row[0]} debe seguir Pendiente`);
    assert.ok(row.every((cell) => cell.length > 0), `${row[0]} tiene celdas vacías`);
    assert.ok(row[5].split(",").map((r) => r.trim()).every((r) => roles.has(r)), `${row[0]}: responsable desconocido`);
    assert.match(row[7], /\S/);
    assert.ok([...row[8].matchAll(/M7-([A-Z])/g)].every((m) => "BCDEFGH".includes(m[1])), `${row[0]}: incremento inexistente`);
  }
  for (const text of [matrixDoc, indexDoc, agendaDoc]) assert.equal(/\|\s*(Aprobado|Respondido, sin evidencia|En revisión|Rechazado[^|]*)\s*\|/.test(text), false, "ningún estado distinto de Pendiente en las tablas");
  assert.match(matrixDoc, /Las 36 decisiones están en Pendiente/);
  assert.match(indexDoc, /Ninguna decisión está aprobada/);
});

test("the registry template carries one Pendiente row per decision and EMPTY answer cells: no invented answers, approvals or dates", () => {
  assert.equal(registry.length, 36);
  for (const row of registry) {
    assert.equal(row.length, 8, row[0]);
    assert.equal(row[1], "Pendiente");
    assert.ok(row.slice(2).every((cell) => cell === ""), `${row[0]} debe tener las celdas de respuesta vacías`);
  }
  for (const text of [matrixDoc, indexDoc, agendaDoc]) {
    assert.equal(/\b\d{4}-\d{2}-\d{2}\b/.test(text), false, "sin fechas ISO");
    assert.equal(/\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b/i.test(text), false, "sin fechas de calendario");
  }
});

test("states and evidence criteria are reused from the M5-B0 acta, never redefined", () => {
  const actaStates = acta.split("## 1. Estados")[1].split("## 2.")[0].split("\n").filter((l) => /^\| \*\*/.test(l)).map((l) => cells(l)[0].replace(/\*/g, ""));
  assert.deepEqual(actaStates, ["Pendiente", "Respondido, sin evidencia", "En revisión", "Aprobado", "Rechazado / requiere rediseño"]);
  for (const text of [matrixDoc, indexDoc, agendaDoc]) {
    assert.match(text, /M5-B0-acta-homologacion\.md/);
    assert.equal(/^## .*(Estados|Evidencia aceptable)/m.test(text), false, "no se redefinen los estados ni los criterios de evidencia");
  }
  assert.ok(actaStates.every((s) => agendaDoc.includes(s.replace(" / requiere rediseño", "")) ), "la agenda cita los cinco estados del acta");
});

test("PF / OP / LT: one class per decision, valid frentes, and counts that do not duplicate conditional decisions", () => {
  const classes = new Map();
  for (const row of meta) {
    assert.equal(row.length, 7, row[0]);
    assert.ok(row.every((cell) => cell.length > 0), `${row[0]} tiene celdas vacías`);
    assert.match(row[1], /^[ABCD] · /);
    assert.ok(["PF", "OP", "LT"].includes(row[2]), `${row[0]}: clase inválida`);
    assert.equal(classes.has(row[0]), false, `${row[0]} aparece dos veces`);
    classes.set(row[0], row[2]);
  }
  const total = (c) => [...classes.values()].filter((x) => x === c).length;
  assert.deepEqual([total("PF"), total("OP"), total("LT")], [13, 18, 5]);
  assert.equal(classes.size, 36);
  // una decisión condicional tiene UNA clase base y su condición en texto; la condición nunca crea una segunda fila
  const conditional = meta.filter((r) => r[3] !== "—");
  assert.ok(conditional.length > 0 && conditional.every((r) => /^(PF|OP) si /.test(r[3])), "las condiciones de reclasificación están redactadas como «PF/OP si …»");
  // los conteos publicados en el índice y en la matriz coinciden con la tabla
  for (const text of [indexDoc, matrixDoc]) {
    assert.match(text, /\| \*\*Total\*\* \| \*\*13\*\* \| \*\*18\*\* \| \*\*5\*\* \| \*\*36\*\* \|/);
    for (const frente of "ABCD") {
      const mine = meta.filter((r) => r[1].startsWith(frente));
      const row = text.split("\n").find((l) => l.startsWith(`| ${frente} · `)) ?? text.split("\n").find((l) => l.startsWith(`| **${frente} · `));
      const published = text.split("\n").filter((l) => new RegExp(`^\\| ${frente} · `).test(l)).map(cells).find((c) => c.length === 5);
      assert.ok(published || row, `${frente}: falta el conteo`);
      if (published) assert.deepEqual(published.slice(1).map(Number), ["PF", "OP", "LT"].map((c) => mine.filter((r) => r[2] === c).length).concat(mine.length));
    }
  }
});

test("dependencies and «responder junto con» only cite existing Conversión keys; the second is symmetric, never self-referential and merges nothing; dependencies have no cycles", () => {
  const dep = new Map(), together = new Map();
  for (const row of meta) {
    dep.set(row[0], refs(row[4], "CV").map((id) => `CV:${id}`));
    together.set(row[0], refs(row[5], "CV").map((id) => `CV:${id}`));
    for (const id of [...dep.get(row[0]), ...together.get(row[0])]) { assert.ok(ids.includes(id), `${row[0]} cita ${id} que no existe`); assert.notEqual(id, row[0]); }
    assert.ok(row[4] === "—" || dep.get(row[0]).length > 0);
    assert.ok(row[5] === "—" || together.get(row[0]).length > 0);
  }
  for (const [id, others] of together) for (const other of others) assert.ok(together.get(other).includes(id), `${id} ↔ ${other} debe ser simétrica`);
  const visiting = new Set(), done = new Set();
  const visit = (id) => { assert.equal(visiting.has(id), false, `ciclo de dependencias en ${id}`); if (done.has(id)) return; visiting.add(id); for (const next of dep.get(id)) visit(next); visiting.delete(id); done.add(id); };
  for (const id of ids) visit(id);
  for (const text of [matrixDoc, indexDoc, agendaDoc]) for (const id of refs(text, "CV")) assert.ok(cvIds.has(id), `CV:${id} no existe`);
});

test("links to Rebobinado exist in M5-B0 (the single source of truth), are links only, and no M5-B0 decision is copied", () => {
  assert.equal(rb.size, 47);
  for (const text of [matrixDoc, indexDoc, agendaDoc]) for (const id of refs(text, "RB")) assert.ok(rb.has(id), `RB:${id} no existe en M5-B0`);
  assert.ok(meta.some((r) => refs(r[6], "RB").length > 0));
  for (const row of meta) assert.ok(row[6] === "—" || refs(row[6], "RB").length > 0);
  // ninguna fila de la matriz M7-A es una decisión de M5-B0: ni IDs H1/H2/H3 como clave ni copia de sus preguntas
  assert.equal(matrixDoc.split("\n").some((l) => /^\| (RB:)?(H[123]|P)-\d+ \|/.test(l)), false);
  assert.match(matrixDoc, /no copia/);
});

test("no bare identifier is ambiguous: every C/P/N/B/H reference in the package carries its CV: or RB: prefix", () => {
  for (const [name, text] of [["matriz", matrixDoc], ["índice", indexDoc], ["agenda", agendaDoc]]) {
    const bare = [...text.matchAll(/(?<![:\w`-])((?:[CPNB]|H[123])-\d+)\b/g)].map((m) => m[1]);
    assert.deepEqual(bare, [], `${name}: identificadores sin prefijo`);
  }
});

test("M5-B0 keeps its 47 decisions, their states and evidence: only one navigation line was added", () => {
  const rows = m5b0.split("\n").filter((l) => /^\| (H[123]|P)-\d+ \|/.test(l)).map(cells);
  assert.equal(rows.length, 47);
  assert.deepEqual(["H1-", "H2-", "H3-", "P-"].map((p) => rows.filter((r) => r[0].startsWith(p)).length), [22, 18, 3, 4]);
  assert.ok(rows.every((r) => r[6] === "Pendiente"));
  assert.equal(m5b0.split("\n").filter((l) => l.includes("M7-A")).length, 1);
  assert.ok(rows.every((r) => !r.join(" ").includes("M7-A")));
});

test("the roadmap lists M7-B to M7-H with explicit GO and NO GO conditions, all NO GO today, with no dates or activation promises", () => {
  const roadmap = rowsOf(section(indexDoc, "## 9. Roadmap", "## 10."), "| **M7-");
  assert.deepEqual(roadmap.map((r) => r[0].match(/M7-[A-H]/)[0]), ["M7-B", "M7-C", "M7-D", "M7-E", "M7-F", "M7-G", "M7-H"]);
  for (const row of roadmap) { assert.equal(row.length, 6); assert.ok(row.slice(1).every((c) => c.length > 0), row[0]); assert.match(row[3], /^(Aprobadas|Aprobada|M7-|`RB|Aprobación|M7)/); assert.ok(row[4].length > 0); }
  assert.match(indexDoc, /Estado actual de todos los incrementos: NO GO/);
  const summary = rowsOf(section(agendaDoc, "## 4. Resumen de avance", "## 5."), "| M7-");
  assert.equal(summary.length, 7);
  assert.ok(summary.every((r) => r[2] === "0" && r[3] === "**NO GO**"));
  assert.match(indexDoc, /no equivale por sí solo a GO/);
  assert.match(indexDoc, /no fija fechas ni promete activación/);
  assert.equal(/\bactivaremos\b|\bse activará\b|\bfecha de activación\b/i.test(indexDoc + agendaDoc), false);
  assert.match(indexDoc, /Aprobada con evidencia|Aprobadas con evidencia/);
});

test("the agenda covers every decision in some block and every master question maps to existing decisions", () => {
  const cited = new Set();
  for (const line of agendaDoc.split("\n").filter((l) => l.startsWith("- **Decisiones:**"))) for (const id of refs(line, "CV")) cited.add(id);
  for (const id of cvIds) assert.ok(cited.has(id), `CV:${id} no está en ninguna sesión de la agenda`);
  const questions = rowsOf(section(indexDoc, "## 8. Preguntas maestras", "## 9."), "| Q");
  assert.deepEqual(questions.map((r) => r[0]), Array.from({ length: 10 }, (_, i) => `Q${i + 1}`));
  assert.ok(questions.every((r) => refs(r[2], "CV").length > 0 || /RB:/.test(r[1])));
  assert.match(indexDoc, /responderlas no equivale por sí solo a GO/);
  assert.match(agendaDoc, /no equivale por sí solo a aprobar/);
});

test("the package states the right counts and keeps the evidence M1-B2-c1 as pending", () => {
  assert.match(indexDoc, /36 decisiones = 11 C \+ 11 P \+ 8 N \+ 6 B/);
  assert.match(indexDoc, /47 decisiones = 22 H1 \+ 18 H2 \+ 3 H3 \+ 4 P/);
  assert.match(indexDoc, /P1-16 \(14 = 5 automáticos \+ 8 manuales \+ 1 calculado\), P1-12 \(37 = 9 \+ 20 \+ 8\), P1-13 \(31 = 8 \+ 18 \+ 5\) y P1-11 \(61 = 5 \+ 34 \+ 22, con 10/);
  assert.match(read(SOURCES.B), /61 campos = 5 automáticos \+ 34 manuales \+ 22 calculados/);
  assert.match(read(SOURCES.B), /10\*\*, no 8|10, no 8/);
  assert.match(indexDoc, /M1-B2-c1/);
  assert.match(indexDoc, /evidencia pendiente/i);
  assert.match(indexDoc, /no inventa/);
});

test("every relative link of the package resolves to an existing document or file", () => {
  for (const [file, text] of [["docs/M7-A-conversion-decisiones-VINTO.md", matrixDoc], ["docs/M7-A-homologacion-indice.md", indexDoc], ["docs/M7-A-agenda-y-registro-conversion.md", agendaDoc]]) {
    for (const m of text.matchAll(/\]\(([^)#]+)(?:#[^)]*)?\)/g)) {
      if (/^https?:/.test(m[1])) continue;
      assert.ok(existsSync(join(root, dirname(file), m[1])), `${file}: enlace roto ${m[1]}`);
    }
  }
});

test("the package is documentation only: it changes no code, policy, migration, seed data or configuration", () => {
  const sectors = read("backend/app/sectors.py"), policy = read("backend/app/capture_service.py");
  assert.match(sectors, /DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)/);
  assert.match(policy, /CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)/);
  for (const text of [matrixDoc, indexDoc, agendaDoc]) assert.match(text, /Ninguna decisión está aprobada|Las 36 decisiones están en Pendiente|No contiene respuestas, aprobaciones ni fechas/);
});
