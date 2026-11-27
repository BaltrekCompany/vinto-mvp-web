"use client";

/** FOFF-03: offline recovery and dynamic Conversion form editor.
 * This screen never forges operational context: every editable field comes
 * from a locally encrypted, signed, server-published reference package.
 * Local passphrase is not a backend login and cannot grant a server write.
 */
import {useCallback,useEffect,useRef,useState} from "react";
import {Button} from "@/components/ui/button";
import {getDeviceKey} from "@/lib/vinto/device";
import {unlockLocalVault,type OfflineVaultIdentity} from "@/lib/vinto/offline-vault";
import {listConversionOfflineProfiles,type ConversionOfflineProfile} from "@/lib/vinto/foff-conversion-profile";
import {listProductionPreparations,readProductionPreparation,type ProductionPreparationRecord}
  from "@/lib/vinto/foff-production-preparation-store";
import {verifyConversionPreparation,verifyConversionReferencePackage,
  type VerifiedConversionPreparation} from "@/lib/vinto/foff-conversion-preparation-verify";
import {verifyConversionCaptureAuthority,type VerifiedConversionCapture}
  from "@/lib/vinto/foff-conversion-capture-authority-verify";
import {parseConversionDefinition,emptyConversionValues,normalizeConversionValues,
  type ConversionDefinition,type ConversionField}
  from "@/lib/vinto/foff-conversion-form-schema";
import {loadConversionDraft,readConversionDraft,saveConversionDraft,
  type ConversionDraftRow} from "@/lib/vinto/foff-conversion-draft-store";
import {enqueueConversionCapture,listConversionQueue,type ConversionQueueRow}
  from "@/lib/vinto/foff-conversion-local-queue";
import {syncConversionPending} from "@/lib/vinto/foff-conversion-sync";

type R=Record<string,unknown>;
const object=(v:unknown):v is R=>Boolean(v&&typeof v==="object"&&!Array.isArray(v));
const errorText=(e:unknown)=>e instanceof Error?e.message:"Error inesperado";
const title=(value:string)=>value.replace(/_/g," ").replace(/\b\w/g,v=>v.toUpperCase());
type OpenForm=Readonly<{
  row:ProductionPreparationRecord;key:CryptoKey;identity:OfflineVaultIdentity;
  preparation:VerifiedConversionPreparation;capture:VerifiedConversionCapture;
  definition:ConversionDefinition;references:R;envelope:R;authority:R;
}>;
type Props=Readonly<{online:boolean;onExit:()=>void;currentUserId?:string|null}>;

function Field({field,value,onChange}:{
  field:ConversionField;value:unknown;onChange:(value:string)=>void;
}){
  const label=`${title(field.key)}${field.required?" *":""}${field.unit?" ("+field.unit+")":""}`;
  const common={className:"mt-1 w-full rounded border border-slate-300 bg-white p-2 text-slate-900",
    value:value===undefined||value===null?"":String(value),onChange:(e:React.ChangeEvent<HTMLInputElement>)=>onChange(e.target.value)};
  return <label className="block text-sm font-medium text-slate-800">{label}
    {field.options.length>0
      ? <select className={common.className} value={common.value}
          onChange={e=>onChange(e.target.value)}>
          <option value="">Seleccionar…</option>
          {field.options.map(option=><option key={option} value={option}>{option}</option>)}
        </select>
      : field.value_type==="boolean"
        ? <select className={common.className} value={common.value}
            onChange={e=>onChange(e.target.value)}>
            <option value="">Seleccionar…</option>
            <option value="true">Sí</option><option value="false">No</option>
          </select>
        : <input {...common} type={field.value_type==="date"?"date":
          field.value_type==="time"?"time":"text"}
          inputMode={field.value_type==="decimal"?"decimal":
            field.value_type==="integer"?"numeric":"text"} />}
  </label>;
}

function EditForm({opened,online}:Readonly<{opened:OpenForm;online:boolean}>){
  const {row,identity,key,definition,preparation,capture,references,envelope,authority}=opened;
  const [draft,setDraft]=useState<R>(()=>emptyConversionValues(definition));
  const [revision,setRevision]=useState(0);
  const [captureId,setCaptureId]=useState(()=>crypto.randomUUID());
  const [initializing,setInitializing]=useState(true);
  const [dirty,setDirty]=useState(false);
  const [message,setMessage]=useState("");
  const [saving,setSaving]=useState(false);
  const [queue,setQueue]=useState<ConversionQueueRow[]>([]);
  const revisionRef=useRef(0);
  const savedRef=useRef<ConversionDraftRow|null>(null);
  const mutex=useRef<Promise<unknown>>(Promise.resolve());
  const valuesRef=useRef<R>(draft);
  const reloadQueue=useCallback(async()=>{
    setQueue(await listConversionQueue(identity));
  },[identity]);
  useEffect(()=>{
    let cancelled=false;
    (async()=>{
      const saved=await loadConversionDraft(identity,row.id);
      const data=saved?await readConversionDraft(identity,key,saved):emptyConversionValues(definition);
      if(cancelled)return;
      if(saved){savedRef.current=saved;revisionRef.current=saved.revision;
        setRevision(saved.revision);setCaptureId(saved.captureId);}
      valuesRef.current=data;setDraft(data);setInitializing(false);
      await reloadQueue();
    })().catch(e=>{if(!cancelled){setMessage("No se pudo abrir el borrador cifrado: "+errorText(e));}});
    return()=>{cancelled=true;};
  },[identity,key,row.id,definition,reloadQueue]);

  const update=(next:R)=>{
    valuesRef.current=next;setDraft(next);setDirty(true);setMessage("");
  };
  const save=useCallback(async(values:R)=>{
    const op=mutex.current.then(async()=>{
      const prior=savedRef.current;
      const saved=await saveConversionDraft({
        identity,key,preparationId:row.id,assignmentId:row.assignmentId,
        machineCode:row.machineCode,formCode:row.formCode,formVersion:row.formVersion,
        captureId,expectedRevision:prior?.revision??0,values,
      });
      savedRef.current=saved;revisionRef.current=saved.revision;
      setRevision(saved.revision);
      return saved;
    });
    mutex.current=op.catch(()=>undefined);
    return op;
  },[identity,key,row.id,row.assignmentId,row.machineCode,row.formCode,row.formVersion,captureId]);
  useEffect(()=>{
    if(!dirty||initializing)return;
    const timer=setTimeout(()=>{
      setSaving(true);
      const latest=valuesRef.current;
      void save(latest).then(()=>{
        if(valuesRef.current===latest){setDirty(false);setMessage("Borrador cifrado guardado.");}
      }).catch(e=>setMessage("Autoguardado detenido: "+errorText(e)))
        .finally(()=>setSaving(false));
    },700);
    return()=>clearTimeout(timer);
  },[draft,dirty,initializing,save]);

  const groupValues=object(draft._groups)?draft._groups:{};
  const editGroup=(code:string,rows:unknown[])=>update({...draft,_groups:{...groupValues,[code]:rows}});
  const queueCurrent=async()=>{
    if(initializing||saving)return;
    try{
      if(Date.now()>=Date.parse(preparation.expiresAt)||Date.now()>=Date.parse(capture.expiresAt))
        throw new Error("La autorización expiró; prepara nuevamente online antes de crear otra captura.");
      const normalized=normalizeConversionValues(definition,valuesRef.current);
      await save(valuesRef.current);
      await enqueueConversionCapture({
        identity,key,captureId,preparation,captureAuthority:capture,
        formCode:row.formCode,formVersion:row.formVersion,machineCode:row.machineCode,
        assignmentId:row.assignmentId,values:normalized,
        preparationEnvelope:envelope,authorityEnvelope:authority,referencePackage:references,
      });
      setDirty(false);setMessage("Captura cifrada puesta en cola. Pendiente de confirmación del servidor.");
      await reloadQueue();
    }catch(e){setMessage("No se pudo poner en cola: "+errorText(e));}
  };
  const sync=async(item:ConversionQueueRow)=>{
    if(!online){setMessage("Sin Internet: la cola permanece cifrada en este dispositivo.");return;}
    setSaving(true);
    try{
      const result=await syncConversionPending(identity,key,item);
      setMessage(result.message);await reloadQueue();
    }catch(e){setMessage("No hay confirmación: "+errorText(e));}
    finally{setSaving(false);}
  };
  const pending=queue.filter(item=>item.scopeSnapshotId===row.scopeSnapshotId&&item.formCode===row.formCode);
  const alreadyQueued=pending.some(x=>x.captureId===captureId);
  const setSimple=(field:string,value:string)=>update({...draft,[field]:value});
  return <section className="space-y-4 rounded-xl border bg-white p-4" data-foff-conversion="editor">
    <h3 className="font-semibold">Formulario {row.formCode} · versión {row.formVersion}</h3>
    <p className="text-sm text-slate-600">Máquina {row.machineCode} · asignación {row.assignmentId}.
      Los valores quedan cifrados localmente. El servidor validará los datos al sincronizar.</p>
    {initializing?<p role="status">Abriendo borrador cifrado…</p>:<>
      <div className="grid gap-3 sm:grid-cols-2">
        {definition.fields.filter(f=>f.group_id===null).map(f=>
          <Field key={f.key} field={f} value={draft[f.key]} onChange={v=>setSimple(f.key,v)}/>)}
      </div>
      {definition.groups.map(g=>{
        const fields=definition.fields.filter(f=>f.group_id===g.id);
        const raw=groupValues[g.code];
        const rows=Array.isArray(raw)?raw.filter(object):[];
        return <div key={g.id} className="space-y-2 border-t pt-3">
          <h4 className="font-medium">{title(g.code)} · {rows.length} filas</h4>
          {rows.map((line,i)=><div key={i} className="rounded border p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              {fields.map(f=><Field key={f.key} field={f} value={line[f.key]}
                onChange={v=>editGroup(g.code,rows.map((r,j)=>i===j?{...r,[f.key]:v}:r))}/>)}
            </div>
            <Button size="sm" variant="outline" onClick={()=>editGroup(g.code,rows.filter((_,j)=>j!==i))}>
              Retirar fila
            </Button>
          </div>)}
          {(g.max_rows===null||rows.length<g.max_rows)&&
            <Button variant="outline" size="sm" onClick={()=>editGroup(g.code,[...rows,{}])}>Añadir fila</Button>}
        </div>;
      })}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={saving} onClick={()=>void save(valuesRef.current)
          .then(()=>{setDirty(false);setMessage("Borrador cifrado guardado.");})
          .catch(e=>setMessage(errorText(e)))}>Guardar borrador</Button>
        <Button disabled={saving||alreadyQueued} onClick={()=>void queueCurrent()}>
          {alreadyQueued?"Captura en cola":"Guardar captura pendiente de sincronización"}
        </Button>
      </div>
      <p className="text-xs text-slate-600">Autoguardado: {saving?"guardando…":
        dirty?"cambios pendientes":"guardado"} · revisión local {revision}</p>
    </>}
    {pending.map(item=><div key={item.captureId} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm">
      <span>Captura {item.captureId.slice(0,8)} · {item.state==="queued"?"Pendiente":
        item.state==="synced"?"Registrada":"Requiere revisión"}</span>
      {item.state==="queued"&&<Button size="sm" variant="outline"
        disabled={!online||saving} onClick={()=>void sync(item)}>Sincronizar</Button>}
    </div>)}
    <p role="status" className="text-sm text-amber-950">{message}</p>
  </section>;
}

export function ConversionOfflineWorkspace({online,onExit,currentUserId}:Props){
  const [profiles,setProfiles]=useState<ConversionOfflineProfile[]>([]);
  const [choice,setChoice]=useState("");
  const [passphrase,setPassphrase]=useState("");
  const [opened,setOpened]=useState<OpenForm|null>(null);
  const [preparations,setPreparations]=useState<ProductionPreparationRecord[]>([]);
  const [key,setKey]=useState<CryptoKey|null>(null);
  const [identity,setIdentity]=useState<OfflineVaultIdentity|null>(null);
  const [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    let active=true;
    listConversionOfflineProfiles(getDeviceKey().toLowerCase())
      .then(items=>{if(active)setProfiles(currentUserId?items.filter(p=>p.ownerId===currentUserId.toLowerCase()):items);})
      .catch(e=>{if(active)setMessage("Sin perfiles disponibles: "+errorText(e));});
    return()=>{active=false;};
  },[currentUserId]);
  const selected=profiles.find(profile=>profile.id===choice)??profiles[0];
  const unlock=async()=>{
    if(!selected||busy)return;
    setBusy(true);setMessage("");
    try{
      const vaultKey=await unlockLocalVault(selected.vaultRecord,passphrase);
      const owner={ownerId:selected.ownerId,deviceKey:selected.deviceKey};
      const items=await listProductionPreparations(owner);
      setIdentity(owner);setKey(vaultKey);setPreparations(items.filter(p=>p.sectorCode==="CONVERSION"));
      setPassphrase("");
    }catch(e){setMessage("No se pudo abrir el perfil cifrado: "+errorText(e));}
    finally{setBusy(false);}
  };
  const open=async(row:ProductionPreparationRecord)=>{
    if(!identity||!key||!selected)return;
    setBusy(true);setMessage("");
    try{
      const data=await readProductionPreparation(identity,key,row);
      const refs=data.referenceData;
      const refPackage=refs.referencePackage,prep=refs.preparationEnvelope,authority=refs.captureAuthority;
      if(!object(refPackage)||!object(prep)||!object(authority))throw new Error("Paquete firmado incompleto.");
      const validated=await verifyConversionPreparation(prep,selected.preparationPin,{
        ownerId:identity.ownerId,deviceKey:identity.deviceKey,
        assignmentId:row.assignmentId,machineCode:row.machineCode,
        formCode:row.formCode,formVersion:row.formVersion,
      },Date.now());
      await verifyConversionReferencePackage(refPackage,validated);
      const capture=await verifyConversionCaptureAuthority(authority,selected.capturePin,{
        ownerId:identity.ownerId,deviceKey:identity.deviceKey,
        assignmentId:row.assignmentId,machineCode:row.machineCode,
        formCode:row.formCode,formVersion:row.formVersion,scopeSnapshotId:row.scopeSnapshotId,
      },validated,Date.now());
      if(validated.context.context_digest!==row.contextDigest||
         validated.snapshotId!==row.scopeSnapshotId)throw new Error("Contexto original no coincide.");
      const definition=parseConversionDefinition(data.formDefinition);
      setOpened({row,key,identity,preparation:validated,capture,definition,
        references:refPackage,envelope:prep,authority});
    }catch(e){setMessage("No se puede habilitar esta preparación: "+errorText(e));}
    finally{setBusy(false);}
  };
  return <main className="mx-auto max-w-4xl space-y-5 p-4" data-foff-conversion="workspace">
    <header className="flex items-center justify-between gap-3">
      <div><h2 className="text-xl font-bold">Conversión Offline</h2>
        <p className="text-sm text-slate-600">Preparaciones firmadas por VINTO en este dispositivo.</p></div>
      <Button variant="outline" onClick={onExit}>Volver</Button>
    </header>
    {!key?<section className="space-y-3 rounded-xl border bg-white p-4">
      <label className="block text-sm">Perfil preparado
        <select className="mt-1 w-full rounded border p-2" value={selected?.id??""}
          onChange={e=>setChoice(e.target.value)}>
          {profiles.map(p=><option key={p.id} value={p.id}>{p.displayName} · {p.ownerId.slice(0,8)}</option>)}
        </select>
      </label>
      <label className="block text-sm">Clave local de Operación
        <input type="password" autoComplete="off" className="mt-1 w-full rounded border p-2"
          value={passphrase} onChange={e=>setPassphrase(e.target.value)}/>
      </label>
      <Button disabled={!selected||!passphrase||busy} onClick={()=>void unlock()}>Abrir preparaciones cifradas</Button>
    </section>:<>
      <section className="space-y-2 rounded-xl border bg-white p-4">
        <h3 className="font-semibold">Formularios preparados ({preparations.length})</h3>
        <div className="flex flex-wrap gap-2">
          {preparations.map(row=><Button key={row.id} variant="outline" disabled={busy}
            onClick={()=>void open(row)}>{row.machineCode} · {row.formCode} v{row.formVersion}</Button>)}
        </div>
      </section>
      {opened&&<EditForm key={opened.row.id} opened={opened} online={online}/>}
    </>}
    {!online&&<p className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
      Sin Internet: los borradores permanecen cifrados. Se requiere iniciar sesión online para sincronizar.
    </p>}
    {message&&<p role="status" className="text-sm text-amber-900">{message}</p>}
  </main>;
}
