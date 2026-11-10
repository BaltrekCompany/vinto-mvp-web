// RB-CRIA-01: formularios P1-07 v3 y parser de crías sin debilitar MP1/MP3.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { P107_CRIA_NUMBERS, P107_FIELDS } from "../lib/vinto/p1-07.ts";
import { parseQualityBobbinInbox, parseQualityBobbinInboxItem } from "../lib/vinto/quality-bobbins.ts";

const id = "40b936c3-387f-4399-a394-33642813ffbd";
const mother = "RB-MADRE-DECLARADA";
const source = {
    bobbin: {
        id: "f96d57a1-ab3d-4d5d-93c0-a1af2a18408b",
        code: "1", machine: { code: "MP1", name: "MP1" }, management_start_year: 2026,
        sequence_number: 1, start_time: "06:30:00", end_time: "07:30:00",
        diameter_mm: "1200", weight_kg: "15.00", grammage_g_m2: null,
        number_of_cuts: "3", notes: null,
    },
    production: {
        capture_id: id, captured_at: "2026-11-10T10:00:00Z", operating_date: "2026-11-10",
        shift: { code: "DIA", name: "Día" },
        work_order: { id: "22222222-2222-4222-8222-222222222222", number: "OT-QA" },
        line: { id: "55555555-5555-4555-8555-555555555555", line_code: "L1",
                pv_reference: "PV1", article: { code: "M1-1220", description: "Artículo QA" } },
    },
    quality: { status: "pending" },
};
const child = (position = 13) => ({
    ...source,
    bobbin: {
        ...source.bobbin,
        machine: { code: "COPASA", name: "Copasa" },
        code: `CRIA-${id.replace(/-/g,"")}-${position}`,
        sequence_number: null,
        number_of_cuts: null,
        rewinding: { child_position: position, mother_label: mother },
        weight_kg: "12.500",
    },
});

test("P1-07 v4: 21 positions with gap 12 and only first child required", () => {
    assert.equal(P107_CRIA_NUMBERS.length, 21);
    assert.equal(P107_CRIA_NUMBERS.includes(12), false);
    const fields = P107_FIELDS.filter(f => f.key.startsWith("peso_cria_"));
    assert.deepEqual(fields.map(f => Number(f.key.slice(10))), P107_CRIA_NUMBERS);
    assert.deepEqual(fields.filter(f => f.required).map(f => f.key), ["peso_cria_1"]);
    assert.ok(fields.every(f => f.kind === "decimal" && f.suffix === "kg"));
    const manifest = JSON.parse(readFileSync(new URL("../backend/seed_data/forms/VINTO-P1-07.json",import.meta.url),"utf8"));
    assert.equal(manifest.version_number, 4);
    const optional = ["producto_refilado", "auxiliar", "formato_2", "formato_3"];
    for (const key of optional) {
        assert.equal(P107_FIELDS.find(f => f.key === key)?.required, false, `frontend ${key}`);
        assert.equal(manifest.fields.find(f => f.key === key)?.required, false, `bundle ${key}`);
    }
    assert.equal(manifest.fields.find(f => f.key === "formato_1")?.required, true);
    assert.equal(manifest.fields.find(f => f.key === "etiqueta_numero_de_bobina")?.required, true);
    assert.deepEqual(manifest.fields.filter(f => f.key.startsWith("peso_cria_") && f.required).map(f => f.key), ["peso_cria_1"]);
});

test("Quality can parse individual crías with mother label and exact decimal", () => {
    const parsed = parseQualityBobbinInboxItem(child());
    assert.ok(parsed);
    assert.equal(parsed.bobbin.rewinding.mother_label, mother);
    assert.equal(parsed.bobbin.rewinding.child_position, 13);
    assert.equal(parsed.bobbin.weight_kg, "12.500");
    assert.equal(parsed.bobbin.sequence_number, null);
    assert.equal(parsed.bobbin.number_of_cuts, null);
    assert.equal(parseQualityBobbinInbox([source, child()]).length, 2);
});

test("Quality rejects missing mother, invalid position and mismatched internal child identity", () => {
    for(const bad of [
        { rewinding: { child_position: 12, mother_label: mother } },
        { rewinding: { child_position: 0, mother_label: mother } },
        { rewinding: { child_position: 13, mother_label: "" } },
        { sequence_number: 13 },
        { number_of_cuts: "3" },
        { code: "not-the-child-code" },
    ]) {
        assert.equal(parseQualityBobbinInboxItem({ ...child(), bobbin: { ...child().bobbin, ...bad } }), null, JSON.stringify(bad));
    }
    assert.equal(parseQualityBobbinInbox([source, {...child(), bobbin: {...child().bobbin, rewinding: null}}]), null);
});

test("F3 item remains strict and without added origin keys", () => {
    const bobbin = parseQualityBobbinInboxItem(source)?.bobbin;
    assert.ok(bobbin);
    assert.equal(bobbin.rewinding, undefined);
    assert.equal(bobbin.code, "1");
    assert.equal(parseQualityBobbinInboxItem({...source,bobbin:{...source.bobbin,code:"2"}}),null);
    assert.equal(parseQualityBobbinInboxItem({...source,bobbin:{...source.bobbin,sequence_number:null}}),null);
});

test("Quality child UI displays position and mother, not an official sequence; buttons reuse existing endpoint", () => {
    const inbox = readFileSync(new URL("../components/vinto/quality-bobbin-inbox.tsx",import.meta.url),"utf8");
    const decision = readFileSync(new URL("../components/vinto/quality-bobbin-decision.tsx",import.meta.url),"utf8");
    assert.match(inbox,/Cría \$\{i\.bobbin\.rewinding\.child_position\}/);
    assert.match(inbox,/Etiqueta \/ bobina madre/);
    assert.match(inbox,/controles físicos F3 no se habilitan/i);
    assert.match(decision,/mother_label|mother_label|mother_label/); // no usado como etiqueta literal: variable tipada
    assert.match(decision,/subject/);
    assert.match(decision,/submitQualityDecision\(item\.bobbin\.id/);
});
