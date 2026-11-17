// OFF-03A: cryptographic contract, no real VINTO capture, secrets or server session.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import {
 createLocalVault, unlockLocalVault, sealLocalDraft, openLocalDraft,
 isOfflineVaultRecord, VAULT_ITERATIONS, VaultError
} from "../lib/vinto/offline-vault.ts";
import { readLocalProfile, PROFILE_DB_NAME } from "../lib/vinto/offline-profile-store.ts";

const USER="11111111-1111-4111-8111-111111111111";
const DEVICE="22222222-2222-4222-8222-222222222222";
const FORM_ID="33333333-3333-4333-8333-333333333333";
const CONTEXT="44444444-4444-4444-8444-444444444444";
const SECRET="My OFFLINE demo vault phrase 238! not real";
const identity={ownerId:USER,deviceKey:DEVICE};
const binding={...identity,id:FORM_ID,contextId:CONTEXT,formCode:"VINTO-P1-22",formVersion:1};

test("no short PIN, weak repeats, missing owner or bad storage metadata", async()=>{
 await assert.rejects(createLocalVault(identity,"1234"),e=>e instanceof VaultError&&e.reason==="weak_passphrase");
 await assert.rejects(createLocalVault(identity,"aaaaaaaaaaaaaaaaaaaaaaaa"),e=>e.reason==="weak_passphrase");
 await assert.rejects(createLocalVault({ownerId:"not-valid",deviceKey:DEVICE},SECRET),e=>e.reason==="invalid");
 assert.equal(isOfflineVaultRecord({...identity,format:"wrong",iterations:VAULT_ITERATIONS,salt:"a"}),false);
});

test("AES-256 key is nonextractable and wrapped under randomized KDF salt and IV",async()=>{
 const first=await createLocalVault(identity,SECRET);
 const second=await createLocalVault(identity,SECRET);
 assert.equal(first.key.extractable,false);
 assert.equal(first.key.algorithm.name,"AES-GCM");
 assert.equal(first.record.iterations,650000);
 assert.notEqual(first.record.salt,second.record.salt);
 assert.notEqual(first.record.wrapIv,second.record.wrapIv);
 assert.notEqual(first.record.wrappedKey,second.record.wrappedKey);
 assert.equal(isOfflineVaultRecord(first.record),true);
 await assert.rejects(crypto.subtle.exportKey("raw",first.key));
});

test("unlock after simulated browser restart; encrypted capture survives and decrypts",async()=>{
 const enrolled=await createLocalVault(identity,SECRET);
 const sealed=await sealLocalDraft(enrolled.key,binding,{peso:4,lista:["uno","dos"],fecha:"2026-11-17"});
 const persisted=JSON.parse(JSON.stringify({record:enrolled.record,sealed})); // synthetic disk roundtrip
 const reopenedKey=await unlockLocalVault(persisted.record,SECRET);
 const restored=await openLocalDraft(reopenedKey,binding,persisted.sealed);
 assert.deepEqual(restored,{peso:4,lista:["uno","dos"],fecha:"2026-11-17"});
 assert.equal(JSON.stringify(persisted).includes('"peso"'),false);
 assert.equal(reopenedKey.extractable,false);
});

test("incorrect secret, wrong author, context or form version cannot decrypt",async()=>{
 const {record,key}=await createLocalVault(identity,SECRET);
 await assert.rejects(unlockLocalVault(record,"not the correct phrase 238!"),e=>e.reason==="unlock_failed");
 const sealed=await sealLocalDraft(key,binding,{data:"mock only"});
 await assert.rejects(openLocalDraft(key,{...binding,ownerId:"99999999-9999-4999-8999-999999999999"},sealed),e=>e.reason==="unlock_failed");
 await assert.rejects(openLocalDraft(key,{...binding,contextId:"99999999-9999-4999-8999-999999999999"},sealed),e=>e.reason==="unlock_failed");
 await assert.rejects(openLocalDraft(key,{...binding,formVersion:2},sealed),e=>e.reason==="unlock_failed");
 await assert.rejects(unlockLocalVault({...record,ownerId:"99999999-9999-4999-8999-999999999999"},SECRET),e=>e.reason==="unlock_failed");
});

test("tampering, replay with altered metadata and raw payloads are rejected",async()=>{
 const {key}=await createLocalVault(identity,SECRET);
 const first=await sealLocalDraft(key,binding,{x:1});
 const second=await sealLocalDraft(key,binding,{x:1});
 assert.notEqual(first.iv,second.iv);
 const altered=first.ciphertext[0]==="A"?"B"+first.ciphertext.slice(1):"A"+first.ciphertext.slice(1);
 await assert.rejects(openLocalDraft(key,binding,{...first,ciphertext:altered}),e=>e.reason==="unlock_failed");
 await assert.rejects(openLocalDraft(key,binding,{...first,format:"plaintext"}),e=>e.reason==="corrupt");
 await assert.rejects(sealLocalDraft(key,binding,["not object"]),e=>e.reason==="invalid");
 await assert.rejects(sealLocalDraft(key,binding,{tooLarge:"X".repeat(1024*1024+1)}),e=>e.reason==="invalid");
});

test("local profile persistence fails closed if IndexedDB unavailable",async()=>{
 assert.equal(PROFILE_DB_NAME,"vinto-off03a-profiles-v1");
 await assert.rejects(readLocalProfile(),e=>e instanceof VaultError&&e.reason==="unavailable");
});

test("OFF-03A is not imported by any production authentication or capture UI",()=>{
 const path=(x)=>readFileSync(resolve(import.meta.dirname,"..",x),"utf8");
 for(const file of ["app/page.tsx","lib/vinto/use-session.ts","lib/vinto/auth-api.ts","components/vinto/offline-registration.tsx"]){
   assert.doesNotMatch(path(file),/offline-vault|offline-profile-store/,file);
 }
 const source=path("lib/vinto/offline-vault.ts");
 assert.doesNotMatch(source,/fetch\s*\(|localStorage|document\.cookie/);
 assert.match(source,/additionalData/);
});
