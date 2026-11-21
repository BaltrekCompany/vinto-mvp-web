/** OFF-04.8L — single-button UI wiring for operational IndexedDB (NOT mounted).
 *
 * No laboratory PWA is changed. The caller must inject a verified signed
 * CAPTURE scope (never readiness-only), the current owner's unlocked vault and
 * the real definition validator. IndexedDB confirm atomically inserts pending
 * AND queue: there is no separate manual bridge.
 */
import {createOfflineCaptureEditorWorkflow, type EditorWorkflowDeps} from "./offline-capture-editor-workflow.ts";
import {createOperationalCaptureBindings, type OperationalCaptureBindingsDeps} from "./offline-operational-capture-bindings.ts";
import {OperationalLocalError} from "./offline-operational-model.ts";

export type OperationalEditorUi=Readonly<Pick<EditorWorkflowDeps,
 "current"|"unlocked"|"setEditorLocked"|"setTimer"|"clearTimer"|"onDraftSaved"|"onDraftError"|"onCaptureBlocked"
> & { notifySync:()=>void }>;

export function createOperationalCaptureEditor(deps:OperationalCaptureBindingsDeps,ui:OperationalEditorUi){
 const bindings=createOperationalCaptureBindings(deps);
 return createOfflineCaptureEditorWorkflow({
  ...ui,
  persistDraft:bindings.persist,
  freezeDraft:bindings.freeze,
  enqueueFrozen:async(captureId)=>{
   // The atomic IndexedDB transaction has already enqueued the pending. This
   // check defends against a future regression that saves only the pending.
   const row=await deps.store.sync.get(captureId);
   if(!row || row.capture_id!==captureId ||
      row.ownerId.toLowerCase()!==deps.identity.ownerId.toLowerCase() ||
      row.deviceKey.toLowerCase()!==deps.identity.deviceKey.toLowerCase())
     throw new OperationalLocalError("missing");
  },
 });
}
