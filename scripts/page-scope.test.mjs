// node --test scripts/page-scope.test.mjs
// Regresión estática de alcance sobre app/page.tsx: la asignación central es solo de Bobinas / Ejecución de producción.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n");

test("Calidad does not consume the central active assignment", () => {
  assert.equal(/qualityOnBobinas|qualityContextFromActive/.test(page), false);
  const hookCalls = page.match(/useActiveAssignment\([^\n]*\n/g) ?? [];
  assert.equal(hookCalls.length, 1);
  assert.match(hookCalls[0], /usesCentralAssignment\(front, activeModule\)/);
  assert.doesNotMatch(hookCalls[0].split("//")[0], /Calidad/); // el comentario puede mencionarla; el código no
});

test("Calidad selection ignores the central assignment state", () => {
  const handler = page.slice(page.indexOf("const handleSelect"), page.indexOf("if (selected)"));
  const calidad = handler.slice(handler.indexOf('front === "Calidad"'), handler.indexOf('if (execState.kind !== "check")'));
  assert.ok(calidad.length > 0);
  assert.equal(/activeAssignment|stale|current_shift/.test(calidad), false);
});

test("Bobinas no longer reads vinto-ot / vinto-asg or the OT-PRUEBA demo", () => {
  assert.match(page, /if \(sector === "Bobinas"\)\s+continue;/);
  assert.match(page, /filter\(o => o\.sector !== "Bobinas"\)/);
  assert.match(page, /filter\(a => !bobinas\.includes\(a\.machine\)\)/);
  assert.match(page, /localStorage\.setItem\("vinto-p1-records"/); // las capturas siguen locales
});
