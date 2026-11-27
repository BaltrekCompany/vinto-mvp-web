"use client";

/** Conversion preparation appears only under the original server-verified
 * machine execution context. It never replaces the online capture screens.
 * No offline editor is mounted until its complete QA gate is satisfied.
 */
import {useState} from "react";
import {Button} from "@/components/ui/button";
import {prepareConversionForm} from "@/lib/vinto/foff-conversion-prepare";

type Offer=Readonly<{code:string;name:string;version:number}>;
type Props=Readonly<{assignmentId:string;machineCode:string;offers:readonly Offer[]}>;
const supported=new Set(["VINTO-P1-11","VINTO-P1-12","VINTO-P1-13","VINTO-P1-16"]);
export function ConversionOfflinePreparation({assignmentId,machineCode,offers}:Props){
  const permitted=offers.filter(o=>supported.has(o.code));
  const [formCode,setFormCode]=useState("");
  const [passphrase,setPassphrase]=useState("");
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const selected=permitted.find(o=>o.code===formCode)??permitted[0];
  if(permitted.length===0)return null;
  const prepare=async()=>{
    if(!selected||busy)return;
    setBusy(true);setMessage("");
    try{
      const saved=await prepareConversionForm({
        assignmentId,machineCode,formCode:selected.code,formVersion:selected.version,
        localPassphrase:passphrase,
      });
      setMessage(`Preparación cifrada almacenada en este dispositivo: ${saved.formCode}. La captura offline todavía está en validación.`);
    }catch(error){
      const detail=error instanceof Error?error.message:"";
      setMessage(detail.includes("not_enabled")||detail.includes("capture_not_enabled")?
        "Conversión Offline aún no está activada en el servidor. Los formularios online siguen disponibles.":
        detail.includes("login")||detail.includes("authorized")?
        "Debes volver a iniciar sesión con un usuario autorizado.":
        detail.includes("pin_rotation")?
        "La firma del servidor cambió. Se requiere un nuevo enrolamiento supervisado.":
        detail.includes("weak_passphrase")?
        "La clave local debe ser más larga y diversa (mínimo 16 caracteres).":
        "No se pudo preparar de forma segura. No se guardó una captura operativa.");
    }finally{
      setBusy(false);
      setPassphrase("");
    }
  };
  return <section data-foff-conversion="preparation" className="mt-4 space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
    <h3 className="font-semibold text-slate-900">Preparación de Conversión sin conexión</h3>
    <p className="text-sm text-slate-700">Usa únicamente la OT y línea iniciadas por Supervisión. Esta preparación no envía registros ni sustituye las fichas actuales.</p>
    <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
      <label className="flex-1 text-sm font-medium text-slate-800">Formulario
        <select className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2" value={selected?.code??""}
          onChange={e=>setFormCode(e.target.value)}>
          {permitted.map(o=><option key={o.code} value={o.code}>{o.name} · v{o.version}</option>)}
        </select>
      </label>
      <label className="flex-1 text-sm font-medium text-slate-800">Clave local de Operación
        <input className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2" type="password"
          autoComplete="off" value={passphrase} onChange={e=>setPassphrase(e.target.value)}
          placeholder="Clave local de este dispositivo" />
      </label>
      <Button type="button" disabled={busy||passphrase.length<16} onClick={()=>void prepare()}>
        {busy?"Verificando...":"Preparar en este dispositivo"}
      </Button>
    </div>
    <p role="status" className="text-sm text-amber-950">{message||"Preparación disponible solo con Internet y autorización vigente. El modo de captura offline sigue desactivado."}</p>
  </section>;
}
