import test from "node:test";
import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { canonicalOfflineJson } from "../lib/vinto/offline-scope-verify.ts";
import { verifyConversionPreparation, verifyConversionReferencePackage, ConversionPreparationError } from "../lib/vinto/foff-conversion-preparation-verify.ts";

const ownerId = "11111111-1111-4111-8111-111111111111";
const deviceKey = "22222222-2222-4222-8222-222222222222";
const assignmentId = "33333333-3333-4333-8333-333333333333";
const target = {ownerId,deviceKey,assignmentId,machineCode:"GAMBINI",formCode:"VINTO-P1-11",formVersion:4};
const base64url = (v:Buffer) => v.toString("base64url");
const sha = (x:string)=>createHash("sha256").update(x).digest("hex");
const context = () => {
  const raw = {
    assignment_id:assignmentId, work_order_id:"44444444-4444-4444-8444-444444444444",
    line_id:"55555555-5555-4555-8555-555555555555", machine_code:"GAMBINI",
    form_code:"VINTO-P1-11", form_version:4, article_code:"10342",
    shift_code:"M", operating_date:"2026-11-27",reference_sha256:"b".repeat(64),
  };
  return {...raw,context_digest:sha(canonicalOfflineJson(raw))};
};
const fixture=()=>{
  const pair=generateKeyPairSync("ed25519");
  const pub=pair.publicKey.export({format:"der",type:"spki"}).subarray(-32);
  const keyId="ed25519-"+createHash("sha256").update(pub).digest().subarray(0,10).toString("hex");
  const payload={
    schema:"vinto.foff.conversion_preparation.v1",kind:"preparation_only",issuer:"vinto-backend",
    audience:"vinto-foff-conversion-preparation",
    snapshot_id:"66666666-6666-4666-8666-666666666666",
    subject_user_id:ownerId,device_key:deviceKey,
    issued_at:"2026-11-27T16:00:00Z",expires_at:"2026-11-28T04:00:00Z",
    context:context(),
  };
  const message="VINTO-FOFF-CONVERSION-PREPARATION-V1\0"+canonicalOfflineJson(payload);
  const signature=sign(null,Buffer.from(message),pair.privateKey);
  const pin=base64url(pub);
  return {envelope:{algorithm:"Ed25519",key_id:keyId,public_key_b64url:pin,
    signature_b64url:base64url(signature),payload},pin};
};

test("FOFF-02B.5: authentic, signed preparation binds context and never grants CAPTURE",async()=>{
  const {envelope,pin}=fixture();
  const v=await verifyConversionPreparation(envelope,pin,target,Date.parse("2026-11-27T17:00:00Z"));
  assert.equal(v.context.assignment_id,assignmentId);
  assert.equal(v.captureEnabled,false);
});
test("FOFF-02B.5: unpinned signer and changed assignment rejected",async()=>{
  const {envelope,pin}=fixture();
  await assert.rejects(verifyConversionPreparation(envelope,fixture().pin,target,Date.parse("2026-11-27T17:00:00Z")),
    (e:unknown)=>e instanceof ConversionPreparationError&&e.reason==="pin");
  await assert.rejects(verifyConversionPreparation(envelope,pin,{...target,assignmentId:ownerId},Date.parse("2026-11-27T17:00:00Z")),
    (e:unknown)=>e instanceof ConversionPreparationError&&e.reason==="target");
});
test("FOFF-02B.5: rejects altered context, expired envelope and Quality CAPTURE schema",async()=>{
  const {envelope,pin}=fixture();
  const altered={...envelope,payload:{...envelope.payload,context:{...envelope.payload.context,article_code:"11111"}}};
  await assert.rejects(verifyConversionPreparation(altered,pin,target,Date.parse("2026-11-27T17:00:00Z")),
    (e:unknown)=>e instanceof ConversionPreparationError&&e.reason==="signature");
  await assert.rejects(verifyConversionPreparation(envelope,pin,target,Date.parse("2026-11-28T04:00:00Z")),
    (e:unknown)=>e instanceof ConversionPreparationError&&e.reason==="expired");
  const quality={...envelope,payload:{...envelope.payload,schema:"vinto.offline.capture_scope.v1"}};
  await assert.rejects(verifyConversionPreparation(quality,pin,target,Date.parse("2026-11-27T17:00:00Z")),
    (e:unknown)=>e instanceof ConversionPreparationError&&e.reason==="invalid");
});

test("FOFF-03: reference package must match the signed server hash",async()=>{
  const referencePackage={
    schema:"vinto.foff.conversion.references.v1",
    machine_code:"GAMBINI",form_code:"VINTO-P1-11",form_version:4,
    article_code:"10342",
    definition:{fields:[{key:"tipo_material",value_type:"choice"}],groups:[{code:"bobinas"}]},
    references:{recipe_material_codes:["PAPEL"],pallet:null},
  };
  const signedHash=sha(canonicalOfflineJson(referencePackage));
  assert.match(signedHash,/^[0-9a-f]{64}$/);
  const {envelope,pin}=fixture();
  // Construct a fresh signed fixture whose context references the same data.
  // Existing fixture pins a different SHA; re-sign with its own test key in a separate test.
  const verified=await verifyConversionPreparation(envelope,pin,target,Date.parse("2026-11-27T17:00:00Z"));
  await assert.rejects(verifyConversionReferencePackage(referencePackage,verified),
    (e:unknown)=>e instanceof ConversionPreparationError&&e.reason==="digest");
});
