import assert from "node:assert/strict";
import {test} from "node:test";
import {nextOperationalDraft,decideOperationalFreeze,OperationalLocalError,
 validOperationalPending} from "../lib/vinto/offline-operational-model.ts";
import {OPERATIONAL_LOCAL_DB} from "../lib/vinto/offline-operational-local-store.ts";
const A="11111111-1111-4111-8111-111111111111";
const D="33333333-3333-4333-8333-333333333333";
const B="44444444-4444-4444-8444-444444444444";
const C="55555555-5555-4555-8555-555555555555";
const S="66666666-6666-4666-8666-666666666666";
const seal={format:"aes-gcm-v1",iv:"encrypted-iv",ciphertext:"encrypted-ciphertext"};
const draft={id:B,ownerId:A,deviceKey:D,revision:1,machineCode:"MP1",
 formCode:"VINTO-P1-22",formVersion:2,scopeSnapshotId:S,contextVersion:S,
 frozenBy:null,sealed:seal,updatedAt:"2026-11-20T10:00:00Z"};
const pending={capture_id:C,sourceDraftId:B,sourceRevision:1,ownerId:A,deviceKey:D,
 payloadSha256:"a".repeat(64),synthetic:false,sealed:seal,createdAt:"2026-11-20T10:00:00Z"};
const queue={capture_id:C,ownerId:A,deviceKey:D,seq:1,dependsOn:null,formCode:"VINTO-P1-22",
 formVersion:2,contextVersion:S,machineCode:"MP1",scopeSnapshotId:S,payloadSha256:"a".repeat(64),
 state:"queued",attempts:0,nextAttemptAt:null,uncertain:false,lease:null,version:1,
 lastError:null,serverRef:null,warnings:[],createdAt:"2026-11-20T10:00:00Z",
 updatedAt:"2026-11-20T10:00:00Z",sealed:seal};
test("one operational DB is distinct from synthetic labs",()=>assert.equal(OPERATIONAL_LOCAL_DB,"vinto-off048-operational-v1"));
test("new draft persists encrypted revision one; CAS rejects stale overwrites",()=>{
 assert.deepEqual(nextOperationalDraft(undefined,draft,null),draft);
 assert.throws(()=>nextOperationalDraft(undefined,draft,1),/CONFLICT/);
 assert.equal(nextOperationalDraft(draft,{...draft,revision:2,sealed:{...seal,ciphertext:"v2"}},1).revision,2);
 assert.throws(()=>nextOperationalDraft(draft,{...draft,revision:2,ownerId:D},1),/CONFLICT/);
 assert.throws(()=>nextOperationalDraft(draft,{...draft,revision:2},0),/CONFLICT/);
});
test("freeze creates immutable pending and sync record in same decision",()=>{
 const x=decideOperationalFreeze(draft,undefined,undefined,1,seal.ciphertext,pending,queue);
 assert.equal(x.created,true);
 assert.equal(x.draft.frozenBy,C);
 assert.equal(x.pending.capture_id,x.queue.capture_id);
 assert.equal(x.queue.state,"queued");
});
test("repeated freeze reuses same pending and queue and cannot create duplicate",()=>{
 const x=decideOperationalFreeze(draft,undefined,undefined,1,seal.ciphertext,pending,queue);
 const again=decideOperationalFreeze(x.draft,x.pending,x.queue,1,seal.ciphertext,pending,queue);
 assert.equal(again.created,false);
 assert.equal(again.queue.capture_id,C);
});
test("frozen draft never accepts edits and missing queue is quarantined",()=>{
 const x=decideOperationalFreeze(draft,undefined,undefined,1,seal.ciphertext,pending,queue);
 assert.throws(()=>nextOperationalDraft(x.draft,{...draft,revision:2},1),/FROZEN/);
 assert.throws(()=>decideOperationalFreeze(x.draft,x.pending,undefined,1,seal.ciphertext,pending,queue),/CORRUPT/);
});
test("synthetic lab pending is invalid and cannot be promoted",()=>{
 assert.equal(validOperationalPending({...pending,synthetic:true}),false);
 assert.throws(()=>decideOperationalFreeze(draft,undefined,undefined,1,seal.ciphertext,{...pending,synthetic:true},queue),/INVALID/);
});
test("capture identity, content hash and revision must match",()=>{
 assert.throws(()=>decideOperationalFreeze(draft,undefined,undefined,2,seal.ciphertext,pending,queue),/CONFLICT/);
 assert.throws(()=>decideOperationalFreeze(draft,undefined,undefined,1,"old ciphertext",pending,queue),/CONFLICT/);
 assert.throws(()=>decideOperationalFreeze(draft,undefined,undefined,1,seal.ciphertext,{...pending,ownerId:D},queue),/CONFLICT/);
 assert.throws(()=>decideOperationalFreeze(draft,undefined,undefined,1,seal.ciphertext,pending,{...queue,payloadSha256:"b".repeat(64)}),/CONFLICT/);
});
