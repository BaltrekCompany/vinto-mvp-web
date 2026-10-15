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

test("Calidad selection ignores the central assignment state: INT-02A removed the Calidad branch of handleSelect and the Calidad local cards", () => {
  const handler = page.slice(page.indexOf("const handleSelect"), page.indexOf("const openCandidate"));
  assert.equal(/Calidad/.test(handler), false, "handleSelect solo sirve a Bobinas (F3 / P1-06)");
  assert.equal(/activeAssignment|stale|current_shift/.test(handler), false);
  const execution = page.slice(page.indexOf("function Execution("), page.indexOf("function Cards("));
  const calidad = execution.slice(execution.indexOf('if (front === "Calidad")'), execution.indexOf("return <>"));
  assert.ok(calidad.length > 0);
  assert.equal(/Cards|forms=|select/.test(calidad), false, "Calidad no abre tarjetas locales");
});

test("INT-02A: the page no longer reads or writes vinto-ot / vinto-asg / vinto-p1-records nor builds demo OT or assignments", () => {
  const code = page.replace(/\/\/.*$/gm, "");
  assert.equal(/localStorage|sessionStorage/.test(code), false);
  assert.equal(/vinto-ot|vinto-asg|vinto-p1-records/.test(code), false);
  assert.equal(/demoSeedData|ensureDemoCoverage|loadCoverage|localContext|OT-PRUEBA/.test(code), false);
  assert.equal(/useState<OT\[\]|useState<Assignment\[\]|setOts|setAsg/.test(code), false);
});
