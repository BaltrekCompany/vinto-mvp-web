/** OFF-04.8M: validate local Quality fields against a verified package.
 * Package is a READ-ONLY definition, NOT capture authority. Operational
 * authorization remains mandatory and separately signed at freeze + upload.
 * This adapter reuses the established OFF-04.6 normalizer across all ten forms.
 */
import { evaluateDraft, type DraftValues } from "./offline-draft-schema.ts";
import type { VerifiedQualityDefinition } from "./offline-quality-verify.ts";
export const MACHINE_QUALITY_FORMS = new Set(["VINTO-P1-18","VINTO-P1-22","VINTO-P1-26","VINTO-P1-27"]);
export const BOBBIN_QUALITY_FORMS = new Set(["VINTO-P1-19","VINTO-P1-20","VINTO-P1-21","VINTO-P1-24","VINTO-P1-25","VINTO-P1-28"]);
export const ALL_OFFLINE_QUALITY_FORMS = new Set([...MACHINE_QUALITY_FORMS,...BOBBIN_QUALITY_FORMS]);

export class OperationalQualityFieldError extends Error {
 constructor(readonly reason:"definition"|"invalid"|"incomplete"|"bobbin"|"context",
             readonly issues:ReadonlyArray<{key:string;code:string}>=[]){
  super("OFF048_QUALITY_"+reason.toUpperCase());
 }
}
export function createOperationalQualityValidator(
 pkg: VerifiedQualityDefinition,
 binding: Readonly<{formCode:string;formVersion:number;machineCode:string;
   bobbin?:Readonly<{bobbin_id:string;context_digest:string}>}>,
){
 const p=pkg.envelope.payload;
 if(!ALL_OFFLINE_QUALITY_FORMS.has(binding.formCode) ||
    p.form_code!==binding.formCode || p.form_version!==binding.formVersion ||
    p.machine_code!==binding.machineCode ||
    p.definition.form_code!==binding.formCode ||
    p.definition.form_version!==binding.formVersion)
   throw new OperationalQualityFieldError("definition");
 const requiresBobbin=BOBBIN_QUALITY_FORMS.has(binding.formCode);
 if(requiresBobbin!==Boolean(binding.bobbin))
   throw new OperationalQualityFieldError("bobbin");
 if(binding.bobbin && (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(binding.bobbin.bobbin_id) ||
    !/^[0-9a-f]{64}$/.test(binding.bobbin.context_digest)))
   throw new OperationalQualityFieldError("context");
 return (values:Readonly<Record<string,string|boolean>>):void=>{
  const result=evaluateDraft(p.definition,values);
  if(result.typeIssues.length)throw new OperationalQualityFieldError("invalid",result.typeIssues);
  if(result.missingRequired.length)throw new OperationalQualityFieldError("incomplete",result.missingRequired);
  // Reject non-canonical values so the local snapshot is exactly the
  // normalized field set that the server validates again on upload.
  const a=Object.keys(values).sort(), b=Object.keys(result.clean).sort();
  if(a.length!==b.length||a.some((key,i)=>key!==b[i]||values[key]!==result.clean[key]))
   throw new OperationalQualityFieldError("invalid");
 };
}
