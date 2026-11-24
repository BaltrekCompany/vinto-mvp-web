/** VINTO OFF-04.8: operational Quality mobile PWA, same-origin only.
 * Reuses the authenticated mobile enrollment and signed definition flow of
 * OFF-04.6, but uses the independent CAPTURE authority and atomic operational
 * IndexedDB store; NEVER touches the synthetic lab pending/engine databases.
 * Bundled only when OFFLINE_OPERATIONAL_CAPTURE=1; no production enablement
 * or secret material is shipped from this source file.
 */
import {interpretSession,interpretLogin,type AuthUser} from "./auth.ts";
import {getDeviceKey} from "./device";
import {createLocalVault,unlockLocalVault,openLocalDraft,type OfflineVaultIdentity,type OfflineVaultRecord} from "./offline-vault.ts";
import {readLocalProfile,storeLocalProfile} from "./offline-profile-store.ts";
import {readOfflineScope,storeOfflineScope,readRawScope,type VerifiedLocalScope} from "./offline-scope-store.ts";
import {renewOfflineBundle,RenewalError} from "./offline-renewal.ts";
import {readQualityPackage,storeQualityPackage} from "./offline-quality-store.ts";
import {MACHINE_QUALITY_FORMS,BOBBIN_QUALITY_FORMS} from "./offline-operational-quality-validation.ts";
import {type VerifiedQualityDefinition,type QualityField} from "./offline-quality-verify.ts";
import {listBobbinContexts,storeBobbinContext} from "./offline-bobbin-store.ts";
import {bobbinContextVersion,type BobbinContext} from "./offline-draft-schema.ts";
import {createOperationalLocalStore} from "./offline-operational-local-store.ts";
import {createOperationalQualityEditor} from "./offline-operational-quality-editor.ts";
import {createOperationalSyncRuntime} from "./offline-operational-sync-runtime.ts";
import {createOperationalHttpTransport} from "./offline-operational-http.ts";
import {storeCaptureAuthority,readCaptureAuthority,listCaptureAuthoritySnapshots} from "./offline-operational-authority-store.ts";
import type {CaptureScopeEnvelope,CaptureScopeTarget} from "./offline-operational-capture-scope-verify.ts";

const el=<T = HTMLElement>(id:string):T=>document.getElementById(id) as unknown as T;
const show=(id:string,enabled:boolean)=>{el(id).hidden=!enabled;};
const message=(text:string)=>{el("status").textContent=text;};
const FORM=/^VINTO-P1-(18|19|20|21|22|24|25|26|27|28)$/;
const MACHINE=/^[A-Za-z0-9_.-]{1,48}$/;
const store=createOperationalLocalStore();
const tabId=crypto.randomUUID();

let key:CryptoKey|null=null,identity:OfflineVaultIdentity|null=null;
let readiness:VerifiedLocalScope|null=null,user:AuthUser|null=null;
let packages:VerifiedQualityDefinition[]=[];
let issuer:CaptureScopeEnvelope|null=null;
let syncRuntime:ReturnType<typeof createOperationalSyncRuntime>|null=null;
let activeEditor:Awaited<ReturnType<typeof createOperationalQualityEditor>>|null=null;
let activeDraftId:string|null=null,revision:number|null=null;
let values:Record<string,string|boolean>={};

function assertOrigin(){
 if(location.protocol!=="https:"&&!["127.0.0.1","localhost"].includes(location.hostname))
  throw Error("Se requiere HTTPS");
}
async function api(method:"GET"|"POST",path:string,body?:unknown){
 assertOrigin();
 if(!path.startsWith("/api/"))throw Error("Ruta no autorizada");
 const response=await fetch(path,{method,credentials:"include",redirect:"error",cache:"no-store",
  headers:{"Accept":"application/json",...(body!==undefined?{"Content-Type":"application/json"}:{})},
  ...(body!==undefined?{body:JSON.stringify(body)}:{})});
 const json=await response.json().catch(()=>null);
 return {status:response.status,json};
}
async function onlineUser():Promise<AuthUser|null>{
 try{
  const r=await api("GET","/api/auth/me");
  const outcome=interpretSession(r.status,r.json);
  return outcome.status==="authenticated"?outcome.user:null;
 }catch{return null;}
}
function requireUnlocked(){
 if(!key||!identity||!readiness)throw Error("El dispositivo está bloqueado");
 return {key,identity,readiness};
}
function fieldsFor(pkg:VerifiedQualityDefinition):QualityField[]{
 return [...pkg.envelope.payload.definition.fields].filter(f=>f.source==="manual")
  .sort((a,b)=>a.display_order-b.display_order);
}
function target(pkg:VerifiedQualityDefinition,snapshot:string):CaptureScopeTarget{
 const p=pkg.envelope.payload;
 return {scopeSnapshotId:snapshot,machineCode:p.machine_code,formCode:p.form_code,formVersion:p.form_version};
}
async function signedFor(pkg:VerifiedQualityDefinition):Promise<CaptureScopeEnvelope>{
 const ctx=requireUnlocked();
 const snapshots=await listCaptureAuthoritySnapshots(ctx.identity);
 // Existing captures retain their original snapshot. New ones use the newest
 // valid signed CAPTURE scope; never infer permissions from readiness packages.
 let latest:CaptureScopeEnvelope|null=null;
 for(const snapshot of snapshots){
  try{
   const candidate=await readCaptureAuthority(ctx.key,ctx.identity,target(pkg,snapshot),ctx.readiness.trustedPublicKey);
   if(!latest||candidate.payload.issued_at>latest.payload.issued_at)latest=candidate;
  }catch{/* An expired/revoked locally invalid snapshot is not selected. Server rechecks revocations. */}
 }
 if(!latest)throw Error("No existe una autorización CAPTURE válida para este formulario. Prepare el dispositivo en línea.");
 return latest;
}
async function loadPackages(){
 const ctx=requireUnlocked();
 const available:VerifiedQualityDefinition[]=[];
 for(const item of ctx.readiness.envelope.payload.form_scopes){
  if(!FORM.test(item.form_code)||
     !(MACHINE_QUALITY_FORMS.has(item.form_code)||BOBBIN_QUALITY_FORMS.has(item.form_code)))continue;
  const pkg=await readQualityPackage(ctx.key,ctx.identity,ctx.readiness,item.machine_code,item.form_code);
  if(pkg)available.push(pkg);
 }
 packages=available.sort((a,b)=>a.envelope.payload.form_code.localeCompare(b.envelope.payload.form_code));
 const select=el<HTMLSelectElement>("form");
 select.replaceChildren();
 packages.forEach((p,i)=>{
  const opt=document.createElement("option");opt.value=String(i);
  opt.textContent=p.envelope.payload.form_code+" · "+p.envelope.payload.machine_code+
    " · "+p.envelope.payload.definition.form_name;
  select.appendChild(opt);
 });
 await refreshBobbins();
}
async function refreshBobbins(){
 const ctx=requireUnlocked(),pkg=packages[Number(el<HTMLSelectElement>("form").value)];
 const needed=!!pkg&&BOBBIN_QUALITY_FORMS.has(pkg.envelope.payload.form_code);
 show("bobbin-area",needed);
 const select=el<HTMLSelectElement>("bobbin");select.replaceChildren();
 if(!needed||!pkg)return;
 const list=await listBobbinContexts(ctx.key,ctx.identity,ctx.readiness.envelope.payload.snapshot_id,
  pkg.envelope.payload.machine_code);
 for(const bobbin of list.contexts){
  const opt=document.createElement("option");opt.value=bobbin.bobbin_id;
  opt.textContent=bobbin.bobbin_code;select.appendChild(opt);
 }
}
async function getBobbin(pkg:VerifiedQualityDefinition):Promise<BobbinContext|undefined>{
 if(!BOBBIN_QUALITY_FORMS.has(pkg.envelope.payload.form_code))return undefined;
 const ctx=requireUnlocked();
 const list=await listBobbinContexts(ctx.key,ctx.identity,ctx.readiness.envelope.payload.snapshot_id,
  pkg.envelope.payload.machine_code);
 const selected=el<HTMLSelectElement>("bobbin").value;
 const bobbin=list.contexts.find(b=>b.bobbin_id===selected);
 if(!bobbin)throw Error("Prepare la bobina en línea antes de capturar offline");
 return bobbin;
}
async function prepareBobbin(code:string){
 const ctx=requireUnlocked(),pkg=packages[Number(el<HTMLSelectElement>("form").value)];
 if(!pkg||!BOBBIN_QUALITY_FORMS.has(pkg.envelope.payload.form_code)||!MACHINE.test(code))
  throw Error("Máquina o bobina inválida");
 const current=await onlineUser();
 if(!current||current.id.toLowerCase()!==ctx.identity.ownerId.toLowerCase())
  throw Error("Se necesita la sesión online del autor original");
 const response=await api("POST","/api/offline/bobbin-context",{
  device_key:ctx.identity.deviceKey,machine_code:pkg.envelope.payload.machine_code,
  bobbin_code:code,signed_scope:ctx.readiness.envelope,
 });
 if(response.status!==200)throw Error("No se obtuvo el contexto histórico de la bobina");
 const result=response.json as {snapshot_id?:string;contexts?:unknown[]};
 if(result.snapshot_id!==ctx.readiness.envelope.payload.snapshot_id||
   !Array.isArray(result.contexts)||result.contexts.length===0)
  throw Error("Respuesta de contexto incompleta");
 for(const bobbin of result.contexts)
  await storeBobbinContext(ctx.key,ctx.identity,result.snapshot_id,bobbin);
 await refreshBobbins();
}
function startSync(){
 const ctx=requireUnlocked();
 syncRuntime?.stop();
 const subscribe=(event:"online"|"focus"|"visible",fn:()=>void)=>{
  const target:EventTarget=event==="visible"?document:window;
  const name=event==="visible"?"visibilitychange":event;
  target.addEventListener(name,fn);
  return ()=>target.removeEventListener(name,fn);
 };
 syncRuntime=createOperationalSyncRuntime({
  store,identity:ctx.identity,unlockedKey:()=>key,
  online:()=>navigator.onLine,
  onlineSession:async()=>{
   const current=await onlineUser();
   return current?{userId:current.id}:null;
  },
  transport:createOperationalHttpTransport({origin:location.origin+"/",fetcher:fetch.bind(window)}),
  tabId,subscribe,
  setTimer:(cb,ms)=>window.setTimeout(cb,ms),
  clearTimer:id=>window.clearTimeout(id as number),
  onError:()=>{el("sync-status").textContent="Sincronización pendiente. Compruebe sesión y conexión.";},
 });
 syncRuntime.start();syncRuntime.notifyReady();
}
async function refreshDrafts(){
 const ctx=requireUnlocked(),list=el<HTMLUListElement>("drafts");
 const [drafts,queue]=await Promise.all([
  store.listDrafts(ctx.identity.ownerId,ctx.identity.deviceKey),
  store.sync.list(ctx.identity.ownerId,ctx.identity.deviceKey),
 ]);
 list.replaceChildren();
 for(const d of drafts){
  const li=document.createElement("li");
  li.textContent=d.formCode+" · "+d.machineCode+" · "+
    (d.frozenBy?"Captura confirmada":"Borrador local");
  if(!d.frozenBy){
   const btn=document.createElement("button");btn.type="button";
   btn.className="secondary";btn.textContent="Continuar borrador";
   btn.addEventListener("click",()=>{void openExisting(d.id).catch(report);});
   li.appendChild(btn);
  }
  list.appendChild(li);
 }
 for(const q of queue){
  const li=document.createElement("li");
  li.textContent=q.formCode+" · "+q.capture_id.slice(0,8)+" · "+
    ({queued:"Pendiente",syncing:"Sincronizando",retry_wait:"Reintento pendiente",
      synced:"Registrado en Calidad",synced_warning:"Registrado con advertencia",
      requires_review:"Requiere revisión",conflict:"Conflicto"} as Record<string,string>)[q.state];
  list.appendChild(li);
 }
 if(!list.childElementCount)list.textContent="No existen borradores ni capturas pendientes en este dispositivo.";
}
function drawFields(pkg:VerifiedQualityDefinition){
 const container=el("fields");container.replaceChildren();
 for(const field of fieldsFor(pkg)){
  const label=document.createElement("label");
  label.textContent=field.label+(field.required?" *":"");
  let control:HTMLInputElement|HTMLSelectElement;
  if(field.options.length){
   const select=document.createElement("select");const empty=document.createElement("option");
   empty.value="";empty.textContent="Seleccione";select.appendChild(empty);
   for(const option of field.options){const el=document.createElement("option");
    el.value=option.option_key;el.textContent=option.label;select.appendChild(el);}
   control=select;
  }else{
   const input=document.createElement("input");
   input.type=field.value_type==="boolean"?"checkbox":
    field.value_type==="date"?"date":field.value_type==="time"?"time":"text";
   control=input;
  }
  control.dataset.field=field.key;
  if(control instanceof HTMLInputElement&&control.type==="checkbox"){
   control.checked=values[field.key]===true;
  }else control.value=String(values[field.key]??"");
  control.addEventListener("input",()=>{
   values[field.key]=control instanceof HTMLInputElement&&control.type==="checkbox"?
    control.checked:control.value;
   activeEditor?.onFieldEdited();
  });
  label.appendChild(control);container.appendChild(label);
 }
}
async function createEditor(pkg:VerifiedQualityDefinition,draftId:string,bobbin?:BobbinContext,
  oldRevision:number|null=null,oldValues:Record<string,string|boolean>={},requiredSnapshot?:string){
 const ctx=requireUnlocked();
 activeEditor?.stop();
 activeDraftId=draftId;revision=oldRevision;values={...oldValues};
 const authority=requiredSnapshot
  ? await readCaptureAuthority(ctx.key,ctx.identity,target(pkg,requiredSnapshot),ctx.readiness.trustedPublicKey)
  : await signedFor(pkg);
 const snapshot=authority.payload.snapshot_id;
 const form={
  draftId,machineCode:pkg.envelope.payload.machine_code,
  formCode:pkg.envelope.payload.form_code,formVersion:pkg.envelope.payload.form_version,
  captureScopeSnapshotId:snapshot,
  ...(bobbin?{bobbin:{bobbin_id:bobbin.bobbin_id,context_digest:bobbin.context_digest}}:{}),
 };
 activeEditor=await createOperationalQualityEditor({
  key:ctx.key,identity:ctx.identity,store,definition:pkg,form,
  assertCaptureScope:async()=>{await readCaptureAuthority(ctx.key,ctx.identity,target(pkg,snapshot),ctx.readiness.trustedPublicKey);},
  ui:{
   current:()=>({draftId,ownerId:ctx.identity.ownerId,revision,values:{...values}}),
   unlocked:()=>key!==null,
   setEditorLocked:locked=>{
    el<HTMLButtonElement>("capture-save").disabled=locked;
   },
   setTimer:(cb,ms)=>window.setTimeout(cb,ms),
   clearTimer:id=>window.clearTimeout(id as number),
   onDraftSaved:v=>{revision=v;},
   onDraftError:()=>message("No se pudo guardar el borrador. Verifique el almacenamiento local."),
   onCaptureBlocked:r=>message("Captura no confirmada: "+r),
   notifySync:()=>syncRuntime?.notifyReady(),
  },
 });
 el("editor-title").textContent=pkg.envelope.payload.definition.form_name+" · "+pkg.envelope.payload.machine_code;
 drawFields(pkg);show("workspace",false);show("editor",true);
}
async function openExisting(id:string){
 const ctx=requireUnlocked(),draft=await store.getDraft(id);
 if(!draft||draft.frozenBy)throw Error("Borrador no editable");
 const pkg=packages.find(p=>p.envelope.payload.form_code===draft.formCode&&
   p.envelope.payload.machine_code===draft.machineCode&&p.envelope.payload.form_version===draft.formVersion);
 if(!pkg)throw Error("La definición del borrador no está disponible");
 const opened=await openLocalDraft(ctx.key,{
  ...ctx.identity,id:draft.id,contextId:draft.scopeSnapshotId,
  formCode:draft.formCode,formVersion:draft.formVersion,
 },draft.sealed);
 const original:Record<string,string|boolean>={};
 for(const [k,v] of Object.entries(opened)){
  if(typeof v!=="string"&&typeof v!=="boolean")throw Error("Borrador corrupto");
  original[k]=v;
 }
 // A historical draft can only be resumed with its OWN snapshot; do not
 // silently substitute a newer signed CAPTURE grant.
 let bobbin:BobbinContext|undefined;
 if(BOBBIN_QUALITY_FORMS.has(draft.formCode)){
  const candidates=await listBobbinContexts(ctx.key,ctx.identity,
    ctx.readiness.envelope.payload.snapshot_id,draft.machineCode);
  for(const candidate of candidates.contexts){
   if(await bobbinContextVersion(draft.scopeSnapshotId,
     candidate.bobbin_id,candidate.context_digest)===draft.contextVersion){
     bobbin=candidate;break;
   }
  }
  if(!bobbin)throw Error("No se encuentra el contexto histórico cifrado de esta bobina");
 }
 await createEditor(pkg,id,bobbin,draft.revision,original,draft.scopeSnapshotId);
}
async function newDraft(){
 const pkg=packages[Number(el<HTMLSelectElement>("form").value)];
 if(!pkg)throw Error("No hay formularios preparados");
 const bobbin=await getBobbin(pkg);
 await createEditor(pkg,crypto.randomUUID(),bobbin);
}
async function enroll(machine:string,passphrase:string|null){
 if(!MACHINE.test(machine))throw Error("Máquina inválida");
 const current=await onlineUser();
 if(!current||!current.permissions.includes("quality.capture")||current.must_change)
  throw Error("Se requiere sesión online con permiso de Calidad");
 const identityNow={ownerId:current.id.toLowerCase(),deviceKey:getDeviceKey().toLowerCase()};
 let profile=await readLocalProfile();
 if(!profile){
  if(passphrase===null)throw Error("Configure una frase local para activar el modo sin conexión en este celular");
  profile=(await createLocalVault(identityNow,passphrase)).record;await storeLocalProfile(profile);
 }
 if(profile.ownerId!==identityNow.ownerId||profile.deviceKey!==identityNow.deviceKey)
  throw Error("Dispositivo registrado para otro usuario");
 const opened=passphrase===null&&key&&identity?.ownerId===identityNow.ownerId&&identity.deviceKey===identityNow.deviceKey
  ?key:passphrase!==null?await unlockLocalVault(profile,passphrase):null;
 if(!opened)throw Error("Desbloquee los datos locales para actualizar formularios");
 const readinessResponse=await api("POST","/api/offline/scope",{
  device_key:identityNow.deviceKey,machine_codes:[machine],
 });
 if(readinessResponse.status!==200)throw Error("No se pudo emitir el alcance de lectura");
 const envelope=readinessResponse.json as {public_key_b64url:string;payload?:{form_scopes?:Array<{machine_code:string;form_code:string}>}};
 const existingScope=await readRawScope(identityNow);
 let count=0;
 if(existingScope){
  // OFF-03C.4: never overwrite a signed scope while encrypted packages
  // still refer to its old snapshot. Renew both in ONE IndexedDB transaction.
  const extras=(envelope.payload?.form_scopes??[])
   .filter(p=>p.machine_code===machine&&FORM.test(p.form_code))
   .map(p=>({machine_code:p.machine_code,form_code:p.form_code}));
  const renewed=await renewOfflineBundle(opened,identityNow,{
   fetchScope:async()=>envelope,
   fetchPackage:async(machineCode,formCode,scope)=>{
    const result=await api("POST","/api/offline/quality-package",{
     device_key:identityNow.deviceKey,machine_code:machineCode,
     form_code:formCode,signed_scope:scope,
    });
    if(result.status!==200)throw Object.assign(Error("No se pudo renovar "+formCode),{status:result.status});
    return result.json;
   },
  },{machineCodes:[machine],extraPairs:extras});
  count=renewed.renewedPackages.filter(p=>p.machine_code===machine).length;
 }else{
  await storeOfflineScope(opened,identityNow,envelope,envelope.public_key_b64url);
  // New device: signed scope must be persisted before individual packages.
  const firstScope=await readOfflineScope(opened,identityNow);
  if(!firstScope)throw Error("Alcance firmado inválido");
  for(const pair of firstScope.envelope.payload.form_scopes){
   if(pair.machine_code!==machine||!FORM.test(pair.form_code))continue;
   const result=await api("POST","/api/offline/quality-package",{
    device_key:identityNow.deviceKey,machine_code:machine,
    form_code:pair.form_code,signed_scope:firstScope.envelope,
   });
   if(result.status!==200)throw Error("No se pudo preparar "+pair.form_code);
   await storeQualityPackage(opened,identityNow,result.json);count++;
  }
 }
 const verifiedReadiness=await readOfflineScope(opened,identityNow);
 if(!verifiedReadiness)throw Error("Alcance firmado inválido");
 const captureResponse=await api("POST","/api/offline/capture-scope",{
  device_key:identityNow.deviceKey,machine_codes:[machine],
 });
 if(captureResponse.status!==200)throw Error("No se pudo emitir CAPTURE para este usuario");
 const signed=captureResponse.json as CaptureScopeEnvelope;
 if(!signed||signed.public_key_b64url!==verifiedReadiness.trustedPublicKey)
  throw Error("Firma CAPTURE incompatible con la firma de confianza");
 const first=signed.payload?.form_scopes.find(p=>p.machine_code===machine&&FORM.test(p.form_code));
 if(!first)throw Error("No hay formularios de Calidad autorizados");
 await storeCaptureAuthority(opened,identityNow,signed,verifiedReadiness.trustedPublicKey,{
  scopeSnapshotId:signed.payload.snapshot_id,machineCode:first.machine_code,
  formCode:first.form_code,formVersion:first.form_version,
 });
 if(!count)throw Error("No se encontró ningún formulario publicado");
 user=current;key=opened;identity=identityNow;readiness=verifiedReadiness;issuer=signed;
 await loadPackages();startSync();show("prepare-panel",false);show("unlock-panel",false);
 show("workspace",true);await refreshDrafts();
 await offlineReadyStatus();
}
const RENEWAL_TEXT:Record<string,string>={
 rollback_scope:"El servidor devolvió un alcance anterior al guardado en este celular (OFFLINE_RENEWAL_ROLLBACK_SCOPE). No se cambió nada.",
 rollback_package:"Un formulario descargado no puede reemplazar al guardado con la misma versión (OFFLINE_RENEWAL_ROLLBACK_PACKAGE). No se cambió nada; avise a soporte.",
 auth:"Su sesión expiró. Inicie sesión de nuevo.",network:"Sin conexión segura con el servidor.",
 revoked:"El servidor ya no concede este acceso.",revoked_unrecorded:"El servidor ya no concede este acceso.",
 identity_mismatch:"El perfil de este celular pertenece a otro usuario o dispositivo.",pin_mismatch:"La clave de firma del servidor no coincide con la guardada.",
};
function renewalText(e:unknown):string{
 if(e instanceof RenewalError)return RENEWAL_TEXT[e.reason]??("No se pudo actualizar ("+e.message+").");
 return e instanceof Error?e.message:"Reintente la actualización.";
}
let preparationBusy=false;
async function offlineReadyStatus(){
 const ctx=requireUnlocked();
 const allowed=ctx.readiness.envelope.payload.form_scopes
  .filter(p=>FORM.test(p.form_code)&&
    (MACHINE_QUALITY_FORMS.has(p.form_code)||BOBBIN_QUALITY_FORMS.has(p.form_code)));
 let valid=0;
 for(const pkg of packages){
  try{await signedFor(pkg);valid++;}catch{/* A downloaded form without CAPTURE is not offline-ready. */}
 }
 const expected=allowed.length;
 if(expected>0&&valid===expected){
  message("Formularios disponibles sin conexión ("+valid+" de "+expected+").");
  show("offline-retry",false);
 }else{
  message("No se descargaron todos los formularios. Vaya a una zona con internet. "+
   valid+" de "+expected+" disponibles para captura offline.");
  show("offline-retry",true);
 }
}
async function autoPrepare(){
 if(!navigator.onLine){
  message("No se descargaron todos los formularios. Vaya a una zona con internet.");
  show("offline-retry",true);return;
 }
 if(preparationBusy||!user||!key||!identity||identity.ownerId!==user.id.toLowerCase())return;
 preparationBusy=true;
 show("offline-retry",false);
 message("Actualizando formularios y permisos…");
 try{await enroll(el<HTMLInputElement>("machine").value.trim(),null);}
 catch(e){
  // Keep the encrypted local set; no silent deletion or permission escalation.
  message("No se descargaron todos los formularios. "+renewalText(e));
  show("offline-retry",true);
 }finally{preparationBusy=false;}
}
async function unlock(passphrase:string){
 const profile=await readLocalProfile();
 if(!profile)throw Error("Este dispositivo no ha sido preparado");
 const localKey=await unlockLocalVault(profile,passphrase);
 const id={ownerId:profile.ownerId,deviceKey:profile.deviceKey};
 const scope=await readOfflineScope(localKey,id);
 if(!scope)throw Error("No hay alcance firmado");
 const device=getDeviceKey();
 if(device.toLowerCase()!==id.deviceKey.toLowerCase())throw Error("Dispositivo distinto");
 key=localKey;identity=id;readiness=scope;
 await loadPackages();startSync();await refreshDrafts();
 // A legacy readiness profile may contain forms but no CAPTURE authority.
 // Unlocking must not hide the online login and renewal route.
 const missingAuthority=await Promise.all(packages.map(async pkg=>{
  try{await signedFor(pkg);return false;}catch{return true;}
 })).then(states=>states.some(Boolean));
 show("login-panel",!user);show("prepare-panel",!!user&&!key);show("unlock-panel",false);
 show("workspace",true);el("owner").textContent="Capturas del usuario: "+id.ownerId.slice(0,8);
 await offlineReadyStatus();
 // The unlock handler starts renewal once, avoiding duplicate issuance.
}
async function lock(){
 try{await activeEditor?.flushDraft();}catch{
  message("No se pudo guardar el borrador. No se ha bloqueado todavía.");return;
 }
 activeEditor?.stop();activeEditor=null;activeDraftId=null;
 syncRuntime?.stop();syncRuntime=null;key=null;identity=null;readiness=null;issuer=null;
 packages=[];values={};revision=null;
 show("editor",false);show("workspace",false);show("unlock-panel",true);
 message("Protección local activada. Los pendientes cifrados se conservan.");
}
function report(e:unknown){
 message(e instanceof Error?e.message:"Operación no disponible");
}
async function start(){
 assertOrigin();
 if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
 // Only PUBLIC static shell files, never authenticated pages, API responses,
 // CAPTURE scopes or field values. Ensures offline reload after the FIRST visit.
 if(navigator.onLine&&"caches" in window){
  void caches.open("vinto-off048-quality-static-v5")
   .then(cache=>cache.addAll(["/offline-calidad.html","/offline-calidad.js"]))
   .catch(()=>message("La pantalla todavía no está disponible sin conexión; vuelva a abrirla online."));
 }
 const profile=await readLocalProfile().catch(()=>null);
 show("unlock-panel",!!profile);
 user=await onlineUser();
 show("login-panel",!user);
 show("prepare-panel",!!user&&!profile);
 if(user)el("identity").textContent="Usuario: "+user.display_name;
 el<HTMLFormElement>("login").addEventListener("submit",event=>{
  event.preventDefault();
  const username=el<HTMLInputElement>("username").value;
  const password=el<HTMLInputElement>("password").value;
  el<HTMLInputElement>("password").value="";
  void (async()=>{
   const r=await api("POST","/api/auth/login",{username,password});
   const answer=interpretLogin(r.status,r.json);
   if(answer.status!=="ok")throw Error("No se pudo iniciar sesión");
   user=answer.user;show("login-panel",false);
   const storedProfile=await readLocalProfile();
   show("prepare-panel",!storedProfile);show("unlock-panel",!!storedProfile&&!key);
   el("identity").textContent="Usuario: "+user.display_name;
   if(key)await autoPrepare();
  })().catch(report);
 });
 el<HTMLFormElement>("prepare").addEventListener("submit",event=>{
  event.preventDefault();const machine=el<HTMLInputElement>("machine").value.trim();
  const passphrase=el<HTMLInputElement>("passphrase").value;
  el<HTMLInputElement>("passphrase").value="";
  void enroll(machine,passphrase).catch(report);
 });
 el<HTMLFormElement>("unlock").addEventListener("submit",event=>{
  event.preventDefault();const pass=el<HTMLInputElement>("unlock-secret").value;
  el<HTMLInputElement>("unlock-secret").value="";
  void unlock(pass).then(()=>autoPrepare()).catch(report);
 });
 el<HTMLSelectElement>("form").addEventListener("change",()=>{void refreshBobbins().catch(report);});
 el<HTMLFormElement>("prepare-bobbin").addEventListener("submit",event=>{
  event.preventDefault();
  const code=el<HTMLInputElement>("bobbin-code").value.trim();
  void prepareBobbin(code).then(()=>message("Bobina preparada y cifrada")).catch(report);
 });
 el("offline-retry").addEventListener("click",()=>{void autoPrepare().catch(report);});
 window.addEventListener("online",()=>{if(key&&user)void autoPrepare().catch(report);});
 el("new").addEventListener("click",()=>{void newDraft().catch(report);});
 el("sync").addEventListener("click",()=>{
  void syncRuntime?.syncOnce().then(async result=>{
   el("sync-status").textContent=result?.paused?"Pausado: "+result.paused:"Sincronización comprobada";
   await refreshDrafts();
  }).catch(report);
 });
 el("lock").addEventListener("click",()=>{void lock().catch(report);});
 el<HTMLFormElement>("capture").addEventListener("submit",event=>{
  event.preventDefault();
  void (async()=>{
   if(!activeEditor)throw Error("Editor bloqueado");
   const result=await activeEditor.onGuardarCaptura();
   if(result.status!=="queued")throw Error("Captura no confirmada: "+result.reason);
   activeEditor=null;activeDraftId=null;
   show("editor",false);show("workspace",true);
   await refreshDrafts();
   message("Captura guardada cifrada. Se registrará al recuperar internet y su sesión.");
  })().catch(report);
 });
 el("back").addEventListener("click",()=>{
  void (async()=>{
   await activeEditor?.flushDraft();
   activeEditor?.stop();activeEditor=null;activeDraftId=null;
   show("editor",false);show("workspace",true);
   await refreshDrafts();
  })().catch(report);
 });
 if(profile)message("Dispositivo preparado. Desbloquee sus datos locales para continuar.");
 else message("Inicie sesión para preparar Calidad offline.");
}
void start().catch(report);
