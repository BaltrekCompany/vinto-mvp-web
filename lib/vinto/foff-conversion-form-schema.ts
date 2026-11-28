/** FOFF-03 Conversion: render and validate ONLY signed server-published
 * manual definitions. The backend remains authoritative at sync.
 * Unknown types, calculated fields, or malformed repeated groups fail closed.
 */
export type ConversionField=Readonly<{
  key:string;value_type:"text"|"textarea"|"decimal"|"integer"|"boolean"|"date"|"time";
  source:"manual";required:boolean;group_id:string|null;unit:string|null;
  display_order:number;options:readonly string[];
}>;
export type ConversionGroup=Readonly<{
  id:string;code:string;repeatable:boolean;min_rows:number;max_rows:number|null;
  display_order:number;
}>;
export type ConversionDefinition=Readonly<{fields:readonly ConversionField[];groups:readonly ConversionGroup[]}>;
const OBJECT=(v:unknown):v is Record<string,unknown>=>v!==null&&typeof v==="object"&&!Array.isArray(v);
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const FIELD=/^[a-zA-Z][a-zA-Z0-9_]{0,79}$/;
const fail=():never=>{throw new Error("foff_conversion_definition_unsupported");};
export function parseConversionDefinition(raw:unknown):ConversionDefinition{
  if(!OBJECT(raw))throw new Error("foff_conversion_definition_unsupported");
  if(!Array.isArray(raw.fields)||!Array.isArray(raw.groups))throw new Error("foff_conversion_definition_unsupported");
  if(raw.fields.length>300||raw.groups.length>30)throw new Error("foff_conversion_definition_unsupported");
  const groups:ConversionGroup[]=raw.groups.map((value:unknown)=>{
    if(!OBJECT(value))throw new Error("foff_conversion_definition_unsupported");
    if(typeof value.id!=="string"||!UUID.test(value.id)||
       typeof value.code!=="string"||!FIELD.test(value.code)||
       value.repeatable!==true||!Number.isSafeInteger(value.min_rows)||
       Number(value.min_rows)<0||Number(value.min_rows)>1000||
       (value.max_rows!==null&&(!Number.isSafeInteger(value.max_rows)||
         Number(value.max_rows)<Number(value.min_rows)||Number(value.max_rows)>1000))||
       !Number.isSafeInteger(value.display_order))throw new Error("foff_conversion_definition_unsupported");
    return {id:value.id,code:value.code,repeatable:true,min_rows:value.min_rows as number,
      max_rows:value.max_rows as number|null,display_order:value.display_order as number};
  });
  const ids=new Set(groups.map(x=>x.id));
  const fields:ConversionField[]=raw.fields.map((value:unknown)=>{
    if(!OBJECT(value))throw new Error("foff_conversion_definition_unsupported");
    if(typeof value.key!=="string"||!FIELD.test(value.key)||
       !["text","textarea","decimal","integer","boolean","date","time"].includes(String(value.value_type))||
       value.source!=="manual"||typeof value.required!=="boolean"||
       (value.group_id!==null&&(typeof value.group_id!=="string"||!ids.has(value.group_id)))||
       (value.unit!==null&&typeof value.unit!=="string")||
       !Number.isSafeInteger(value.display_order)||!Array.isArray(value.options)||
       value.options.some((v:unknown)=>typeof v!=="string")||value.options.length>1000)throw new Error("foff_conversion_definition_unsupported");
    return {key:value.key,value_type:value.value_type as ConversionField["value_type"],
      source:"manual",required:value.required,group_id:value.group_id as string|null,
      unit:value.unit as string|null,display_order:value.display_order as number,
      options:value.options as string[]};
  });
  if(new Set(groups.map(x=>x.code)).size!==groups.length)throw new Error("foff_conversion_definition_unsupported");
  if(new Set(fields.map(x=>[x.group_id??"",x.key].join(":"))).size!==fields.length)throw new Error("foff_conversion_definition_unsupported");
  return {fields:fields.sort((a,b)=>a.display_order-b.display_order),
    groups:groups.sort((a,b)=>a.display_order-b.display_order)};
}
export function emptyConversionValues(definition:ConversionDefinition):Record<string,unknown>{
  const groups=Object.fromEntries(definition.groups.map(g=>[g.code,[]]));
  return {...(definition.groups.length?{_groups:groups}:{} )};
}
/** Editor accepts strings until submission, then applies explicit numeric/boolean conversion.
 * This validation is a local UX guard only; server validation is mandatory.
 */
export function normalizeConversionValues(definition:ConversionDefinition,
  draft:Record<string,unknown>, recipeMaterialCodes:readonly string[]=[]):Record<string,unknown>{
  if(!OBJECT(draft))throw new Error("foff_conversion_definition_unsupported");
  const simple=definition.fields.filter(f=>f.group_id===null);
  const byCode=new Map(definition.groups.map(g=>[g.code,g]));
  const fieldByGroup=new Map(definition.groups.map(g=>[g.id,definition.fields.filter(f=>f.group_id===g.id)]));
  const result:Record<string,unknown>={};
  const toValue=(field:ConversionField,raw:unknown)=>{
    if(raw===null||raw===undefined||raw===""){
      if(field.required)throw new Error("foff_conversion_required:"+field.key);
      return undefined;
    }
    if(!["string","number","boolean"].includes(typeof raw))throw new Error("foff_conversion_definition_unsupported");
    const value=String(raw).trim();
    if(field.options.length>0&&!field.options.includes(value))throw new Error("foff_conversion_definition_unsupported");
    if(field.key==="tipo_material"&&recipeMaterialCodes.length>0&&
       !recipeMaterialCodes.includes(value))throw new Error("foff_conversion_definition_unsupported");
    if(field.value_type==="decimal"){
      if(!/^-?[0-9]+(?:\.[0-9]+)?$/.test(value))throw new Error("foff_conversion_definition_unsupported");
      return value;
    }
    if(field.value_type==="integer"){
      if(!/^-?[0-9]+$/.test(value)||!Number.isSafeInteger(Number(value)))throw new Error("foff_conversion_definition_unsupported");
      return Number(value);
    }
    if(field.value_type==="boolean"){
      if(raw===true||value==="true")return true;
      if(raw===false||value==="false")return false;
      fail();
    }
    if(field.value_type==="date"&&!/^\d{4}-\d{2}-\d{2}$/.test(value))throw new Error("foff_conversion_definition_unsupported");
    if(field.value_type==="time"&&!/^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value))throw new Error("foff_conversion_definition_unsupported");
    if(value.length>10000)throw new Error("foff_conversion_definition_unsupported");
    return value;
  };
  for(const field of simple){
    const parsed=toValue(field,draft[field.key]);
    if(parsed!==undefined)result[field.key]=parsed;
  }
  for(const key of Object.keys(draft)){
    if(key!=="_groups"&&!simple.some(f=>f.key===key))throw new Error("foff_conversion_definition_unsupported");
  }
  if(definition.groups.length){
    const all=draft._groups;
    if(all!==undefined&&!OBJECT(all))throw new Error("foff_conversion_definition_unsupported");
    const input=OBJECT(all)?all:{};
    const out:Record<string,unknown[]>={};
    for(const group of definition.groups){
      const rows=input[group.code]??[];
      if(!Array.isArray(rows))throw new Error("foff_conversion_definition_unsupported");
      if(rows.length<group.min_rows||
         (group.max_rows!==null&&rows.length>group.max_rows))throw new Error("foff_conversion_definition_unsupported");
      const fields=fieldByGroup.get(group.id)??[];
      out[group.code]=rows.map((row:unknown)=>{
        if(!OBJECT(row))throw new Error("foff_conversion_definition_unsupported");
        const clean:Record<string,unknown>={};
        for(const f of fields){
          const parsed=toValue(f,row[f.key]);
          if(parsed!==undefined)clean[f.key]=parsed;
        }
        if(Object.keys(row).some(k=>!fields.some(f=>f.key===k)))throw new Error("foff_conversion_definition_unsupported");
        return clean;
      });
    }
    if(Object.keys(input).some(key=>!byCode.has(key)))throw new Error("foff_conversion_definition_unsupported");
    result._groups=out;
  }
  return result;
}
