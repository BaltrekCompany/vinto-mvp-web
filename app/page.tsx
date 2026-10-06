"use client";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, BarChart3, ClipboardList, CloudOff, Download, LogOut, PlayCircle, Search, Send, Wifi } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { AuthChecking, AuthUnavailable } from "@/components/vinto/auth-status";
import { Brand } from "@/components/vinto/brand";
import { CaptureCount } from "@/components/vinto/capture-count";
import { Login } from "@/components/vinto/login";
import { TechnicalView } from "@/components/vinto/technical-view";
import { logout } from "@/lib/vinto/auth-api";
import { INITIAL_VIEW, ROLE_LABELS, activeRole, hasPermission, operationalRolesFromProfiles, type OperationalRole } from "@/lib/vinto/auth";
import { useSession } from "@/lib/vinto/use-session";
import { FORM_DEFINITIONS, REPORT_DEFINITIONS } from "@/lib/vinto/form-definitions";
import { PRODUCTS_BY_MACHINE } from "@/lib/vinto/catalogs";
import { RECIPES_BY_PRODUCT } from "@/lib/vinto/recipes";
import { NOMINAL_WEIGHT_BY_PRODUCT } from "@/lib/vinto/product-weights";
import type { CaptureRecord, FieldDefinition, FormDefinition } from "@/lib/vinto/types";
type Front = "Bobinas" | "Rebobinado" | "Conversión" | "Calidad";
type Module = "programacion" | "ejecucion" | "seguimiento";
type Role = OperationalRole;
type Line = {
    id: string;
    pv: string;
    productCode: string;
    productName: string;
    quantity: number;
    unit: string;
    dueDate: string;
};
type OT = {
    id: string;
    sector: Exclude<Front, "Calidad">;
    machine: string;
    status: "Borrador" | "Publicada" | "En ejecución" | "Cerrada";
    baseline: number;
    lines: Line[];
};
type Assignment = {
    id: string;
    ot: string;
    line: string;
    machine: string;
    shift: string;
    date: string;
    status: "Activa" | "Finalizada";
    by: string;
};
type Release = {
    bobbin: string;
    machine: string;
    ot: string;
    line: string;
    status: "Pendiente" | "Liberada" | "Rechazada";
};
const GROUPS: Record<Exclude<Front, "Calidad">, string[]> = { Bobinas: ["MP1", "MP3"], Rebobinado: ["Beloit", "Over", "Copasa", "Perichun", "Tubetera"], Conversión: ["Gambini", "Sincro II", "Sincro III", "OMET I", "OMET II", "8.2", "8.5", "8002", "Serv 4", "Wally", "Pañuelera"] };
const CHEMICALS = [["309109", "Fieltro Albany"], ["309307", "Tela Albany"], ["9304", "Crepetrol 3930"], ["9314", "Sal"], ["9315", "Wet Boil 101"], ["9316", "Wet Boil 201"], ["9317", "Wet Boil 402"], ["9320", "Soda cáustica"], ["9357", "Rezosol 1318"], ["9384", "Floculante"], ["9421", "Fieltro pasivador"], ["9422", "Tela pasivador"], ["9423", "Monofosfato M278"], ["9426", "Kymene"], ["9434", "Wet Boil 206"], ["9442", "Alcalino Prest"], ["9448", "Biocida"], ["94494", "Coagulante"], ["94495", "Xelorex B2000"], ["94502", "Resistencia en seco"], ["9511", "Stretch Film"]] as const;
const FLOW: Record<string, [
    number,
    string
]> = {
    form_4_registro_de_consumo_de_fibra: [10, "1. Consumo de fibra"], form_31_consumo_de_quimicos: [20, "2. Químicos · preparación de pasta"], form_18_porcentaje_de_consistencia: [30, "3. Consistencia"], form_22_grado_de_refinacion_schopper: [40, "4. Refinación"], form_1_operacion_e_inspeccion_de_maquina: [50, "5. Operación de máquina"], form_2_parametros_de_operacion_de_maquina: [50, "5. Parámetros de máquina"], form_3_registro_de_produccion_de_bobinas: [60, "6. Bobina madre"], form_21_perfil_de_gramaje_y_humedad: [70, "7. Perfil de gramaje y humedad"], form_19_control_de_humedad: [80, "8. Control de humedad"], form_20_propiedades_fisicas_de_bobina: [90, "9. Propiedades y liberación"], form_24_propiedades_fisicas_en_humedo: [100, "10. Propiedades en húmedo"], form_25_resistencia_en_humedo_curado: [110, "11. Resistencia en húmedo-curado"], form_26_medicion_de_secos: [120, "12. Control de secos"], form_27_analisis_de_agua_para_caldero: [125, "Control transversal de caldero"], form_28_registro_de_bobinas_rechazadas: [140, "Rechazo condicional"], form_6_registro_de_control_de_fardos: [150, "Cierre de fardos"], form_29_produccion_tubetera: [210, "1. Producción Tubetera"], form_7_registro_de_productos_rebobinados: [220, "2. Bobinas refiladas"], form_30_produccion_perichun: [220, "2. Producción Perichun"], form_10_registro_de_fardos: [250, "3. Control de fardos · cierre"], form_11_consumo_de_bobinas: [310, "1. Consumo de bobinas"], form_12_produccion_diaria_de_papel_higienico: [320, "2. Producción de packs"], form_13_produccion_diaria_de_servilletas_y_especiales: [320, "2. Servilletas, especiales y sobreempaque"], form_16_registro_de_control_de_merma: [330, "3. Merma"]
};
const RECIPE_GAPS = new Set(["M3-3051", "M3-3213", "M3-3422", "M3-3401", "M3-3424", "11104", "11202", "10333", "10334", "10403", "11402", "10328", "10332", "10330", "10331", "10326", "10337"]);
function norm(v: string) { return v.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
function products(machine: string) { const k = Object.keys(PRODUCTS_BY_MACHINE).find(x => norm(x) === norm(machine)); return k ? [...(PRODUCTS_BY_MACHINE as Record<string, readonly {
        code: string;
        name: string;
        unit: string;
    }[]>)[k]] : []; }
function grammage(name: string) { return name.match(/\bG\s*[-–]?\s*(\d+(?:[.,]\d+)?)/i)?.[1]?.replace(",", ".") || "Según maestro"; }
function ctx(front: Front) { const d = new Date(), h = d.getHours(); let shift = "Día"; if (front === "Conversión") {
    if (h >= 6 && h < 14)
        shift = "Mañana";
    else if (h >= 14 && h < 22)
        shift = "Tarde";
    else {
        shift = "Noche";
        if (h < 6)
            d.setDate(d.getDate() - 1);
    }
}
else if (h < 7 || h >= 19) {
    shift = "Noche";
    if (h < 7)
        d.setDate(d.getDate() - 1);
} return { shift, date: d.toISOString().slice(0, 10) }; }
function fld(key: string, label: string, type: FieldDefinition["type"], required = true, unit?: string): FieldDefinition { return { id: key, key, label, description: "Dato validado para captura To-Be.", type, source: "manual", required, unit, classification: "Mantener", proposal: "Captura digital", needsValidation: false, order: 1 }; }
function calc(key: string, label: string, unit?: string): FieldDefinition { return { ...fld(key, label, "decimal", true, unit), source: "calculated", classification: "Calcular", proposal: "Cálculo automático validado" }; }
function effectiveForms() {
    return FORM_DEFINITIONS.filter(f => f.id !== "form_5_registro_de_tubetes").map(f => {
        if (f.id === "form_31_consumo_de_quimicos")
            return { ...f, area: "quality" as const, sector: "Calidad · Bobinas", machineLabel: "MP1 / MP3" };
        if (f.id === "form_3_registro_de_produccion_de_bobinas")
            return { ...f, version: f.version + 1, fields: [...f.fields.filter(x => !["hora_inicio", "hora_fin", "hora_termino", "gramaje", "descripcion_producto"].includes(x.key)), fld("codigo_tubete", "Código de tubete utilizado", "text"), fld("hora_inicio", "Hora de inicio", "time"), fld("hora_fin", "Hora de fin", "time")] };
        if (f.id === "form_6_registro_de_control_de_fardos")
            return { ...f, version: f.version + 1, fields: [fld("cantidad_fardos", "Cantidad de fardos", "integer"), fld("peso_kg", "Peso real total", "decimal", true, "kg"), fld("observaciones", "Observaciones", "textarea", false)] };
        if (f.id === "form_11_consumo_de_bobinas")
            return { ...f, version: f.version + 1, fields: [] };
        if (f.id === "form_12_produccion_diaria_de_papel_higienico")
            return { ...f, version: f.version + 1, fields: [] };
        if (f.id === "form_13_produccion_diaria_de_servilletas_y_especiales")
            return { ...f, version: f.version + 1, fields: [] };
        if (f.id === "form_16_registro_de_control_de_merma")
            return { ...f, version: f.version + 1, fields: [] };
        if (f.id === "form_7_registro_de_productos_rebobinados" || f.id === "form_30_produccion_perichun")
            return { ...f, version: f.version + 1, fields: [] };
        if (f.id === "form_10_registro_de_fardos")
            return { ...f, version: f.version + 1, fields: [] };
        if (f.id === "form_20_propiedades_fisicas_de_bobina")
            return { ...f, fields: f.fields.map(x => x.key.includes("espesor") ? { ...x, unit: "mm", needsValidation: false, label: x.label.replace("centro", "comando") } : x.label.toLowerCase().includes("centro") ? { ...x, label: x.label.replace("centro", "comando") } : x) };
        if (f.id === "form_19_control_de_humedad")
            return { ...f, fields: [fld("peso_humedo_comando", "Peso húmedo · Comando", "decimal", true, "kg"), fld("peso_seco_comando", "Peso seco · Comando", "decimal", true, "kg"), calc("humedad_comando", "% humedad · Comando", "%"), fld("peso_humedo_medio", "Peso húmedo · Medio", "decimal", true, "kg"), fld("peso_seco_medio", "Peso seco · Medio", "decimal", true, "kg"), calc("humedad_medio", "% humedad · Medio", "%"), fld("peso_humedo_transversal", "Peso húmedo · Transversal", "decimal", true, "kg"), fld("peso_seco_transversal", "Peso seco · Transversal", "decimal", true, "kg"), calc("humedad_transversal", "% humedad · Transversal", "%"), calc("promedio_humedad", "Promedio de humedad", "%"), fld("observaciones", "Observaciones", "textarea", false)] };
        return f;
    });
}
function demoSeedData(): {
    ots: OT[];
    asg: Assignment[];
} {
    const d = new Date().toISOString().slice(0, 10), ots: OT[] = [], asg: Assignment[] = [];
    let n = 1;
    for (const [sector, machines] of Object.entries(GROUPS) as [
        Exclude<Front, "Calidad">,
        string[]
    ][]) {
        for (const machine of machines) {
            const product = products(machine)[0];
            if (!product)
                continue;
            const suffix = String(n).padStart(3, "0"), otId = `OT-PRUEBA-${suffix}`, lineId = "L1", c = ctx(sector);
            ots.push({ id: otId, sector, machine, status: "En ejecución", baseline: 1, lines: [{ id: lineId, pv: `PV-PRUEBA-${suffix}`, productCode: product.code, productName: product.name, quantity: 1, unit: product.unit, dueDate: d }] });
            asg.push({ id: `ASG-PRUEBA-${suffix}`, ot: otId, line: lineId, machine, shift: c.shift, date: c.date, status: "Activa", by: "Datos de prueba" });
            n++;
        }
    }
    return { ots, asg };
}
function ensureDemoCoverage(savedOts: OT[], savedAsg: Assignment[]) {
    const demo = demoSeedData(), ots = [...savedOts], asg = [...savedAsg];
    for (const candidate of demo.asg) {
        if (asg.some(a => a.machine === candidate.machine && a.status === "Activa"))
            continue;
        const demoOt = demo.ots.find(o => o.id === candidate.ot);
        if (demoOt && !ots.some(o => o.id === demoOt.id))
            ots.push(demoOt);
        asg.push(candidate);
    }
    return { ots, asg };
}
function loadCoverage() {
    const demo = demoSeedData();
    return ensureDemoCoverage(read("vinto-ot", demo.ots), read("vinto-asg", demo.asg));
}
export default function Home() {
    const [frontChoice, setFrontChoice] = useState<Front | null>(null), [moduleChoice, setModuleChoice] = useState<Module | null>(null), [roleChoice, setRoleChoice] = useState<Role | null>(null), [loggingOut, setLoggingOut] = useState(false), [logoutNotice, setLogoutNotice] = useState(false), [machine, setMachine] = useState("MP1"), [query, setQuery] = useState(""), [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine), [selected, setSelected] = useState<FormDefinition | null>(null), [ots, setOts] = useState<OT[]>(() => loadCoverage().ots), [asg, setAsg] = useState<Assignment[]>(() => loadCoverage().asg), [records, setRecords] = useState<CaptureRecord[]>(() => read("vinto-p1-records", [])), [releases, setReleases] = useState<Release[]>([{ bobbin: "BM-2609-001", machine: "MP1", ot: "OT-2026-001", line: "L1", status: "Pendiente" }]);
    // Autenticación: la autoridad es GET /api/auth/me (cookie HttpOnly). Nada de esto se persiste en el navegador.
    const { view, retry, setSession } = useSession();
    const user = view.status === "authenticated" ? view.user : null;
    const roles = user ? operationalRolesFromProfiles(user.profiles) : [];
    const role = activeRole(roles, roleChoice);
    const initialView = role ? INITIAL_VIEW[role] : null;
    const front: Front = frontChoice ?? initialView?.front ?? "Bobinas";
    const activeModule: Module = moduleChoice ?? initialView?.module ?? "programacion";
    // Gating visual por permisos del backend (UX; la autorización real vivirá en los endpoints).
    const canManageOrders = hasPermission(user, "work_order.manage"), canManageAssignments = hasPermission(user, "assignment.manage"), canRelease = hasPermission(user, "quality.release");
    const canCapture = hasPermission(user, front === "Calidad" ? "quality.capture" : "production.capture");
    async function endSession() {
        setLoggingOut(true);
        const result = await logout();
        setRoleChoice(null); setFrontChoice(null); setModuleChoice(null); setSelected(null);
        setLogoutNotice(!result.confirmed);
        setSession({ status: "anonymous" });
        setLoggingOut(false);
    }
    useEffect(() => { const u = () => setOnline(navigator.onLine); addEventListener("online", u); addEventListener("offline", u); return () => { removeEventListener("online", u); removeEventListener("offline", u); }; }, []);
    useEffect(() => { if (ots.length)
        localStorage.setItem("vinto-ot", JSON.stringify(ots)); }, [ots]);
    useEffect(() => { if (asg.length)
        localStorage.setItem("vinto-asg", JSON.stringify(asg)); }, [asg]);
    useEffect(() => localStorage.setItem("vinto-p1-records", JSON.stringify(records)), [records]);
    const changeFront = (next: Front) => { setFrontChoice(next); if (next !== "Calidad" && !GROUPS[next].includes(machine))
        setMachine(GROUPS[next][0]); };
    const forms = useMemo(() => effectiveForms().filter(f => front === "Calidad" ? f.area === "quality" && norm(`${f.name} ${f.machineLabel}`).includes(norm(query)) : f.area === "production" && norm(f.sector).includes(norm(front)) && applies(f, machine) && norm(`${f.name} ${f.machineLabel}`).includes(norm(query))).sort((a, b) => (FLOW[a.id]?.[0] || 999) - (FLOW[b.id]?.[0] || 999)), [front, machine, query]);
    if (loggingOut)
        return <AuthChecking label="Cerrando sesión…"/>;
    if (view.status === "checking")
        return <AuthChecking/>;
    if (view.status === "unavailable")
        return <AuthUnavailable onRetry={retry}/>;
    if (!user)
        return <Login notice={logoutNotice ? "No se pudo confirmar la revocación central de la sesión." : undefined} onAuthenticated={u => { setLogoutNotice(false); setSession({ status: "authenticated", user: u }); }}/>;
    if (!role)
        return <TechnicalView user={user} onLogout={endSession}/>;
    if (selected)
        return <Capture form={selected} front={front} machine={machine} ots={ots} asg={asg} online={online} back={() => setSelected(null)} save={r => { setRecords(x => [r, ...x]); setSelected(null); toast.success("Registro guardado con vínculo OT–PV–producto"); }}/>;
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/><header className="sticky top-0 z-30 border-b bg-white/95"><div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4"><Brand /><div className="flex items-center gap-2"><span className="hidden text-right text-sm md:block"><b>{user.display_name}</b><br /><span className="text-slate-600">{ROLE_LABELS[role]}</span></span><Badge variant="outline" className={online ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-amber-300 bg-amber-50 text-amber-950"}>{online ? <Wifi className="mr-1 h-3.5 w-3.5"/> : <CloudOff className="mr-1 h-3.5 w-3.5"/>}{online ? "En línea" : "Offline"}</Badge><Button variant="ghost" size="icon" aria-label="Cerrar sesión" onClick={endSession}><LogOut className="h-4 w-4"/></Button></div></div></header><div className="mx-auto grid max-w-[1600px] lg:grid-cols-[270px_1fr]"><aside className="hidden min-h-[calc(100vh-64px)] bg-[#123f32] p-5 text-white lg:block"><SideTitle>Front operativo</SideTitle>{(["Bobinas", "Rebobinado", "Conversión", "Calidad"] as Front[]).map(x => <Nav key={x} label={x} active={front === x} click={() => changeFront(x)}/>)}<SideTitle>Módulos</SideTitle><Nav label="Programación" active={activeModule === "programacion"} click={() => setModuleChoice("programacion")} icon={<ClipboardList />}/><Nav label="Ejecución" active={activeModule === "ejecucion"} click={() => setModuleChoice("ejecucion")} icon={<PlayCircle />}/><Nav label="Seguimiento" active={activeModule === "seguimiento"} click={() => setModuleChoice("seguimiento")} icon={<BarChart3 />}/><div className="mt-8 rounded-xl border border-white/15 bg-white/10 p-4 text-sm"><p className="text-emerald-100">Perfil</p><p className="font-bold">{ROLE_LABELS[role]}</p>{roles.length > 1 && <div className="mt-2 flex flex-wrap gap-1">{roles.map(r => <Button key={r} size="sm" variant={r === role ? "default" : "outline"} className="h-7 px-2 text-xs text-slate-950" onClick={() => { setRoleChoice(r); setFrontChoice(null); setModuleChoice(null); }}>{ROLE_LABELS[r]}</Button>)}</div>}<p className="mt-3 text-xs text-emerald-100">Sin Monday Producción. Expertus queda como integración futura.</p></div></aside><section className="p-4 md:p-8"><Badge className="bg-[#146b4f]">MVP To-Be actualizado</Badge><h1 className="mt-3 text-3xl font-black">{front} · {activeModule[0].toUpperCase() + activeModule.slice(1)}</h1><p className="mt-1 text-slate-700">PV → OT multiproducto → línea base → gestión operativa → ejecución → calidad → seguimiento.</p><div className="mt-5 flex gap-2 overflow-x-auto lg:hidden">{(["Bobinas", "Rebobinado", "Conversión", "Calidad"] as Front[]).map(x => <Button key={x} variant={front === x ? "default" : "outline"} onClick={() => changeFront(x)}>{x}</Button>)}</div><div className="mt-2 flex gap-2 lg:hidden">{(["programacion", "ejecucion", "seguimiento"] as Module[]).map(x => <Button key={x} variant={activeModule === x ? "default" : "outline"} onClick={() => setModuleChoice(x)} className="capitalize">{x}</Button>)}</div><div className="mt-6">{activeModule === "programacion" && <Programming front={front} canManageOrders={canManageOrders} canManageAssignments={canManageAssignments} ots={ots} setOts={setOts} asg={asg} setAsg={setAsg} releases={releases}/>} {activeModule === "ejecucion" && <Execution front={front} machine={machine} setMachine={setMachine} forms={forms} query={query} setQuery={setQuery} asg={asg} ots={ots} releases={releases} setReleases={setReleases} select={setSelected} canCapture={canCapture} canRelease={canRelease}/>} {activeModule === "seguimiento" && <Tracking front={front} ots={ots} asg={asg} records={records} releases={releases}/>}</div></section></div></main>;
}
function Programming({ front, ots, setOts, asg, setAsg, releases, canManageOrders, canManageAssignments }: {
    front: Front;
    canManageOrders: boolean;
    canManageAssignments: boolean;
    ots: OT[];
    setOts: (x: OT[]) => void;
    asg: Assignment[];
    setAsg: (x: Assignment[]) => void;
    releases: Release[];
}) { const machines = front === "Calidad" ? ["MP1", "MP3"] : GROUPS[front]; const [machine, setMachine] = useState(machines[0]), [pv, setPv] = useState(""), [code, setCode] = useState(""), [qty, setQty] = useState(""), [date, setDate] = useState(""); const catalog = products(machine), product = catalog.find(p => p.code === code), relevant = ots.filter(o => front === "Calidad" || o.sector === front); function add(ot?: OT) { if (!canManageOrders)
    return toast.error("Tu perfil no puede crear ni modificar OT"); if (front === "Calidad" || !pv || !product || !qty || !date)
    return toast.error("Completa PV, producto, cantidad y fecha"); const line = { id: `L${(ot?.lines.length || 0) + 1}`, pv, productCode: product.code, productName: product.name, quantity: Number(qty), unit: product.unit, dueDate: date }; if (ot)
    setOts(ots.map(o => o.id === ot.id ? { ...o, lines: [...o.lines, line] } : o));
else
    setOts([{ id: `OT-${new Date().getFullYear()}-${String(ots.length + 1).padStart(3, "0")}`, sector: front, machine, status: "Borrador", baseline: 1, lines: [line] }, ...ots]); toast.success(ot ? "Línea añadida a la misma OT" : "OT creada"); } ; function activate(ot: OT, l: Line) { if (!canManageAssignments)
    return toast.error("Tu perfil no puede asignar OT"); const c = ctx(front); setAsg(asg.map(a => a.machine === ot.machine && a.status === "Activa" ? { ...a, status: "Finalizada" as const } : a).concat({ id: crypto.randomUUID(), ot: ot.id, line: l.id, machine: ot.machine, shift: c.shift, date: c.date, status: "Activa", by: "Supervisión" })); setOts(ots.map(o => o.id === ot.id ? { ...o, status: "En ejecución" } : o)); toast.success("OT, línea y producto enviados al punto de captura"); } ; if (front === "Calidad")
    return <Panel title="Priorización de liberaciones" note="Calidad recibe bobinas completas pendientes; no existe liberación parcial."><ReleaseCards releases={releases}/></Panel>; return <div className="space-y-5">{canManageOrders ? <Panel title="Programa base de Jefatura" note="Una OT puede contener productos de varios PV. Supervisión opera una copia sin sobrescribir la línea base."><div className="grid gap-4 md:grid-cols-5"><Select label="Máquina" value={machine} set={v => { setMachine(v); setCode(""); }} options={machines}/><Text label="PV" value={pv} set={setPv}/><Select label="Producto" value={code} set={setCode} options={catalog.map(p => p.code)} render={v => { const p = catalog.find(x => x.code === v); return p ? `${p.code} · ${p.name}` : v; }}/><Text label="Cantidad" value={qty} set={setQty} type="number"/><Text label="Entrega" value={date} set={setDate} type="date"/></div><Button className="mt-5 bg-[#146b4f]" onClick={() => add()}>Crear OT inicial</Button></Panel> : <Panel title="Programa base" note="Tu perfil puede consultar las OT; su creación y publicación corresponden a Jefatura."><p className="text-sm text-slate-700">Solo lectura.</p></Panel>}{relevant.map(ot => <div key={ot.id} className="overflow-hidden rounded-2xl border bg-white shadow-sm"><div className="flex flex-wrap justify-between gap-3 border-b p-5"><div><h3 className="font-black">{ot.id} · {ot.machine}</h3><p className="text-sm text-slate-600">Base v{ot.baseline} · {ot.lines.length} producto(s) · {new Set(ot.lines.map(l => l.pv)).size} PV</p></div><div className="flex gap-2"><Badge>{ot.status}</Badge>{canManageOrders && ot.status === "Borrador" && <Button size="sm" variant="outline" onClick={() => setOts(ots.map(o => o.id === ot.id ? { ...o, status: "Publicada" } : o))}>Publicar base</Button>}{canManageOrders && <Button size="sm" variant="outline" onClick={() => add(ot)}>Añadir línea actual</Button>}</div></div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-3">Línea</th><th className="p-3">PV</th><th className="p-3">Producto</th><th className="p-3">Cantidad</th><th className="p-3">Entrega</th><th className="p-3">Gestión</th></tr></thead><tbody>{ot.lines.map(l => <tr key={l.id} className="border-t"><td className="p-3 font-bold">{l.id}</td><td className="p-3">{l.pv}</td><td className="p-3"><b>{l.productCode}</b><br />{l.productName}</td><td className="p-3">{l.quantity} {l.unit}</td><td className="p-3">{l.dueDate}</td><td className="p-3">{canManageAssignments ? <Button size="sm" className="bg-[#146b4f]" disabled={ot.status === "Borrador"} onClick={() => activate(ot, l)}>Activar</Button> : <span className="text-slate-500">—</span>}</td></tr>)}</tbody></table></div></div>)}</div>; }
function Execution({ front, machine, setMachine, forms, query, setQuery, asg, ots, releases, setReleases, select, canCapture, canRelease }: {
    front: Front;
    machine: string;
    setMachine: (x: string) => void;
    forms: FormDefinition[];
    query: string;
    setQuery: (x: string) => void;
    asg: Assignment[];
    ots: OT[];
    releases: Release[];
    setReleases: (x: Release[]) => void;
    select: (x: FormDefinition) => void;
    canCapture: boolean;
    canRelease: boolean;
}) { const deny = () => { toast.error("Tu perfil no tiene permiso para capturar en este frente"); }; const notice = !canCapture && <div className="mb-4 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">Tu perfil puede consultar este frente, pero no capturar en él.</div>; if (front === "Calidad")
    return <div className="space-y-5"><Panel title="Compuerta de liberación completa" note="La bobina queda bloqueada hasta finalizar ensayos y aprobarla completa."><ReleaseCards releases={releases} action={canRelease ? (bobbin, status) => setReleases(releases.map(r => r.bobbin === bobbin ? { ...r, status } : r)) : undefined}/></Panel>{notice}<Cards forms={forms} select={canCapture ? select : deny}/></div>; const active = asg.find(a => a.machine === machine && a.status === "Activa"), ot = ots.find(o => o.id === active?.ot), line = ot?.lines.find(l => l.id === active?.line); return <><Panel title="Punto de captura" note="Máquina fija por equipo; OT y producto llegan desde Supervisión."><div className="flex flex-wrap gap-2">{GROUPS[front].map(m => <Button key={m} size="sm" variant={machine === m ? "default" : "outline"} className={machine === m ? "bg-[#146b4f]" : ""} onClick={() => setMachine(m)}>{m}</Button>)}</div></Panel><div className={`mt-5 rounded-2xl border p-5 ${active ? "border-emerald-300 bg-emerald-50" : "border-amber-300 bg-amber-50"}`}><p className="font-black">{active ? `${active.ot} · ${active.line} · ${line?.productName}` : "Sin asignación operativa activa"}</p><p className="mt-1 text-sm">{active ? `${line?.pv} · ${machine} · ${active.shift} · ${active.date}` : "Supervisión debe activar una línea de OT."}</p></div><div className="relative mt-5"><Search className="absolute left-3 top-3 h-4 w-4 text-slate-500"/><Input className="pl-9 text-slate-950" placeholder="Buscar formato" value={query} onChange={e => setQuery(e.target.value)}/></div><div className="mt-5">{notice}<Cards forms={forms} select={f => !canCapture ? deny() : active ? select(f) : toast.error("No hay OT/producto activo")}/></div></>; }
function Cards({ forms, select }: {
    forms: FormDefinition[];
    select: (f: FormDefinition) => void;
}) { return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{forms.map(f => <button key={f.id} onClick={() => select(f)} className="rounded-2xl border bg-white p-5 text-left shadow-sm hover:border-emerald-400"><Badge variant="outline" className="border-emerald-300 text-emerald-900">{FLOW[f.id]?.[1] || "Paso operativo"}</Badge><h3 className="mt-4 font-black">{f.name}</h3><p className="mt-2 text-sm text-slate-700">{f.machineLabel}</p><p className="mt-4 border-t pt-3 text-xs font-semibold text-emerald-800">Contexto OT–PV–producto heredado</p></button>)}</div>; }
function Capture({ form, front, machine, ots, asg, online, back, save }: {
    form: FormDefinition;
    front: Front;
    machine: string;
    ots: OT[];
    asg: Assignment[];
    online: boolean;
    back: () => void;
    save: (r: CaptureRecord) => void;
}) { const [v, setV] = useState<Record<string, string | number | boolean>>({}); const active = asg.find(a => a.machine === machine && a.status === "Activa"), ot = ots.find(o => o.id === active?.ot), line = ot?.lines.find(l => l.id === active?.line), c = ctx(front), recipe = line ? RECIPES_BY_PRODUCT[line.productCode] || [] : [], nominalWeight=line?NOMINAL_WEIGHT_BY_PRODUCT[line.productCode]:undefined, chemical = form.id === "form_31_consumo_de_quimicos", fiber = form.id === "form_4_registro_de_consumo_de_fibra", humidity = form.id === "form_19_control_de_humedad", recipeGap = !!line && RECIPE_GAPS.has(line.productCode); function set(k: string, x: string | number) { setV(old => { const n = { ...old, [k]: x }; if (humidity) {
    ["comando", "medio", "transversal"].forEach(p => { const w = Number(n[`peso_humedo_${p}`]), d = Number(n[`peso_seco_${p}`]); n[`humedad_${p}`] = w > 0 ? Number((((w - d) / w) * 100).toFixed(2)) : 0; });
    n.promedio_humedad = Number((["comando", "medio", "transversal"].reduce((s, p) => s + Number(n[`humedad_${p}`] || 0), 0) / 3).toFixed(2));
} return n; }); } function submit() { if (!active || !line)
    return toast.error("No hay OT activa"); const palletForm=form.id==="form_12_produccion_diaria_de_papel_higienico"||form.id==="form_13_produccion_diaria_de_servilletas_y_especiales"; if(palletForm&&nominalWeight===undefined)return toast.error("El producto no tiene peso nominal en el maestro"); const id=crypto.randomUUID(), stamp=id.slice(0,6).toUpperCase(); const generated=palletForm?{numero_pallet:`PAL-${active.date.replaceAll("-","")}-${stamp}`,peso_nominal_jaba:nominalWeight||0,peso_total_pallet:Number(v.cantidad_jabas||0)*(nominalWeight||0)} : form.id==="form_10_registro_de_fardos"?{fardo_id:`FAR-${active.date.replaceAll("-","")}-${stamp}`} : {}; save({ id, formId: form.id, formVersion: form.version, formName: form.name, area: form.area, sector: form.sector, machine, userId: "usuario-demo", deviceId: `equipo-${machine}`, capturedAt: new Date().toISOString(), operatingDate: active.date || c.date, shiftId: active.shift || c.shift, syncStatus: online ? "synced" : "pending", workflowStatus: "submitted", values: { ...v, ...generated, orden_trabajo: ot?.id || "", linea_ot: line.id, pv: line.pv, codigo_producto: line.productCode, producto: line.productName, gramaje: grammage(line.productName) } }); } const special=form.id==="form_11_consumo_de_bobinas"?<MaterialConsumption v={v} set={set} recipe={recipe}/>:form.id==="form_12_produccion_diaria_de_papel_higienico"?<PalletProduction v={v} set={set} nominalWeight={nominalWeight}/>:form.id==="form_13_produccion_diaria_de_servilletas_y_especiales"?<NapkinSheet v={v} set={set} recipe={recipe} nominalWeight={nominalWeight}/>:form.id==="form_16_registro_de_control_de_merma"?<WasteCapture v={v} set={set}/>:form.id==="form_6_registro_de_control_de_fardos"?<BobbinBales v={v} set={set}/>:form.id==="form_10_registro_de_fardos"?<RewinderBale v={v} set={set}/>:form.id==="form_7_registro_de_productos_rebobinados"||form.id==="form_30_produccion_perichun"?<GenealogyCapture v={v} set={set}/>:null; return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/><header className="border-b bg-white p-4"><Button variant="ghost" onClick={back}><ArrowLeft className="mr-2 h-4 w-4"/>Volver</Button></header><section className="mx-auto max-w-6xl p-4 md:p-8"><div className="overflow-hidden rounded-2xl border bg-white shadow-sm"><div className="bg-[#123f32] p-6 text-white"><p className="text-emerald-200">{FLOW[form.id]?.[1] || "Ejecución"}</p><h1 className="mt-2 text-2xl font-black">{form.name}</h1></div><div className="grid gap-3 border-b bg-emerald-50 p-5 md:grid-cols-6"><Auto label="OT" value={ot?.id || "—"}/><Auto label="Línea / PV" value={`${line?.id || "—"} / ${line?.pv || "—"}`}/><Auto label="Producto" value={line?.productName || "—"}/><Auto label="Gramaje" value={`${grammage(line?.productName || "")} g/m²`}/><Auto label="Máquina" value={machine}/><Auto label="Turno / fecha" value={`${active?.shift || c.shift} · ${active?.date || c.date}`}/></div>{recipeGap && <div className="border-b border-amber-300 bg-amber-50 p-5 text-sm text-amber-950"><AlertTriangle className="mr-2 inline h-4 w-4"/><b>Receta no encontrada en el maestro.</b> El producto puede probarse, pero el sistema no inventará componentes ni cantidades.</div>}{chemical ? <Chemical v={v} set={set}/> : fiber ? <Fiber v={v} set={set}/> : special || <div className="grid gap-5 p-6 md:grid-cols-2">{form.fields.filter(f => f.source !== "automatic").map(f => <FormField key={f.id} f={f} value={v[f.key]} set={x => set(f.key, x)}/>)}</div>}{recipe.length > 0 && !["form_11_consumo_de_bobinas","form_13_produccion_diaria_de_servilletas_y_especiales"].includes(form.id) && <Recipe recipe={recipe} v={v} set={set}/>}<div className="flex justify-end border-t p-5"><Button className="bg-[#146b4f]" onClick={submit}><Send className="mr-2 h-4 w-4"/>Enviar registro trazable</Button></div></div></section></main>; }
function Fiber({ v, set }: {
    v: Record<string, string | number | boolean>;
    set: (k: string, x: string | number) => void;
}) { const origins:Record<string,string[]>={"Fibra larga":["Laja","Susano","Dorado"],"Fibra corta":["Laja","Cóndor"],Recorte:["Sauce Rancho","Máquina"]}; const material=String(v.material||""),subtotal=Number(v.cantidad_um||0)*Number(v.peso_unitario_real||0); return <div className="grid gap-5 p-6 md:grid-cols-2"><SelectBox label="Hora de consumo" type="time" value={v.hora_consumo} set={x=>set("hora_consumo",x)}/><Choice label="Material" value={v.material} set={x=>{set("material",x);set("origen","")}} options={Object.keys(origins)}/><Choice label="Origen" value={v.origen} set={x=>set("origen",x)} options={origins[material]||[]}/><Choice label="Presentación" value={v.presentacion} set={x=>set("presentacion",x)} options={material==="Recorte"?["Fardo"]:["Caja","Fardo"]}/><SelectBox label="Cantidad de UM" type="number" value={v.cantidad_um} set={x=>set("cantidad_um",x)}/><SelectBox label="Peso unitario real" type="number" value={v.peso_unitario_real} set={x=>set("peso_unitario_real",x)} suffix="kg"/><Readout label="Subtotal calculado" value={`${subtotal.toFixed(2)} kg`}/><p className="md:col-span-2 text-sm text-slate-700">Cada consumo queda ligado automáticamente a OT, producto, máquina, fecha operativa, turno y usuario.</p></div>; }

function MaterialConsumption({v,set,recipe}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void;recipe:{code:string;name:string}[]}){const rows=[0,1,2];return <Section title="Bobinas e insumos consumidos" note="El consumo físico se calcula: saldo inicial + ingreso − saldo final. La merma se registra por separado."><div className="space-y-4">{rows.map(i=>{const consumption=Number(v[`saldo_inicial_${i}`]||0)+Number(v[`ingreso_${i}`]||0)-Number(v[`saldo_final_${i}`]||0);return <div key={i} className="grid gap-3 rounded-xl border p-4 md:grid-cols-6"><Choice label="Posición" value={v[`posicion_${i}`]} set={x=>set(`posicion_${i}`,x)} options={["Superior","Inferior","No aplica"]}/><Choice label="Tipo según receta" value={v[`material_${i}`]} set={x=>set(`material_${i}`,x)} options={recipe.map(r=>`${r.code} · ${r.name}`)}/><SelectBox label="N.º bobina" value={v[`bobina_${i}`]} set={x=>set(`bobina_${i}`,x)}/><SelectBox label="Saldo inicial" type="number" value={v[`saldo_inicial_${i}`]} set={x=>set(`saldo_inicial_${i}`,x)} suffix="kg"/><SelectBox label="Ingreso" type="number" value={v[`ingreso_${i}`]} set={x=>set(`ingreso_${i}`,x)} suffix="kg"/><SelectBox label="Saldo final" type="number" value={v[`saldo_final_${i}`]} set={x=>{set(`saldo_final_${i}`,x);set(`consumo_${i}`,Number(v[`saldo_inicial_${i}`]||0)+Number(v[`ingreso_${i}`]||0)-Number(x||0))}} suffix="kg"/><Readout label="Consumo calculado" value={`${consumption.toFixed(2)} kg`}/></div>})}</div></Section>}
function PalletProduction({v,set,nominalWeight}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void;nominalWeight?:number}){const total=Number(v.cantidad_jabas||0)*Number(nominalWeight||0);return <Section title="Producción por pallet" note="Cada envío representa un pallet independiente. El código se genera al guardar y permite TVC por OT y producto."><div className="grid gap-5 md:grid-cols-2"><Readout label="N.º pallet" value="Automático al enviar"/><SelectBox label="Cantidad de jabas" type="number" value={v.cantidad_jabas} set={x=>set("cantidad_jabas",x)}/><Readout label="Peso nominal por jaba · maestro" value={nominalWeight===undefined?"Falta en maestro":`${nominalWeight} kg`}/><Readout label="Peso total calculado" value={nominalWeight===undefined?"Bloqueado":`${total.toFixed(2)} kg`}/><SelectBox label="Hora inicio pallet" type="time" value={v.hora_inicio} set={x=>set("hora_inicio",x)}/><SelectBox label="Hora fin pallet" type="time" value={v.hora_fin} set={x=>set("hora_fin",x)}/></div>{nominalWeight===undefined&&<p className="mt-4 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-900">No se permitirá enviar hasta completar el peso nominal del producto en el maestro.</p>}</Section>}
function NapkinSheet({v,set,recipe,nominalWeight}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void;recipe:{code:string;name:string}[];nominalWeight?:number}){return <div><Section title="1. Consumo de bobina" note="Una sola ficha digital por máquina y responsable."><div className="grid gap-4 md:grid-cols-5"><Choice label="Tipo de bobina" value={v.tipo_bobina} set={x=>set("tipo_bobina",x)} options={recipe.map(r=>`${r.code} · ${r.name}`)}/><SelectBox label="N.º bobina" value={v.numero_bobina} set={x=>set("numero_bobina",x)}/><SelectBox label="Saldo inicial" type="number" value={v.saldo_inicial} set={x=>set("saldo_inicial",x)} suffix="kg"/><SelectBox label="Ingreso" type="number" value={v.ingreso} set={x=>set("ingreso",x)} suffix="kg"/><SelectBox label="Saldo final" type="number" value={v.saldo_final} set={x=>{set("saldo_final",x);set("consumo_bobina",Number(v.saldo_inicial||0)+Number(v.ingreso||0)-Number(x||0))}} suffix="kg"/><Readout label="Consumo" value={`${(Number(v.saldo_inicial||0)+Number(v.ingreso||0)-Number(v.saldo_final||0)).toFixed(2)} kg`}/></div></Section><Section title="2. Sobreempaque e insumos" note="El tipo se hereda de la receta; el operario registra el consumo real."><div className="grid gap-4 md:grid-cols-2"><Choice label="Insumo" value={v.insumo} set={x=>set("insumo",x)} options={recipe.map(r=>`${r.code} · ${r.name}`)}/><SelectBox label="Cantidad consumida" type="number" value={v.cantidad_insumo} set={x=>set("cantidad_insumo",x)}/></div></Section><PalletProduction v={v} set={set} nominalWeight={nominalWeight}/></div>}
function WasteCapture({v,set}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void}){return <Section title="Merma central" note="Registro pesado independiente; no se duplica dentro de producción."><div className="grid gap-5 md:grid-cols-3"><Choice label="Tipo" value={v.tipo_merma} set={x=>set("tipo_merma",x)} options={["Hoja doble","Hoja simple","Servilleta","Toalla","Cartón","Plástico"]}/><Choice label="Origen" value={v.origen_merma} set={x=>set("origen_merma",x)} options={["Logs","Cola","Máquina"]}/><SelectBox label="Peso real" type="number" value={v.peso_merma_kg} set={x=>set("peso_merma_kg",x)} suffix="kg"/></div></Section>}
function BobbinBales({v,set}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void}){return <Section title="Control de fardos" note="Línea genérica para bobina rechazada o recorte de máquina."><div className="grid gap-5 md:grid-cols-2"><SelectBox label="Cantidad de fardos" type="number" value={v.cantidad_fardos} set={x=>set("cantidad_fardos",x)}/><Choice label="Punto de merma" value={v.punto_merma} set={x=>set("punto_merma",x)} options={["Bobina rechazada","Recorte de máquina"]}/><Choice label="Tipo de producto" value={v.tipo_producto} set={x=>set("tipo_producto",x)} options={["Servilleta","Hoja doble","Hoja simple"]}/><SelectBox label="Peso real total" type="number" value={v.peso_kg} set={x=>set("peso_kg",x)} suffix="kg"/></div></Section>}
function RewinderBale({v,set}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void}){return <Section title="Control de fardos · cierre" note="El identificador del fardo se genera al enviar."><div className="grid gap-5 md:grid-cols-3"><Readout label="ID de fardo" value="Automático al enviar"/><Choice label="Tipo de producto" value={v.tipo_producto} set={x=>set("tipo_producto",x)} options={["Papel higiénico","Toalla","Servilleta"]}/><SelectBox label="Peso real" type="number" value={v.peso_kg} set={x=>set("peso_kg",x)} suffix="kg"/></div></Section>}
function GenealogyCapture({v,set}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void}){const rows=[0,1,2,3],total=rows.reduce((s,i)=>s+Number(v[`peso_hija_${i}`]||0),0);return <Section title="Genealogía madre → hijas" note="El producto y gramaje se heredan de la OT. Cada bobina hija conserva su madre."><div className="grid gap-4 md:grid-cols-2"><SelectBox label="Código bobina madre" value={v.bobina_madre} set={x=>set("bobina_madre",x)}/><Readout label="Peso madre" value="Automático desde producción"/></div><div className="mt-4 space-y-3">{rows.map(i=><div key={i} className="grid gap-3 rounded-xl border p-3 md:grid-cols-3"><SelectBox label={`Código hija ${i+1}`} value={v[`bobina_hija_${i}`]} set={x=>set(`bobina_hija_${i}`,x)}/><SelectBox label="Formato" value={v[`formato_hija_${i}`]} set={x=>set(`formato_hija_${i}`,x)}/><SelectBox label="Peso" type="number" value={v[`peso_hija_${i}`]} set={x=>{set(`peso_hija_${i}`,x);set("peso_total_hijas",total-Number(v[`peso_hija_${i}`]||0)+Number(x||0))}} suffix="kg"/></div>)}</div><div className="mt-4"><Readout label="Peso total de hijas" value={`${total.toFixed(2)} kg`}/></div></Section>}
function Section({title,note,children}:{title:string;note:string;children:React.ReactNode}){return <div className="border-b p-6"><h2 className="font-black">{title}</h2><p className="mb-4 text-sm text-slate-700">{note}</p>{children}</div>}
function Choice({label,value,set,options}:{label:string;value:string|number|boolean|undefined;set:(x:string)=>void;options:string[]}){return <div><Label>{label} *</Label><select className="mt-2 h-10 w-full rounded-md border bg-white px-3 text-slate-950" value={String(value||"")} onChange={e=>set(e.target.value)}><option value="">Seleccionar…</option>{options.map(x=><option key={x} value={x}>{x}</option>)}</select></div>}
function SelectBox({label,value,set,type="text",suffix}:{label:string;value:string|number|boolean|undefined;set:(x:string)=>void;type?:string;suffix?:string}){return <div><Label>{label} *</Label><div className="relative"><Input className="mt-2 text-slate-950" type={type} step={type==="number"?"any":undefined} value={String(value??"")} onChange={e=>set(e.target.value)}/>{suffix&&<span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">{suffix}</span>}</div></div>}
function Readout({label,value}:{label:string;value:string}){return <div className="rounded-lg border bg-blue-50 p-3"><p className="text-xs font-semibold text-blue-900">{label}</p><p className="mt-1 font-black">{value}</p></div>}
function Chemical({ v, set }: {
    v: Record<string, string | number | boolean>;
    set: (k: string, x: string | number) => void;
}) { return <div className="p-6"><Badge variant="outline">Responsable: Analista de Calidad</Badge><h2 className="mt-3 font-black">Químicos e insumos fijos</h2><div className="mt-4 max-h-[520px] overflow-auto rounded-xl border"><table className="w-full min-w-[700px] text-sm"><thead className="sticky top-0 bg-[#123f32] text-left text-white"><tr><th className="p-3">Código</th><th className="p-3">Químico / insumo</th><th className="p-3">Caudal (ml/min)</th><th className="p-3">Consumo día (kg)</th></tr></thead><tbody>{CHEMICALS.map(([c, n]) => <tr key={c} className="border-t"><td className="p-3 font-bold">{c}</td><td className="p-3">{n}</td><td className="p-2"><Input type="number" value={String(v[`c${c}`] || "")} onChange={e => set(`c${c}`, e.target.value)}/></td><td className="p-2"><Input type="number" value={String(v[`k${c}`] || "")} onChange={e => set(`k${c}`, e.target.value)}/></td></tr>)}</tbody></table></div></div>; }
function Recipe({ recipe, v, set }: {
    recipe: {
        code: string;
        name: string;
        usage: string;
        quantity: number;
        unit: string;
    }[];
    v: Record<string, string | number | boolean>;
    set: (k: string, x: string | number) => void;
}) { return <div className="border-t bg-blue-50 p-6"><h2 className="font-black">Receta maestra de referencia</h2><p className="text-sm text-slate-700">Tipos heredados del producto; cantidades reales registradas en kg.</p><div className="mt-4 overflow-x-auto rounded-xl border bg-white"><table className="w-full min-w-[700px] text-sm"><thead className="bg-[#285e8e] text-left text-white"><tr><th className="p-3">Código</th><th className="p-3">Insumo</th><th className="p-3">Uso</th><th className="p-3">Estándar</th><th className="p-3">Real (kg)</th></tr></thead><tbody>{recipe.map((r, i) => <tr key={`${r.code}-${i}`} className="border-t"><td className="p-3 font-bold">{r.code}</td><td className="p-3">{r.name}</td><td className="p-3">{r.usage}</td><td className="p-3">{r.quantity} {r.unit}</td><td className="p-2"><Input type="number" value={String(v[`r${i}`] || "")} onChange={e => set(`r${i}`, e.target.value)}/></td></tr>)}</tbody></table></div></div>; }
function FormField({ f, value, set }: {
    f: FieldDefinition;
    value: string | number | boolean | undefined;
    set: (x: string | number) => void;
}) { return <div className={f.type === "textarea" ? "md:col-span-2" : ""}><div className="mb-2 flex gap-2"><Label>{f.label}{f.required && f.source === "manual" ? " *" : ""}</Label>{f.source === "calculated" && <Badge variant="outline" className="border-blue-300 text-blue-900">Calculado</Badge>}{f.needsValidation && <Badge variant="outline" className="border-amber-300 text-amber-900">Pendiente</Badge>}</div>{f.type === "textarea" ? <Textarea className="text-slate-950" value={String(value || "")} onChange={e => set(e.target.value)}/> : <div className="relative"><Input disabled={f.source === "calculated"} type={["decimal", "integer"].includes(f.type) ? "number" : f.type} step={f.type === "decimal" ? "any" : undefined} className="text-slate-950 disabled:bg-blue-50" value={String(value ?? "")} onChange={e => set(e.target.value)}/>{f.unit && <span className="absolute right-3 top-2.5 text-sm font-semibold text-slate-700">{f.unit}</span>}</div>}<p className="mt-1 text-xs text-slate-600">{f.description}</p></div>; }
function Tracking({ front, ots, asg, records, releases }: {
    front: Front;
    ots: OT[];
    asg: Assignment[];
    records: CaptureRecord[];
    releases: Release[];
}) { const visible = ots.filter(o => front === "Calidad" || o.sector === front), rec = front === "Calidad" ? records.filter(r => r.area === "quality") : records.filter(r => norm(r.sector).includes(norm(front))), tubetes=records.filter(r=>r.formId==="form_3_registro_de_produccion_de_bobinas"&&r.values.codigo_tubete); const summary=Object.values(rec.reduce((a,r)=>{const key=`${r.values.orden_trabajo}|${r.values.linea_ot}|${r.values.codigo_producto}`,x=a[key]||{ot:r.values.orden_trabajo,linea:r.values.linea_ot,producto:r.values.producto,registros:0,peso:0,jabas:0};x.registros++;x.peso+=Number(r.values.peso_total_pallet||0);x.jabas+=Number(r.values.cantidad_jabas||0);a[key]=x;return a},{} as Record<string,{ot:string|number|boolean;linea:string|number|boolean;producto:string|number|boolean;registros:number;peso:number;jabas:number}>)); return <div className="space-y-6"><div className="grid gap-4 md:grid-cols-4"><Metric label="OT visibles" value={visible.length}/><Metric label="Líneas PV/producto" value={visible.reduce((s, o) => s + o.lines.length, 0)}/><CaptureCount front={front} localCount={rec.length}/><Metric label="Bobinas liberadas" value={releases.filter(r => r.status === "Liberada").length}/></div><Panel title="Descargas estructuradas" note="Cada captura conserva OT, PV, producto, máquina, fecha operativa, turno, usuario e identificador."><div className="flex flex-wrap gap-3"><Button className="bg-[#146b4f]" onClick={()=>downloadRecords(rec,`${front}-registros.csv`)}><Download className="mr-2 h-4 w-4"/>Registros del front</Button><Button variant="outline" onClick={()=>downloadRows(summary,`${front}-resumen-OT-producto.csv`)}><Download className="mr-2 h-4 w-4"/>Resumen OT–producto</Button>{front==="Bobinas"&&<Button variant="outline" onClick={()=>downloadTubetes(tubetes)}><Download className="mr-2 h-4 w-4"/>Historial de tubetes</Button>}</div></Panel><Panel title="Programado base vs operativo vs ejecutado" note="La gestión de Supervisión no sobrescribe la línea base publicada por Jefatura."><div className="overflow-x-auto"><table className="w-full min-w-[800px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-3">OT</th><th className="p-3">PV</th><th className="p-3">Producto</th><th className="p-3">Base</th><th className="p-3">Asignación</th><th className="p-3">Capturas</th></tr></thead><tbody>{visible.flatMap(o => o.lines.map(l => <tr key={`${o.id}${l.id}`} className="border-t"><td className="p-3 font-bold">{o.id} · {l.id}</td><td className="p-3">{l.pv}</td><td className="p-3">{l.productName}</td><td className="p-3">{l.quantity} {l.unit}</td><td className="p-3">{asg.some(a => a.ot === o.id && a.line === l.id && a.status === "Activa") ? "Activa" : "—"}</td><td className="p-3">{records.filter(r => r.values.orden_trabajo === o.id && r.values.linea_ot === l.id).length}</td></tr>))}</tbody></table></div></Panel><div className="grid gap-5 lg:grid-cols-2"><Panel title="Genealogía y calidad" note="Madre → refilada/directa → código consumido → producto terminado."><ReleaseCards releases={releases}/></Panel><Panel title="Reportes automáticos" note="Se generan desde registros fuente; ya no se vuelven a llenar."><div className="space-y-2">{REPORT_DEFINITIONS.map(r => <div key={r.id} className="rounded-lg border p-3 font-semibold">{r.name}</div>)}<div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 font-semibold">Historial de usos de tubete · derivado de Producción de bobinas</div><div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 font-semibold">TVC por producto · suma de intervalos de pallets</div></div></Panel></div><div className="rounded-2xl border border-amber-300 bg-amber-50 p-5"><h2 className="font-black text-amber-950">Conciliación pendiente con el maestro</h2><p className="mt-1 text-sm text-amber-950">17 productos activos no tienen ruta en MFRutaMaterialOP. El MVP los identifica sin inventar recetas y permite continuar las pruebas.</p></div></div>; }
function downloadRows(rows:Record<string,unknown>[],name:string){if(!rows.length)return toast.error("Todavía no existen registros para descargar");const keys=[...new Set(rows.flatMap(r=>Object.keys(r)))],csv=[keys.join(","),...rows.map(r=>keys.map(k=>`"${String(r[k]??"").replaceAll('"','""')}"`).join(","))].join("\n"),a=document.createElement("a");a.href=URL.createObjectURL(new Blob(["\ufeff"+csv],{type:"text/csv;charset=utf-8"}));a.download=name;a.click();URL.revokeObjectURL(a.href)}
function downloadRecords(rows:CaptureRecord[],name:string){downloadRows(rows.map(r=>({id:r.id,formato:r.formName,maquina:r.machine,fecha_operativa:r.operatingDate,turno:r.shiftId,usuario:r.userId,...r.values})),name)}
function downloadTubetes(rows:CaptureRecord[]){downloadRows(rows.map(r=>({codigo_tubete:r.values.codigo_tubete,fecha:r.operatingDate,turno:r.shiftId,maquina:r.machine,bobina:r.values.codigo_de_bobina,ot:r.values.orden_trabajo,producto:r.values.producto})),"historial-uso-tubetes.csv")}
function ReleaseCards({ releases, action }: {
    releases: Release[];
    action?: (b: string, s: "Liberada" | "Rechazada") => void;
}) { return <div className="mt-4 grid gap-3 md:grid-cols-3">{releases.map(r => <div key={r.bobbin} className="rounded-xl border p-4"><p className="font-bold">{r.bobbin}</p><p className="text-sm text-slate-600">{r.ot} · {r.machine}</p><Badge className="mt-3" variant="outline">{r.status}</Badge>{action && <div className="mt-3 flex gap-2"><Button size="sm" className="bg-[#146b4f]" onClick={() => action(r.bobbin, "Liberada")}>Liberar</Button><Button size="sm" variant="destructive" onClick={() => action(r.bobbin, "Rechazada")}>Rechazar</Button></div>}</div>)}</div>; }
function Panel({ title, note, children }: {
    title: string;
    note: string;
    children: React.ReactNode;
}) { return <div className="rounded-2xl border bg-white p-6 shadow-sm"><h2 className="text-xl font-black">{title}</h2><p className="mb-5 mt-1 text-sm text-slate-700">{note}</p>{children}</div>; }
function applies(f: FormDefinition, m: string) { const s = norm(f.machineLabel).replace("tubertera", "tubetera"); return s.includes(norm(m)) || s.includes("todas") || s.includes("por definir") || s.includes("todas las rebobinadoras"); }
function read<T>(k: string, f: T): T { try {
    const v = localStorage.getItem(k);
    return v ? JSON.parse(v) : f;
}
catch {
    return f;
} }
function SideTitle({ children }: {
    children: React.ReactNode;
}) { return <p className="mb-2 mt-6 text-xs font-bold uppercase tracking-[.18em] text-emerald-200 first:mt-0">{children}</p>; }
function Nav({ label, active, click, icon }: {
    label: string;
    active: boolean;
    click: () => void;
    icon?: React.ReactNode;
}) { return <button onClick={click} className={`mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold ${active ? "bg-white text-[#123f32]" : "text-emerald-50 hover:bg-white/10"}`}><span className="[&>svg]:h-4 [&>svg]:w-4">{icon}</span>{label}</button>; }
function Select({ label, value, set, options, render }: {
    label: string;
    value: string;
    set: (x: string) => void;
    options: string[];
    render?: (x: string) => string;
}) { return <div><Label>{label}</Label><select className="mt-2 h-10 w-full rounded-md border bg-white px-3 text-sm text-slate-950" value={value} onChange={e => set(e.target.value)}><option value="">Seleccionar…</option>{options.map(x => <option key={x} value={x}>{render ? render(x) : x}</option>)}</select></div>; }
function Text({ label, value, set, type = "text" }: {
    label: string;
    value: string;
    set: (x: string) => void;
    type?: string;
}) { return <div><Label>{label}</Label><Input className="mt-2 text-slate-950" type={type} value={value} onChange={e => set(e.target.value)}/></div>; }
function Auto({ label, value }: {
    label: string;
    value: string;
}) { return <div><p className="text-xs font-semibold text-emerald-800">{label}</p><p className="mt-1 font-bold">{value}</p></div>; }
function Metric({ label, value }: {
    label: string;
    value: number;
}) { return <div className="rounded-2xl border bg-white p-5"><p className="text-sm text-slate-700">{label}</p><p className="mt-2 text-3xl font-black">{value}</p></div>; }
