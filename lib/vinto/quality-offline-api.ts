/** HTTPS/session-only offline preparation. No browser-side grant generation. */
import {apiBaseUrl} from "./api";
import type {CaptureScopeEnvelope} from "./offline-operational-capture-scope-verify";
import type {QualityBobbinInboxItem} from "./quality-bobbins";

type Obj=Record<string,unknown>;
const obj=(x:unknown):x is Obj=>!!x&&typeof x==="object"&&!Array.isArray(x);
const url=(path:string)=>apiBaseUrl()+path;
async function json(path:string,method:"GET"|"POST",payload?:unknown):Promise<unknown>{
 const response=await fetch(url(path),{
  method,credentials:"include",cache:"no-store",redirect:"error",
  headers:{"Accept":"application/json",...(method==="POST"?{"Content-Type":"application/json"}:{})},
  ...(method==="POST"?{body:JSON.stringify(payload)}:{}),
 });
 if(!response.ok)throw new Error("offline_online_preparation_unavailable");
 const value=await response.json();
 if(!obj(value))throw new Error("offline_preparation_invalid");
 // This timestamp is sampled from the authenticated HTTPS response, NOT
 // from the handset wall clock. A new signed grant is verified separately.
 if(path==="/api/offline/quality/capture-authority"){
  const serverDate=response.headers.get("Date");
  const receivedAt=Date.now();
  if(!serverDate)throw new Error("offline_server_clock_unavailable");
  const serverMs=Date.parse(serverDate);
  if(!Number.isFinite(serverMs))throw new Error("offline_server_clock_invalid");
  return {...value,serverReceivedAtMs:receivedAt,serverDateMs:serverMs};
 }
 return value;
}
export async function enrollQualityOfflineDevice(deviceKey:string):Promise<string>{
 const value=await json("/api/offline/quality/enroll","POST",{device_key:deviceKey});
 if(!obj(value)||value.device_key!==deviceKey||
    typeof value.public_key_b64url!=="string"||!/^[a-zA-Z0-9_-]{43}$/.test(value.public_key_b64url))
   throw new Error("offline_enrollment_invalid");
 return value.public_key_b64url;
}
export type QualityOfflineAuthorityResponse=Readonly<{
 envelope:CaptureScopeEnvelope;
 context:Readonly<{
  formVersion:number;scopeSnapshotId:string;contextVersion:string;
  bobbinContextDigest:string|null;
 }>;
 /** HTTPS Date header, sampled when the authorization was received. */
 serverReceivedAtMs:number;
 serverDateMs:number;
}>;
export async function requestQualityOfflineAuthority(
 deviceKey:string,machineCode:string,formCode:string,bobbinId?:string,
):Promise<QualityOfflineAuthorityResponse>{
 const value=await json("/api/offline/quality/capture-authority","POST",{
  device_key:deviceKey,machine_code:machineCode,form_code:formCode,
  ...(bobbinId?{bobbin_id:bobbinId}:{}),
 });
 if(!obj(value)||!obj(value.envelope)||!obj(value.context)||
    !Number.isSafeInteger(value.context.formVersion)||
    typeof value.context.scopeSnapshotId!=="string"||
    typeof value.context.contextVersion!=="string"||
    !(value.context.bobbinContextDigest===null||typeof value.context.bobbinContextDigest==="string")||
    !Number.isFinite(value.serverReceivedAtMs)||!Number.isFinite(value.serverDateMs))
   throw new Error("offline_capture_authority_invalid");
 return value as unknown as QualityOfflineAuthorityResponse;
}
type AvailableForm=Readonly<{code:string;name:string;version_number:number;eligible:boolean}>;
type Machine=Readonly<{code:string;name:string;forms:AvailableForm[];bobbin_forms?:AvailableForm[]}>;
export type OfflineFormOffer=Readonly<{formCode:string;formVersion:number;machineCode:string;
 machineName:string;name:string;kind:"machine"|"bobbin"}>;
const MACHINE_CODES=new Set(["VINTO-P1-18","VINTO-P1-22","VINTO-P1-26","VINTO-P1-27"]);
const BOBBIN_CODES=new Set(["VINTO-P1-19","VINTO-P1-20","VINTO-P1-21","VINTO-P1-24","VINTO-P1-25","VINTO-P1-28"]);
export async function listQualityOfflineOffers():Promise<OfflineFormOffer[]>{
 const [m,b]=await Promise.all([
  json("/api/quality/machine-forms","GET"),json("/api/quality/bobbin-forms","GET"),
 ]);
 const out:OfflineFormOffer[]=[];
 for(const [data,kind] of [[m,"machine"],[b,"bobbin"]] as const){
  if(!obj(data)||!Array.isArray(data.sectors))throw new Error("offline_quality_offers_invalid");
  for(const sector of data.sectors){
   if(!obj(sector)||!Array.isArray(sector.machines))continue;
   for(const machine of sector.machines as Machine[]){
    if(!machine||typeof machine.code!=="string"||typeof machine.name!=="string")continue;
    const forms=kind==="machine"?machine.forms:
     [...(machine.forms??[]),...(machine.bobbin_forms??[])];
    for(const item of forms??[]){
     if(item?.eligible!==true||typeof item.code!=="string"||
        typeof item.name!=="string"||!Number.isSafeInteger(item.version_number))continue;
     if(!(kind==="machine"?MACHINE_CODES:BOBBIN_CODES).has(item.code))continue;
     if(!out.some(o=>o.machineCode===machine.code&&o.formCode===item.code))
      out.push({formCode:item.code,formVersion:item.version_number,
       machineCode:machine.code,machineName:machine.name,name:item.name,kind});
    }
   }
  }
 }
 return out;
}
export async function listQualityOfflineBobbins():Promise<QualityBobbinInboxItem[]>{
 // The backend owns the inbox and sector permission; no local guess is used.
 const lists=await Promise.all(["pending","released","rejected"].map(async status=>{
  try{
   const r=await fetch(url("/api/quality/bobbins?status="+status),{
    credentials:"include",cache:"no-store",redirect:"error"});
   if(!r.ok)throw Error("offline_bobbin_inbox_unavailable");
   const v=await r.json();if(!Array.isArray(v))throw Error("offline_bobbin_inbox_invalid");
   return v as QualityBobbinInboxItem[];
  }catch{return [] as QualityBobbinInboxItem[];}
 }));
 const ids=new Set<string>();
 return lists.flat().filter(item=>{
  const id=item?.bobbin?.id;
  if(!id||ids.has(id)||!item.bobbin.machine?.code)return false;
  ids.add(id);return true;
 });
}
