import test from "node:test";
import assert from "node:assert/strict";
import { authorizedOfflineProductionNavigation } from "../lib/vinto/foff-navigation.ts";
import type { Availability } from "../lib/vinto/availability.ts";

test("FOFF-02: only explicitly eligible forms appear by sector and machine", () => {
  const data: Availability = { sectors: [
    { code: "CONVERSION", name: "Conversión", machines: [
      { code: "GAMBINI", name: "Gambini", forms: [
        { code: "VINTO-P1-11", name: "Consumo", version_number: 4, eligible: true },
        { code: "VINTO-P1-12", name: "Pallet", version_number: 4, eligible: false },
      ] },
      { code: "SINCRO_II", name: "Sincro", forms: [{ code: "VINTO-P1-16", name: "Merma", version_number: 4 }] },
    ] },
    { code: "REBOBINADO", name: "Rebobinado", machines: [
      { code: "COPASA", name: "Copasa", forms: [{ code: "VINTO-P1-07", name: "Madre", version_number: 5, eligible: true }] },
    ] },
    { code: "BOBINAS", name: "Bobinas", machines: [
      { code: "MP3", name: "MP3", forms: [], bobbin_forms: [
        { code: "VINTO-P1-03", name: "Bobina", version_number: 4, eligible: true },
      ] },
    ] },
  ] };
  assert.deepEqual(authorizedOfflineProductionNavigation(data), [
    { code: "CONVERSION", label: "Conversión", machines: [
      { code: "GAMBINI", name: "Gambini", forms: [{ code: "VINTO-P1-11", name: "Consumo", version: 4 }] },
    ] },
    { code: "REBOBINADO", label: "Rebobinado", machines: [
      { code: "COPASA", name: "Copasa", forms: [{ code: "VINTO-P1-07", name: "Madre", version: 5 }] },
    ] },
    { code: "BOBINAS", label: "Bobinas", machines: [
      { code: "MP3", name: "MP3", forms: [{ code: "VINTO-P1-03", name: "Bobina", version: 4 }] },
    ] },
  ]);
});

test("FOFF-02: missing eligibility, empty sectors and unauthorized machine fail closed", () => {
  assert.deepEqual(authorizedOfflineProductionNavigation({ sectors: [
    { code: "CONVERSION", name: "Conversión", machines: [
      { code: "OMET_II", name: "Omet", forms: [{ code: "VINTO-P1-13", name: "Servilletas", version_number: 4, eligible: false }] },
    ] },
  ] }), []);
  assert.deepEqual(authorizedOfflineProductionNavigation({ sectors: [] }), []);
});
