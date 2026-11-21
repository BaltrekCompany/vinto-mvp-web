import assert from "node:assert/strict";
import { test } from "node:test";
import {webcrypto} from "node:crypto";
import {verifyOperationalCaptureScope,CaptureScopeError} from "../lib/vinto/offline-operational-capture-scope-verify.ts";
import {canonicalOfflineJson} from "../lib/vinto/offline-scope-verify.ts";
const cryptoApi=globalThis.crypto??webcrypto;
Object.defineProperty(globalThis,"crypto",{value:cryptoApi,configurable:true});
const user="11111111-1111-4111-8111-111111111111";
const device="33333333-3333-4333-8333-333333333333";
const snapshot="66666666-6666-4666-8666-666666666666";
const target={scopeSnapshotId:snapshot,machineCode:"MP1",formCode:"VINTO-P1-22",formVersion:2};
const identity={ownerId:user,deviceKey:device};
const NOW=Date.UTC(2026,10,21,9,0,0);
const b64=(raw)=>Buffer.from(raw).toString("base64url");
const hex=(bytes)=>Buffer.from(bytes).toString("hex");
async function fixture(){
 const keys=await cryptoApi.subtle.generateKey({name:"Ed25519"},true,["sign","verify"]);
 const pub=new Uint8Array(await cryptoApi.subtle.exportKey("raw",keys.publicKey));
 const pin=b64(pub),digest=await cryptoApi.subtle.digest("SHA-256",pub);
 const base={schema:"vinto.offline.capture_scope.v1",issuer:"vinto-backend",
  audience:"vinto-offline-operational-capture",kind:"capture_authority",
  snapshot_id:snapshot,subject_user_id:user,device_key:device,
  issued_at:"2026-11-21T00:00:00Z",expires_at:"2026-11-22T00:00:00Z",
  form_scopes:[{machine_code:"MP1",form_code:"VINTO-P1-22",form_version:2,
   operation:"quality_machine_capture",grant_id:"77777777-7777-4777-8777-777777777777"}]};
 const sign=async(payload)=>{
  const data=new TextEncoder().encode("VINTO-OFFLINE-CAPTURE-SCOPE-V1\0"+canonicalOfflineJson(payload));
  const signature=await cryptoApi.subtle.sign("Ed25519",keys.privateKey,data);
  return {algorithm:"Ed25519",key_id:"ed25519-"+hex(digest).slice(0,20),
   public_key_b64url:pin,signature_b64url:b64(new Uint8Array(signature)),payload};
 };
 return {sign,base,pin};
}
test("real Ed25519 signature authorizes only the intended Quality capture target",async()=>{
 const f=await fixture(),env=await f.sign(f.base);
 assert.equal((await verifyOperationalCaptureScope(env,f.pin,identity,target,NOW)).payload.snapshot_id,snapshot);
});
test("readiness-only payload cannot grant capture even with a valid Ed25519 signature",async()=>{
 const f=await fixture();
 for(const changed of [{audience:"vinto-offline-readiness"},{kind:"scope_readiness_only"},
   {schema:"vinto.offline.scope.v1"}]){
  const signed=await f.sign({...f.base,...changed});
  await assert.rejects(verifyOperationalCaptureScope(signed,f.pin,identity,target,NOW),CaptureScopeError);
 }
});
test("wrong owner, device, snapshot or form version are rejected",async()=>{
 const f=await fixture(),env=await f.sign(f.base);
 for(const [ident,tgt] of [
  [{...identity,ownerId:device},target],
  [{...identity,deviceKey:"88888888-8888-4888-8888-888888888888"},target],
  [identity,{...target,scopeSnapshotId:device}],
  [identity,{...target,formVersion:3}],
 ]){
  await assert.rejects(verifyOperationalCaptureScope(env,f.pin,ident,tgt,NOW),CaptureScopeError);
 }
});
test("signed time window fails closed after expiry and before issue",async()=>{
 const f=await fixture(),env=await f.sign(f.base);
 await assert.rejects(verifyOperationalCaptureScope(env,f.pin,identity,target,Date.UTC(2026,10,22)),CaptureScopeError);
 await assert.rejects(verifyOperationalCaptureScope(env,f.pin,identity,target,Date.UTC(2026,10,20)),CaptureScopeError);
});
test("wrong pin, altered signature and altered form grants cannot pass",async()=>{
 const f=await fixture(),env=await f.sign(f.base);
 await assert.rejects(verifyOperationalCaptureScope(env,b64(cryptoApi.getRandomValues(new Uint8Array(32))),identity,target,NOW),CaptureScopeError);
 await assert.rejects(verifyOperationalCaptureScope({...env,payload:{...env.payload,device_key:user}},f.pin,identity,target,NOW),CaptureScopeError);
 const altered=await f.sign({...f.base,form_scopes:[{...f.base.form_scopes[0],operation:"quality_bobbin_capture"}]});
 await assert.rejects(verifyOperationalCaptureScope(altered,f.pin,identity,target,NOW),CaptureScopeError);
});
test("duplicate grants and malformed signature fail closed",async()=>{
 const f=await fixture();
 const duplicate=await f.sign({...f.base,form_scopes:[...f.base.form_scopes,...f.base.form_scopes]});
 await assert.rejects(verifyOperationalCaptureScope(duplicate,f.pin,identity,target,NOW),CaptureScopeError);
 const env=await f.sign(f.base);
 await assert.rejects(verifyOperationalCaptureScope({...env,signature_b64url:"invalid"},f.pin,identity,target,NOW),CaptureScopeError);
});
