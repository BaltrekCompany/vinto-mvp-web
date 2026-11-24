import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
const read=(name)=>readFileSync(new URL("../"+name,import.meta.url),"utf8");
const mobile=read("lib/vinto/offline-operational-mobile-page.ts");
const html=read("lab/offline-calidad.html");

test("offline mobile prepares after authenticated unlock, no permanent manual preparation",()=>{
 assert.match(mobile,/void unlock\(pass\)\.then\(\(\)=>autoPrepare\(\)\)/);
 assert.match(mobile,/if\(key\)await autoPrepare\(\)/);
 assert.match(mobile,/async function autoPrepare\(\)/);
 assert.match(mobile,/if\(!navigator\.onLine\)/);
 assert.match(mobile,/preparationBusy\|\|!user\|\|!key/);
 assert.match(mobile,/window\.addEventListener\("online"/);
 assert.match(mobile,/identity\.ownerId!==user\.id\.toLowerCase\(\)/);
 assert.match(mobile,/preparationBusy=true/);
 assert.match(html,/Configurar almacenamiento offline \(primera vez\)/);
});

test("readiness requires verified CAPTURE for each authorized package and offers contextual retry",()=>{
 assert.match(mobile,/async function offlineReadyStatus\(\)/);
 assert.match(mobile,/await signedFor\(pkg\)/);
 assert.match(mobile,/Formularios disponibles sin conexión/);
 assert.match(mobile,/No se descargaron todos los formularios/);
 assert.match(mobile,/show\("offline-retry",true\)/);
 assert.match(mobile,/show\("offline-retry",false\)/);
 assert.match(html,/id="offline-retry".*Reintentar modo sin conexión/);
});

test("atomic renewal preserves previous encrypted profile; no wipe or scope overwrite",()=>{
 const enroll=mobile.slice(mobile.indexOf("async function enroll("),mobile.indexOf("let preparationBusy"));
 assert.match(enroll,/if\(existingScope\)\{/);
 assert.match(enroll,/renewOfflineBundle\(opened,identityNow,/);
 assert.match(enroll,/storeCaptureAuthority\(opened,identityNow,signed/);
 assert.doesNotMatch(enroll,/indexedDB\.deleteDatabase|caches\.delete|localStorage\.clear/);
});
