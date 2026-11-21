/** OFF-04.8O — browser verification for the INDEPENDENT, signed Quality
 * CAPTURE authority. Readiness-only scopes/packages can NEVER authorise Save.
 *
 * The trusted Ed25519 pin must come from prior authenticated HTTPS enrolment,
 * NEVER from the untrusted envelope. Device time is only an offline advisory:
 * the server always rechecks issued/revoked snapshot, original author, current
 * grants and expiration in the same transaction as operational registration.
 */
import { canonicalOfflineJson, type OfflineScopeIdentity } from "./offline-scope-verify.ts";

const DOMAIN="VINTO-OFFLINE-CAPTURE-SCOPE-V1\0";
const SCHEMA="vinto.offline.capture_scope.v1";
const AUDIENCE="vinto-offline-operational-capture";
const ENVELOPE_KEYS=["algorithm","key_id","public_key_b64url","payload","signature_b64url"];
const PAYLOAD_KEYS=["schema","issuer","audience","kind","snapshot_id","subject_user_id","device_key","issued_at","expires_at","form_scopes"];
const ENTRY_KEYS=["machine_code","form_code","form_version","operation","grant_id"];
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID4=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const B64URL=/^[A-Za-z0-9_-]+$/;
const DATE=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const MACHINE=/^[A-Za-z0-9_.-]{1,48}$/;
const DAY_MS=24*60*60*1000;
const MACHINE_FORMS=new Set(["VINTO-P1-18","VINTO-P1-22","VINTO-P1-26","VINTO-P1-27"]);
const BOBBIN_FORMS=new Set(["VINTO-P1-19","VINTO-P1-20","VINTO-P1-21","VINTO-P1-24","VINTO-P1-25","VINTO-P1-28"]);
type FormScope=Readonly<{
 machine_code:string;form_code:string;form_version:number;
 operation:"quality_machine_capture"|"quality_bobbin_capture";grant_id:string;
}>;
export type CaptureScopeEnvelope=Readonly<{
 algorithm:"Ed25519";key_id:string;public_key_b64url:string;signature_b64url:string;
 payload:Readonly<{
  schema:typeof SCHEMA;issuer:"vinto-backend";audience:typeof AUDIENCE;kind:"capture_authority";
  snapshot_id:string;subject_user_id:string;device_key:string;issued_at:string;expires_at:string;
  form_scopes:ReadonlyArray<FormScope>;
 }>;
}>;
export type CaptureScopeTarget=Readonly<{
 scopeSnapshotId:string;machineCode:string;formCode:string;formVersion:number;
}>;
export type CaptureScopeReason="invalid"|"identity_mismatch"|"pin_mismatch"|"signature"|"expired"|"scope"|"unavailable";
export class CaptureScopeError extends Error{
 readonly reason:CaptureScopeReason;
 constructor(reason:CaptureScopeReason){super("OFF048_CAPTURE_SCOPE_"+reason.toUpperCase());this.name="CaptureScopeError";this.reason=reason;}
}
const record=(v:unknown):v is Record<string,unknown>=>v!==null&&typeof v==="object"&&!Array.isArray(v);
const exact=(v:unknown,keys:readonly string[]):v is Record<string,unknown>=>record(v)&&Object.keys(v).sort().join("|")===[...keys].sort().join("|");
const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();
const operation=(formCode:string):FormScope["operation"]|null=>
 MACHINE_FORMS.has(formCode)?"quality_machine_capture":BOBBIN_FORMS.has(formCode)?"quality_bobbin_capture":null;
function decode(text:string,size:number):Uint8Array{
 if(!B64URL.test(text))throw new CaptureScopeError("invalid");
 let bytes:Uint8Array;
 try{bytes=Uint8Array.from(atob(text.replace(/-/g,"+").replace(/_/g,"/").padEnd(Math.ceil(text.length/4)*4,"=")),c=>c.charCodeAt(0));}
 catch{throw new CaptureScopeError("invalid");}
 let binary="";for(const b of bytes)binary+=String.fromCharCode(b);
 const canonical=btoa(binary).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
 if(bytes.length!==size||canonical!==text)throw new CaptureScopeError("invalid");
 return bytes;
}
function validate(input:unknown,identity:OfflineScopeIdentity,target:CaptureScopeTarget,nowMs:number):asserts input is CaptureScopeEnvelope{
 if(!record(identity)||typeof identity.ownerId!=="string"||!UUID.test(identity.ownerId)||
    typeof identity.deviceKey!=="string"||!UUID4.test(identity.deviceKey)||
    !record(target)||typeof target.scopeSnapshotId!=="string"||!UUID4.test(target.scopeSnapshotId)||
    typeof target.machineCode!=="string"||!MACHINE.test(target.machineCode)||
    typeof target.formCode!=="string"||operation(target.formCode)===null||
    !Number.isSafeInteger(target.formVersion)||target.formVersion<1||
    !Number.isFinite(nowMs))throw new CaptureScopeError("invalid");
 if(!exact(input,ENVELOPE_KEYS)||input.algorithm!=="Ed25519"||
    typeof input.key_id!=="string"||!/^ed25519-[0-9a-f]{20}$/.test(input.key_id)||
    typeof input.public_key_b64url!=="string"||typeof input.signature_b64url!=="string"||
    !exact(input.payload,PAYLOAD_KEYS))throw new CaptureScopeError("invalid");
 const p=input.payload as Record<string,unknown>;
 if(p.schema!==SCHEMA||p.issuer!=="vinto-backend"||p.audience!==AUDIENCE||
    p.kind!=="capture_authority"||typeof p.snapshot_id!=="string"||!UUID4.test(p.snapshot_id)||
    typeof p.subject_user_id!=="string"||!UUID.test(p.subject_user_id)||
    typeof p.device_key!=="string"||!UUID4.test(p.device_key)||
    typeof p.issued_at!=="string"||!DATE.test(p.issued_at)||
    typeof p.expires_at!=="string"||!DATE.test(p.expires_at))throw new CaptureScopeError("invalid");
 if(!same(p.subject_user_id,identity.ownerId)||!same(p.device_key,identity.deviceKey))
    throw new CaptureScopeError("identity_mismatch");
 if(!same(p.snapshot_id,target.scopeSnapshotId))throw new CaptureScopeError("scope");
 const issued=Date.parse(p.issued_at),expires=Date.parse(p.expires_at);
 if(!Number.isFinite(issued)||!Number.isFinite(expires)||expires<=issued||
    expires-issued>DAY_MS||nowMs<issued||nowMs>=expires)throw new CaptureScopeError("expired");
 if(!Array.isArray(p.form_scopes)||p.form_scopes.length<1||p.form_scopes.length>200)
    throw new CaptureScopeError("invalid");
 const seen=new Set<string>();let matches=0;
 for(const item of p.form_scopes){
  if(!exact(item,ENTRY_KEYS))throw new CaptureScopeError("invalid");
  const e=item as Record<string,unknown>;
  if(typeof e.machine_code!=="string"||!MACHINE.test(e.machine_code)||
     typeof e.form_code!=="string"||operation(e.form_code)===null||
     !Number.isSafeInteger(e.form_version)||(e.form_version as number)<1||
     typeof e.grant_id!=="string"||!UUID.test(e.grant_id)||
     e.operation!==operation(e.form_code))throw new CaptureScopeError("invalid");
  const unique=[e.machine_code,e.form_code,e.form_version,e.operation].join(":");
  if(seen.has(unique))throw new CaptureScopeError("invalid");
  seen.add(unique);
  if(e.machine_code===target.machineCode&&e.form_code===target.formCode&&
    e.form_version===target.formVersion&&e.operation===operation(target.formCode))matches++;
 }
 if(matches!==1)throw new CaptureScopeError("scope");
}
export async function verifyOperationalCaptureScope(
 input:unknown,trustedPublicKeyB64url:string,identity:OfflineScopeIdentity,
 target:CaptureScopeTarget,nowMs:number,
):Promise<CaptureScopeEnvelope>{
 if(!globalThis.crypto?.subtle)throw new CaptureScopeError("unavailable");
 validate(input,identity,target,nowMs);
 if(typeof trustedPublicKeyB64url!=="string"||input.public_key_b64url!==trustedPublicKeyB64url)
   throw new CaptureScopeError("pin_mismatch");
 const pub=decode(trustedPublicKeyB64url,32),sig=decode(input.signature_b64url,64);
 const hash=new Uint8Array(await crypto.subtle.digest("SHA-256",pub as BufferSource));
 const keyId="ed25519-"+Array.from(hash.slice(0,10),x=>x.toString(16).padStart(2,"0")).join("");
 if(input.key_id!==keyId)throw new CaptureScopeError("pin_mismatch");
 try{
   const key=await crypto.subtle.importKey("raw",pub as BufferSource,{name:"Ed25519"},false,["verify"]);
   const signed=new TextEncoder().encode(DOMAIN+canonicalOfflineJson(input.payload));
   if(!await crypto.subtle.verify({name:"Ed25519"},key,sig as BufferSource,signed as BufferSource))
      throw new CaptureScopeError("signature");
 }catch(e){if(e instanceof CaptureScopeError)throw e;throw new CaptureScopeError("unavailable");}
 return input;
}
