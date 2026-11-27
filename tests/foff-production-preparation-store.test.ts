import test from "node:test";
import assert from "node:assert/strict";
import { PRODUCTION_PREPARATIONS_DB, validateProductionPreparationContext,
  listProductionPreparations, saveProductionPreparation } from "../lib/vinto/foff-production-preparation-store.ts";

const uuid = "11111111-1111-4111-8111-111111111111";
const context = {
  id: uuid, assignmentId: "22222222-2222-4222-8222-222222222222",
  scopeSnapshotId: "33333333-3333-4333-8333-333333333333",
  sectorCode: "CONVERSION", machineCode: "GAMBINI",
  formCode: "VINTO-P1-11", formVersion: 4,
  contextDigest: "a".repeat(64), capturedContextAt: "2026-11-27T16:00:00Z",
};

test("FOFF-02B.3: production preparations never use Quality IndexedDB name", () => {
  assert.notEqual(PRODUCTION_PREPARATIONS_DB, "vinto-quality-offline-preparations-v1");
  assert.notEqual(PRODUCTION_PREPARATIONS_DB, "vinto-off048-operational-v1");
});

test("FOFF-02B.3: accept assigned, versioned, digest-bound context", () => {
  assert.doesNotThrow(() => validateProductionPreparationContext(context));
  assert.throws(() => validateProductionPreparationContext({...context, formVersion: 0}));
  assert.throws(() => validateProductionPreparationContext({...context, contextDigest: "wrong"}));
  assert.throws(() => validateProductionPreparationContext({...context, sectorCode: "CALIDAD"}));
  assert.throws(() => validateProductionPreparationContext({...context, assignmentId: ""}));
});

test("FOFF-02B.3: without IndexedDB, no plaintext or demo fallback", async () => {
  const identity = { ownerId: uuid, deviceKey: "44444444-4444-4444-8444-444444444444" };
  await assert.rejects(listProductionPreparations(identity), /foff_preparation_unavailable/);
  await assert.rejects(saveProductionPreparation(identity, {} as CryptoKey, context, {
    workOrderId: uuid, lineId: uuid, articleCode: "10342", assignmentStatus: "active",
    operatingDate: "2026-11-27", shiftCode: "M", formDefinition: {}, referenceData: {},
  }));
});
