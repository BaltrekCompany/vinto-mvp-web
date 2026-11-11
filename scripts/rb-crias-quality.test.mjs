// RB-CRIA-01: formularios P1-07 v3 y parser de crías sin debilitar MP1/MP3.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { P107_CRIA_NUMBERS, P107_FIELDS } from "../lib/vinto/p1-07.ts";
import { groupQualityBobbinFamilies, parseQualityBobbinInbox, parseQualityBobbinInboxItem } from "../lib/vinto/quality-bobbins.ts";

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
        id: `f96d57a1-ab3d-4d5d-93c0-${String(position).padStart(12,"0")}`,
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

test("P1-07 mother shows one family card while F3 stays independent", () => {
    const f3 = source;
    const items = [child(13), f3, child(1), child(2)];
    const groups = groupQualityBobbinFamilies(parseQualityBobbinInbox(items));
    assert.ok(groups);
    assert.equal(groups.length, 2);
    assert.equal(groups[0].production.capture_id, id);
    assert.deepEqual(groups[0].children.map(x => x.bobbin.rewinding.child_position), [1, 2, 13]);
    assert.equal(groups[1].children, undefined);
    assert.equal(groups[1].bobbin.code, "1");

    // Dos capturas con la MISMA etiqueta declarada son dos madres, nunca una.
    const secondId = "9a4c7542-912a-4afd-89ba-3f956ef2c831";
    const otherCapture = { ...child(1),
        production: { ...child(1).production, capture_id: secondId },
        bobbin: { ...child(1).bobbin, code: `CRIA-${secondId.replace(/-/g,"")}-1` },
    };
    const separate = groupQualityBobbinFamilies(parseQualityBobbinInbox([child(1), otherCapture]));
    assert.equal(separate?.length, 2);
    assert.equal(separate[0].bobbin.rewinding.mother_label, separate[1].bobbin.rewinding.mother_label);

    const decided = { ...child(13), quality: { status: "rejected" } };
    const withSibling = groupQualityBobbinFamilies(parseQualityBobbinInbox([child(2), decided]));
    assert.deepEqual(withSibling[0].children.map(x => x.quality.status), ["pending", "rejected"]);
    assert.equal(groupQualityBobbinFamilies(parseQualityBobbinInbox([child(13), child(13)])), null);
    assert.equal(groupQualityBobbinFamilies(parseQualityBobbinInbox([
        child(13), { ...child(2), bobbin: { ...child(2).bobbin,
            rewinding: { ...child(2).bobbin.rewinding, mother_label: "OTRA MADRE" } } },
    ])), null);
});

test("Quality child UI displays position and mother, not an official sequence; buttons reuse existing endpoint", () => {
    const inbox = readFileSync(new URL("../components/vinto/quality-bobbin-inbox.tsx",import.meta.url),"utf8");
    const decision = readFileSync(new URL("../components/vinto/quality-bobbin-decision.tsx",import.meta.url),"utf8");
    assert.match(inbox,/Cría \{child\.bobbin\.rewinding\?\.child_position\}/);
    assert.match(inbox,/Etiqueta \/ bobina madre/);
    assert.match(inbox,/no habilita sus controles físicos/i);
    assert.match(decision,/mother_label/); // no usado como etiqueta literal: variable tipada
    assert.match(decision,/subject/);
    assert.match(decision,/submitQualityDecision\(item\.bobbin\.id/);
    assert.match(inbox,/groupQualityBobbinFamilies\(resource\.data\)/);
    assert.match(decision,/role=\{isChild \? "dialog" : undefined\}/);
});
