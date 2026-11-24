/** Pure shared queue record validator. Has NO IndexedDB, network, lab DB or API access. */
import type { SyncRecord } from "./offline-sync-types.ts";
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATES=["queued","syncing","retry_wait","synced","synced_warning","requires_review","conflict"];
export function isSyncRecord(v:unknown):v is SyncRecord{
 if(typeof v!=="object"||v===null)return false;
 const x=v as Record<string,unknown>;
 const s=x.sealed as Record<string,unknown>|null;
 return typeof x.capture_id==="string"&&UUID.test(x.capture_id)&&typeof x.ownerId==="string"&&UUID.test(x.ownerId)&&
 typeof x.deviceKey==="string"&&UUID.test(x.deviceKey)&&Number.isSafeInteger(x.seq)&&(x.dependsOn===null||(typeof x.dependsOn==="string"&&UUID.test(x.dependsOn)))&&
 typeof x.formCode==="string"&&Number.isSafeInteger(x.formVersion)&&typeof x.contextVersion==="string"&&
 typeof x.payloadSha256==="string"&&/^[0-9a-f]{64}$/.test(x.payloadSha256)&&typeof x.state==="string"&&STATES.includes(x.state)&&
 Number.isSafeInteger(x.attempts)&&typeof x.uncertain==="boolean"&&Number.isSafeInteger(x.version)&&
 Array.isArray(x.warnings)&&!!s&&s.format==="aes-gcm-v1"&&typeof s.iv==="string"&&typeof s.ciphertext==="string";
}
