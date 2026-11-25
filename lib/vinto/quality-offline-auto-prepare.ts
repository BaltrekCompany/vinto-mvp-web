/**
 * One shared, idempotent path for automatic and manually requested Quality
 * preparations. Machine forms need no bobbin. Bobbin forms are prepared only
 * against a real, authorized bobbin context; never fabricate that context.
 */
import type {QualityBobbinInboxItem} from "./quality-bobbins";
import type {OfflineFormOffer} from "./quality-offline-api";
import {requestQualityOfflineAuthority} from "./quality-offline-api";
import {validateQualityServerClock,qualityScopeNow,type QualityOfflineClock} from "./quality-offline-clock";
import {prepareQualityDevice} from "./quality-offline-device-preparation";
import {saveOfflinePreparation,type OfflineLocalProfile} from "./quality-offline-preparation-store";
import type {OfflineVaultIdentity} from "./offline-vault";
import type {OperationalLocalStore} from "./offline-operational-local-store";
import type {OperationalFormContext} from "./offline-operational-capture-bindings";
import type {CaptureScopeEnvelope} from "./offline-operational-capture-scope-verify";

export type OfflinePreparedForm=Readonly<{
 context:OperationalFormContext;
 envelope:CaptureScopeEnvelope;
 bobbin:QualityBobbinInboxItem|null;
 clock:QualityOfflineClock;
}>;
export type QualityPreparationIdentity=Readonly<{
 profile:OfflineLocalProfile;
 key:CryptoKey;
 identity:OfflineVaultIdentity;
}>;
export type QualityPreparationDeps=Readonly<{
 state:QualityPreparationIdentity;
 store:OperationalLocalStore;
 initialValues:(formCode:string,bobbin:QualityBobbinInboxItem|null)=>Record<string,string>;
 validateComplete:(formCode:string,values:Readonly<Record<string,string|boolean>>)=>void;
}>;

export function matchingQualityPreparation(
 list:readonly OfflinePreparedForm[],offer:OfflineFormOffer,
 bobbin:QualityBobbinInboxItem|null,
):boolean{
 return list.some(p=>p.context.formCode===offer.formCode&&
   p.context.machineCode===offer.machineCode&&
   (p.context.bobbin?.bobbin_id??null)===(bobbin?.bobbin.id??null));
}

export async function prepareAuthorizedQualityForm(
 deps:QualityPreparationDeps,offer:OfflineFormOffer,
 bobbin:QualityBobbinInboxItem|null,
):Promise<OfflinePreparedForm>{
 if(offer.kind==="bobbin"&&(!bobbin||bobbin.bobbin.machine.code!==offer.machineCode))
   throw new Error("offline_quality_bobbin_required");
 if(offer.kind==="machine"&&bobbin)throw new Error("offline_quality_bobbin_unexpected");
 const result=await requestQualityOfflineAuthority(
   deps.state.identity.deviceKey,offer.machineCode,offer.formCode,bobbin?.bobbin.id);
 if(result.context.formVersion!==offer.formVersion)
   throw new Error("offline_quality_version_changed");
 const envelope=result.envelope;
 const clock=validateQualityServerClock(envelope,{
   serverDateMs:result.serverDateMs,clientReceivedAtMs:result.serverReceivedAtMs,
 });
 const context:OperationalFormContext={
   draftId:crypto.randomUUID(),machineCode:offer.machineCode,
   formCode:offer.formCode,formVersion:result.context.formVersion,
   scopeSnapshotId:result.context.scopeSnapshotId,
   contextVersion:result.context.contextVersion,
   ...(bobbin?{bobbin:{bobbin_id:bobbin.bobbin.id,
     context_digest:result.context.bobbinContextDigest??""}}:{}),
 };
 const gate={
   envelope,trustedPublicKeyB64url:deps.state.profile.trustedPublicKeyB64url,
   identity:deps.state.identity,
   target:{scopeSnapshotId:context.scopeSnapshotId,machineCode:context.machineCode,
     formCode:context.formCode,formVersion:context.formVersion},
   now:()=>qualityScopeNow(clock),
 };
 const prepared=await prepareQualityDevice({
   identity:deps.state.identity,key:deps.state.key,context,
   captureAuthority:gate,store:deps.store,
   validateComplete:values=>deps.validateComplete(context.formCode,values),
 });
 await prepared.draft.prepare(deps.initialValues(context.formCode,bobbin));
 const payload:OfflinePreparedForm={context,envelope,bobbin,clock};
 await saveOfflinePreparation(deps.state.identity,deps.state.key,{
   draftId:context.draftId,scopeSnapshotId:context.scopeSnapshotId,
   formCode:context.formCode,formVersion:context.formVersion,
   machineCode:context.machineCode,payload,
 });
 return payload;
}

/** Availability is user-grant-specific; never claim 10/10 without 10 grants.
 * Only one starter draft per distinct form/machine/bobbin pair is prepared.
 * Existing encrypted drafts are never edited, cleared or overwritten.
 */
export async function autoPrepareQualityForms(
 deps:QualityPreparationDeps,offers:readonly OfflineFormOffer[],
 bobbins:readonly QualityBobbinInboxItem[],
 existing:readonly OfflinePreparedForm[],
 onProgress?:(completed:number,total:number)=>void,
):Promise<{prepared:number;skipped:number;failed:string[]}>{
 const limited=offers.slice(0,40);
 let prepared=0,skipped=0,completed=0;
 const failed:string[]=[];
 const saved=[...existing];
 for(const offer of limited){
   const bobbin=offer.kind==="bobbin"?
     bobbins.find(b=>b.bobbin.machine.code===offer.machineCode)??null:null;
   if(offer.kind==="bobbin"&&!bobbin){failed.push(offer.formCode+": sin bobina autorizada");}
   else if(matchingQualityPreparation(saved,offer,bobbin)){skipped++;}
   else{
     try{
       const result=await prepareAuthorizedQualityForm(deps,offer,bobbin);
       saved.push(result);prepared++;
     }catch(error){
       failed.push(offer.formCode+": "+(error instanceof Error?error.message:"error de preparación"));
     }
   }
   completed++;
   onProgress?.(completed,limited.length);
 }
 return {prepared,skipped,failed};
}
