/** FOFF-03: independent Ed25519 CAPTURE authority for Conversion editors.
 * Must use a public key pinned during authenticated HTTPS device enrollment.
 * This is a local eligibility guard, never a substitute for server rechecks.
 */
import {canonicalOfflineJson} from "./offline-scope-verify.ts";
import type {VerifiedConversionPreparation} from "./foff-conversion-preparation-verify.ts";

const DOMAIN="VINTO-FOFF-CONVERSION-CAPTURE-AUTHORITY-V1\0";
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const UUID4=/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const HASH=/^[a-f0-9]{64}$/;
const UTC=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const MACHINE=/^[a-zA-Z0-9_.-]{1,48}$/;
const B64=/^[A-Za-z0-9_-]+$/;
const KEYS=["algorithm","key_id","public_key_b64url","payload","signature_b64url"];
const PAYLOAD=["schema","issuer","audience","kind","snapshot_id","subject_user_id",
  "device_key","assignment_id","machine_code","form_code","form_version",
  "grant_id","reference_sha256","issued_at","expires_at"];
type R=Record<string,unknown>;
const object=(v:unknown):v is R=>v!==null&&typeof v==="object"&&!Array.isArray(v);
const exact=(v:unknown,keys:readonly string[]):v is R=>object(v)&&
  Object.keys(v).sort().join("|")===[...keys].sort().join("|");
const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();
const hex=(bytes:Uint8Array)=>Array.from(bytes,x=>x.toString(16).padStart(2,"0")).join("");
const decode=(value:string,len:number):Uint8Array=>{
  if(!B64.test(value))throw new ConversionCaptureAuthorityError("invalid");
  let bytes:Uint8Array;
  try{bytes=Uint8Array.from(atob(value.replace(/-/g,"+").replace(/_/g,"/")
    .padEnd(Math.ceil(value.length/4)*4,"=")),x=>x.charCodeAt(0));}
  catch{throw new ConversionCaptureAuthorityError("invalid");}
  let binary="";for(const b of bytes)binary+=String.fromCharCode(b);
  if(bytes.length!==len||btoa(binary).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")!==value)
    throw new ConversionCaptureAuthorityError("invalid");
  return bytes;
};
export class ConversionCaptureAuthorityError extends Error{
  readonly reason:"invalid"|"identity"|"scope"|"expired"|"pin"|"signature"|"unavailable";
  constructor(reason:ConversionCaptureAuthorityError["reason"]){
    super("FOFF_CONVERSION_CAPTURE_"+reason.toUpperCase());this.reason=reason;
  }
}
export type ConversionCaptureTarget=Readonly<{
  ownerId:string;deviceKey:string;assignmentId:string;machineCode:string;
  formCode:string;formVersion:number;scopeSnapshotId:string;
}>;
export type VerifiedConversionCapture=Readonly<{
  grantId:string;issuedAt:string;expiresAt:string;snapshotId:string;captureEnabled:true;
}>;
export async function verifyConversionCaptureAuthority(
  input:unknown,trustedPublicKeyB64url:string,target:ConversionCaptureTarget,
  preparation:VerifiedConversionPreparation,nowMs:number,
):Promise<VerifiedConversionCapture>{
  if(!globalThis.crypto?.subtle||!Number.isFinite(nowMs))
    throw new ConversionCaptureAuthorityError("unavailable");
  if(!target||!UUID.test(target.ownerId)||!UUID4.test(target.deviceKey)||
     !UUID.test(target.assignmentId)||!UUID4.test(target.scopeSnapshotId)||
     !MACHINE.test(target.machineCode)||!Number.isSafeInteger(target.formVersion)||
     target.formVersion<1)throw new ConversionCaptureAuthorityError("invalid");
  if(!exact(input,KEYS)||input.algorithm!=="Ed25519"||
     typeof input.key_id!=="string"||!/^ed25519-[a-f0-9]{20}$/.test(input.key_id)||
     typeof input.public_key_b64url!=="string"||
     typeof input.signature_b64url!=="string"||!exact(input.payload,PAYLOAD))
    throw new ConversionCaptureAuthorityError("invalid");
  const p=input.payload;
  if(p.schema!=="vinto.foff.conversion_capture.v1"||
     p.issuer!=="vinto-backend"||p.audience!=="vinto-foff-conversion-capture"||
     p.kind!=="capture_authority"||
     typeof p.subject_user_id!=="string"||!UUID.test(p.subject_user_id)||
     typeof p.device_key!=="string"||!UUID4.test(p.device_key)||
     typeof p.assignment_id!=="string"||!UUID.test(p.assignment_id)||
     typeof p.machine_code!=="string"||!MACHINE.test(p.machine_code)||
     typeof p.form_code!=="string"||!/^VINTO-P1-(11|12|13|16)$/.test(p.form_code)||
     !Number.isSafeInteger(p.form_version)||Number(p.form_version)<1||
     typeof p.snapshot_id!=="string"||!UUID4.test(p.snapshot_id)||
     typeof p.grant_id!=="string"||!UUID.test(p.grant_id)||
     typeof p.reference_sha256!=="string"||!HASH.test(p.reference_sha256)||
     typeof p.issued_at!=="string"||!UTC.test(p.issued_at)||
     typeof p.expires_at!=="string"||!UTC.test(p.expires_at))
    throw new ConversionCaptureAuthorityError("invalid");
  const c=preparation.context;
  if(!same(p.subject_user_id,target.ownerId)||!same(p.device_key,target.deviceKey))
    throw new ConversionCaptureAuthorityError("identity");
  if(!same(p.assignment_id,target.assignmentId)||p.machine_code!==target.machineCode||
     p.form_code!==target.formCode||p.form_version!==target.formVersion||
     !same(p.snapshot_id,target.scopeSnapshotId)||
     !same(preparation.snapshotId,target.scopeSnapshotId)||
     p.reference_sha256!==c.reference_sha256||
     c.machine_code!==target.machineCode||c.form_code!==target.formCode||
     c.form_version!==target.formVersion||!same(c.assignment_id,target.assignmentId))
    throw new ConversionCaptureAuthorityError("scope");
  const issued=Date.parse(p.issued_at),expires=Date.parse(p.expires_at);
  if(!Number.isFinite(issued)||!Number.isFinite(expires)||expires<=issued||
     expires-issued>12*3600*1000||nowMs<issued||nowMs>=expires)
    throw new ConversionCaptureAuthorityError("expired");
  if(typeof trustedPublicKeyB64url!=="string"||
     input.public_key_b64url!==trustedPublicKeyB64url)
    throw new ConversionCaptureAuthorityError("pin");
  const pub=decode(trustedPublicKeyB64url,32),sig=decode(input.signature_b64url,64);
  const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",pub as BufferSource));
  if(input.key_id!=="ed25519-"+hex(digest.slice(0,10)))
    throw new ConversionCaptureAuthorityError("pin");
  try{
    const key=await crypto.subtle.importKey("raw",pub as BufferSource,{name:"Ed25519"},false,["verify"]);
    const signed=new TextEncoder().encode(DOMAIN+canonicalOfflineJson(p));
    if(!await crypto.subtle.verify("Ed25519",key,sig as BufferSource,signed as BufferSource))
      throw new ConversionCaptureAuthorityError("signature");
  }catch(e){
    if(e instanceof ConversionCaptureAuthorityError)throw e;
    throw new ConversionCaptureAuthorityError("unavailable");
  }
  return {grantId:p.grant_id,snapshotId:p.snapshot_id,
    issuedAt:p.issued_at,expiresAt:p.expires_at,captureEnabled:true};
}
