// CV-P111-v3: tres posiciones, filtro por artículo y contrato histórico v2 intacto.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { RECIPES_BY_PRODUCT } from "../lib/vinto/recipes.ts";
import { parseP111Capture } from "../lib/vinto/p1-11.ts";
import { P111_V3_GROUPS, P111_V4_GROUPS, emptyP111V3Draft, normalizeP111V3Draft, createP111V3Attempt, calculatedConsumption, materialOptionsFor } from "../lib/vinto/p1-11-v3.ts";
import { setCell } from "../lib/vinto/capture-groups.ts";

const ASSIGNMENT="44444444-4444-4444-8444-444444444444", DEVICE="99999999-9999-4999-8999-999999999999";
const CAPTURE="11111111-1111-4111-8111-111111111111";
const values = { posicion: "no_aplica", tipo_material: "9483", numero_bobina: "M3-0001", saldo_inicial_kg: "100,5", ingreso_kg: "20", saldo_final_kg: "60.25" };
function row(draft, index, cells=values) {
  let list=draft.groups.bobinas;
  for(const [key,value] of Object.entries(cells)) list=setCell(list,list[index].rowKey,key,value);
  return {...draft,groups:{bobinas:list}};
}
function envelope(version,rows){
  return {id:CAPTURE,status:"submitted",revision:1,captured_at:"2026-10-06T16:00:00Z",submitted_at:"2026-10-06T16:01:00Z",
    form:{code:"VINTO-P1-11",version_number:version,name:"Consumo de bobinas"},machine:{code:"GAMBINI",name:"Gambini"},
    shift:{code:"MANANA",name:"Mañana"},operating_date:"2026-10-06",assignment:{id:ASSIGNMENT},
    work_order:{id:CAPTURE,number:"OT-1"},line:{id:CAPTURE,line_code:"L1",pv_reference:"PV-1",article:{code:"10327",description:"PERLITA HOJA DOBLE EXTRA 6*8"}},
    values:{_groups:{bobinas:rows}}};
}
test("exactamente tres espacios, primera posición obligatoria y tres opciones",()=>{
  assert.equal(emptyP111V3Draft().groups.bobinas.length,3);
  assert.deepEqual(P111_V3_GROUPS[0].fields[0].options.map(x=>x.value),["superior","inferior","no_aplica"]);
  assert.deepEqual([P111_V3_GROUPS[0].minRows,P111_V3_GROUPS[0].maxRows],[1,3]);
  assert.deepEqual(P111_V3_GROUPS[0].fields.map(x=>x.key),["posicion","tipo_material","numero_bobina","saldo_inicial_kg","ingreso_kg","saldo_final_kg"]);
  assert.deepEqual(P111_V3_GROUPS[0].fields.map(x=>x.required),[true,true,true,true,true,true], "V3 permanece intacta");
  assert.deepEqual(P111_V4_GROUPS[0].fields.map(x=>x.required),[true,true,true,false,false,false], "V4 opcionales");
  assert.equal(normalizeP111V3Draft(emptyP111V3Draft(),"10327").ok,false);
});
test("el artículo 10327 tiene las diez opciones exactas del Excel",()=>{
  const codes=materialOptionsFor("10327").map(x=>x.code);
  assert.deepEqual(codes,["9483","9484","9481","9482","M3-3038","9534","9397","9733","9455","9670"]);
  assert.equal(materialOptionsFor("INEXISTENTE").length,0);
});
test("se deduplican las opciones por código cuando el Excel repite materiales",()=>{
  const raw=RECIPES_BY_PRODUCT["10345"];
  assert.ok(raw.length > new Set(raw.map(item=>item.code)).size);
  const unique=materialOptionsFor("10345");
  assert.equal(unique.length,new Set(unique.map(item=>item.code)).size);
  assert.equal(unique.length,new Set(raw.map(item=>item.code)).size);
});
test("la lista backend se deriva exactamente del catálogo de frontend",()=>{
  const backend=JSON.parse(readFileSync(new URL("../backend/app/p111_material_codes.json",import.meta.url),"utf8"));
  for(const [article,materials] of Object.entries(RECIPES_BY_PRODUCT)){
    assert.deepEqual(backend[article],[...new Set(materials.map(x=>x.code))],article);
  }
  assert.deepEqual(Object.keys(backend).sort(),Object.keys(RECIPES_BY_PRODUCT).sort());
});
test("solo la fila uno se transmite; dos/tres sin tocar no se envían",()=>{
  const checked=normalizeP111V3Draft(row(emptyP111V3Draft(),0),"10327");
  assert.equal(checked.ok,true);
  assert.deepEqual(checked.values._groups.bobinas,[{posicion:"no_aplica",tipo_material:"9483",numero_bobina:"M3-0001",saldo_inicial_kg:"100.5",ingreso_kg:"20",saldo_final_kg:"60.25"}]);
});
test("se permite fila 1 y 3, conservando orden, y todas las tres completas",()=>{
  let draft=row(emptyP111V3Draft(),0);
  draft=row(draft,2,{...values,tipo_material:"9484",numero_bobina:"M3-0003",posicion:"inferior"});
  const checked=normalizeP111V3Draft(draft,"10327");
  assert.equal(checked.ok,true);
  assert.deepEqual(checked.values._groups.bobinas.map(x=>x.numero_bobina),["M3-0001","M3-0003"]);
  draft=row(draft,1,{...values,tipo_material:"9481",posicion:"superior",numero_bobina:"M3-0002"});
  const full=normalizeP111V3Draft(draft,"10327");
  assert.equal(full.ok,true);
  assert.equal(full.values._groups.bobinas.length,3);
});
test("una fila opcional parcialmente completada requiere sus campos restantes",()=>{
  let draft=row(emptyP111V3Draft(),0);
  draft=row(draft,2,{tipo_material:"9483"});
  const checked=normalizeP111V3Draft(draft,"10327");
  assert.equal(checked.ok,false);
  assert.ok(checked.errors.some(e=>e.row===3 && e.field==="numero_bobina"));
});
test("falla cerrado sin receta y rechaza un material que no corresponde al producto",()=>{
  const draft=row(emptyP111V3Draft(),0);
  assert.equal(normalizeP111V3Draft(draft,"MATERIAL_INEXISTENTE").ok,false);
  assert.equal(normalizeP111V3Draft(row(draft,0,{tipo_material:"OTRO_999"}),"10327").ok,false);
});
test("el consumo visual es la fórmula, sin guardar el campo calculado",()=>{
  const draft=row(emptyP111V3Draft(),0);
  const checked=normalizeP111V3Draft(draft,"10327");
  assert.equal(checked.ok,true);
  assert.equal(calculatedConsumption(draft.groups.bobinas[0].cells),"60.25 kg");
  assert.equal(calculatedConsumption(emptyP111V3Draft().groups.bobinas[0].cells),"0.00 kg");
  assert.equal("consumo_kg" in checked.values._groups.bobinas[0],false);
  assert.equal("consumo" in checked.values,false);
});
test("consumo en vivo: saldos vacíos cuentan como cero en cualquiera de las tres posiciones",()=>{
  const scenarios = [
    [{saldo_inicial_kg:"2",ingreso_kg:"3"},"5.00 kg"],
    [{saldo_inicial_kg:"2"},"2.00 kg"],
    [{ingreso_kg:"3"},"3.00 kg"],
    [{saldo_final_kg:"5"},"-5.00 kg"],
    [{saldo_inicial_kg:"1",ingreso_kg:"2",saldo_final_kg:"5"},"-2.00 kg"],
    [{saldo_inicial_kg:"1,5",ingreso_kg:"2"},"3.50 kg"],
    [{saldo_inicial_kg:"abc",ingreso_kg:"2"},"—"],
  ];
  for(const [cells,result] of scenarios) assert.equal(calculatedConsumption(cells),result,JSON.stringify(cells));
  for (const position of [0,1,2]) {
    const draft=emptyP111V3Draft();
    draft.groups.bobinas[position].cells={saldo_inicial_kg:"2",ingreso_kg:"3"};
    assert.equal(calculatedConsumption(draft.groups.bobinas[position].cells),"5.00 kg");
  }
});
test("V4: se pueden guardar tres saldos vacíos y parciales en las tres posiciones, sin ceros inventados",()=>{
  const required={posicion:"no_aplica",tipo_material:"9483",numero_bobina:"M3-PARCIAL"};
  const scenarios=[
    [required,required],
    [{...required,saldo_inicial_kg:"2",ingreso_kg:"3"},{...required,saldo_inicial_kg:"2",ingreso_kg:"3"}],
    [{...required,saldo_final_kg:"5"},{...required,saldo_final_kg:"5"}],
  ];
  for(const [cells,expected] of scenarios){
    let draft=emptyP111V3Draft();
    draft=row(draft,0,cells);
    const check=normalizeP111V3Draft(draft,"10327");
    assert.equal(check.ok,true);
    assert.deepEqual(check.values._groups.bobinas,[expected]);
  }
  let three=emptyP111V3Draft();
  for(const i of [0,1,2]) three=row(three,i,{...required,numero_bobina:"M3-"+i,...(i===1?{ingreso_kg:"7"}:{})});
  const checked=normalizeP111V3Draft(three,"10327");
  assert.equal(checked.ok,true);
  assert.equal(checked.values._groups.bobinas.length,3);
  assert.equal(checked.values._groups.bobinas[2].saldo_inicial_kg,undefined);
  assert.equal(calculatedConsumption(three.groups.bobinas[1].cells),"7.00 kg");
  assert.equal(normalizeP111V3Draft(row(emptyP111V3Draft(),0,{...required,ingreso_kg:"abc"}),"10327").ok,false);
  assert.equal(normalizeP111V3Draft(row(emptyP111V3Draft(),0,{posicion:"no_aplica",tipo_material:"9483"}),"10327").ok,false);
});
test("historial: V3 sigue exigiendo tres saldos, V4 acepta su ausencia",()=>{
  const minimal={posicion:"no_aplica",tipo_material:"9483",numero_bobina:"M3-HIST"};
  assert.equal(parseP111Capture(envelope(3,[minimal])),null);
  assert.deepEqual(parseP111Capture(envelope(4,[minimal])).values._groups.bobinas,[minimal]);
  assert.equal(parseP111Capture(envelope(4,[{...minimal,ingreso_kg:"2"}])).values._groups.bobinas[0].ingreso_kg,"2");
});
test("intentos son inmutables; payload contiene solo campos permitidos",()=>{
  const created=createP111V3Attempt(row(emptyP111V3Draft(),0),ASSIGNMENT,DEVICE,"10327",()=>CAPTURE);
  assert.equal(created.ok,true);
  assert.equal(created.attempt.payload.form_code,"VINTO-P1-11");
  assert.deepEqual(Object.keys(created.attempt.payload.values),["_groups"]);
  assert.equal(created.attempt.payload.values._groups.bobinas.length,1);
  assert.equal(Object.isFrozen(created.attempt.payload.values._groups.bobinas),true);
});
test("parser v3 acepta material y no aplica; el v2 no acepta material",()=>{
  const row={posicion:"no_aplica",tipo_material:"9483",numero_bobina:"B",saldo_inicial_kg:"100",ingreso_kg:"0",saldo_final_kg:"25"};
  assert.equal(parseP111Capture(envelope(3,[row])).values._groups.bobinas[0].tipo_material,"9483");
  const legacy={numero_bobina:"B",posicion:"superior",saldo_inicial_kg:"100",ingreso_kg:"0",saldo_final_kg:"25"};
  assert.deepEqual(parseP111Capture(envelope(1,[legacy])).values._groups.bobinas[0],legacy);
  assert.equal(parseP111Capture(envelope(2,[row])),null);
});
