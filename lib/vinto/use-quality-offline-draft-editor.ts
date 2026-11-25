"use client";

/**
 * Opt-in encrypted draft bridge for VINTO's existing Quality editors.
 * No new screens, storage keys, credentials or permissions are created here.
 * An authenticated preparation flow must supply the unlocked/verified port.
 */
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { beginSessionOperation } from "./session-epoch";

export type QualityDraftValues = Readonly<Record<string,string|boolean>>;
export type QualityDraftSnapshot = Readonly<{revision:number;frozen:boolean;values:QualityDraftValues}>;
export type QualityDraftPort = Readonly<{
  recover:()=>Promise<QualityDraftSnapshot|null>;
  save:(values:QualityDraftValues,expectedRevision:number)=>Promise<QualityDraftSnapshot>;
}>;
type Status = "inactive"|"loading"|"ready"|"missing"|"frozen"|"error";
const equal=(a:QualityDraftValues,b:QualityDraftValues):boolean=>{
  const ka=Object.keys(a).sort(),kb=Object.keys(b).sort();
  return ka.length===kb.length&&ka.every((key,i)=>key===kb[i]&&a[key]===b[key]);
};

/** Rehydrates the real form's existing state and serializes its encrypted saves. */
export function useQualityOfflineDraftEditor<T extends object>(
  draft:T, setDraft:Dispatch<SetStateAction<T>>,
  port:QualityDraftPort|undefined, active:boolean,
  allowedKeys:readonly string[],
){
  const [status,setStatus]=useState<Status>("inactive");
  const [saving,setSaving]=useState(false);
  const revision=useRef<number|null>(null);
  const lastSaved=useRef<QualityDraftValues|null>(null);
  const scheduled=useRef<QualityDraftValues|null>(null);
  const current=useRef<T>(draft);
  const chain=useRef<Promise<void>>(Promise.resolve());
  const failed=useRef(false);
  const hydrated=useRef(false);
  const generation=useRef(0);
  const count=useRef(0);
  const keys=allowedKeys.join("|");

  useEffect(()=>{
    const epoch=++generation.current;
    hydrated.current=false;
    failed.current=false;
    revision.current=null;
    lastSaved.current=null;
    scheduled.current=null;
    chain.current=Promise.resolve();
    count.current=0;
    if(!active||!port)return;
    const live=beginSessionOperation();
    Promise.resolve().then(()=>{
      if(generation.current!==epoch||!live())return null;
      setStatus("loading");
      return port.recover();
    }).then(snapshot=>{
      if(generation.current!==epoch||!live())return;
      if(!snapshot){setStatus("missing");return;}
      if(!Number.isSafeInteger(snapshot.revision)||snapshot.revision<1){
        setStatus("error");return;
      }
      const allowed=new Set(keys.split("|"));
      if(Object.entries(snapshot.values).some(([key,val])=>!allowed.has(key)||typeof val!=="string")){
        setStatus("error");return;
      }
      if(snapshot.frozen){setStatus("frozen");return;}
      const restored={...current.current,...snapshot.values} as T;
      revision.current=snapshot.revision;
      lastSaved.current={...restored} as QualityDraftValues;
      scheduled.current={...restored} as QualityDraftValues;
      hydrated.current=true;
      current.current=restored;
      setDraft(restored);
      setStatus("ready");
    }).catch(()=>{
      if(generation.current===epoch&&live()){failed.current=true;setStatus("error");}
    });
    return ()=>{generation.current+=1;hydrated.current=false;};
  // key list and trusted port identity may invalidate the previous context
  },[active,port,keys,setDraft]);

  const schedule=(values:QualityDraftValues)=>{
    if(!active||!port||!hydrated.current||failed.current)return;
    if(scheduled.current&&equal(scheduled.current,values))return;
    const snapshot={...values};
    const epoch=generation.current;
    scheduled.current=snapshot;
    count.current+=1;
    chain.current=chain.current.then(async()=>{
      if(epoch!==generation.current||failed.current)return;
      const expected=revision.current;
      if(expected===null)throw new Error("offline_revision_missing");
      const next=await port.save(snapshot,expected);
      if(next.frozen||!equal(next.values,snapshot)||
          !Number.isSafeInteger(next.revision)||next.revision!==expected+1)
        throw new Error("offline_draft_conflict");
      if(epoch!==generation.current)return;
      revision.current=next.revision;
      lastSaved.current=snapshot;
    }).catch(()=>{
      if(epoch===generation.current){failed.current=true;hydrated.current=false;setStatus("error");}
    }).finally(()=>{
      if(epoch===generation.current){
        count.current-=1;
        if(count.current===0)setSaving(false);
      }
    });
    Promise.resolve().then(()=>{
      if(epoch===generation.current&&count.current>0)setSaving(true);
    });
  };

  useEffect(()=>{
    current.current=draft;
    if(!active||!port||!hydrated.current||failed.current)return;
    schedule(draft as QualityDraftValues);
  // scheduling is intentionally triggered by form edits, not by the queue promise
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[draft,active,port,status]);

  const flush=async(latest:T):Promise<boolean>=>{
    if(!active||!port||!hydrated.current||failed.current||status!=="ready")return false;
    // Pass the exact submit-click snapshot so a pending React effect cannot
    // cause the previous revision to be frozen instead of the latest values.
    schedule(latest as QualityDraftValues);
    await chain.current;
    return !failed.current&&hydrated.current&&
      Boolean(lastSaved.current&&equal(lastSaved.current,latest as QualityDraftValues)&&
        equal(lastSaved.current,current.current as QualityDraftValues));
  };
  return {
    flush,status,saving,
    // Edits remain possible during a queued autosave; flush() waits before freeze.
    blocked:active&&(status!=="ready"||!hydrated.current||failed.current),
  };
}
