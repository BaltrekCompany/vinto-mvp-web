import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
const read=p=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
const ui=read("components/vinto/quality-offline-workspace.tsx");
const api=read("lib/vinto/quality-offline-api.ts");
const clock=read("lib/vinto/quality-offline-clock.ts");
const auto=read("lib/vinto/quality-offline-auto-prepare.ts");
const verifier=read("lib/vinto/offline-operational-capture-scope-verify.ts");

test("new offline CAPTURE authority uses authenticated server Date, not raw handset Date.now",()=>{
 assert.match(api,/response\.headers\.get\("Date"\)/);
 assert.match(api,/credentials:"include"/);
 assert.match(clock,/validateQualityServerClock/);
 assert.match(clock,/qualityScopeNow/);
 assert.match(clock,/expires<=issued/);
 assert.match(clock,/clock\.serverDateMs>=expires/);
 assert.match(clock,/clock\.serverDateMs<issued-MAX_RESPONSE_SKEW_MS/);
 assert.match(ui,/now:\(\)=>qualityScopeNow\(active\.data\.clock\)/);
 assert.doesNotMatch(ui,/now:Date\.now/);
 assert.match(verifier,/nowMs>=expires/);
 assert.match(verifier,/crypto\.subtle\.verify/);
});

test("authorized form templates are prepared automatically after unlock without replacing drafts",()=>{
 assert.match(ui,/await autoPrepareQualityForms/);
 assert.match(ui,/await listOfflinePreparations\(identity\)/);
 assert.match(ui,/await readOfflinePreparation\(key,row\)/);
 assert.match(ui,/setPreparationProgress/);
 assert.match(auto,/matchingQualityPreparation/);
 assert.match(auto,/if\(matchingQualityPreparation\(saved,offer,bobbin\)\)\{skipped\+\+;\}/);
 assert.match(auto,/saveOfflinePreparation/);
 assert.match(auto,/offer\.kind==="bobbin"&&\(!bobbin/);
 assert.match(auto,/onProgress\?\./);
 assert.match(ui,/Formularios disponibles sin internet|Cobertura por bobina y formulario/);
});

test("original Quality forms, single-author offline vault and actual capture ACK remain intact",()=>{
 assert.match(ui,/CandidateFormCapture/);
 assert.match(ui,/QualityHumidityCapture/);
 assert.match(ui,/QualityPhysicalCapture/);
 assert.match(ui,/createOperationalSyncRuntime/);
 assert.match(ui,/fetcher:fetch\.bind\(window\)/);
 assert.match(auto,/prepareQualityDevice/);
 assert.match(auto,/validateQualityServerClock/);
 assert.match(ui,/requirePersistedQualityDevice/);
});
