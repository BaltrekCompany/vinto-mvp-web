import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
const read=path=>readFileSync(new URL("../"+path,import.meta.url),"utf8");
const app=read("app/page.tsx");
const ui=read("components/vinto/quality-offline-workspace.tsx");
const sw=read("public/vinto-quality-offline-sw.js");
const api=read("backend/app/quality/offline_router.py");
const receiver=read("backend/app/quality/offline_sync_router.py");
const config=read("backend/app/config.py");
test("existing VINTO login exposes original Quality workspace without replacing online routes",()=>{
 assert.match(app,/QualityOfflineWorkspace/);
 assert.match(app,/Recuperar formularios de Calidad preparados sin internet/);
 assert.match(app,/front === "Calidad"/);
 assert.match(ui,/QUALITY_CANDIDATES/);
 assert.match(ui,/QUALITY_BOBBIN_CANDIDATES/);
 assert.match(ui,/QualityHumidityCapture/);
 assert.match(ui,/QualityPhysicalCapture/);
});
test("online preparation has signed scope, original user, vault and explicit shell gate",()=>{
 assert.match(ui,/enrollQualityOfflineDevice/);
 assert.match(ui,/requestQualityOfflineAuthority/);
 assert.match(ui,/prepareQualityDevice/);
 assert.match(ui,/prepareQualityOfflineShell/);
 assert.match(ui,/requirePersistedQualityDevice/);
 assert.match(ui,/unlockLocalVault/);
 assert.match(ui,/listOfflinePreparations/);
 assert.match(ui,/createOperationalCaptureBindings/);
});
test("automatic synchronization only uploads under a revalidated online original-author session",()=>{
 assert.match(ui,/createOperationalSyncRuntime/);
 assert.match(ui,/getCurrentUser\(\)/);
 assert.match(ui,/result.status==="authenticated"/);
 assert.match(ui,/notifyReady\(\)/);
 assert.match(receiver,/author_user_id/);
 assert.match(receiver,/str\(body.author_user_id\) != str\(user.user_id\)/);
 assert.match(receiver,/operational_registered":True/);
 assert.match(receiver,/quality_bobbin_context_digest/);
 assert.match(receiver,/gate_for\(user, "enforce"/);
});
test("production stays OFF by default; signed grants never authorize release/reject",()=>{
 assert.match(config,/offline_quality_capture_enabled: bool = False/);
 assert.match(api,/offline_quality_capture_enabled/);
 assert.doesNotMatch(receiver,/QUALITY_RELEASE|quality_release\s+SET/);
});
test("service worker caches only the existing shell and static chunks, never API data",()=>{
 assert.match(sw,/u.pathname.startsWith\("\/_next\/static\/"\)/);
 assert.match(sw,/u.pathname==="\/" && request.mode==="navigate"/);
 assert.match(sw,/request.method!=="GET"/);
 assert.doesNotMatch(sw,/cache\.put\([^)]*api/);
 assert.doesNotMatch(sw,/indexedDB|localStorage|postMessage\(\{.*key/);
});

test("operational transport binds window.fetch to avoid Illegal invocation",()=>{
 assert.match(ui,/fetcher:fetch\.bind\(window\)/);
 assert.doesNotMatch(ui,/fetcher:fetch\s*[,}]/);
});
