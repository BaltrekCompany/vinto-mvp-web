// node --test scripts/quality-bobbin-ux.test.mjs
// UX-only invariants: no backend contract changes, no hidden decisions,
// explicit review before a destructive rejection, and accessible compact cards.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const inbox = read("../components/vinto/quality-bobbin-inbox.tsx");
const decision = read("../components/vinto/quality-bobbin-decision.tsx");
const api = read("../lib/vinto/quality-decision-api.ts");

test("each pending bobbin has visible decisions, without a wide horizontal table", () => {
  assert.match(inbox, /items\.map\(i => <article key=\{i\.bobbin\.id\}/);
  assert.match(inbox, /<QualityBobbinDecision item=\{i\} refresh=\{refresh\}\/>/);
  assert.match(decision, /grid grid-cols-2 gap-2/);
  assert.match(decision, />\s*Liberar\s*<\/Button>/);
  assert.match(decision, />\s*Rechazar\s*<\/Button>/);
  assert.doesNotMatch(inbox, /<table|min-w-\[1320px\]|overflow-x-auto/);
  assert.match(inbox, /aria-label=\{"Bobina " \+ i\.bobbin\.code/);
});

test("secondary controls and full production metadata remain reachable", () => {
  assert.match(inbox, /<summary[^>]*>Controles e historial<\/summary>/);
  assert.match(inbox, /<summary[^>]*>Ver más datos de producción<\/summary>/);
  for (const value of ["production.work_order.number", "production.line.line_code", "production.line.pv_reference",
    "production.operating_date", "bobbin.weight_kg", "bobbin.diameter_mm", "bobbin.start_time", "bobbin.end_time",
    "bobbin.number_of_cuts", "bobbin.notes", "production.shift.name"]) {
    assert.ok(inbox.includes("i." + value), value);
  }
  assert.match(inbox, /candidateOffers\?\.\(i\.bobbin\.machine\.code\)/);
  assert.match(inbox, /onRegisterCandidate\?\.\(screen, i\)/);
  assert.match(inbox, /onRegisterHumidity\(i\)/);
  assert.match(inbox, /onRegisterProperties\(i\)/);
  assert.match(inbox, /onViewHistory\(i\)/);
});

test("rejection requires a review step with the exact four entered fields", () => {
  assert.match(decision, /const \[review, setReview\] = useState\(false\)/);
  assert.match(decision, /action === "reject" && \(!canReject \|\| !review\)/);
  assert.match(decision, /setReview\(true\)/);
  assert.match(decision, />Revisar rechazo<\/Button>/);
  assert.match(decision, /Revisa antes de confirmar/);
  assert.match(decision, /Verifica que la clasificación coincida con el detalle/);
  assert.match(decision, /\{typeLabel\}/);
  assert.match(decision, /\{classLabel\}/);
  assert.match(decision, /\{detail\.trim\(\)\}/);
  assert.match(decision, /\{correctiveAction\.trim\(\)\}/);
  assert.match(decision, /"Confirmar rechazo definitivo"/); // explicit second-stage submit
  assert.match(decision, /Volver a editar/);
  assert.match(decision, /setReview\(false\)/);
  assert.match(decision, /rejection_type: rejectionType, classification, detail: detail\.trim\(\), corrective_action: correctiveAction\.trim\(\)/);
});

test("release still confirms context and the endpoint contract remains unchanged", () => {
  assert.match(decision, /window\.confirm\(/);
  assert.match(decision, /item\.production\.work_order\.number/);
  assert.match(decision, /submit\("release"\)/);
  assert.match(decision, /submitQualityDecision\(item\.bobbin\.id, body\)/);
  assert.match(decision, /crypto\.randomUUID\(\)/);
  assert.match(api, /requestJson\(\`\/api\/quality\/bobbins\/\$\{encodeURIComponent\(bobbinId\)\}\/decision\`/);
  for (const text of [inbox, decision]) {
    assert.doesNotMatch(text, /localStorage|sessionStorage|indexedDB|document\.cookie|setInterval|\bfetch\(/);
  }
});
