import test from "node:test";
import assert from "node:assert/strict";
import {generateKeyPairSync,createHash,sign} from "node:crypto";
import {canonicalOfflineJson} from "../lib/vinto/offline-scope-verify.ts";
import {verifyConversionPreparation} from "../lib/vinto/foff-conversion-preparation-verify.ts";
import {verifyConversionCaptureAuthority,ConversionCaptureAuthorityError}
  from "../lib/vinto/foff-conversion-capture-authority-verify.ts";

const sha=(v:string)=>createHash("sha256").update(v).digest("hex");
const id="11111111-1111-4111-8111-111111111111";
const device="22222222-2222-4222-8222-222222222222";
const assignment="33333333-3333-4333-8333-333333333333";
const snapshot="44444444-4444-4444-8444-444444444444";
const target={ownerId:id,deviceKey:device,assignmentId:assignment,machineCode:"GAMBINI",
  formCode:"VINTO-P1-16",formVersion:4,scopeSnapshotId:snapshot};
const signPayload=(domain:string,payload:Record<string,unknown>)=>{
  const keys=generateKeyPairSync("ed25519");
  const publicRaw=keys.publicKey.export({format:"der",type:"spki"}).subarray(-32);
  const pub=publicRaw.toString("base64url");
  const keyId="ed25519-"+createHash("sha256").update(publicRaw).digest().subarray(0,10).toString("hex");
  return {pin:pub,envelope:{algorithm:"Ed25519",key_id:keyId,public_key_b64url:pub,
    signature_b64url:sign(null,Buffer.from(domain+canonicalOfflineJson(payload)),keys.privateKey).toString("base64url"),
    payload}};
};
const fixture=async()=>{
  const rawContext={assignment_id:assignment,work_order_id:"55555555-5555-4555-8555-555555555555",
    line_id:"66666666-6666-4666-8666-666666666666",machine_code:"GAMBINI",
    form_code:"VINTO-P1-16",form_version:4,article_code:"10342",shift_code:"M",
    operating_date:"2026-11-27",reference_sha256:"a".repeat(64)};
  const context={...rawContext,context_digest:sha(canonicalOfflineJson(rawContext))};
  const p={schema:"vinto.foff.conversion_preparation.v1",issuer:"vinto-backend",
    audience:"vinto-foff-conversion-preparation",kind:"preparation_only",
    snapshot_id:snapshot,subject_user_id:id,device_key:device,
    issued_at:"2026-11-27T16:00:00Z",expires_at:"2026-11-28T04:00:00Z",context};
  const prep=signPayload("VINTO-FOFF-CONVERSION-PREPARATION-V1\0",p);
  const verified=await verifyConversionPreparation(prep.envelope,prep.pin,
    {ownerId:id,deviceKey:device,assignmentId:assignment,
      machineCode:"GAMBINI",formCode:"VINTO-P1-16",formVersion:4},
    Date.parse("2026-11-27T17:00:00Z"));
  const scope={schema:"vinto.foff.conversion_capture.v1",issuer:"vinto-backend",
    audience:"vinto-foff-conversion-capture",kind:"capture_authority",snapshot_id:snapshot,
    subject_user_id:id,device_key:device,assignment_id:assignment,
    machine_code:"GAMBINI",form_code:"VINTO-P1-16",form_version:4,
    grant_id:"77777777-7777-4777-8777-777777777777",
    reference_sha256:context.reference_sha256,issued_at:"2026-11-27T16:00:00Z",
    expires_at:"2026-11-28T04:00:00Z"};
  return {verified,scope:signPayload("VINTO-FOFF-CONVERSION-CAPTURE-AUTHORITY-V1\0",scope)};
};
test("FOFF-03 requires separate trusted CAPTURE authority",async()=>{
  const {verified,scope}=await fixture();
  const result=await verifyConversionCaptureAuthority(scope.envelope,scope.pin,target,verified,
    Date.parse("2026-11-27T17:00:00Z"));
  assert.equal(result.captureEnabled,true);
  assert.equal(result.snapshotId,snapshot);
});
test("FOFF-03 rejects different grant scope, unpinned key and expiry",async()=>{
  const {verified,scope}=await fixture();
  const now=Date.parse("2026-11-27T17:00:00Z");
  await assert.rejects(verifyConversionCaptureAuthority(scope.envelope,scope.pin,
    {...target,assignmentId:id},verified,now),
    (e:unknown)=>e instanceof ConversionCaptureAuthorityError&&e.reason==="scope");
  await assert.rejects(verifyConversionCaptureAuthority(scope.envelope,"bad",target,verified,now),
    (e:unknown)=>e instanceof ConversionCaptureAuthorityError&&e.reason==="pin");
  await assert.rejects(verifyConversionCaptureAuthority(scope.envelope,scope.pin,target,verified,
    Date.parse("2026-11-28T04:00:00Z")),
    (e:unknown)=>e instanceof ConversionCaptureAuthorityError&&e.reason==="expired");
  const changed={...scope.envelope,payload:{...scope.envelope.payload,reference_sha256:"b".repeat(64)}};
  await assert.rejects(verifyConversionCaptureAuthority(changed,scope.pin,target,verified,now),
    (e:unknown)=>e instanceof ConversionCaptureAuthorityError&&e.reason==="scope");
});
