/** OFF-04.8M — Quality form factory for the ten offline forms (NOT mounted).
 *
 * The definition package is READINESS-ONLY and supplies FIELD METADATA ONLY.
 * The signed CAPTURE authority is checked independently and is mandatory
 * before freezing. Never conflate the two scope snapshot IDs.
 */
import type { VerifiedQualityDefinition } from "./offline-quality-verify.ts";
import { bobbinContextVersion } from "./offline-draft-schema.ts";
import { createOperationalCaptureEditor, type OperationalEditorUi } from "./offline-operational-editor-integration.ts";
import type { OperationalCaptureBindingsDeps, OperationalFormContext } from "./offline-operational-capture-bindings.ts";
import { BOBBIN_QUALITY_FORMS, MACHINE_QUALITY_FORMS, createOperationalQualityValidator } from "./offline-operational-quality-validation.ts";

export type OperationalQualityEditorDeps=Readonly<Omit<OperationalCaptureBindingsDeps,"context"|"validateComplete"> & {
  /** A separately verified READINESS package: metadata, never authority. */
  definition:VerifiedQualityDefinition;
  form:Readonly<{draftId:string;machineCode:string;formCode:string;formVersion:number;
    captureScopeSnapshotId:string;
    bobbin?:Readonly<{bobbin_id:string;context_digest:string}>;
  }>;
  ui:OperationalEditorUi;
}>;
export async function createOperationalQualityEditor(deps:OperationalQualityEditorDeps) {
 const {form,definition}=deps;
 if(!MACHINE_QUALITY_FORMS.has(form.formCode)&&!BOBBIN_QUALITY_FORMS.has(form.formCode))
   throw Error("unsupported_quality_form");
 const validateComplete=createOperationalQualityValidator(definition,{
  formCode:form.formCode,formVersion:form.formVersion,machineCode:form.machineCode,
  ...(form.bobbin?{bobbin:form.bobbin}:{})
 });
 const contextVersion=form.bobbin
  ? await bobbinContextVersion(form.captureScopeSnapshotId,form.bobbin.bobbin_id,form.bobbin.context_digest)
  : form.captureScopeSnapshotId;
 const context:OperationalFormContext={
  draftId:form.draftId,machineCode:form.machineCode,formCode:form.formCode,
  formVersion:form.formVersion,
  scopeSnapshotId:form.captureScopeSnapshotId,contextVersion,
  ...(form.bobbin?{bobbin:form.bobbin}:{})
 };
 return createOperationalCaptureEditor({
   key:deps.key,identity:deps.identity,store:deps.store,context,
   assertCaptureScope:deps.assertCaptureScope,validateComplete,
   ...(deps.now?{now:deps.now}:{})
 },deps.ui);
}
