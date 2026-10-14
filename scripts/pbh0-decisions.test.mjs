// node --test scripts/pbh0-decisions.test.mjs
// PB-H0 · integridad del paquete documental de homologación de Bobinas MP1/MP3 y Calidad: las decisiones `BO:` tienen claves únicas y bien formadas, cubren las 21 preguntas de origen (Q-1..Q-8, B-1..B-5, O-1..O-8)
// del diagnóstico del piloto, enlazan a brechas PB, decisiones CV y RB que existen, siguen todas «Pendiente», no tienen dependencias cíclicas ni relaciones «responder junto con» asimétricas, clasifican los bloqueos
// de Q-LIB, PB-MAESTROS y PB-ENV, y son coherentes con las 18 condiciones GO / NO GO. Solo lee documentos y dos constantes de código; no valida reglas industriales ni aprueba nada: un test que pasa no es evidencia de aprobación.
// El número de decisiones se DERIVA de la matriz; no se fija de antemano.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";

const root = resolve(import.meta.dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8").replace(/\r\n/g, "\n");
const DOCS = { index: "docs/PB-H0-homologacion-indice.md", matrix: "docs/PB-H0-decisiones-VINTO.md", agenda: "docs/PB-H0-agenda-y-registro.md" };
const indexDoc = read(DOCS.index), matrixDoc = read(DOCS.matrix), agendaDoc = read(DOCS.agenda);
const diagnosis = read("docs/PILOTO-BOBINAS-brechas-y-GO-NOGO.md"), m5b0 = read("docs/M5-B0-decisiones-VINTO.md"), m7a = read("docs/M7-A-conversion-decisiones-VINTO.md");

const cells = (line) => line.split(/(?<!\\)\|/).slice(1, -1).map((c) => c.trim());
const section = (text, from, to) => text.split(from)[1].split(to)[0];
const rowsOf = (text, prefix) => text.split("\n").filter((l) => l.startsWith(prefix)).map(cells);
const list = (value) => (value === "—" || value === "" ? [] : value.split(",").map((s) => s.trim()));
const sortKey = (id) => id.replace(/^BO:/, "");

const main = rowsOf(section(matrixDoc, "## 2. Matriz de decisiones", "## 3. Trazabilidad"), "| BO:");
const meta = rowsOf(section(matrixDoc, "## 3. Trazabilidad", "### Revisión de las dependencias"), "| BO:");
const registry = rowsOf(section(agendaDoc, "## 3. Formato breve de registro", "## 4. Resumen"), "| BO:");
const ids = main.map((r) => r[0]);
const byId = new Map(meta.map((r) => [r[0], { origin: list(r[1]), pb: list(r[2]), dep: list(r[3]), just: r[4], soft: list(r[5]), links: list(r[6]), qlib: r[7], mae: r[8], env: r[9], go: list(r[10]), cond: r[11] }]));

const pbIds = new Set(diagnosis.split("\n").map((l) => l.match(/^\| (?:\*\*)?(PB-[ABC]\d+)/)?.[1]).filter(Boolean));
const questionIds = [...diagnosis.matchAll(/^- \*\*([QBO]-\d+)\*\*/gm)].map((m) => m[1]);
const cvIds = new Set(rowsOf(m7a.split("## 2. Matriz de decisiones")[1].split("## 3.")[0], "| CV:").map((r) => r[0]));
const rbIds = new Set(m5b0.split("\n").filter((l) => /^\| (H[123]|P)-\d+ \|/.test(l)).map((l) => cells(l)[0]));
const conditions = rowsOf(section(diagnosis, "## 10. Checklist GO / NO GO del piloto", "**Regla de decisión"), "| ").filter((r) => /^\d+$/.test(r[0]));

test("las claves BO: son únicas, bien formadas, contiguas por familia y están en el mismo orden en matriz, trazabilidad y registro", () => {
  assert.ok(ids.length > 0);
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every((id) => /^BO:(CAL|CON|MAE|OPS)-\d{2}$/.test(id)), "todas las claves llevan BO:<FAM>-NN");
  for (const fam of ["CAL", "CON", "MAE", "OPS"]) {
    const nums = ids.filter((id) => id.startsWith(`BO:${fam}-`)).map((id) => Number(id.split("-")[1]));
    assert.ok(nums.length > 0, fam);
    assert.deepEqual(nums, Array.from({ length: nums.length }, (_, i) => i + 1), `${fam}: IDs contiguos desde 01`);
  }
  assert.deepEqual(meta.map((r) => r[0]), ids);
  assert.deepEqual(registry.map((r) => r[0]), ids);
  assert.equal(ids.some((id) => /^BO:(PB|CV|RB)/.test(id)), false);
});

test("el conteo declarado en el índice y en la matriz coincide con el derivado de la matriz", () => {
  const total = ids.length, count = (fam) => ids.filter((id) => id.startsWith(`BO:${fam}-`)).length;
  assert.ok(matrixDoc.includes(`(${total})\n`), "el título de la matriz declara el total derivado");
  assert.ok(matrixDoc.includes(`**${total} decisiones = ${count("CAL")} CAL + ${count("CON")} CON + ${count("MAE")} MAE + ${count("OPS")} OPS**`));
  assert.ok(indexDoc.includes(`| **Total** | | **${total}** | |`));
  for (const fam of ["CAL", "CON", "MAE", "OPS"]) assert.ok(new RegExp(`\`BO:${fam}\` \\| ${count(fam)} \\|`).test(indexDoc), `índice: conteo de ${fam}`);
  assert.equal(agendaDoc.includes(`las ${total} decisiones`), true);
});

test("las 21 preguntas de origen del diagnóstico están cubiertas en ambos sentidos y las decisiones de contratos son individuales", () => {
  assert.equal(questionIds.length, 21);
  assert.equal(new Set(questionIds).size, 21);
  assert.deepEqual([...questionIds].sort(), [..."Q-1 Q-2 Q-3 Q-4 Q-5 Q-6 Q-7 Q-8 B-1 B-2 B-3 B-4 B-5 O-1 O-2 O-3 O-4 O-5 O-6 O-7 O-8".split(" ")].sort());
  const covered = new Map(questionIds.map((q) => [q, []]));
  for (const [id, info] of byId) {
    assert.ok(info.origin.length > 0, `${id} sin origen`);
    for (const o of info.origin) assert.ok(covered.has(o) || pbIds.has(o), `${id}: origen desconocido ${o}`);
    for (const o of info.origin) if (covered.has(o)) covered.get(o).push(id);
  }
  for (const [q, mine] of covered) assert.ok(mine.length > 0, `${q} sin decisión`);
  const table = new Map(rowsOf(section(indexDoc, "## 6. Cobertura de las 21 preguntas de origen", "Las 3 decisiones adicionales"), "| ").filter((r) => /^[QBO]-\d+$/.test(r[0])).map((r) => [r[0], list(r[2])]));
  assert.equal(table.size, 21);
  for (const [q, mine] of covered) assert.deepEqual([...table.get(q)].sort(), [...mine].sort(), `${q}: tabla del índice distinta de la matriz`);
  // B-1 se divide: un contrato por formulario, sin una respuesta general que cubra los cuatro
  const contract = (formText) => main.filter((r) => r[0].startsWith("BO:CON-") && r[2].includes(formText)).map((r) => r[0]);
  for (const form of ["F3", "P1-06", "P1-19", "P1-20"]) assert.ok(contract(form).length >= 1, `contrato individual de ${form}`);
  assert.equal(new Set([...contract("F3"), ...contract("P1-06"), ...contract("P1-19"), ...contract("P1-20")]).size >= 4, true);
});

test("las referencias a brechas PB, decisiones CV y decisiones RB existen y las decisiones CV y RB no se copian", () => {
  assert.equal(pbIds.size, 27);
  for (const [id, info] of byId) {
    assert.ok(info.pb.length > 0, `${id} sin brecha PB`);
    for (const p of info.pb) assert.ok(pbIds.has(p), `${id}: brecha inexistente ${p}`);
    for (const l of info.links) {
      if (l.startsWith("CV:")) assert.ok(cvIds.has(l), `${id}: ${l} no existe en M7-A`);
      else if (l.startsWith("RB:")) assert.ok(rbIds.has(l.slice(3)), `${id}: ${l} no existe en M5-B0`);
      else assert.fail(`${id}: vínculo desconocido ${l}`);
    }
  }
  for (const text of [indexDoc, matrixDoc, agendaDoc]) {
    for (const m of text.matchAll(/\bCV:([CPNB]-\d+)\b/g)) assert.ok(cvIds.has(`CV:${m[1]}`), `CV:${m[1]} no existe`);
    for (const m of text.matchAll(/\bRB:((?:H[123]|P)-\d+)\b/g)) assert.ok(rbIds.has(m[1]), `RB:${m[1]} no existe`);
  }
  assert.equal(cvIds.size, 36);
  assert.equal(rbIds.size, 47);
  assert.equal(new RegExp(String.raw`^\| (CV|RB):`, "m").test(matrixDoc.split("## 2. Matriz de decisiones")[1].split("## 3.")[0]), false, "las decisiones CV y RB no se copian como filas");
});

test("todas las decisiones siguen Pendiente y el registro tiene una fila por decisión con respuestas vacías", () => {
  const roles = new Set(["JP", "CAL", "DB", "TI", "DIR"]);
  for (const row of main) {
    assert.equal(row.length, 8, row[0]);
    assert.equal(row[7], "Pendiente", `${row[0]} debe seguir Pendiente`);
    assert.ok(row.every((c) => c.length > 0), `${row[0]} tiene celdas vacías`);
    assert.ok(row[6].split(",").map((r) => r.trim()).every((r) => roles.has(r)), `${row[0]}: responsable desconocido`);
  }
  assert.equal(registry.length, ids.length);
  for (const row of registry) {
    assert.equal(row.length, 10, row[0]);
    assert.equal(row[2], "Pendiente", `${row[0]} registro`);
    assert.deepEqual(row.filter((_, i) => i !== 0 && i !== 2), Array(8).fill(""), `${row[0]}: el registro inicial debe tener las respuestas vacías`);
  }
  for (const text of [indexDoc, matrixDoc, agendaDoc]) assert.equal(/\|\s*(Aprobado|Respondido, sin evidencia|En revisión|Rechazado[^|]*)\s*\|/.test(text), false, "ningún estado distinto de Pendiente en las tablas");
  // nombre exacto del estado, como en M5-B0 acta §1 (la variante sin coma es incorrecta)
  const actaStates = read("docs/M5-B0-acta-homologacion.md").split("\n").filter((l) => /^\| \*\*[^*]+\*\* \|/.test(l)).map((l) => cells(l)[0].replace(/\*/g, ""));
  assert.deepEqual(actaStates, ["Pendiente", "Respondido, sin evidencia", "En revisión", "Aprobado", "Rechazado / requiere rediseño"]);
  assert.ok(agendaDoc.includes(`${actaStates.slice(0, 4).join(", ")}, ${actaStates[4]}`), "la lista de estados del registro usa los nombres exactos de M5-B0");
  for (const text of [indexDoc, matrixDoc, agendaDoc]) assert.equal(/Respondido sin evidencia/.test(text), false, "«Respondido sin evidencia» (sin coma) es una variante incorrecta");
  assert.match(agendaDoc, /M5-B0-acta-homologacion\.md/);
});

test("no hay dependencias cíclicas, cada dependencia dura está justificada y «responder junto con» es simétrico y disjunto de las dependencias duras", () => {
  const hard = new Map(), soft = new Map();
  for (const [id, info] of byId) {
    for (const t of [...info.dep, ...info.soft]) assert.ok(byId.has(t), `${id}: referencia inexistente ${t}`);
    assert.equal(info.dep.includes(id) || info.soft.includes(id), false, `${id}: se referencia a sí misma`);
    assert.equal(new Set(info.dep).size, info.dep.length);
    assert.equal(info.dep.length === 0 || (info.just !== "—" && info.just.length > 40), true, `${id}: la dependencia dura exige justificación`);
    assert.equal(info.dep.length === 0 && info.just !== "—", false, `${id}: justificación sin dependencia`);
    for (const t of info.dep) assert.equal(info.soft.includes(t), false, `${id}: ${t} es dura y «junto con» a la vez`);
    hard.set(id, info.dep); soft.set(id, info.soft);
  }
  for (const [a, mine] of soft) for (const b of mine) assert.ok(soft.get(b).includes(a), `${a} ↔ ${b} no es simétrica`);
  const state = new Map();
  const visit = (id, trail) => {
    if (state.get(id) === 1) assert.fail(`ciclo: ${[...trail, id].join(" → ")}`);
    if (state.get(id) === 2) return;
    state.set(id, 1);
    for (const t of hard.get(id)) visit(t, [...trail, id]);
    state.set(id, 2);
  };
  for (const id of ids) visit(id, []);
  const declared = matrixDoc.match(/Solo se conservan \*\*(\d+) dependencias duras\*\*/);
  assert.equal(Number(declared[1]), [...hard.values()].reduce((n, v) => n + v.length, 0), "el conteo de dependencias duras declarado coincide con la matriz");
});

test("los bloqueos de Q-LIB, PB-MAESTROS y PB-ENV están clasificados, derivados de la matriz y reflejados en el índice, el roadmap y el resumen de avance", () => {
  for (const [id, info] of byId) for (const col of ["qlib", "mae", "env"]) assert.ok(["B", "C", "—"].includes(info[col]), `${id}: ${col} inválido`);
  const set = (col, v) => ids.filter((id) => byId.get(id)[col] === v);
  const qb = set("qlib", "B"), qc = set("qlib", "C"), mb = set("mae", "B"), eb = set("env", "B");
  assert.ok(qb.length > 0 && qb.every((id) => id.startsWith("BO:CAL-")), "los bloqueos de Q-LIB son decisiones de Calidad");
  assert.ok(ids.filter((id) => id.startsWith("BO:CAL-")).every((id) => ["B", "C"].includes(byId.get(id).qlib)), "toda decisión de Calidad condiciona Q-LIB");
  assert.ok(mb.length > 0 && mb.every((id) => id.startsWith("BO:MAE-")));
  assert.ok(eb.length > 0 && eb.every((id) => id.startsWith("BO:OPS-")));
  const puerta2 = indexDoc.split("\n").find((l) => l.startsWith("| **2 · GO de diseño"));
  const q = indexDoc.split("\n").find((l) => l.startsWith("| **Q-LIB**")), mae = indexDoc.split("\n").find((l) => l.startsWith("| **PB-MAESTROS**")), env = indexDoc.split("\n").find((l) => l.startsWith("| **PB-ENV**"));
  for (const [row, bs] of [[puerta2, qb], [q, qb], [mae, mb], [env, eb]]) for (const id of bs) assert.ok(row.includes(id), `${id} debe figurar en la fila de su incremento`);
  const mentioned = (row) => [...row.matchAll(/BO:[A-Z]{3}-\d{2}/g)].map((m) => m[0]);
  assert.deepEqual([...new Set(mentioned(q))].sort(), [...qb, ...qc.filter((id) => q.includes(id))].sort());
  const summary = rowsOf(section(agendaDoc, "## 4. Resumen de avance", "## 5."), "| ");
  const row = (name) => summary.find((r) => r[0].startsWith(name));
  for (const name of ["Q-LIB", "PB-MAESTROS", "PB-ENV", "UAT", "GO del piloto"]) assert.ok(row(name)[3].includes("NO GO") && row(name)[2] === "0", name);
  for (const id of qb) assert.ok(row("Q-LIB")[1].includes(id));
});

test("la puerta de Q-LIB distingue regla industrial, validación automática, comprobación manual y no aplicabilidad formal, y no admite «no aplicable» por falta de automatización", () => {
  for (const word of ["regla industrial exigida por VINTO", "validación automática", "comprobación manual", "decisión formal de no aplicabilidad"]) { assert.ok(indexDoc.includes(word), `índice: ${word}`); assert.ok(matrixDoc.includes(word), `matriz: ${word}`); }
  assert.match(indexDoc, /no\*\* pasa a «no aplicable» porque el sistema no la automatice/);
  assert.match(indexDoc, /\*\*aprobación identificable\*\*[^.]*antes de implementar el flujo/);
  assert.match(indexDoc, /nunca por falta de automatización/);
  const cond = (id) => byId.get(id).cond;
  for (const id of ["BO:CAL-02", "BO:CAL-03", "BO:CAL-10", "BO:CAL-11"]) {
    assert.equal(byId.get(id).qlib, "B", `${id}: una regla industrial aplicable no es condicional por el grado de automatización`);
    assert.match(cond(id), /aunque|incluso/, `${id}: la condición aclara que rige sin automatización`);
  }
  for (const id of ["BO:CAL-02", "BO:CAL-03"]) assert.match(main.find((r) => r[0] === id)[3], /Verificación: automática en el sistema \/ manual por persona autorizada: … \/ no aplica \(decisión formal de VINTO con evidencia\)/);
  const cal10 = main.find((r) => r[0] === "BO:CAL-10"), cal11 = main.find((r) => r[0] === "BO:CAL-11");
  assert.ok(/solo informativo o produce efectos operativos/.test(cal10[2]) && /Solo informativo \(sin efecto operativo\)/.test(cal10[3]));
  assert.ok(/aunque el sistema únicamente registre su estado/.test(cal11[2]));
  // CAL-04 es condicional únicamente por aplicabilidad real frente a CAL-03
  assert.equal(byId.get("BO:CAL-04").qlib, "C");
  assert.deepEqual(byId.get("BO:CAL-04").dep, ["BO:CAL-03"]);
  assert.match(cond("BO:CAL-04"), /solo por aplicabilidad[\s\S]*nunca por falta de automatización/);
  // OPS-19: condicional solo para vistas adicionales; los controles mínimos de la pantalla de decisión salen de CAL-05..09
  assert.equal(byId.get("BO:OPS-19").qlib, "C");
  assert.match(cond("BO:OPS-19"), /solo para vistas e indicadores adicionales/);
  assert.match(cond("BO:OPS-19"), /controles mínimos de la pantalla de decisión/);
  for (const id of ["BO:CAL-05", "BO:CAL-06", "BO:CAL-07", "BO:CAL-08", "BO:CAL-09"]) assert.equal(byId.get(id).qlib, "B", `${id} sostiene los controles mínimos de la pantalla de decisión`);
  // ninguna decisión condicional de Calidad se justifica por «el sistema no lo valida»
  for (const id of ids.filter((x) => x.startsWith("BO:CAL-") && byId.get(x).qlib === "C")) assert.equal(/si el sistema (debe )?valid|solo si el sistema/i.test(cond(id)), false, `${id}: condicional por automatización`);
  assert.match(indexDoc, /puerta 2 \*\*NO GO\*\*/);
});

test("BO:MAE-03 no depende de forma dura de BO:MAE-02: se responden juntas y la homologación de pesos por artículo exige los artículos oficiales", () => {
  assert.deepEqual(byId.get("BO:MAE-03").dep, []);
  assert.ok(byId.get("BO:MAE-03").soft.includes("BO:MAE-02") && byId.get("BO:MAE-02").soft.includes("BO:MAE-03"));
  assert.match(byId.get("BO:MAE-03").cond, /Puede resolverse antes de aprobar la lista de artículos/);
  assert.match(byId.get("BO:MAE-03").cond, /por artículo\*\* sí requerirá la correspondencia con los artículos oficiales/);
});

test("las tres puertas están separadas y la aprobación documental no autoriza la activación; Q-LIB sigue NO GO con la política pendiente", () => {
  for (const heading of ["| **1 · Cierre documental PB-H0**", "| **2 · GO de diseño / implementación de Q-LIB**", "| **3 · GO del piloto**"]) assert.ok(indexDoc.includes(heading), heading);
  assert.match(indexDoc, /puerta 2 \*\*NO GO\*\*/);
  assert.match(indexDoc, /puerta 3 \*\*NO GO\*\*/);
  assert.match(indexDoc, /La aprobación documental nunca autoriza por sí misma la activación del sistema/);
  assert.match(indexDoc, /autorización \*\*expresa\*\* de desarrollo/);
  assert.match(indexDoc, /PB-H0 no equivale a una homologación industrial/);
  assert.match(matrixDoc, /Este paquete no equivale a una homologación industrial/);
  assert.match(indexDoc, /18 condiciones/);
  assert.match(indexDoc, /independiente de M7-B, que pertenece a Conversión/);
  const gate2 = indexDoc.split("\n").find((l) => l.startsWith("| **2 · GO de diseño"));
  assert.ok(gate2.includes("**Aprobadas con evidencia**") && gate2.includes("autorización **expresa**"));
  // mientras haya una decisión de Calidad bloqueante Pendiente, el estado de Q-LIB no puede ser GO
  const pending = ids.filter((id) => byId.get(id).qlib === "B" && main.find((r) => r[0] === id)[7] === "Pendiente");
  assert.ok(pending.length > 0);
  assert.equal(/Q-LIB[^\n]*\*\*GO\*\*/.test(indexDoc.replace(/NO GO/g, "")), false);
});

test("la matriz es coherente con las 18 condiciones GO / NO GO del diagnóstico", () => {
  assert.equal(conditions.length, 18);
  assert.deepEqual(conditions.map((r) => Number(r[0])), Array.from({ length: 18 }, (_, i) => i + 1));
  const type = new Map(conditions.map((r) => [Number(r[0]), r[1]]));
  assert.deepEqual([...type].filter(([, t]) => t === "T").map(([n]) => n), [4, 6, 7, 8, 9, 10, 11, 12, 16, 17]);
  assert.deepEqual([...type].filter(([, t]) => t === "V").map(([n]) => n), [1, 2, 3, 5, 15, 18]);
  assert.equal(type.get(13), "A");
  assert.equal(type.get(14), "R");
  const used = new Set();
  for (const [id, info] of byId) {
    assert.ok(info.go.length > 0, `${id} sin condición GO`);
    for (const n of info.go) { assert.ok(type.has(Number(n)), `${id}: condición inexistente ${n}`); used.add(Number(n)); }
  }
  for (const n of [1, 2, 3, 5, 15, 18]) assert.ok(used.has(n), `la condición V ${n} debe estar alimentada por una decisión`);
  for (const n of [13, 14]) assert.ok(used.has(n), `la condición ${type.get(n)} ${n} debe estar alimentada por una decisión`);
  for (const n of [8, 9, 10, 12, 16]) assert.ok(used.has(n), `la condición T ${n} con insumos de VINTO debe estar alimentada`);
  // las condiciones que no pueden omitirse no dependen de ninguna decisión que las excluya
  for (const t of ["BO:OPS-06", "BO:OPS-10", "BO:OPS-04"]) assert.equal(byId.get(t).go.some((n) => ["4", "6", "7", "11", "16", "17"].includes(n)), false, `${t} no puede excluir una condición T técnica`);
  assert.match(indexDoc, /no pueden omitirse/);
  assert.match(indexDoc, /política temporal con responsable, procedimiento de incidencias y tratamiento de registros incorrectos/);
});

test("el correlativo F3 registra la discrepancia sin resolverla ni modificar la lógica", () => {
  for (const text of [indexDoc, matrixDoc]) assert.match(text, /01\/04–31\/03/);
  assert.match(indexDoc, /31\/12/);
  assert.match(indexDoc, /No se resuelve aquí/);
  assert.match(indexDoc, /No se modifica código ni migraciones/);
  const mae09 = main.find((r) => r[0] === "BO:MAE-09");
  assert.ok(mae09[2].includes("01/04–31/03") && mae09[2].includes("31/12") && mae09[4].includes("ninguna fuente del repositorio"));
  for (const id of ["BO:MAE-09", "BO:MAE-10", "BO:MAE-11", "BO:MAE-12"]) assert.ok(byId.has(id));
  assert.deepEqual(byId.get("BO:MAE-10").dep, ["BO:MAE-09"]);
  assert.deepEqual(byId.get("BO:MAE-12").dep, ["BO:MAE-10"]);
});

test("cada decisión de Calidad respeta que quality.release no es autoridad industrial y no se fija ninguna política", () => {
  const cal05 = main.find((r) => r[0] === "BO:CAL-05");
  assert.ok(cal05[4].includes("no equivale a autoridad industrial"));
  for (const id of ["BO:CAL-06", "BO:CAL-08", "BO:CAL-09", "BO:CAL-12"]) assert.ok(byId.has(id));
  for (const row of main.filter((r) => r[0].startsWith("BO:CAL-"))) assert.equal(/Aprobad[oa]/.test(row[7]), false);
  assert.equal(/tolerancias? de \d|límite de \d|≥ ?\d|≤ ?\d/.test(matrixDoc), false, "no se fijan tolerancias numéricas");
  assert.match(matrixDoc, /el diagnóstico no impide ni prescribe la reversión/);
});

test("la agenda cubre cada decisión exactamente una vez, lista las evidencias y no duplica las agendas de M5-B0 ni de M7-A", () => {
  const sessions = agendaDoc.split("\n").filter((l) => l.startsWith("- **Decisiones:**"));
  assert.ok(sessions.length >= 5);
  const listed = sessions.flatMap((l) => [...l.matchAll(/BO:[A-Z]{3}-\d{2}/g)].map((m) => m[0]));
  assert.deepEqual([...listed].sort(), [...ids].sort(), "cada decisión debe figurar una vez en una sesión");
  assert.equal(new Set(listed).size, listed.length);
  assert.equal([...agendaDoc.matchAll(/^### Sesión /gm)].length, 6);
  for (const label of ["Participantes recomendados", "Objetivo", "Preguntas maestras", "Decisiones", "Material que VINTO debe llevar", "Resultado esperado", "Pendientes y responsables"]) assert.equal([...agendaDoc.matchAll(new RegExp(`\\*\\*${label}:\\*\\*`, "g"))].length >= 6, true, label);
  assert.match(agendaDoc, /M5-B0-agenda-homologacion\.md/);
  assert.match(agendaDoc, /M7-A-agenda-y-registro-conversion\.md/);
  assert.equal(agendaDoc.split("\n").length < 250, true);
});

test("ninguna aprobación, aprobador ni fecha inventados y no se tocan los sectores habilitados ni CENTRAL_FORM_CODES", () => {
  for (const [name, text] of Object.entries({ index: indexDoc, matrix: matrixDoc, agenda: agendaDoc })) {
    assert.equal(/\b20\d{2}-\d{2}-\d{2}\b/.test(text.replace(/2026-01-01/g, "")), false, `${name}: sin fechas`);
    assert.equal(/\b\d{1,2}\/\d{1,2}\/20\d{2}\b/.test(text), false, `${name}: sin fechas`);
    assert.equal(/aprobad[oa] por [A-ZÁÉÍÓÚ][a-záéíóú]+ [A-ZÁÉÍÓÚ]/.test(text), false, `${name}: sin aprobadores`);
  }
  assert.match(indexDoc, /no inventa/);
  const sectors = readFileSync(join(root, "backend/app/sectors.py"), "utf8"), capture = readFileSync(join(root, "backend/app/capture_service.py"), "utf8");
  assert.match(sectors, /^DEFAULT_OPERATIONAL_SECTORS = \(SECTOR_BOBINAS,\)$/m);
  assert.match(capture, /^FORM_CODE = "VINTO-P1-06"/m);
  assert.match(capture, /^CENTRAL_FORM_CODES = frozenset\(\{FORM_CODE\}\)$/m);
});

test("los enlaces relativos a documentos existen", () => {
  for (const [name, file] of Object.entries(DOCS)) {
    const text = read(file);
    for (const m of text.matchAll(/\]\(([^)#\s]+\.md)(?:#[^)]*)?\)/g)) assert.ok(existsSync(join(dirname(join(root, file)), m[1])), `${name}: enlace roto ${m[1]}`);
  }
  for (const f of ["docs/PILOTO-BOBINAS-brechas-y-GO-NOGO.md", "docs/M5-B0-acta-homologacion.md", "docs/M5-B0-agenda-homologacion.md", "docs/M7-A-agenda-y-registro-conversion.md"]) assert.ok(existsSync(join(root, f)), f);
});
