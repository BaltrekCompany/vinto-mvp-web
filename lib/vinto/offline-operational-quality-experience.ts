/** OFF-04.8 — final opt-in browser composition for Quality capture-only flow.
 *
 * Connects the existing encrypted editor, atomic IndexedDB pending/queue,
 * event-driven automatic sync, same-origin authenticated transport, original
 * author session gate and operational ACK. No page, app/main, worker or backend
 * route is mounted by importing this file. Activation belongs to an explicitly
 * authorized QA integration surface.
 */
import {createOperationalQualityEditor, type OperationalQualityEditorDeps}
 from "./offline-operational-quality-editor.ts";
import type {OperationalEditorUi} from "./offline-operational-editor-integration.ts";
import {createOperationalSyncRuntime, type OperationalSyncRuntimeDeps}
 from "./offline-operational-sync-runtime.ts";
import {createOperationalHttpTransport, type OperationalHttpDeps}
 from "./offline-operational-http.ts";

type EditorInputs = Omit<OperationalQualityEditorDeps, "ui"> & {
  ui: Omit<OperationalEditorUi, "notifySync">;
};
type SyncInputs = Omit<OperationalSyncRuntimeDeps, "store" | "identity" | "transport">;
export type OperationalQualityExperienceDeps = Readonly<{
  editor: EditorInputs;
  sync: SyncInputs;
  http: OperationalHttpDeps;
}>;

export async function createOperationalQualityExperience(deps: OperationalQualityExperienceDeps) {
  const transport=createOperationalHttpTransport(deps.http);
  const runtime=createOperationalSyncRuntime({
    ...deps.sync, store:deps.editor.store, identity:deps.editor.identity, transport,
  });
  const editor=await createOperationalQualityEditor({
    ...deps.editor,
    ui:{...deps.editor.ui, notifySync:runtime.notifyReady},
  });
  let started=false;
  return {
    editor,
    start() {
      if(started)return;
      started=true;
      runtime.start();
    },
    notifySessionRestored() { runtime.notifyReady(); },
    syncNow:runtime.syncOnce,
    stop() {
      started=false;
      runtime.stop();
      editor.stop();
    },
  };
}
