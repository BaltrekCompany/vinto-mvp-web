/**
 * OFF-03C.2 read-only Quality definition verification.
 * Signature + SHA256 integrity + exact signed scope / grant / version binding.
 * A verified package is NOT a permission to capture. Offline trust is historical.
 */
import { canonicalOfflineJson, type OfflineScopeIdentity } from "./offline-scope-verify.ts";
import type { VerifiedLocalScope } from "./offline-scope-store.ts";

const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HEX64=/^[0-9a-f]{64}$/;
const FORM=/^VINTO-P1-[0-9]{2}$/;
const MACHINE=/^[A-Za-z0-9_.-]{1,48}$/;
const B64=/^[A-Za-z0-9_-]+$/;
const DOMAIN="VINTO-OFFLINE-QUALITY-PACKAGE-V1\0";
const SCHEMA="vinto.offline.quality-package.v1";
const AUDIENCE="vinto-offline-quality-definition";
const ENVELOPE_KEYS=["algorithm","key_id","public_key_b64url","payload","signature_b64url"];
const PAYLOAD_KEYS=["schema","issuer","audience","kind","captures_enabled","package_id","scope_snapshot_id",
  "subject_user_id","device_key","machine_code","form_code","form_version","grant_id","issued_at",
  "content_sha256","definition"];
const DEFINITION_KEYS=["form_code","form_name","form_version","area","source_definition_checksum","published_at",
  "groups","fields","calculated_rules","option_dependencies","recipe_bundle_included","capture_eligible","note"];
const FIELD_KEYS=["key","label","description","value_type","source","required","unit","classification",
  "proposal","needs_validation","display_order","calculation_rule","options"];
const OPTION_KEYS=["option_key","label","display_order"];
const TYPE=new Set(["text","textarea","decimal","integer","boolean","date","time"]);
const SOURCE=new Set(["manual","calculated"]);
const encoder=new TextEncoder();

export type VerifiedQualityDefinition=Readonly<{
  envelope: {algorithm:"Ed25519";key_id:string;public_key_b64url:string;signature_b64url:string;payload:QualityPayload};
}>;
export type QualityField=Readonly<{key:string;label:string;description:string;value_type:string;source:string;
    required:boolean;unit:string|null;classification:string|null;proposal:string|null;
    needs_validation:boolean;display_order:number;calculation_rule:string|null;
    options:ReadonlyArray<{option_key:string;label:string;display_order:number}>}>;
export type QualityDefinition=Readonly<{form_code:string;form_name:string;form_version:number;area:"quality";
  source_definition_checksum:string;published_at:string|null;groups:[];fields:QualityField[];
  calculated_rules:Record<string,unknown>;option_dependencies:[];recipe_bundle_included:false;
  capture_eligible:false;note:string}>;
export type QualityPayload=Readonly<{schema:typeof SCHEMA;issuer:"vinto-backend";audience:typeof AUDIENCE;
  kind:"quality_definition_readiness_only";captures_enabled:false;package_id:string;scope_snapshot_id:string;
  subject_user_id:string;device_key:string;machine_code:string;form_code:string;form_version:number;grant_id:string;
  issued_at:string;content_sha256:string;definition:QualityDefinition;}>;
export class QualityPackageError extends Error {
  readonly reason:"invalid"|"scope"|"signature"|"pin"|"digest"|"unavailable";
  constructor(reason:QualityPackageError["reason"]){super("OFFLINE_QUALITY_PACKAGE_"+reason.toUpperCase());this.reason=reason;this.name="QualityPackageError";}
}
function rec(value:unknown):value is Record<string,unknown>{
  return value!==null&&typeof value==="object"&&!Array.isArray(value);
}
function exact(v:unknown,keys:readonly string[]):v is Record<string,unknown>{
  return rec(v)&&Object.keys(v).sort().join("|")===[...keys].sort().join("|");
}
function decode(v:string,expected:number):Uint8Array{
  if(!B64.test(v))throw new QualityPackageError("invalid");
  let bytes:Uint8Array;
  try{bytes=Uint8Array.from(atob(v.replace(/-/g,"+").replace(/_/g,"/").padEnd(Math.ceil(v.length/4)*4,"=")),c=>c.charCodeAt(0));}
  catch{throw new QualityPackageError("invalid");}
  let encoded="";for(const b of bytes)encoded+=String.fromCharCode(b);
  if(bytes.length!==expected||btoa(encoded).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"")!==v)throw new QualityPackageError("invalid");
  return bytes;
}
function validDefinition(input:unknown,formCode:string,version:number):asserts input is QualityDefinition{
  if(!exact(input,DEFINITION_KEYS)||input.form_code!==formCode||input.form_version!==version||
      input.area!=="quality"||typeof input.form_name!=="string"||!input.form_name||
      typeof input.source_definition_checksum!=="string"||!HEX64.test(input.source_definition_checksum)||
      (input.published_at!==null&&typeof input.published_at!=="string")||
      input.capture_eligible!==false||input.recipe_bundle_included!==false||
      typeof input.note!=="string"||!Array.isArray(input.groups)||input.groups.length!==0||
      !Array.isArray(input.option_dependencies)||input.option_dependencies.length!==0||
      !Array.isArray(input.fields)||input.fields.length<1||input.fields.length>128||
      !rec(input.calculated_rules))throw new QualityPackageError("invalid");
  const seen=new Set<string>(),calculated=new Set<string>();let count=0;
  for(const field of input.fields){
    if(!exact(field,FIELD_KEYS)||typeof field.key!=="string"||!field.key||
      field.key==="_groups"||seen.has(field.key)||typeof field.label!=="string"||
      typeof field.description!=="string"||!TYPE.has(String(field.value_type))||
      !SOURCE.has(String(field.source))||typeof field.required!=="boolean"||
      typeof field.needs_validation!=="boolean"||
      !Number.isSafeInteger(field.display_order)||(field.display_order as number)<0||
      !(field.unit===null||typeof field.unit==="string")||
      !(field.classification===null||typeof field.classification==="string")||
      !(field.proposal===null||typeof field.proposal==="string")||
      !(field.calculation_rule===null||typeof field.calculation_rule==="string")||
      !Array.isArray(field.options))throw new QualityPackageError("invalid");
    seen.add(field.key);
    if(field.source==="calculated"){if(field.required!==false)throw new QualityPackageError("invalid");calculated.add(field.key);}
    const opts=new Set<string>();
    for(const o of field.options){
      if(!exact(o,OPTION_KEYS)||typeof o.option_key!=="string"||!o.option_key||opts.has(o.option_key)||
        typeof o.label!=="string"||!Number.isSafeInteger(o.display_order)||
        (o.display_order as number)<0)throw new QualityPackageError("invalid");
      opts.add(o.option_key);count++;
    }
  }
  if(count>512||Object.keys(input.calculated_rules).sort().join("|")!==[...calculated].sort().join("|"))
      throw new QualityPackageError("invalid");
  for(const key of calculated){
    const rule=input.calculated_rules[key];
    if(!exact(rule,["method","numerator","denominator","denominator_zero"])||
       rule.method!=="percent_two_decimals_half_up"||rule.denominator_zero!=="omit_calculation"||
       typeof rule.numerator!=="string"||typeof rule.denominator!=="string"){
      throw new QualityPackageError("invalid");
    }
    const source=input.fields.find(x=>x.key===key);
    const num=input.fields.find(x=>x.key===rule.numerator);
    const den=input.fields.find(x=>x.key===rule.denominator);
    if(source?.value_type!=="decimal"||num?.source!=="manual"||num.value_type!=="decimal"||
      den?.source!=="manual"||den.value_type!=="decimal")throw new QualityPackageError("invalid");
  }
}
/** Only accepts the pin already decrypted and verified from the signed local scope. */
export async function verifyQualityPackage(input:unknown,scope:VerifiedLocalScope,
                                           identity:OfflineScopeIdentity):Promise<VerifiedQualityDefinition>{
  if(!crypto?.subtle)throw new QualityPackageError("unavailable");
  if(!exact(input,ENVELOPE_KEYS)||input.algorithm!=="Ed25519"||
      typeof input.key_id!=="string"||typeof input.signature_b64url!=="string"||
      typeof input.public_key_b64url!=="string"||!exact(input.payload,PAYLOAD_KEYS))throw new QualityPackageError("invalid");
  const p=input.payload;
  if(p.schema!==SCHEMA||p.issuer!=="vinto-backend"||p.audience!==AUDIENCE||
     p.kind!=="quality_definition_readiness_only"||p.captures_enabled!==false||
     typeof p.package_id!=="string"||!UUID.test(p.package_id)||
     typeof p.scope_snapshot_id!=="string"||!UUID.test(p.scope_snapshot_id)||
     typeof p.subject_user_id!=="string"||!UUID.test(p.subject_user_id)||
     typeof p.device_key!=="string"||!UUID.test(p.device_key)||
     typeof p.machine_code!=="string"||!MACHINE.test(p.machine_code)||
     typeof p.form_code!=="string"||!FORM.test(p.form_code)||
     !Number.isSafeInteger(p.form_version)||(p.form_version as number)<1||
     typeof p.grant_id!=="string"||!UUID.test(p.grant_id)||
     typeof p.issued_at!=="string"||!Number.isFinite(Date.parse(p.issued_at))||
     typeof p.content_sha256!=="string"||!HEX64.test(p.content_sha256))throw new QualityPackageError("invalid");
  if(p.subject_user_id.toLowerCase()!==identity.ownerId.toLowerCase()||
     p.device_key.toLowerCase()!==identity.deviceKey.toLowerCase()||
     p.scope_snapshot_id!==scope.envelope.payload.snapshot_id)throw new QualityPackageError("scope");
  const candidates=scope.envelope.payload.form_scopes.filter(x=>x.machine_code===p.machine_code&&
      x.form_code===p.form_code&&x.operation==="quality_machine_capture");
  if(candidates.length!==1||candidates[0].form_version!==p.form_version||
     candidates[0].grant_id!==p.grant_id)throw new QualityPackageError("scope");
  if(input.public_key_b64url!==scope.trustedPublicKey)throw new QualityPackageError("pin");
  validDefinition(p.definition,p.form_code,p.form_version);
  const plain=encoder.encode(canonicalOfflineJson(p.definition));
  if(plain.length>350_000)throw new QualityPackageError("invalid");
  const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",plain as BufferSource));
  const hex=Array.from(digest,b=>b.toString(16).padStart(2,"0")).join("");
  if(hex!==p.content_sha256)throw new QualityPackageError("digest");
  const pub=decode(scope.trustedPublicKey,32),sig=decode(input.signature_b64url,64);
  const pubhash=new Uint8Array(await crypto.subtle.digest("SHA-256",pub as BufferSource));
  if(input.key_id!=="ed25519-"+Array.from(pubhash.slice(0,10),b=>b.toString(16).padStart(2,"0")).join(""))
      throw new QualityPackageError("pin");
  try{
    const publicKey=await crypto.subtle.importKey("raw",pub as BufferSource,{name:"Ed25519"},false,["verify"]);
    const content=encoder.encode(DOMAIN+canonicalOfflineJson(p));
    if(!await crypto.subtle.verify({name:"Ed25519"},publicKey,sig as BufferSource,content as BufferSource))
        throw new QualityPackageError("signature");
  }catch(e){if(e instanceof QualityPackageError)throw e;throw new QualityPackageError("unavailable");}
  return { envelope: input as VerifiedQualityDefinition["envelope"] };
}
