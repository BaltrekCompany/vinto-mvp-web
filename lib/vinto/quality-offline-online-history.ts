/** Only authenticated server history can establish an already completed
 * form on another device or via VINTO Online. We never download/edit values.
 * The backend's 409 rule remains authoritative if this GET fails or is stale.
 */
import {apiBaseUrl} from "./api";
export type BobbinFormIdentity=Readonly<{bobbinId:string;formCode:string}>;
export function onlineCompletionKey(bobbinId:string,formCode:string):string{
 return bobbinId+"|"+formCode;
}
export async function listCompletedBobbinForms(
 bobbinIds:readonly string[],
):Promise<ReadonlySet<string>>{
 const out=new Set<string>();
 for(const id of new Set(bobbinIds)){
  const response=await fetch(
   apiBaseUrl()+"/api/quality/bobbins/"+encodeURIComponent(id)+"/captures",
   {credentials:"include",cache:"no-store",redirect:"error",
    headers:{Accept:"application/json"}},
  );
  if(!response.ok)throw new Error("offline_quality_history_unavailable");
  const rows:unknown=await response.json();
  if(!Array.isArray(rows))throw new Error("offline_quality_history_invalid");
  for(const item of rows){
   if(!item||typeof item!=="object")continue;
   const x=item as Record<string,unknown>;
   const form=x.form;
   if(x.bobbin&&typeof x.bobbin==="object"&&
      (x.bobbin as Record<string,unknown>).id===id&&
      form&&typeof form==="object"&&
      typeof (form as Record<string,unknown>).code==="string"&&
      (x.status==="submitted"||x.status==="closed")){
    out.add(onlineCompletionKey(id,(form as Record<string,string>).code));
   }
  }
 }
 return out;
}
