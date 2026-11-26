/** Human-oriented navigation for PREPARED Quality drafts.
 * Pure projection only: never alters machine/bobbin context, grants, or drafts.
 * Each item retains its real encrypted draft ID.
 */
import type {QualityBobbinInboxItem} from "./quality-bobbins";
import type {OfflineFormOffer} from "./quality-offline-api";

export type OfflinePreparedNavItem<T>=Readonly<{
 id:string;
 formCode:string;
 machineCode:string;
 bobbin:QualityBobbinInboxItem|null;
 data:T;
}>;
export type OfflinePreparedGroup<T>=Readonly<{
 key:string;
 title:string;
 subtitle:string;
 kind:"machine"|"bobbin";
 items:ReadonlyArray<OfflinePreparedNavItem<T>>;
}>;

export function groupOfflinePreparedForms<T>(
 items:readonly OfflinePreparedNavItem<T>[],
):OfflinePreparedGroup<T>[]{
 const identities=new Map<string,Set<string>>();
 for(const item of items){
  if(!item.bobbin)continue;
  const k=item.machineCode+"|"+item.bobbin.bobbin.code;
  if(!identities.has(k))identities.set(k,new Set());
  identities.get(k)!.add(item.bobbin.bobbin.id);
 }
 const result=new Map<string,{
   key:string;title:string;subtitle:string;
   kind:"machine"|"bobbin";items:OfflinePreparedNavItem<T>[];
 }>();
 for(const item of items){
   const bobbin=item.bobbin;
   const kind=bobbin?"bobbin":"machine";
   const key=kind==="bobbin"?
     "bobbin|"+item.machineCode+"|"+bobbin!.bobbin.id:
     "machine|"+item.machineCode;
   let group=result.get(key);
   if(!group){
     group=kind==="bobbin"?{
       key,kind,title:"Bobina "+bobbin!.bobbin.code+" · "+item.machineCode+
         ((identities.get(item.machineCode+"|"+bobbin!.bobbin.code)?.size??0)>1?
          " · ID "+bobbin!.bobbin.id.slice(0,8):""),
       subtitle:"OT "+bobbin!.production.work_order.number+
         " · Línea "+bobbin!.production.line.line_code+
         " · "+(bobbin!.quality.status==="pending"?"Pendiente":
           bobbin!.quality.status==="released"?"Liberada":"Rechazada"),
       items:[],
     }:{
       key,kind,title:"Máquina "+item.machineCode,
       subtitle:"Controles generales · sin bobina ni OT",
       items:[],
     };
     result.set(key,group);
   }
   group.items.push(item);
 }
 return [...result.values()].sort((a,b)=>
   (a.kind===b.kind?a.title.localeCompare(b.title,"es",{numeric:true}):
     a.kind==="bobbin"?-1:1));
}

const LABELS:Readonly<Record<string,string>>={
 "VINTO-P1-18":"Porcentaje de consistencia",
 "VINTO-P1-19":"Registro de humedad",
 "VINTO-P1-20":"Propiedades físicas de bobina",
 "VINTO-P1-21":"Perfil de gramaje y humedad",
 "VINTO-P1-22":"Grado de refinación Schopper",
 "VINTO-P1-24":"Propiedades físicas en húmedo",
 "VINTO-P1-25":"Resistencia en húmedo-curado",
 "VINTO-P1-26":"Medición de secos",
 "VINTO-P1-27":"Análisis de agua para caldero",
 "VINTO-P1-28":"Registro de bobinas rechazadas",
};
/** Server catalog is preferred; static official titles are only UI fallback
 * when the original shell is reopened offline.
 */
export function offlineFormTitle(
 code:string,machineCode:string,offers:readonly OfflineFormOffer[],
):string{
 return offers.find(x=>x.machineCode===machineCode&&x.formCode===code)?.name
   ||LABELS[code]||code;
}
