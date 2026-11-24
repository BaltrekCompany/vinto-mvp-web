import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
const mobile=readFileSync(new URL("../lib/vinto/offline-operational-mobile-page.ts",import.meta.url),"utf8");
const renewal=readFileSync(new URL("../lib/vinto/offline-renewal.ts",import.meta.url),"utf8");

test("existing encrypted profile renews signed readiness and packages atomically",()=>{
 const enroll=mobile.slice(mobile.indexOf("async function enroll("),mobile.indexOf("async function unlock("));
 assert.match(enroll,/const existingScope=await readRawScope\(identityNow\)/);
 assert.match(enroll,/if\(existingScope\)\{/);
 assert.match(enroll,/await renewOfflineBundle\(opened,identityNow,/);
 assert.match(enroll,/fetchPackage:async\(machineCode,formCode,scope\)/);
 assert.match(enroll,/extraPairs:extras/);
 assert.match(enroll,/const verifiedReadiness=await readOfflineScope\(opened,identityNow\)/);
 assert.ok(enroll.indexOf("renewOfflineBundle(")<enroll.indexOf('"/api/offline/capture-scope"'));
 assert.ok(!enroll.includes("allowReplaceUnreadable:true"));
});

test("fresh profiles retain signed enrollment and never bypass CAPTURE validation",()=>{
 const enroll=mobile.slice(mobile.indexOf("async function enroll("),mobile.indexOf("async function unlock("));
 assert.match(enroll,/else\{\s*await storeOfflineScope\(opened,identityNow/);
 assert.match(enroll,/await storeCaptureAuthority\(opened,identityNow,signed/);
 assert.match(renewal,/const expectedScopeSnapshotId/);
 assert.match(renewal,/await commit\(\{/);
 assert.match(renewal,/db\.transaction\(\["profiles", SCOPE_STORE_NAME, PACKAGE_STORE_NAME\], "readwrite"\)/);
});
