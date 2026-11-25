"use client";

/** Offline Quality inside VINTO, using the EXACT existing capture components.
 * Authentication for upload is always /api/auth/me; local vault unlock is
 * limited to editing already prepared records on a shared device.
 */
import {useEffect,useMemo,useRef,useState} from "react";
import {CandidateFormCapture} from "@/components/vinto/candidate-form-capture";
import {QualityHumidityCapture} from "@/components/vinto/quality-humidity-capture";
import {QualityPhysicalCapture} from "@/components/vinto/quality-physical-capture";
import type {AuthUser} from "@/lib/vinto/auth";
import {getCurrentUser} from "@/lib/vinto/auth-api";
import {apiBaseUrl} from "@/lib/vinto/api";
import {getDeviceKey,DEVICE_KEY_STORAGE} from "@/lib/vinto/device";
import {QUALITY_CANDIDATES} from "@/lib/vinto/quality-candidates";
import {QUALITY_BOBBIN_CANDIDATES} from "@/lib/vinto/quality-bobbin-candidates";
import type {QualityBobbinInboxItem} from "@/lib/vinto/quality-bobbins";
import {QUALITY_SCREEN_BY_FORM,BOBBIN_SCREEN_BY_FORM} from "@/lib/vinto/quality-offers";
import {EMPTY_HUMIDITY_DRAFT,normalizeHumidityDraft} from "@/lib/vinto/quality-captures";
import {EMPTY_PHYSICAL_DRAFT,normalizePhysicalDraft} from "@/lib/vinto/quality-physical";
import {enrollQualityOfflineDevice,requestQualityOfflineAuthority,
 listQualityOfflineOffers,listQualityOfflineBobbins,
 type OfflineFormOffer} from "@/lib/vinto/quality-offline-api";
import {createLocalVault,unlockLocalVault} from "@/lib/vinto/offline-vault";
import type {OfflineVaultIdentity} from "@/lib/vinto/offline-vault";
import {createOperationalLocalStore} from "@/lib/vinto/offline-operational-local-store";
import {createOperationalCaptureBindings,type OperationalFormContext} from "@/lib/vinto/offline-operational-capture-bindings";
import {createQualityOfflineDraftLifecycle} from "@/lib/vinto/quality-offline-draft-lifecycle";
import {createOperationalCaptureGate} from "@/lib/vinto/offline-operational-capture-gate";
import {verifyOperationalCaptureScope,type CaptureScopeEnvelope} from "@/lib/vinto/offline-operational-capture-scope-verify";
import {createQualityOfflineQueuePort} from "@/lib/vinto/quality-offline-queue-port";
import {prepareQualityDevice} from "@/lib/vinto/quality-offline-device-preparation";
import {requirePersistedQualityDevice} from "@/lib/vinto/quality-offline-device-identity";
import {getOfflineProfile,listOfflineProfiles,saveOfflineProfile,
 saveOfflinePreparation,listOfflinePreparations,readOfflinePreparation,
 type OfflineLocalProfile} from "@/lib/vinto/quality-offline-preparation-store";
import {createOperationalHttpTransport} from "@/lib/vinto/offline-operational-http";
import {createOperationalSyncRuntime} from "@/lib/vinto/offline-operational-sync-runtime";
import type {QualityDraftPort} from "@/lib/vinto/use-quality-offline-draft-editor";

type Props={user:AuthUser|null;online:boolean;onExit:()=>void};
type Prepared=Readonly<{context:OperationalFormContext;envelope:CaptureScopeEnvelope;
 bobbin:QualityBobbinInboxItem|null}>;
type NamedPreparation=Readonly<{id:string;formCode:string;machineCode:string;
 data:Prepared}>;
type Unlocked=Readonly<{profile:OfflineLocalProfile;key:CryptoKey;identity:OfflineVaultIdentity}>;
const obj=(x:unknown):x is Record<string,unknown>=>x!==null&&typeof x==="object"&&!Array.isArray(x);
const isUuid=(x:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(x);
const formFor=(code:string)=>{
 const machine=QUALITY_SCREEN_BY_FORM[code],bobbin=BOBBIN_SCREEN_BY_FORM[code];
 return machine?QUALITY_CANDIDATES[machine].form:
  bobbin?QUALITY_BOBBIN_CANDIDATES[bobbin].form:null;
};
const initialValues=(code:string,bobbin:QualityBobbinInboxItem|null):Record<string,string>=>{
 if(code==="VINTO-P1-19")return {...EMPTY_HUMIDITY_DRAFT};
 if(code==="VINTO-P1-20")return {...EMPTY_PHYSICAL_DRAFT};
 const form=formFor(code);
 if(!form)throw new Error("offline_form_unknown");
 const fields=form.emptyDraft();
 const screen=BOBBIN_SCREEN_BY_FORM[code];
 if(screen&&bobbin){
  const k=QUALITY_BOBBIN_CANDIDATES[screen].bobbinCodeField;
  if(k)fields[k]=bobbin.bobbin.code;
 }
 return fields;
};
const normalize=(code:string,values:Readonly<Record<string,string|boolean>>):Readonly<Record<string,string>>=>{
 const draft=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,String(v)]));
 const check=code==="VINTO-P1-19"?normalizeHumidityDraft(draft as typeof EMPTY_HUMIDITY_DRAFT):
  code==="VINTO-P1-20"?normalizePhysicalDraft(draft as typeof EMPTY_PHYSICAL_DRAFT):
  formFor(code)?.normalizeDraft(draft);
 if(!check||!check.ok)throw new Error("offline_quality_fields_invalid");
 return check.values;
};
const validPrep=(x:unknown):x is Prepared=>{
 if(!obj(x)||!obj(x.context)||!obj(x.envelope))return false;
 const c=x.context;
 return typeof c.draftId==="string"&&isUuid(c.draftId)&&
  typeof c.machineCode==="string"&&typeof c.formCode==="string"&&
  Number.isSafeInteger(c.formVersion)&&typeof c.scopeSnapshotId==="string"&&
  typeof c.contextVersion==="string"&&
  (x.bobbin===null||obj(x.bobbin));
};

export function QualityOfflineWorkspace({user,online,onExit}:Props){
 const [profiles,setProfiles]=useState<OfflineLocalProfile[]>([]);
 const [chosen,setChosen]=useState("");
 const [passphrase,setPassphrase]=useState("");
 const [unlocked,setUnlocked]=useState<Unlocked|null>(null);
 const [offers,setOffers]=useState<OfflineFormOffer[]>([]);
 const [bobbins,setBobbins]=useState<QualityBobbinInboxItem[]>([]);
 const [offerChoice,setOfferChoice]=useState("");
 const [bobbinChoice,setBobbinChoice]=useState("");
 const [preps,setPreps]=useState<NamedPreparation[]>([]);
 const [activeId,setActiveId]=useState<string|null>(null);
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState("");
 const [queueInfo,setQueueInfo]=useState("");
 const store=useMemo(()=>createOperationalLocalStore(),[]);
 const runtime=useRef<ReturnType<typeof createOperationalSyncRuntime>|null>(null);
 const active=preps.find(p=>p.id===activeId)??null;
 const pickedOffer=offers.find(x=>offerChoice===x.machineCode+"|"+x.formCode);
 const activeBobbin=bobbins.find(x=>x.bobbin.id===bobbinChoice)??null;

 useEffect(()=>{
  void listOfflineProfiles().then(setProfiles).catch(()=>setMessage("No se pudo abrir el almacenamiento local."));
 },[]);
 useEffect(()=>{
  if(!user||!online)return;
  void Promise.all([listQualityOfflineOffers(),listQualityOfflineBobbins()])
   .then(([a,b])=>{setOffers(a);setBobbins(b);})
   .catch(()=>setMessage("No se pudo consultar la preparación de Calidad. Verifica tu conexión y permisos."));
 },[user?.id,online]);
 const refresh=async(state:Unlocked)=>{
  const rows=await listOfflinePreparations(state.identity);
  const data:NamedPreparation[]=[];
  for(const row of rows){
   try{
    const opened=await readOfflinePreparation(state.key,row);
    if(!validPrep(opened)||opened.context.draftId!==row.id||
       opened.context.formCode!==row.formCode||
       opened.context.formVersion!==row.formVersion||
       opened.context.machineCode!==row.machineCode||
       opened.context.scopeSnapshotId!==row.scopeSnapshotId)continue;
    data.push({id:row.id,formCode:row.formCode,machineCode:row.machineCode,data:opened});
   }catch{/* One corrupt record cannot expose or delete any others. */}
  }
  setPreps(data);
  const queue=await store.sync.list(state.identity.ownerId,state.identity.deviceKey);
  setQueueInfo(queue.length?queue.reduce((acc,x)=>{
   acc[x.state]=(acc[x.state]??0)+1;return acc;
  },{} as Record<string,number>)&&
   queue.map(x=>x.state).reduce((a,x)=>(a[x]=(a[x]??0)+1,a),{} as Record<string,number>)
     ?Object.entries(queue.map(x=>x.state).reduce((a,x)=>(a[x]=(a[x]??0)+1,a),{} as Record<string,number>)).map(([k,v])=>k+": "+v).join(" · "):"" :"Sin capturas en cola");
 };
 const unlock=async()=>{
  if(busy||!passphrase)return;
  setBusy(true);setMessage("");
  try{
   let profile:OfflineLocalProfile|null=null;
   let key:CryptoKey;
   let identity:OfflineVaultIdentity;
   if(user){
    if(!online)throw Error("La preparación inicial requiere internet.");
    const deviceKey=getDeviceKey();
    const persisted=localStorage.getItem(DEVICE_KEY_STORAGE);
    if(deviceKey!==persisted)throw Error("La clave del dispositivo no se pudo conservar.");
    identity={ownerId:user.id.toLowerCase(),deviceKey:deviceKey.toLowerCase()};
    const pin=await enrollQualityOfflineDevice(deviceKey);
    profile=await getOfflineProfile(identity);
    if(profile){
     identity=requirePersistedQualityDevice({userId:user.id},{
      ownerId:profile.ownerId,deviceKey:profile.deviceKey,record:profile.vaultRecord,
     },localStorage);
     if(profile.trustedPublicKeyB64url!==pin)throw Error("La firma de VINTO cambió. No se sustituirá automáticamente la autorización local.");
     key=await unlockLocalVault(profile.vaultRecord,passphrase);
    }else{
     const created=await createLocalVault(identity,passphrase);
     key=created.key;
     profile={id:identity.ownerId+":"+identity.deviceKey,
      ownerId:identity.ownerId,deviceKey:identity.deviceKey,
      displayName:user.display_name,vaultRecord:created.record,trustedPublicKeyB64url:pin};
     await saveOfflineProfile(profile);
    }
   }else{
    profile=profiles.find(x=>x.id===chosen)??null;
    if(!profile)throw Error("Selecciona el usuario que preparó este dispositivo.");
    identity={ownerId:profile.ownerId,deviceKey:profile.deviceKey};
    identity=requirePersistedQualityDevice({userId:profile.ownerId},{
     ownerId:profile.ownerId,deviceKey:profile.deviceKey,record:profile.vaultRecord,
    },localStorage);
    key=await unlockLocalVault(profile.vaultRecord,passphrase);
   }
   const state={profile,key,identity};
   setUnlocked(state);setPassphrase("");
   await refresh(state);
  }catch(error){
   setMessage(error instanceof Error?error.message:"No se pudo desbloquear el almacenamiento.");
  }finally{setBusy(false);}
 };
 const prepare=async(reuse?:Prepared)=>{
  if(!unlocked||busy)return;
  setBusy(true);setMessage("");
  try{
   let context:OperationalFormContext;
   let envelope:CaptureScopeEnvelope;
   let selectedBobbin:QualityBobbinInboxItem|null=null;
   if(reuse){
    context={...reuse.context,draftId:crypto.randomUUID()};
    envelope=reuse.envelope;
    selectedBobbin=reuse.bobbin;
   }else{
    if(!user||!online||!pickedOffer)throw Error("Selecciona un formulario autorizado con conexión.");
    if(pickedOffer.kind==="bobbin"){
     if(!activeBobbin||activeBobbin.bobbin.machine.code!==pickedOffer.machineCode)
      throw Error("Selecciona una bobina de la máquina autorizada.");
     selectedBobbin=activeBobbin;
    }
    const response=await requestQualityOfflineAuthority(
     unlocked.identity.deviceKey,pickedOffer.machineCode,pickedOffer.formCode,
     selectedBobbin?.bobbin.id,
    );
    if(response.context.formVersion!==pickedOffer.formVersion)
     throw Error("La versión del formulario cambió; actualiza antes de preparar.");
    envelope=response.envelope;
    context={
     draftId:crypto.randomUUID(),machineCode:pickedOffer.machineCode,
     formCode:pickedOffer.formCode,formVersion:response.context.formVersion,
     scopeSnapshotId:response.context.scopeSnapshotId,
     contextVersion:response.context.contextVersion,
     ...(selectedBobbin?{bobbin:{bobbin_id:selectedBobbin.bobbin.id,
      context_digest:response.context.bobbinContextDigest??""}}:{}),
    };
   }
   const gate={
    envelope,trustedPublicKeyB64url:unlocked.profile.trustedPublicKeyB64url,
    identity:unlocked.identity,
    target:{scopeSnapshotId:context.scopeSnapshotId,machineCode:context.machineCode,
      formCode:context.formCode,formVersion:context.formVersion},now:Date.now,
   };
   const prepared=await prepareQualityDevice({
    identity:unlocked.identity,key:unlocked.key,context,captureAuthority:gate,
    validateComplete:values=>{normalize(context.formCode,values);},store,
   });
   await prepared.draft.prepare(initialValues(context.formCode,selectedBobbin));
   await saveOfflinePreparation(unlocked.identity,unlocked.key,{
    draftId:context.draftId,scopeSnapshotId:context.scopeSnapshotId,
    formCode:context.formCode,formVersion:context.formVersion,
    machineCode:context.machineCode,
    payload:{context,envelope,bobbin:selectedBobbin},
   });
   await refresh(unlocked);setActiveId(context.draftId);
   setMessage("Formulario preparado. Las mediciones se guardarán cifradas en este dispositivo.");
  }catch(error){setMessage(error instanceof Error?error.message:"No se pudo preparar el formulario.");}
  finally{setBusy(false);}
 };
 const port=useMemo(()=>{
  if(!active||!unlocked)return null;
  const {context,envelope}=active.data;
  const gate=createOperationalCaptureGate({
   envelope,trustedPublicKeyB64url:unlocked.profile.trustedPublicKeyB64url,
   identity:unlocked.identity,
   target:{scopeSnapshotId:context.scopeSnapshotId,machineCode:context.machineCode,
    formCode:context.formCode,formVersion:context.formVersion},now:Date.now,
  });
  const bindings=createOperationalCaptureBindings({
   identity:unlocked.identity,key:unlocked.key,context,store,
   assertCaptureScope:gate,
   validateComplete:values=>{normalize(context.formCode,values);},
  });
  const draft:QualityDraftPort=createQualityOfflineDraftLifecycle({
   bindings,identity:unlocked.identity,draftId:context.draftId,
   assertPreparedCaptureScope:gate,
  });
  const queue=createQualityOfflineQueuePort({
   bindingsFor:async prepared=>{
    if(prepared.scopeSnapshotId!==context.scopeSnapshotId||
       prepared.contextVersion!==context.contextVersion||
       prepared.target.formCode!==context.formCode||
       prepared.target.machineCode!==context.machineCode||
       prepared.formVersion!==context.formVersion||
       (context.bobbin?.bobbin_id??null)!==(prepared.target.kind==="bobbin"?prepared.target.bobbinId:null))
      throw new Error("offline_preparation_changed");
    return bindings;
   },
   normalizeDraft:(_prepared,values)=>normalize(context.formCode,values),
  });
  return {draft,queue,context};
 },[active,unlocked,store]);
 useEffect(()=>{
  if(!unlocked||!user||user.id.toLowerCase()!==unlocked.identity.ownerId)return;
  const session=async()=>{
   const result=await getCurrentUser();
   return result.status==="authenticated"?{userId:result.user.id}:null;
  };
  const origin=apiBaseUrl();
  const runner=createOperationalSyncRuntime({
   store,identity:unlocked.identity,unlockedKey:()=>unlocked.key,
   online:()=>navigator.onLine,onlineSession:session,
   transport:createOperationalHttpTransport({origin,fetcher:fetch,
    corsApprovedApi:new URL(origin).origin!==window.location.origin}),
   tabId:crypto.randomUUID(),
   subscribe:(event,listener)=>{
    if(event==="visible"){
     const fn=()=>{if(document.visibilityState==="visible")listener();};
     document.addEventListener("visibilitychange",fn);
     return ()=>document.removeEventListener("visibilitychange",fn);
    }
    window.addEventListener(event==="focus"?"focus":"online",listener);
    return ()=>window.removeEventListener(event==="focus"?"focus":"online",listener);
   },
   setTimer:(callback,ms)=>window.setTimeout(callback,ms),
   clearTimer:timer=>window.clearTimeout(timer as number),
   onRunComplete:()=>{void refresh(unlocked);},
  });
  runtime.current=runner;
  runner.start();runner.notifyReady();
  return ()=>{runner.stop();if(runtime.current===runner)runtime.current=null;};
 // Preserve the original login-bound key across ordinary component renders.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[unlocked,user?.id,store]);
 const notifyQueued=()=>{
  if(unlocked)void refresh(unlocked);
  runtime.current?.notifyReady();
 };
 const syncManual=async()=>{
  if(!runtime.current){setMessage("Para sincronizar debes iniciar sesión con internet como el autor original.");return;}
  setBusy(true);
  try{await runtime.current.syncOnce();if(unlocked)await refresh(unlocked);}
  catch{setMessage("No se confirmó la sincronización. Conservamos las capturas locales.");}
  finally{setBusy(false);}
 };
 const current=active?.data.context;
 const candidateMachine=current&&QUALITY_SCREEN_BY_FORM[current.formCode];
 const candidateBobbin=current&&BOBBIN_SCREEN_BY_FORM[current.formCode];
 if(active&&port&&current){
  const common={online:false,attempt:null,back:()=>setActiveId(null),onSessionLost:()=>setActiveId(null),
   onOfflineQueued:notifyQueued};
  const bobbin=active.data.bobbin;
  const top=<div className="p-3 text-sm bg-amber-50 text-amber-950" role="status">
   Formulario cifrado del operario original. Se guardará localmente y se sincronizará al volver la sesión autorizada.
   <button className="ml-4 underline" onClick={()=>void prepare(active.data)}>Preparar nueva captura</button>
  </div>;
  if(candidateMachine)return <>{top}<CandidateFormCapture
   key={current.draftId} candidate={QUALITY_CANDIDATES[candidateMachine]}
   machine={{code:current.machineCode,name:current.machineCode}}
   {...common} setAttempt={()=>{}}
   onAssignmentChanged={()=>setActiveId(null)}
   offlineQuality={{prepared:{formVersion:current.formVersion,scopeSnapshotId:current.scopeSnapshotId,
     contextVersion:current.contextVersion},queue:port.queue,draft:port.draft}}/></>;
  if(bobbin&&candidateBobbin)return <>{top}<CandidateFormCapture
   key={current.draftId} candidate={QUALITY_BOBBIN_CANDIDATES[candidateBobbin]}
   bobbin={bobbin} {...common} setAttempt={()=>{}}
   onAssignmentChanged={()=>setActiveId(null)}
   offlineQuality={{prepared:{formVersion:current.formVersion,scopeSnapshotId:current.scopeSnapshotId,
     contextVersion:current.contextVersion,bobbinContextDigest:current.bobbin?.context_digest},
     queue:port.queue,draft:port.draft}}/></>;
  if(bobbin&&current.formCode==="VINTO-P1-19")return <>{top}<QualityHumidityCapture
   key={current.draftId} item={bobbin} {...common} setAttempt={()=>{}} onSubmitted={()=>{}}
   offlineQuality={{context:{machineCode:current.machineCode,bobbinId:bobbin.bobbin.id,
    formVersion:current.formVersion,scopeSnapshotId:current.scopeSnapshotId,
    contextVersion:current.contextVersion,bobbinContextDigest:current.bobbin?.context_digest??""},
    queue:port.queue,draft:port.draft}}/></>;
  if(bobbin&&current.formCode==="VINTO-P1-20")return <>{top}<QualityPhysicalCapture
   key={current.draftId} item={bobbin} {...common} setAttempt={()=>{}} onSubmitted={()=>{}}
   offlineQuality={{context:{machineCode:current.machineCode,bobbinId:bobbin.bobbin.id,
    formVersion:current.formVersion,scopeSnapshotId:current.scopeSnapshotId,
    contextVersion:current.contextVersion,bobbinContextDigest:current.bobbin?.context_digest??""},
    queue:port.queue,draft:port.draft}}/></>;
 }
 return <main className="min-h-screen bg-[#f3f6f4] text-slate-950 p-4 md:p-8">
  <section className="max-w-4xl mx-auto space-y-4">
   <header className="rounded-xl bg-[#123f32] text-white p-5">
    <h1 className="text-xl font-bold">VINTO · Calidad Offline</h1>
    <p className="text-sm mt-2">Formularios originales · almacenamiento cifrado por operario y dispositivo.</p>
    <button className="underline mt-3 text-sm" onClick={()=>{setUnlocked(null);onExit();}}>Volver a VINTO</button>
   </header>
   {message&&<p role="alert" className="rounded-xl p-3 bg-amber-50 text-amber-950">{message}</p>}
   {!unlocked?<div className="rounded-xl bg-white p-5 space-y-3 border">
    <p className="font-semibold">Desbloquear dispositivo compartido</p>
    {!user&&<select aria-label="Operario preparado" className="w-full border rounded p-2" value={chosen}
      onChange={e=>setChosen(e.target.value)}>
      <option value="">Seleccionar operario</option>
      {profiles.map(p=><option key={p.id} value={p.id}>{p.displayName}</option>)}
    </select>}
    <label className="block text-sm">Clave local (16 caracteres mínimo)</label>
    <input type="password" autoComplete="off" className="w-full border rounded p-2"
      value={passphrase} onChange={e=>setPassphrase(e.target.value)}
      onKeyDown={e=>{if(e.key==="Enter")void unlock();}}/>
    <button disabled={busy||!passphrase} className="rounded bg-[#146b4f] text-white p-2 disabled:opacity-50"
      onClick={()=>void unlock()}>{busy?"Verificando…":user?"Preparar o desbloquear":"Desbloquear borradores"}</button>
    <p className="text-sm">La clave local no sustituye el login de VINTO. Para sincronizar necesitarás la sesión online del autor original.</p>
   </div>:<div className="rounded-xl bg-white border p-5 space-y-4">
    <p className="font-semibold">Operario: {unlocked.profile.displayName}</p>
    <p role="status" className="text-sm">Cola: {queueInfo}</p>
    <button disabled={busy||!online||!user} onClick={()=>void syncManual()}
      className="border rounded p-2 disabled:opacity-50">Sincronizar ahora</button>
    {user&&online&&<div className="border-t pt-4 space-y-2">
     <h2 className="font-semibold">Preparar otro formulario</h2>
     <select aria-label="Formulario autorizado" value={offerChoice}
      onChange={e=>{setOfferChoice(e.target.value);setBobbinChoice("");}}
      className="w-full border rounded p-2">
      <option value="">Seleccionar formulario</option>
      {offers.map(o=><option key={o.machineCode+"|"+o.formCode} value={o.machineCode+"|"+o.formCode}>
       {o.machineCode} · {o.formCode} · {o.name}</option>)}
     </select>
     {pickedOffer?.kind==="bobbin"&&<select aria-label="Bobina autorizada" value={bobbinChoice}
       className="w-full border rounded p-2" onChange={e=>setBobbinChoice(e.target.value)}>
       <option value="">Seleccionar bobina</option>
       {bobbins.filter(x=>x.bobbin.machine.code===pickedOffer.machineCode).map(x=>
        <option key={x.bobbin.id} value={x.bobbin.id}>{x.bobbin.code} · {x.quality.status}</option>)}
      </select>}
     <button disabled={busy||!pickedOffer||(pickedOffer.kind==="bobbin"&&!activeBobbin)}
       className="bg-[#146b4f] text-white rounded p-2 disabled:opacity-50"
       onClick={()=>void prepare()}>Preparar formulario offline</button>
    </div>}
    <div className="border-t pt-4 space-y-2">
     <h2 className="font-semibold">Borradores y capturas preparadas</h2>
     {preps.length===0?<p className="text-sm">Sin formularios preparados para este operario.</p>:
      preps.map(p=><div key={p.id} className="border rounded p-3 flex justify-between gap-3">
       <div><b>{p.formCode}</b><p className="text-sm">{p.machineCode} · {p.data.bobbin?.bobbin.code??"Control por máquina"}</p></div>
       <button className="border rounded px-3" onClick={()=>setActiveId(p.id)}>Abrir formulario</button>
      </div>)}
    </div>
   </div>}
  </section>
 </main>;
}
