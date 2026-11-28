/** FOFF-02B.5: verifies PREPARATION ONLY; never authorizes offline capture.
 * The trusted key must be pinned during authenticated HTTPS enrolment, not
 * copied out of the signed envelope. Every subsequent POST is re-authorized.
 */
import {canonicalOfflineJson} from "./offline-scope-verify.ts";

const DOMAIN = "VINTO-FOFF-CONVERSION-PREPARATION-V1\0";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HEX = /^[0-9a-f]{64}$/;
const BASE64 = /^[A-Za-z0-9_-]+$/;
const CLOCK = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MACHINE = /^[A-Za-z0-9_.-]{1,48}$/;
const FORMS = new Set(["VINTO-P1-11","VINTO-P1-12","VINTO-P1-13","VINTO-P1-16"]);
const ENVELOPE = ["algorithm","key_id","public_key_b64url","payload","signature_b64url"];
const PAYLOAD = ["schema","kind","issuer","audience","snapshot_id","subject_user_id",
  "device_key","issued_at","expires_at","context"];
const CONTEXT = ["assignment_id","work_order_id","line_id","machine_code","form_code",
  "form_version","article_code","shift_code","operating_date","reference_sha256","context_digest"];
type Obj = Record<string,unknown>;
const object = (v:unknown):v is Obj => v!==null && typeof v==="object" && !Array.isArray(v);
const exact = (v:unknown,keys:string[]):v is Obj =>
  object(v) && Object.keys(v).sort().join("|") === [...keys].sort().join("|");
const equal = (a:string,b:string)=>a.toLowerCase()===b.toLowerCase();
const b64 = (v:string,length:number):Uint8Array => {
  if(!BASE64.test(v))throw new ConversionPreparationError("invalid");
  let result:Uint8Array;
  try{result=Uint8Array.from(atob(v.replace(/-/g,"+").replace(/_/g,"/")
    .padEnd(Math.ceil(v.length/4)*4,"=")),x=>x.charCodeAt(0));}
  catch{throw new ConversionPreparationError("invalid");}
  let binary=""; for(const b of result)binary+=String.fromCharCode(b);
  if(result.length!==length || btoa(binary).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"")!==v)
    throw new ConversionPreparationError("invalid");
  return result;
};
const hex=(bytes:Uint8Array)=>Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
export class ConversionPreparationError extends Error {
  readonly reason:"invalid"|"identity"|"target"|"expired"|"pin"|"signature"|"unavailable"|"digest";
  constructor(reason:"invalid"|"identity"|"target"|"expired"|"pin"|"signature"|"unavailable"|"digest"){
    super("FOFF_CONVERSION_PREPARATION_"+reason.toUpperCase());
    this.reason=reason;
  }
}
export type ConversionPreparationTarget=Readonly<{
  ownerId:string;deviceKey:string;assignmentId:string;machineCode:string;
  formCode:string;formVersion:number;
}>;
export type VerifiedConversionPreparation=Readonly<{
  snapshotId:string; issuedAt:string; expiresAt:string;
  context:Readonly<{
    assignment_id:string;work_order_id:string;line_id:string;machine_code:string;
    form_code:string;form_version:number;article_code:string;shift_code:string;
    operating_date:string;reference_sha256:string;context_digest:string;
  }>;
  captureEnabled:false;
}>;

/** The reference bundle must match the signed digest, not just the response body. */
export async function verifyConversionReferencePackage(
  referencePackage:unknown,
  verified:VerifiedConversionPreparation,
):Promise<void>{
  if(!globalThis.crypto?.subtle || !object(referencePackage))
    throw new ConversionPreparationError("unavailable");
  const c=verified.context;
  if(referencePackage.schema!=="vinto.foff.conversion.references.v1" ||
     referencePackage.machine_code!==c.machine_code ||
     referencePackage.form_code!==c.form_code ||
     referencePackage.form_version!==c.form_version ||
     referencePackage.article_code!==c.article_code ||
     !object(referencePackage.definition) || !object(referencePackage.references))
    throw new ConversionPreparationError("target");
  const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",
    new TextEncoder().encode(canonicalOfflineJson(referencePackage))));
  if(hex(digest)!==c.reference_sha256)throw new ConversionPreparationError("digest");
}

export async function verifyConversionPreparation(
  input:unknown, trustedPublicKeyB64url:string,
  target:ConversionPreparationTarget, nowMs:number,
):Promise<VerifiedConversionPreparation>{
  if(!globalThis.crypto?.subtle || !Number.isFinite(nowMs))throw new ConversionPreparationError("unavailable");
  if(!target || !UUID.test(target.ownerId) || !UUID4.test(target.deviceKey) ||
     !UUID.test(target.assignmentId) || !MACHINE.test(target.machineCode) ||
     !FORMS.has(target.formCode) || !Number.isSafeInteger(target.formVersion) ||
     target.formVersion<1)throw new ConversionPreparationError("invalid");
  if(!exact(input,ENVELOPE) || input.algorithm!=="Ed25519" ||
     typeof input.key_id!=="string" || !/^ed25519-[0-9a-f]{20}$/.test(input.key_id) ||
     typeof input.public_key_b64url!=="string" || typeof input.signature_b64url!=="string" ||
     !exact(input.payload,PAYLOAD))throw new ConversionPreparationError("invalid");
  const p=input.payload;
  if(p.schema!=="vinto.foff.conversion_preparation.v1" ||
     p.kind!=="preparation_only" || p.issuer!=="vinto-backend" ||
     p.audience!=="vinto-foff-conversion-preparation" ||
     typeof p.snapshot_id!=="string" || !UUID4.test(p.snapshot_id) ||
     typeof p.subject_user_id!=="string" || !UUID.test(p.subject_user_id) ||
     typeof p.device_key!=="string" || !UUID4.test(p.device_key) ||
     typeof p.issued_at!=="string" || !CLOCK.test(p.issued_at) ||
     typeof p.expires_at!=="string" || !CLOCK.test(p.expires_at) ||
     !exact(p.context,CONTEXT))throw new ConversionPreparationError("invalid");
  if(!equal(p.subject_user_id,target.ownerId) || !equal(p.device_key,target.deviceKey))
    throw new ConversionPreparationError("identity");
  const c=p.context;
  if(typeof c.assignment_id!=="string" || !UUID.test(c.assignment_id) ||
     typeof c.work_order_id!=="string" || !UUID.test(c.work_order_id) ||
     typeof c.line_id!=="string" || !UUID.test(c.line_id) ||
     typeof c.machine_code!=="string" || !MACHINE.test(c.machine_code) ||
     typeof c.form_code!=="string" || !FORMS.has(c.form_code) ||
     typeof c.form_version!=="number" || !Number.isSafeInteger(c.form_version) || c.form_version<1 ||
     typeof c.article_code!=="string" || !c.article_code ||
     typeof c.shift_code!=="string" || !c.shift_code ||
     typeof c.operating_date!=="string" || !DAY.test(c.operating_date) ||
     typeof c.reference_sha256!=="string" || !HEX.test(c.reference_sha256) ||
     typeof c.context_digest!=="string" || !HEX.test(c.context_digest))
    throw new ConversionPreparationError("invalid");
  if(!equal(c.assignment_id,target.assignmentId) ||
     c.machine_code!==target.machineCode || c.form_code!==target.formCode ||
     c.form_version!==target.formVersion)throw new ConversionPreparationError("target");
  const issued=Date.parse(p.issued_at),expires=Date.parse(p.expires_at);
  if(!Number.isFinite(issued) || !Number.isFinite(expires) || expires<=issued ||
     expires-issued>12*60*60*1000 || nowMs<issued || nowMs>=expires)
    throw new ConversionPreparationError("expired");
  if(typeof trustedPublicKeyB64url!=="string" ||
     input.public_key_b64url!==trustedPublicKeyB64url)
    throw new ConversionPreparationError("pin");
  const pub=b64(trustedPublicKeyB64url,32),signature=b64(input.signature_b64url,64);
  const keyHash=new Uint8Array(await crypto.subtle.digest("SHA-256",pub as BufferSource));
  if(input.key_id!=="ed25519-"+hex(keyHash.slice(0,10)))
    throw new ConversionPreparationError("pin");
  try{
    const key=await crypto.subtle.importKey("raw",pub as BufferSource,{name:"Ed25519"},false,["verify"]);
    const message=new TextEncoder().encode(DOMAIN+canonicalOfflineJson(p));
    if(!await crypto.subtle.verify({name:"Ed25519"},key,signature as BufferSource,message))
      throw new ConversionPreparationError("signature");
  }catch(e){
    if(e instanceof ConversionPreparationError)throw e;
    throw new ConversionPreparationError("unavailable");
  }
  const {context_digest: claimed,...digestFields}=c;
  const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",
    new TextEncoder().encode(canonicalOfflineJson(digestFields))));
  if(hex(digest)!==claimed)throw new ConversionPreparationError("digest");
  return {
    snapshotId:p.snapshot_id,issuedAt:p.issued_at,expiresAt:p.expires_at,
    context:c as VerifiedConversionPreparation["context"],captureEnabled:false,
  };
}
