import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { P113_V3, P113_V3_FIELDS, P113_LEGACY_FIELDS, checkP113Recipe, materialOptionsFor, calculatedConsumption } from "../lib/vinto/p1-13-v3.ts";
import { previewTotalKg } from "../lib/vinto/pallet-weight.ts";

const seed = JSON.parse(readFileSync(new URL("../backend/seed_data/forms/VINTO-P1-13.json", import.meta.url), "utf8"));
const base = { tipo_bobina: "BC-1229-210", numero_bobina: "B-001", saldo_inicial_kg: "15",
    ingreso_kg: "20", saldo_final_kg: "5", cantidad_jabas: "10",
    hora_inicio: "08:15", hora_fin: "09:05", observaciones: "" };
const id="11111111-1111-4111-8111-111111111111", assign="22222222-2222-4222-8222-222222222222", device="33333333-3333-4333-8333-333333333333";
function capture(version, values, pallet) {
    return { id, status:"submitted", revision:1, captured_at:"2026-11-01T16:00:00Z", submitted_at:"2026-11-01T16:00:01Z",
        form:{code:"VINTO-P1-13",version_number:version,name:"Producción diaria de servilletas y especiales"},
        machine:{code:"OMET_II",name:"Omet II"}, shift:{code:"MANANA",name:"Mañana"}, operating_date:"2026-11-01",
        assignment:{id:assign}, work_order:{id:assign,number:"OT-1"},
        line:{id:assign,line_code:"L1",pv_reference:"PV-1",article:{code:"11203",description:"SERVILLETA INSTITUCIONAL"}},
        values,...(pallet?{pallet}:{}) };
}
test("P113 v3: definicion nueva, legacy intacto y dos bloques funcionales",()=>{
    assert.equal(seed.version_number,3);
    assert.equal(seed.fields.length,9);
    assert.deepEqual(seed.fields.map(f=>f.key),P113_V3_FIELDS.map(f=>f.key));
    assert.ok(P113_LEGACY_FIELDS.length>10);
    const source=readFileSync(new URL("../components/vinto/p1-13-v3-capture.tsx",import.meta.url),"utf8");
    assert.equal(source.includes("Sobreempaque e insumos"),false);
    assert.ok(source.includes('data-p113-v3="consumo-bobina"'));
    assert.ok(source.includes('data-p113-v3="produccion-pallet"'));
});
test("11203: tres materiales todos visibles; 11104/11202 sin receta",()=>{
    assert.deepEqual(materialOptionsFor("11203").map(x=>x.code),["BC-1229-210","9570","9632"]);
    for(const material of ["BC-1229-210","9570","9632"])assert.equal(checkP113Recipe({...base,tipo_bobina:material},"11203"),null);
    assert.ok(checkP113Recipe({...base,tipo_bobina:"9126"},"11203"));
    for(const missing of ["11104","11202"])assert.ok(checkP113Recipe(base,missing));
});
test("cantidad de jabas positiva, formula en pantalla y peso por producto",()=>{
    assert.equal(P113_V3.createAttempt(base,assign,device,()=>id).ok,true);
    for(const bad of ["0","-1","1.5","1000000000",""])assert.equal(P113_V3.createAttempt({...base,cantidad_jabas:bad},assign,device,()=>id).ok,false,bad);
    assert.equal(calculatedConsumption(base),"30.00 kg");
    assert.equal(previewTotalKg("2.02","10"),"20.20");
    assert.equal("peso_total_pallet" in P113_V3.createAttempt(base,assign,device,()=>id).attempt.payload.values,false);
});
test("captura v3 exige pallet persistido; v2 legible sin pallet",()=>{
    const values={...base,cantidad_jabas:10,hora_inicio:"08:15:00",hora_fin:"09:05:00",observaciones:""};
    const pallet={number:1,quantity_jabas:10,nominal_weight_kg:"2.020000",total_weight_kg:"20.200000"};
    const captured=P113_V3.parseCapture(capture(3,values,pallet));
    assert.ok(captured);
    assert.equal(captured.pallet.total_weight_kg,"20.200000");
    assert.equal(P113_V3.parseCapture(capture(3,values)),null);
    const legacy=P113_V3.parseCapture(capture(2,{hora_inicio:"08:15:00",hora_fin:"09:05:00",saldo_inicial:"30",numero_bobina_consumida:"X-1"}));
    assert.ok(legacy);
    assert.equal(legacy.values.numero_bobina_consumida,"X-1");
    assert.equal(legacy.pallet,undefined);
});
