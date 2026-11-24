import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";

const mobile=readFileSync(new URL("../lib/vinto/offline-operational-mobile-page.ts",import.meta.url),"utf8");

test("legacy encrypted profile does not hide online login without active session",()=>{
 assert.match(mobile,/show\("login-panel",!user\);/);
 assert.doesNotMatch(mobile,/show\("login-panel",!user&&!profile\)/);
});

test("unlock preserves draft state and exposes renewal when no CAPTURE authority exists",()=>{
 const unlock=mobile.slice(mobile.indexOf("async function unlock(passphrase:"),mobile.indexOf("async function lock(){"));
 assert.match(unlock,/await loadPackages\(\);startSync\(\);await refreshDrafts\(\)/);
 assert.match(unlock,/const missingAuthority=await Promise\.all\(packages\.map/);
 assert.match(unlock,/await signedFor\(pkg\)/);
 assert.match(unlock,/show\("login-panel",!user\);show\("prepare-panel",!!user\)/);
 assert.match(unlock,/Falta autorización CAPTURE/);
 assert.doesNotMatch(unlock,/show\("login-panel",false\)/);
});

test("capture remains fail closed: new draft requires signed authorization",()=>{
 assert.match(mobile,/if\(!latest\)throw Error\("No existe una autorización CAPTURE válida/);
 assert.match(mobile,/const authority=requiredSnapshot[\s\S]*?: await signedFor\(pkg\)/);
});
