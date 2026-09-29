export type FieldSource = "manual" | "automatic" | "calculated";
export type FieldType = "text" | "decimal" | "integer" | "date" | "time" | "boolean" | "textarea";

export interface FieldDefinition {
  id: string;
  key: string;
  label: string;
  description: string;
  type: FieldType;
  source: FieldSource;
  required: boolean;
  unit?: string | null;
  classification: string;
  proposal: string;
  needsValidation: boolean;
  order: number;
}

export interface FormDefinition {
  id: string;
  code: string;
  legacyNumber: number;
  name: string;
  area: "production" | "quality";
  sector: string;
  machineLabel: string;
  allowedMachineIds: string[];
  version: number;
  workflowId: string;
  active: boolean;
  fields: FieldDefinition[];
}

export interface ReportDefinition {
  id: string;
  name: string;
  source: string;
  description: string;
}

export interface CaptureRecord {
  id: string;
  formId: string;
  formVersion: number;
  formName: string;
  area: FormDefinition["area"];
  sector: string;
  machine: string;
  userId: string;
  deviceId: string;
  capturedAt: string;
  operatingDate: string;
  shiftId: string;
  syncStatus: "pending" | "synced";
  workflowStatus: "draft" | "submitted" | "blocked" | "closed";
  values: Record<string, string | number | boolean>;
}
