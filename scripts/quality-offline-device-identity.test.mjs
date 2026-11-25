import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source=readFileSync(new URL("../lib/vinto/quality-offline-device-identity.ts",import.meta.url),"utf8");
test("Quality offline requires persistent device identity rather than memory fallback",()=>{
 assert.match(source,/storage\.getItem\(DEVICE_KEY_STORAGE\)/);
 assert.match(source,/offline_quality_device_storage_unavailable/);
 assert.match(source,/offline_quality_device_not_enrolled/);
 assert.doesNotMatch(source,/getDeviceKey\(/);
});
test("signed-in owner, enrolled device, and vault must belong to the same identity",()=>{
 assert.match(source,/same\(login\.userId,enrollment\.ownerId\)/);
 assert.match(source,/same\(enrollment\.record\.ownerId,enrollment\.ownerId\)/);
 assert.match(source,/same\(enrollment\.record\.deviceKey,enrollment\.deviceKey\)/);
 assert.match(source,/offline_quality_user_device_mismatch/);
});
