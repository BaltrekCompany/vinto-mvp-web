import test from "node:test";
import assert from "node:assert/strict";
import {CONVERSION_QUEUE_DB,enqueueConversionCapture,listConversionQueue}
  from "../lib/vinto/foff-conversion-local-queue.ts";
import type {VerifiedConversionPreparation} from "../lib/vinto/foff-conversion-preparation-verify.ts";
import type {VerifiedConversionCapture} from "../lib/vinto/foff-conversion-capture-authority-verify.ts";

const ownerId="11111111-1111-4111-8111-111111111111";
const deviceKey="22222222-2222-4222-8222-222222222222";
const assignmentId="33333333-3333-4333-8333-333333333333";
const snapshotId="44444444-4444-4444-8444-444444444444";
const identity={ownerId,deviceKey};
const preparation:VerifiedConversionPreparation={
  snapshotId,issuedAt:"2026-11-27T16:00:00Z",expiresAt:"2026-11-28T04:00:00Z",
  context:{assignment_id:assignmentId,work_order_id:ownerId,line_id:deviceKey,
    machine_code:"GAMBINI",form_code:"VINTO-P1-16",form_version:4,
    article_code:"10342",shift_code:"M",operating_date:"2026-11-27",
    reference_sha256:"a".repeat(64),context_digest:"b".repeat(64)},
  captureEnabled:false,
};
const captureAuthority:VerifiedConversionCapture={
  grantId:ownerId,issuedAt:preparation.issuedAt,
  expiresAt:preparation.expiresAt,snapshotId,captureEnabled:true,
};
const argumentsFor=()=>({
  identity,key:{} as CryptoKey,captureId:"55555555-5555-4555-8555-555555555555",
  preparation,captureAuthority,formCode:"VINTO-P1-16",formVersion:4,
  machineCode:"GAMBINI",assignmentId,values:{peso_merma_kg:"1.25"},
  preparationEnvelope:{},authorityEnvelope:{},referencePackage:{},
});

test("Conversion queue lives outside Quality store",()=>{
  assert.notEqual(CONVERSION_QUEUE_DB,"vinto-off048-operational-v1");
  assert.notEqual(CONVERSION_QUEUE_DB,"vinto-quality-offline-preparations-v1");
});
test("Conversion queue refuses different assignment or missing trusted scope",async()=>{
  await assert.rejects(enqueueConversionCapture({...argumentsFor(),assignmentId:ownerId}),/foff_conversion_queue_scope/);
  await assert.rejects(enqueueConversionCapture({...argumentsFor(),
    captureAuthority:{...captureAuthority,snapshotId:deviceKey}}),/foff_conversion_queue_scope/);
});
test("Conversion queue never falls back to memory for missing IndexedDB",async()=>{
  await assert.rejects(listConversionQueue(identity),/foff_conversion_queue_unavailable/);
});
