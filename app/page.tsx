"use client";
import { useEffect, useRef, useState } from "react";
import { BarChart3, ClipboardList, CloudOff, LogOut, PlayCircle, Wifi } from "lucide-react";
import { toast, Toaster } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthChecking, AuthUnavailable } from "@/components/vinto/auth-status";
import { BobbinasProgramming } from "@/components/vinto/bobinas-programming";
import { Brand } from "@/components/vinto/brand";
import { CentralStatus } from "@/components/vinto/central-status";
import { QualityBobbinHistory } from "@/components/vinto/quality-bobbin-history";
import { QualityBobbinInbox } from "@/components/vinto/quality-bobbin-inbox";
import { QualityHumidityCapture } from "@/components/vinto/quality-humidity-capture";
import { QualityPhysicalCapture } from "@/components/vinto/quality-physical-capture";
import { listQualityBobbins } from "@/lib/vinto/quality-api";
import type { QualityBobbinInboxItem } from "@/lib/vinto/quality-bobbins";
import type { PendingHumidityAttempt } from "@/lib/vinto/quality-captures";
import type { PendingPhysicalAttempt } from "@/lib/vinto/quality-physical";
import { getQualityBobbinHistory } from "@/lib/vinto/quality-history-api";
import type { QualityHistoryLoad } from "@/lib/vinto/quality-history";
import { ContextBanner, type ExecState } from "@/components/vinto/context-banner";
import { CaptureCount } from "@/components/vinto/capture-count";
import { CentralCaptures } from "@/components/vinto/central-captures";
import { F3BobbinCapture } from "@/components/vinto/f3-bobbin-capture";
import { F6Capture } from "@/components/vinto/f6-capture";
import { P110CaptureForm } from "@/components/vinto/p1-10-capture";
import { P111CaptureForm } from "@/components/vinto/p1-11-capture";
import { P129CaptureForm } from "@/components/vinto/p1-29-capture";
import { ConversionCentral } from "@/components/vinto/conversion-central";
import { RebobinadoCentral } from "@/components/vinto/rebobinado-central";
import { Login } from "@/components/vinto/login";
import { Panel } from "@/components/vinto/panels";
import { PendingMetric, PendingNotice, QualityTrackingPending } from "@/components/vinto/tracking-pending";
import { TechnicalView } from "@/components/vinto/technical-view";
import { logout } from "@/lib/vinto/auth-api";
import { INITIAL_VIEW, ROLE_LABELS, activeRole, hasPermission, operationalRolesFromProfiles, type OperationalRole } from "@/lib/vinto/auth";
import { CONTEXT_MESSAGES, contextFromActive, failureMessage, toDisplayAssignment, toDisplayOt, usesCentralAssignment, type CaptureContext, type DisplayAssignment, type DisplayOt } from "@/lib/vinto/orders";
import { listCaptures } from "@/lib/vinto/captures-api";
import { F3_FORM_ID, type PendingBobbinAttempt } from "@/lib/vinto/bobbins";
import { F6_FORM_ID, type CentralCapture, type PendingAttempt } from "@/lib/vinto/captures";
import type { FormScreen } from "@/lib/vinto/availability";
import type { P110Attempt } from "@/lib/vinto/p1-10";
import type { P111Attempt } from "@/lib/vinto/p1-11";
import type { P129Attempt } from "@/lib/vinto/p1-29";
import { useActiveAssignment, useAssignments, useResource, useWorkOrders } from "@/lib/vinto/use-central";
import { useAccess } from "@/lib/vinto/use-access";
import { AccessGate } from "@/components/vinto/access-gate";
import { eligibleMachineCodes, eligibleView, F3_CODE, F6_CODE, effectiveFront, offersForm, qualityBobbinActions } from "@/lib/vinto/eligibility";
import { BobinasCandidateCards, offeredCandidates, publishedCandidates } from "@/components/vinto/bobinas-candidate-cards";
import { CandidateFormCapture } from "@/components/vinto/candidate-form-capture";
import { CandidateHistory } from "@/components/vinto/candidate-history";
import { QualityMachineControls } from "@/components/vinto/quality-machine-controls";
import { REBOBINADO_CANDIDATES, isRebobinadoCandidate, type RebobinadoCandidateScreen } from "@/lib/vinto/rebobinado-candidates";
import { CONVERSION_CANDIDATES, isConversionCandidate, type ConversionCandidateScreen } from "@/lib/vinto/conversion-candidates";
import { QualityBobbinCandidateCapture } from "@/components/vinto/quality-bobbin-candidate-capture";
import { bobbinScreensFor, type QualityBobbinScreen } from "@/lib/vinto/quality-offers";
import { QUALITY_CANDIDATES } from "@/lib/vinto/quality-candidates";
import type { QualityCandidateScreen } from "@/lib/vinto/quality-offers";
import { BOBINAS_CANDIDATES, type BobinasCandidateScreen } from "@/lib/vinto/bobinas-candidates";
import { candidateHistoryKey, qualityHistoryKey, qualityInboxKey, sessionScope } from "@/lib/vinto/resource-view";
import type { CandidateAttempt, CandidateCapture } from "@/lib/vinto/candidate-form";
import { useSession } from "@/lib/vinto/use-session";
import { FORM_DEFINITIONS, REPORT_DEFINITIONS } from "@/lib/vinto/form-definitions";
import type { FieldDefinition, FormDefinition } from "@/lib/vinto/types";
import { bumpSessionEpoch } from "@/lib/vinto/session-epoch";
type Front = "Bobinas" | "Rebobinado" | "Conversión" | "Calidad";
type Module = "programacion" | "ejecucion" | "seguimiento";
type Role = OperationalRole;
const GROUPS: Record<Exclude<Front, "Calidad">, string[]> = { Bobinas: ["MP1", "MP3"], Rebobinado: ["Beloit", "Over", "Copasa", "Perichun", "Tubetera"], Conversión: ["Gambini", "Sincro II", "Sincro III", "OMET I", "OMET II", "8.2", "8.5", "8002", "Serv 4", "Wally", "Pañuelera"] };
// Solo los formularios CENTRALES de Producción de Bobinas que esta pantalla abre por asignación (F3 → POST /api/bobbins; P1-06 → POST /api/captures). Las fichas candidatas salen de la disponibilidad del backend.
const FLOW: Record<string, [number, string]> = { form_3_registro_de_produccion_de_bobinas: [60, "6. Bobina madre"], form_6_registro_de_control_de_fardos: [150, "Cierre de fardos"] };
function norm(v: string) { return v.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
function applies(f: FormDefinition, m: string) { const s = norm(f.machineLabel); return s.includes(norm(m)) || s.includes("todas") || s.includes("por definir"); }
// INT-02A: formularios CENTRALES de Producción de Bobinas (F3 y P1-06). No hay lista local de respaldo: sin asignación activa, sin permiso o con la API caída no se abre nada.
const CENTRAL_BOBINAS_FORMS = FORM_DEFINITIONS.filter(f => f.id === F3_FORM_ID || f.id === F6_FORM_ID).sort((a, b) => (FLOW[a.id]?.[0] || 999) - (FLOW[b.id]?.[0] || 999));
export default function Home() {
    const [frontChoice, setFrontChoice] = useState<Front | null>(null), [moduleChoice, setModuleChoice] = useState<Module | null>(null), [roleChoice, setRoleChoice] = useState<Role | null>(null), [loggingOut, setLoggingOut] = useState(false), [logoutNotice, setLogoutNotice] = useState(false), [machineChoice, setMachine] = useState("MP1"), [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine), [selected, setSelected] = useState<FormDefinition | null>(null), [captureContext, setCaptureContext] = useState<CaptureContext | null>(null), [f6Attempt, setF6Attempt] = useState<PendingAttempt | null>(null), [f3Attempt, setF3Attempt] = useState<PendingBobbinAttempt | null>(null), [selectedQualityBobbin, setSelectedQualityBobbin] = useState<QualityBobbinInboxItem | null>(null), [humidityAttempt, setHumidityAttempt] = useState<PendingHumidityAttempt | null>(null);
    // Historial de controles de UNA Bobina (solo lectura). Estado PROPIO, independiente de selectedQualityBobbin y del intento de humedad.
    // seq numera cada apertura: reabrir (o abrir otra Bobina) usa otra clave, cancela la consulta previa y nunca reutiliza un resultado anterior.
    const [qualityHistory, setQualityHistory] = useState<{ item: QualityBobbinInboxItem; seq: number } | null>(null), historySeq = useRef(0);
    // Calidad · VINTO-P1-20: selección e intento pendiente PROPIOS, independientes de los de P1-19 (humedad) y del historial.
    const [selectedPhysicalBobbin, setSelectedPhysicalBobbin] = useState<QualityBobbinInboxItem | null>(null), [physicalAttempt, setPhysicalAttempt] = useState<PendingPhysicalAttempt | null>(null);
    // Rebobinado CENTRAL (M4-A): formulario abierto (P1-10 / P1-29) con el contexto de la asignación central, e intentos pendientes PROPIOS (el contexto original se conserva con el intento).
    const [rebCapture, setRebCapture] = useState<{ screen: FormScreen; context: CaptureContext } | null>(null), [rebRefresh, setRebRefresh] = useState(0);
    // DEV-B1: fichas candidatas centrales de Bobinas (P1-05 / P1-31); solo se ofrecen si el backend las publica. El intento pendiente conserva SU contexto original.
    const [bobCandidate, setBobCandidate] = useState<{ screen: BobinasCandidateScreen; context: CaptureContext } | null>(null), [candAttempts, setCandAttempts] = useState<Partial<Record<BobinasCandidateScreen, { attempt: CandidateAttempt; context: CaptureContext }>>>({}), [candRefresh, setCandRefresh] = useState(0);
    // DEV-Q1: controles de Calidad por máquina (P1-22 / P1-26), sin bobina ni asignación; solo se ofrecen si el backend los publica. El intento pendiente conserva SU máquina.
    const [qualCapture, setQualCapture] = useState<{ screen: QualityCandidateScreen; machine: { code: string; name: string } } | null>(null), [qualAttempts, setQualAttempts] = useState<Partial<Record<QualityCandidateScreen, { attempt: CandidateAttempt; machine: { code: string; name: string } }>>>({}), [qualRefresh, setQualRefresh] = useState(0);
    // DEV-Q2: candidato de Calidad ligado a UNA bobina (P1-21); solo se ofrece si el backend lo publica para la máquina de la bobina. El intento pendiente conserva SU bobina (snapshot del inbox).
    const [bobbinCand, setBobbinCand] = useState<{ screen: QualityBobbinScreen; item: QualityBobbinInboxItem } | null>(null), [bobbinCandAttempts, setBobbinCandAttempts] = useState<Partial<Record<QualityBobbinScreen, { attempt: CandidateAttempt; item: QualityBobbinInboxItem }>>>({});
    // DEV-R2: fichas candidatas de Rebobinado (P1-30 / P1-07), contexto de asignación; el intento pendiente conserva SU contexto original por formulario.
    const [rebCandAttempts, setRebCandAttempts] = useState<Partial<Record<RebobinadoCandidateScreen, { attempt: CandidateAttempt; context: CaptureContext }>>>({});
    const [p110Attempt, setP110Attempt] = useState<P110Attempt | null>(null), [p110Context, setP110Context] = useState<CaptureContext | null>(null);
    const [p129Attempt, setP129Attempt] = useState<P129Attempt | null>(null), [p129Context, setP129Context] = useState<CaptureContext | null>(null);
    // Conversión CENTRAL (M6-A/G.12-C4-FINAL25): formulario abierto (P1-11 / P1-12 / P1-13 / P1-16) con el contexto de la asignación central e intento pendiente PROPIO (el contexto original se conserva con el intento).
    const [convCapture, setConvCapture] = useState<{ screen: FormScreen; context: CaptureContext } | null>(null), [convRefresh, setConvRefresh] = useState(0);
    // G.12-C4-FINAL25: fichas candidatas de Conversión (P1-12 / P1-13 / P1-16), mismo patrón que REBOBINADO_CANDIDATES; el intento pendiente conserva SU contexto original por formulario.
    const [convCandAttempts, setConvCandAttempts] = useState<Partial<Record<ConversionCandidateScreen, { attempt: CandidateAttempt; context: CaptureContext }>>>({});
    const [p111Attempt, setP111Attempt] = useState<P111Attempt | null>(null), [p111Context, setP111Context] = useState<CaptureContext | null>(null);
    // Autenticación: la autoridad es GET /api/auth/me (cookie HttpOnly). Nada de esto se persiste en el navegador.
    const { view, retry, setSession } = useSession();
    const user = view.status === "authenticated" ? view.user : null;
    const roles = user ? operationalRolesFromProfiles(user.profiles) : [];
    const role = activeRole(roles, roleChoice);
    const initialView = role ? INITIAL_VIEW[role] : null;
    // MF-13-02: los frentes visibles salen de la elegibilidad que verifica el backend (nunca de listas locales). Mientras no se confirma, no hay frentes; el frente efectivo es el elegido si sigue visible.
    const access = useAccess({ enabled: user !== null && role !== null, canManage: hasPermission(user, "work_order.manage") || hasPermission(user, "assignment.manage"), canQuality: hasPermission(user, "quality.capture"), scope: sessionScope(user), onUnauthorized: sessionLost });
    const fronts: Front[] = access.state.status === "ready" ? access.state.fronts : [];
    const preferredFront: Front = frontChoice ?? initialView?.front ?? "Bobinas";
    const front: Front = effectiveFront(fronts, preferredFront) ?? preferredFront;
    const bobEligible = eligibleView(access.production);
    const bobMachines = bobEligible.status === "ready" ? eligibleMachineCodes(bobEligible.data, "BOBINAS") : [];
    const machine = bobMachines.includes(machineChoice) ? machineChoice : bobMachines[0] ?? machineChoice;
    const bobEligibleMachine = bobEligible.status === "ready" ? bobEligible.data.sectors.find(s => s.code === "BOBINAS")?.machines.find(m => m.code === machine) : undefined;
    const activeModule: Module = moduleChoice ?? initialView?.module ?? "programacion";
    // Gating visual por permisos del backend (UX; la autorización real vivirá en los endpoints).
    const canManageOrders = hasPermission(user, "work_order.manage"), canManageAssignments = hasPermission(user, "assignment.manage");
    const canCapture = hasPermission(user, front === "Calidad" ? "quality.capture" : "production.capture");
    // INT-01B: ÚNICO punto que descarta todo el estado de pantalla ligado a una sesión (selecciones, intentos pendientes con su contexto original, aperturas). Se usa al cerrar sesión, al perderla y cuando
    // cambia la identidad del usuario autenticado: los intentos pendientes de una cuenta nunca reaparecen asociados a otra. No toca el almacenamiento local (INT-02A: esta pantalla ya no lee ni escribe vinto-ot, vinto-asg ni vinto-p1-records).
    function resetSessionState() {
        bumpSessionEpoch(); // INT-01: invalida las operaciones asíncronas (capturas POST) de la sesión anterior: sus respuestas tardías ya no tocan este estado
        setRoleChoice(null); setFrontChoice(null); setModuleChoice(null); setSelected(null); setCaptureContext(null); setF6Attempt(null); setF3Attempt(null); setSelectedQualityBobbin(null); setHumidityAttempt(null); setQualityHistory(null); setSelectedPhysicalBobbin(null); setPhysicalAttempt(null); setRebCapture(null); setP110Attempt(null); setP110Context(null); setP129Attempt(null); setP129Context(null); setBobCandidate(null); setCandAttempts({}); setQualCapture(null); setQualAttempts({}); setBobbinCand(null); setBobbinCandAttempts({}); setRebCandAttempts({}); setConvCapture(null); setConvCandAttempts({}); setP111Attempt(null); setP111Context(null);
    }
    // Cambio de identidad sin pasar por «sesión perdida» / «cerrar sesión» (p. ej. otra cuenta que entra en el mismo navegador): se descarta el estado de la cuenta anterior ANTES de dibujar nada.
    const [stateOwner, setStateOwner] = useState<string | null>(null);
    if (user && stateOwner !== user.id) { setStateOwner(user.id); if (stateOwner !== null) resetSessionState(); }
    // Sesión perdida (401 de una API central): vuelve al Login por el mecanismo de autenticación existente.
    function sessionLost() {
        resetSessionState();
        setLogoutNotice(false);
        setSession({ status: "anonymous" });
    }
    // Datos CENTRALES de Bobinas (MP1/MP3): sin polling; se cargan al habilitarse y se reconcilian con GET después de cada mutación.
    const scope = sessionScope(user); // las claves de los recursos candidatos incluyen al usuario: otra cuenta en el mismo navegador nunca ve la vista de la anterior, ni siquiera mientras carga
    const authenticated = user !== null && role !== null, bobinasFront = front === "Bobinas";
    const canReadOrders = hasPermission(user, "work_order.read"), canReadAssignments = hasPermission(user, "assignment.read");
    const workOrders = useWorkOrders(authenticated && bobinasFront && canReadOrders && (activeModule === "programacion" || activeModule === "seguimiento"), sessionLost, scope);
    const centralAssignments = useAssignments(authenticated && bobinasFront && canReadAssignments && activeModule === "seguimiento", sessionLost, scope);
    const activeAssignment = useActiveAssignment(machine, authenticated && canReadAssignments && usesCentralAssignment(front, activeModule), sessionLost, scope); // solo Bobinas / Ejecución de producción; Calidad no la consulta
    // F6 central: lista de PostgreSQL solo para quien captura producción (Bobinas / Seguimiento); sin polling, se refresca tras un envío.
    const canReadCaptures = hasPermission(user, "production.capture");
    const f6List = useResource<CentralCapture[]>(candidateHistoryKey("f6", scope, 0), authenticated && bobinasFront && canReadCaptures && activeModule === "seguimiento", signal => listCaptures(signal), sessionLost);
    // DEV-B1: la disponibilidad (qué formularios publica el backend para MP1 / MP3) decide si se ofrecen P1-05 y P1-31; con la configuración real no se publican y no aparece nada.
    const publishedCand = publishedCandidates(access.production); // historial (Seguimiento): lo publicado para la sesión; las OFERTAS de captura usan solo lo elegible (bobEligible)
    const candHistory = {
        p104: useResource<CandidateCapture[]>(candidateHistoryKey("p104", scope, candRefresh), authenticated && bobinasFront && canReadCaptures && activeModule === "seguimiento" && publishedCand.includes("p104"), signal => BOBINAS_CANDIDATES.p104.api.list(signal), sessionLost),
        p105: useResource<CandidateCapture[]>(candidateHistoryKey("p105", scope, candRefresh), authenticated && bobinasFront && canReadCaptures && activeModule === "seguimiento" && publishedCand.includes("p105"), signal => BOBINAS_CANDIDATES.p105.api.list(signal), sessionLost),
        p131: useResource<CandidateCapture[]>(candidateHistoryKey("p131", scope, candRefresh), authenticated && bobinasFront && canReadCaptures && activeModule === "seguimiento" && publishedCand.includes("p131"), signal => BOBINAS_CANDIDATES.p131.api.list(signal), sessionLost),
        p102: useResource<CandidateCapture[]>(candidateHistoryKey("p102", scope, candRefresh), authenticated && bobinasFront && canReadCaptures && activeModule === "seguimiento" && publishedCand.includes("p102"), signal => BOBINAS_CANDIDATES.p102.api.list(signal), sessionLost),
        p101: useResource<CandidateCapture[]>(candidateHistoryKey("p101", scope, candRefresh), authenticated && bobinasFront && canReadCaptures && activeModule === "seguimiento" && publishedCand.includes("p101"), signal => BOBINAS_CANDIDATES.p101.api.list(signal), sessionLost),
    };
    // Inbox CENTRAL de Calidad (solo lectura, GET /api/quality/bobbins, status pendiente): no depende de la asignación activa.
    const canReadQualityInbox = hasPermission(user, "quality.capture");
    const qualityInbox = useResource<QualityBobbinInboxItem[]>(qualityInboxKey(scope), authenticated && front === "Calidad" && canReadQualityInbox && activeModule === "ejecucion", signal => listQualityBobbins(signal), sessionLost);
    const bobbinForms = { view: eligibleView(access.qualityBobbin) }; // MF-13-02: ofertas de Calidad por bobina solo con elegibilidad confirmada por el backend
    const bobbinOffers = (machineCode: string): QualityBobbinScreen[] => (bobbinForms.view.status === "ready" ? bobbinScreensFor(bobbinForms.view.data, machineCode) : []);
    const historyBobbin = qualityHistory?.item.bobbin ?? null;
    const bobbinHistory = useResource<QualityHistoryLoad>(qualityHistoryKey(scope, qualityHistory ? qualityHistory.item.bobbin.id : null, qualityHistory ? qualityHistory.seq : 0), authenticated && front === "Calidad" && canReadQualityInbox && historyBobbin !== null, signal => historyBobbin ? getQualityBobbinHistory({ id: historyBobbin.id, code: historyBobbin.code }, signal) : Promise.reject(new Error("Sin bobina seleccionada")), sessionLost);
    const openQualityHistory = (item: QualityBobbinInboxItem) => { historySeq.current += 1; setQualityHistory({ item, seq: historySeq.current }); };
    const refreshCentral = () => { workOrders.refresh(); centralAssignments.refresh(); activeAssignment.refresh(); };
    async function endSession() {
        setLoggingOut(true);
        const result = await logout();
        resetSessionState();
        setLogoutNotice(!result.confirmed);
        setSession({ status: "anonymous" });
        setLoggingOut(false);
    }
    useEffect(() => { const u = () => setOnline(navigator.onLine); addEventListener("online", u); addEventListener("offline", u); return () => { removeEventListener("online", u); removeEventListener("offline", u); }; }, []);
    const changeFront = (next: Front) => { setFrontChoice(next); if (next === "Bobinas" && !GROUPS.Bobinas.includes(machine))
        setMachine(GROUPS.Bobinas[0]); };
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
    // Estado del punto de captura: SOLO la ejecución de producción de Bobinas usa la asignación CENTRAL. Los demás fronts no tienen aquí punto de captura propio (Rebobinado y Conversión viven en SectorCentral;
    // Calidad abre sus capturas desde el inbox y los controles que publica el backend). Nunca hay un contexto local de respaldo.
    let execState: ExecState;
    if (bobinasFront) {
        const resource = activeAssignment.view;
        if (resource.status === "ready")
            execState = { kind: "check", check: contextFromActive(resource.data) };
        else if (resource.status === "error")
            execState = { kind: "error", message: resource.kind === "forbidden" ? "Acceso no permitido." : failureMessage(resource.kind), retry: activeAssignment.refresh };
        else
            execState = { kind: "loading" };
    }
    else
        execState = { kind: "loading" };
    const handleSelect = (f: FormDefinition) => {
        // Un envío F3 incierto se reabre con SU contexto original (mismo assignment_id y capture_id), aunque el selector apunte a otra máquina.
        if (f.id === F3_FORM_ID && f3Attempt) {
            setCaptureContext(null);
            return void setSelected(f);
        }
        if (execState.kind !== "check")
            return void toast.error("Aún se está consultando la asignación activa");
        if (!execState.check.ok)
            return void toast.error(CONTEXT_MESSAGES[execState.check.reason]);
        setCaptureContext(execState.check.context);
        setSelected(f);
    };
    const openCandidate = (screen: BobinasCandidateScreen) => {
        if (execState.kind !== "check") return void toast.error("Aún se está consultando la asignación activa");
        if (!execState.check.ok) return void toast.error(CONTEXT_MESSAGES[execState.check.reason]);
        setBobCandidate({ screen, context: execState.check.context });
    };
    // Calidad · controles por máquina (P1-22 / P1-26): solo API central de Calidad (nunca Capture/save() ni vinto-p1-records ni la asignación activa). Con un intento pendiente se reabre con SU máquina.
    if (qualCapture && front === "Calidad") {
        const screen = qualCapture.screen, pending = qualAttempts[screen];
        return <CandidateFormCapture key={screen} candidate={QUALITY_CANDIDATES[screen]} machine={pending ? pending.machine : qualCapture.machine} online={online} attempt={pending?.attempt ?? null}
            setAttempt={a => setQualAttempts(old => ({ ...old, [screen]: a ? { attempt: a, machine: old[screen]?.machine ?? qualCapture.machine } : undefined }))}
            back={() => setQualCapture(null)} onSubmitted={() => setQualRefresh(n => n + 1)} onAssignmentChanged={() => setQualCapture(null)} onSessionLost={sessionLost} user={user}/>;
    }
    // Bobinas · fichas candidatas centrales (P1-05 / P1-31): solo API central (nunca Capture/save() ni vinto-p1-records). Con un intento pendiente se reabre con SU contexto original.
    if (bobCandidate && front === "Bobinas") {
        const screen = bobCandidate.screen, pending = candAttempts[screen];
        return <CandidateFormCapture key={screen} candidate={BOBINAS_CANDIDATES[screen]} context={pending ? pending.context : bobCandidate.context} online={online} attempt={pending?.attempt ?? null}
            setAttempt={a => setCandAttempts(old => ({ ...old, [screen]: a ? { attempt: a, context: old[screen]?.context ?? bobCandidate.context } : undefined }))}
            back={() => setBobCandidate(null)} onSubmitted={() => setCandRefresh(n => n + 1)} onAssignmentChanged={() => setBobCandidate(null)} onSessionLost={sessionLost} user={user}/>;
    }
    // Rebobinado CENTRAL: P1-10 / P1-29 se envían solo a la API central (nunca Capture/save() ni vinto-p1-records). Con un intento pendiente se reabre con SU contexto original.
    if (rebCapture && front === "Rebobinado" && isRebobinadoCandidate(rebCapture.screen)) {
        const screen = rebCapture.screen, pending = rebCandAttempts[screen];
        return <CandidateFormCapture key={screen} candidate={REBOBINADO_CANDIDATES[screen]} context={pending ? pending.context : rebCapture.context} online={online} attempt={pending?.attempt ?? null}
            setAttempt={a => setRebCandAttempts(old => ({ ...old, [screen]: a ? { attempt: a, context: old[screen]?.context ?? rebCapture.context } : undefined }))}
            back={() => setRebCapture(null)} onSubmitted={() => setRebRefresh(n => n + 1)} onAssignmentChanged={() => setRebCapture(null)} onSessionLost={sessionLost} user={user}/>;
    }
    if (rebCapture && front === "Rebobinado" && rebCapture.screen === "p110")
        return <P110CaptureForm context={p110Attempt && p110Context ? p110Context : rebCapture.context} online={online} attempt={p110Attempt} setAttempt={a => { setP110Attempt(a); setP110Context(a ? (p110Context ?? rebCapture.context) : null); }} back={() => setRebCapture(null)} onSubmitted={() => setRebRefresh(n => n + 1)} onAssignmentChanged={() => setRebCapture(null)} onSessionLost={sessionLost} user={user}/>;
    if (rebCapture && front === "Rebobinado" && rebCapture.screen === "p129")
        return <P129CaptureForm context={p129Attempt && p129Context ? p129Context : rebCapture.context} online={online} attempt={p129Attempt} setAttempt={a => { setP129Attempt(a); setP129Context(a ? (p129Context ?? rebCapture.context) : null); }} back={() => setRebCapture(null)} onSubmitted={() => setRebRefresh(n => n + 1)} onAssignmentChanged={() => setRebCapture(null)} onSessionLost={sessionLost} user={user}/>;
    // Conversión CENTRAL: P1-12 / P1-13 / P1-16 (candidatos, renderizador genérico de campos planos) se envían solo a la API central. Con un intento pendiente se reabre con SU contexto original.
    if (convCapture && front === "Conversión" && isConversionCandidate(convCapture.screen)) {
        const screen = convCapture.screen, pending = convCandAttempts[screen];
        return <CandidateFormCapture key={screen} candidate={CONVERSION_CANDIDATES[screen]} context={pending ? pending.context : convCapture.context} online={online} attempt={pending?.attempt ?? null}
            setAttempt={a => setConvCandAttempts(old => ({ ...old, [screen]: a ? { attempt: a, context: old[screen]?.context ?? convCapture.context } : undefined }))}
            back={() => setConvCapture(null)} onSubmitted={() => setConvRefresh(n => n + 1)} onAssignmentChanged={() => setConvCapture(null)} onSessionLost={sessionLost} user={user}/>;
    }
    // Conversión CENTRAL: P1-11 (candidato, grupo repetible de bobinas declaradas) se envía solo a la API central. Con un intento pendiente se reabre con SU contexto original.
    if (convCapture && front === "Conversión" && convCapture.screen === "p111")
        return <P111CaptureForm context={p111Attempt && p111Context ? p111Context : convCapture.context} online={online} attempt={p111Attempt} setAttempt={a => { setP111Attempt(a); setP111Context(a ? (p111Context ?? convCapture.context) : null); }} back={() => setConvCapture(null)} onSubmitted={() => setConvRefresh(n => n + 1)} onAssignmentChanged={() => setConvCapture(null)} onSessionLost={sessionLost} user={user}/>;
    // F6 NO usa Capture/save(): se envía solo a la API central y no se escribe en vinto-p1-records.
    if (selected && selected.id === F6_FORM_ID && captureContext)
        return <F6Capture context={captureContext} online={online} attempt={f6Attempt} setAttempt={setF6Attempt} back={() => { setSelected(null); setCaptureContext(null); }} onSubmitted={() => { setSelected(null); setCaptureContext(null); f6List.refresh(); }} onAssignmentChanged={() => { setSelected(null); setCaptureContext(null); activeAssignment.refresh(); }} onSessionLost={sessionLost}/>;
    // Calidad · candidato por bobina (P1-21): solo API central de Calidad por bobina (sin guardado local ni la asignación activa). Con un intento pendiente se reabre con SU bobina.
    if (bobbinCand && front === "Calidad" && canReadQualityInbox) {
        const screen = bobbinCand.screen, pending = bobbinCandAttempts[screen];
        return <QualityBobbinCandidateCapture key={screen} screen={screen} item={pending ? pending.item : bobbinCand.item} scope={scope} online={online} attempt={pending?.attempt ?? null}
            setAttempt={a => setBobbinCandAttempts(old => ({ ...old, [screen]: a ? { attempt: a, item: old[screen]?.item ?? bobbinCand.item } : undefined }))}
            back={() => setBobbinCand(null)} user={user} onSessionLost={sessionLost}/>;
    }
    // Calidad · VINTO-P1-19 (central): la Bobina seleccionada del inbox es la autoridad; no usa la asignación activa ni Capture/save().
    if (selectedQualityBobbin)
        return <QualityHumidityCapture item={selectedQualityBobbin} online={online} attempt={humidityAttempt} setAttempt={setHumidityAttempt} back={() => setSelectedQualityBobbin(null)} onSubmitted={() => { setSelectedQualityBobbin(null); qualityInbox.refresh(); }} onSessionLost={sessionLost}/>;
    // Calidad · VINTO-P1-20 (central): como P1-19, la Bobina seleccionada del inbox (o la del intento pendiente) es la autoridad; no usa la asignación activa ni el guardado local de Capture.
    if (selectedPhysicalBobbin && canReadQualityInbox)
        return <QualityPhysicalCapture item={selectedPhysicalBobbin} online={online} attempt={physicalAttempt} setAttempt={setPhysicalAttempt} back={() => setSelectedPhysicalBobbin(null)} onSubmitted={() => { setSelectedPhysicalBobbin(null); qualityInbox.refresh(); }} onSessionLost={sessionLost}/>;
    // Calidad · historial de controles de la Bobina (solo lectura): no usa el formulario editable ni toca el intento pendiente de humedad.
    if (qualityHistory && canReadQualityInbox)
        return <QualityBobbinHistory item={qualityHistory.item} resource={bobbinHistory.view} refresh={bobbinHistory.refresh} back={() => setQualityHistory(null)}/>;
    // F3 tampoco usa Capture/save(): POST /api/bobbins (captura + bobina + Calidad pendiente), sin records ni vinto-p1-records.
    if (selected && selected.id === F3_FORM_ID && (f3Attempt || captureContext))
        return <F3BobbinCapture context={captureContext} online={online} attempt={f3Attempt} setAttempt={setF3Attempt} back={() => { setSelected(null); setCaptureContext(null); }} onSubmitted={() => { setSelected(null); setCaptureContext(null); activeAssignment.refresh(); }} onAssignmentChanged={() => { setSelected(null); setCaptureContext(null); activeAssignment.refresh(); }} onSessionLost={sessionLost}/>;
    // MF-13-02: sin frente que mostrar (accesos en verificación, sin confirmar o sin asignar) NO se dibuja el área operativa; los borradores pendientes se tratan arriba y se conservan en memoria.
    if (access.state.status !== "ready" || fronts.length === 0)
        return <AccessGate state={access.state} user={user} onRetry={access.retry} onLogout={endSession}/>;
    // INT-02A: no existe ruta de captura local. Un formulario seleccionado que no sea F3 / P1-06 (que ya tienen su componente central arriba) no abre nada; nunca se guarda un registro solo en el navegador.
    return <main className="min-h-screen bg-[#f3f6f4] text-slate-950"><Toaster richColors/><header className="sticky top-0 z-30 border-b bg-white/95"><div className="mx-auto flex h-16 max-w-[1600px] items-center justify-between px-4"><Brand /><div className="flex items-center gap-2"><span className="hidden text-right text-sm md:block"><b>{user.display_name}</b><br /><span className="text-slate-600">{ROLE_LABELS[role]}</span></span><Badge variant="outline" className={online ? "border-emerald-300 bg-emerald-50 text-emerald-900" : "border-amber-300 bg-amber-50 text-amber-950"}>{online ? <Wifi className="mr-1 h-3.5 w-3.5"/> : <CloudOff className="mr-1 h-3.5 w-3.5"/>}{online ? "En línea" : "Offline"}</Badge>{hasPermission(user, "user.manage") && <a href="/admin" className="rounded-md px-2 py-1 text-sm font-semibold text-[#146b4f] hover:bg-emerald-50">Administración</a>}<Button variant="ghost" size="icon" aria-label="Cerrar sesión" onClick={endSession}><LogOut className="h-4 w-4"/></Button></div></div></header><div className="mx-auto grid max-w-[1600px] lg:grid-cols-[270px_minmax(0,1fr)]"><aside className="hidden min-h-[calc(100vh-64px)] bg-[#123f32] p-5 text-white lg:block"><SideTitle>Front operativo</SideTitle>{fronts.map(x => <Nav key={x} label={x} active={front === x} click={() => changeFront(x)}/>)}<SideTitle>Módulos</SideTitle><Nav label="Programación" active={activeModule === "programacion"} click={() => setModuleChoice("programacion")} icon={<ClipboardList />}/><Nav label="Ejecución" active={activeModule === "ejecucion"} click={() => setModuleChoice("ejecucion")} icon={<PlayCircle />}/><Nav label="Seguimiento" active={activeModule === "seguimiento"} click={() => setModuleChoice("seguimiento")} icon={<BarChart3 />}/><div className="mt-8 rounded-xl border border-white/15 bg-white/10 p-4 text-sm"><p className="text-emerald-100">Perfil</p><p className="font-bold">{ROLE_LABELS[role]}</p>{roles.length > 1 && <div className="mt-2 flex flex-wrap gap-1">{roles.map(r => <Button key={r} size="sm" variant={r === role ? "default" : "outline"} className="h-7 px-2 text-xs text-slate-950" onClick={() => { setRoleChoice(r); setFrontChoice(null); setModuleChoice(null); }}>{ROLE_LABELS[r]}</Button>)}</div>}<p className="mt-3 text-xs text-emerald-100">Sin Monday Producción. Expertus queda como integración futura.</p></div></aside><section className="min-w-0 p-4 md:p-8"><Badge className="bg-[#146b4f]">MVP To-Be actualizado</Badge><h1 className="mt-3 text-3xl font-black">{front} · {activeModule[0].toUpperCase() + activeModule.slice(1)}</h1><p className="mt-1 text-slate-700">PV → OT multiproducto → línea base → gestión operativa → ejecución → calidad → seguimiento.</p><div className="mt-5 flex gap-2 overflow-x-auto lg:hidden">{fronts.map(x => <Button key={x} variant={front === x ? "default" : "outline"} onClick={() => changeFront(x)}>{x}</Button>)}</div><div className="mt-2 flex gap-2 lg:hidden">{(["programacion", "ejecucion", "seguimiento"] as Module[]).map(x => <Button key={x} variant={activeModule === x ? "default" : "outline"} onClick={() => setModuleChoice(x)} className="capitalize">{x}</Button>)}</div><div className="mt-6">{front === "Conversión" ? <ConversionCentral module={activeModule} canManageOrders={canManageOrders} canManageAssignments={canManageAssignments} canCapture={canCapture} canReadOrders={canReadOrders} canReadAssignments={canReadAssignments} refreshKey={convRefresh} scope={scope} onOpenForm={(screen, context) => setConvCapture({ screen, context })} onSessionLost={sessionLost}/> : front === "Rebobinado" ? <RebobinadoCentral module={activeModule} canManageOrders={canManageOrders} canManageAssignments={canManageAssignments} canCapture={canCapture} canReadOrders={canReadOrders} canReadAssignments={canReadAssignments} refreshKey={rebRefresh} scope={scope} onOpenForm={(screen, context) => setRebCapture({ screen, context })} onSessionLost={sessionLost}/> : <>{activeModule === "programacion" && (bobinasFront ? <BobbinasProgramming machines={GROUPS.Bobinas} workOrders={workOrders.view} onChanged={refreshCentral} onSessionLost={sessionLost} canManageOrders={canManageOrders} canManageAssignments={canManageAssignments}/> : <QualityProgrammingNote/>)} {activeModule === "ejecucion" && <Execution front={front} machine={machine} machines={bobMachines} setMachine={setMachine} forms={CENTRAL_BOBINAS_FORMS.filter(f => applies(f, machine) && offersForm(bobEligibleMachine, f.id === F3_FORM_ID ? F3_CODE : F6_CODE))} select={handleSelect} canCapture={canCapture} online={online} qualityInbox={canReadQualityInbox ? <QualityBobbinInbox resource={qualityInbox.view} refresh={qualityInbox.refresh} onRegisterHumidity={item => setSelectedQualityBobbin(humidityAttempt ? humidityAttempt.bobbin : item)} onRegisterProperties={item => setSelectedPhysicalBobbin(physicalAttempt ? physicalAttempt.bobbin : item)} onViewHistory={openQualityHistory} candidateOffers={bobbinOffers} actionOffers={m => qualityBobbinActions(access.qualityBobbin.status === "ready" ? access.qualityBobbin.data : null, m)} onRegisterCandidate={(screen, item) => setBobbinCand({ screen, item })}/> : <Panel title="Bobinas pendientes de Calidad" note="Tu perfil no tiene acceso al inbox de Calidad."><p className="text-sm text-slate-700">Solo lectura para el perfil de Calidad.</p></Panel>} banner={<ContextBanner state={execState} machine={machine} showProgrammedQuantity/>} machineControls={front === "Calidad" ? <QualityMachineControls scope={scope} canCapture={canReadQualityInbox} mode="execution" refreshKey={qualRefresh} onOpen={(screen, m) => setQualCapture({ screen, machine: m })} onSessionLost={sessionLost}/> : undefined} candidates={bobinasFront ? <BobinasCandidateCards offered={offeredCandidates(bobEligible, machine)} canCapture={canCapture} onOpen={openCandidate}/> : undefined}/>} {activeModule === "seguimiento" && (bobinasFront ? (workOrders.view.status === "ready" && centralAssignments.view.status === "ready"
                ? <><Tracking front={front} ots={workOrders.view.data.map(toDisplayOt)} asg={centralAssignments.view.data.map(toDisplayAssignment)} userKey={user.id} onSessionLost={sessionLost}/>{canReadCaptures && <div className="mt-6"><CentralCaptures resource={f6List.view} refresh={f6List.refresh}/></div>}{canReadCaptures && publishedCand.map(screen => <div key={screen} className="mt-6"><CandidateHistory candidate={BOBINAS_CANDIDATES[screen]} resource={candHistory[screen].view} refresh={candHistory[screen].refresh}/></div>)}</>
                : <CentralStatus state={workOrders.view.status !== "ready" ? workOrders.view : centralAssignments.view} onRetry={refreshCentral}/>)
            : <><QualityTrackingPending/><QualityMachineControls scope={scope} canCapture={canReadQualityInbox} mode="tracking" refreshKey={qualRefresh} onOpen={(screen, m) => setQualCapture({ screen, machine: m })} onSessionLost={sessionLost}/></>)}</>}</div></section></div></main>;
}
// Calidad no programa ni prioriza aquí: las bobinas pendientes salen del inbox central de Ejecución.
function QualityProgrammingNote() { return <Panel title="Bobinas de Calidad" note="Las bobinas pendientes se gestionan desde Ejecución."><p className="text-sm text-slate-700">El listado sale del inbox central de Calidad (PostgreSQL); aquí no se programa ni se prioriza.</p></Panel>; }
function Execution({ front, machine, machines, setMachine, forms, select, canCapture, online, banner, qualityInbox, candidates, machineControls }: {
    front: Front;
    machine: string;
    machines: string[]; // MF-13-02: máquinas de Bobinas con algún formulario elegible (backend); sin ninguna no se ofrece punto de captura
    setMachine: (x: string) => void;
    forms: FormDefinition[];
    select: (x: FormDefinition) => void;
    canCapture: boolean;
    online: boolean;
    banner: React.ReactNode;
    qualityInbox: React.ReactNode; // Calidad: inbox CENTRAL de bobinas; sin acciones locales de liberar/rechazar
    candidates?: React.ReactNode; // Bobinas: fichas candidatas centrales que el backend publica para la máquina (DEV-B1)
    machineControls?: React.ReactNode; // Calidad: controles por máquina candidatos que el backend publica (DEV-Q1)
}) {
    const deny = () => { toast.error("Tu perfil no tiene permiso para capturar en este frente"); };
    const notice = !canCapture && <div className="mb-4 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">Tu perfil puede consultar este frente, pero no capturar en él.</div>;
    // INT-02A: sin conexión no se puede registrar; NO se guarda nada en el navegador (no hay captura offline aprobada por VINTO).
    const offline = !online && <div role="status" className="mb-4 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950" data-section="offline">Sin conexión: no es posible registrar capturas. Nada se guarda en este navegador; reintenta cuando vuelva la conexión.</div>;
    if (front === "Calidad")
        return <div className="space-y-5">{offline}{qualityInbox}{machineControls}{notice}</div>;
    return <>
        <Panel title="Punto de captura" note="Máquina fija por equipo; OT y producto llegan desde Supervisión (asignación central).">
            <div className="flex flex-wrap gap-2">{machines.map(m => <Button key={m} size="sm" variant={machine === m ? "default" : "outline"} className={machine === m ? "bg-[#146b4f]" : ""} onClick={() => setMachine(m)}>{m}</Button>)}{machines.length === 0 && <p className="text-sm text-slate-700" data-section="no-eligible-machines">No tienes formularios de Bobinas habilitados en este momento.</p>}</div>
        </Panel>
        {banner}{offline}{candidates}
        <div className="mt-5">{notice}<Cards forms={forms} select={canCapture ? select : deny}/></div>
    </>;
}
function Cards({ forms, select }: {
    forms: FormDefinition[];
    select: (f: FormDefinition) => void;
}) { return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{forms.map(f => <button key={f.id} data-form={f.id} onClick={() => select(f)} className="rounded-2xl border bg-white p-5 text-left shadow-sm hover:border-emerald-400"><Badge variant="outline" className="border-emerald-300 text-emerald-900">{FLOW[f.id]?.[1] || "Paso operativo"}</Badge><h3 className="mt-4 font-black">{f.name}</h3><p className="mt-2 text-sm text-slate-700">{f.machineLabel}</p><p className="mt-4 border-t pt-3 text-xs font-semibold text-emerald-800">Captura central (PostgreSQL) con la asignación activa</p></button>)}</div>; }
function Tracking({ front, ots, asg, userKey, onSessionLost }: {
    userKey: string;
    onSessionLost: () => void;
    front: Front;
    ots: DisplayOt[];
    asg: DisplayAssignment[];
}) {
    // INT-02A: `ots` y `asg` son los CENTRALES. No se leen, muestran, descargan ni suman registros locales del navegador (vinto-p1-records); un indicador sin fuente central se marca Pendiente, nunca un cero ficticio.
    const visible = ots.filter(o => o.sector === front);
    return <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-4">
            <Metric label="OT visibles" value={visible.length}/>
            <Metric label="Líneas PV/producto" value={visible.reduce((s, o) => s + o.lines.length, 0)}/>
            <CaptureCount front={front} userKey={userKey} onSessionLost={onSessionLost}/>
            <PendingMetric label="Bobinas liberadas" note="Sin fuente central: el servicio de liberación y rechazo todavía no existe. No se muestra ningún valor."/>
        </div>
        <Panel title="Programado base vs operativo" note="La gestión de Supervisión no sobrescribe la línea base publicada por Jefatura. El conteo de capturas centrales por OT todavía no está disponible."><div className="overflow-x-auto"><table className="w-full min-w-[800px] text-sm"><thead className="bg-slate-50 text-left"><tr><th className="p-3">OT</th><th className="p-3">PV</th><th className="p-3">Producto</th><th className="p-3">Base</th><th className="p-3">Asignación</th></tr></thead><tbody>{visible.flatMap(o => o.lines.map(l => <tr key={`${o.id}${l.id}`} className="border-t"><td className="p-3 font-bold">{o.id} · {l.id}</td><td className="p-3">{l.pv}</td><td className="p-3">{l.productName}</td><td className="p-3">{l.quantity} {l.unit}</td><td className="p-3">{asg.some(a => a.ot === o.id && a.line === l.id && a.status === "Activa") ? "Activa" : "—"}</td></tr>))}</tbody></table></div></Panel>
        <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Genealogía y calidad" note="Funcionalidad pendiente."><PendingNotice>La genealogía y el estado de liberación de las bobinas todavía no tienen fuente central, por lo que no se muestran datos. El estado de Calidad de cada bobina se consulta en Calidad › Ejecución.</PendingNotice></Panel>
            <Panel title="Reportes" note="Todavía no existen reportes centrales: solo están definidos por nombre y no se generan."><div className="space-y-2">{REPORT_DEFINITIONS.map(r => <div key={r.id} className="flex items-center justify-between gap-3 rounded-lg border p-3 font-semibold"><span>{r.name}</span><Badge variant="outline">Pendiente</Badge></div>)}</div></Panel>
        </div>
    </div>;
}

// ======================================================================================================================================================================================
// INT-02A · FUENTE LEGACY DE LA SIEMBRA DE DATOS — INERTE (no es una ruta operativa)
//
// scripts/export-seed-data.mjs (y backend/seed_data/manifest.json, que NO se modifica en INT-02A) extraen de ESTE archivo, por texto, valores que alimentan la siembra aprobada: las máquinas de GROUPS, los
// overrides de etiquetas / unidades de F6, P1-19 y P1-20 dentro de effectiveForms(), los selectores de BobbinBales y la regla de turno nocturno de ctx(). Retirarlos cambiaría la huella de la siembra.
// Por eso se CONSERVAN, byte a byte en su contenido semántico, pero NINGUNA pantalla los usa: no se llaman desde Home, no generan OT, asignaciones ni capturas y no leen ni escriben localStorage.
// Pendiente (INT-02B / siembra): mover esta fuente a un módulo propio con un cambio de manifiesto aprobado y retirar este bloque.
// ======================================================================================================================================================================================
/* eslint-disable @typescript-eslint/no-unused-vars */
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
            // F3 central (POST /api/bobbins): solo los seis campos manuales. Fecha, turno, máquina, operador, código de bobina,
            // producto, gramaje y OT/PV/línea los deriva el backend; ya no hay codigo_tubete ni gramaje/descripción manuales.
            return { ...f, version: f.version + 1, fields: [fld("hora_inicio", "Hora inicio", "time"), fld("hora_fin", "Hora fin", "time"), fld("diametro", "Diámetro", "decimal", true, "mm"), fld("peso_kg", "Peso", "decimal", true, "kg"), fld("numero_de_cortes", "Número de cortes", "text"), fld("observaciones", "Observaciones", "textarea", false)] };
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
function BobbinBales({v,set}:{v:Record<string,string|number|boolean>;set:(k:string,x:string|number)=>void}){return <Section title="Control de fardos" note="Línea genérica para bobina rechazada o recorte de máquina."><div className="grid gap-5 md:grid-cols-2"><SelectBox label="Cantidad de fardos" type="number" value={v.cantidad_fardos} set={x=>set("cantidad_fardos",x)}/><Choice label="Punto de merma" value={v.punto_merma} set={x=>set("punto_merma",x)} options={["Bobina rechazada","Recorte de máquina"]}/><Choice label="Tipo de producto" value={v.tipo_producto} set={x=>set("tipo_producto",x)} options={["Servilleta","Hoja doble","Hoja simple"]}/><SelectBox label="Peso real total" type="number" value={v.peso_kg} set={x=>set("peso_kg",x)} suffix="kg"/></div></Section>}function Section({title,note,children}:{title:string;note:string;children:React.ReactNode}){return <div className="border-b p-6"><h2 className="font-black">{title}</h2><p className="mb-4 text-sm text-slate-700">{note}</p>{children}</div>}function Choice({label,value,set,options}:{label:string;value:string|number|boolean|undefined;set:(x:string)=>void;options:string[]}){return <div><Label>{label} *</Label><select className="mt-2 h-10 w-full rounded-md border bg-white px-3 text-slate-950" value={String(value||"")} onChange={e=>set(e.target.value)}><option value="">Seleccionar…</option>{options.map(x=><option key={x} value={x}>{x}</option>)}</select></div>}function SelectBox({label,value,set,type="text",suffix}:{label:string;value:string|number|boolean|undefined;set:(x:string)=>void;type?:string;suffix?:string}){return <div><Label>{label} *</Label><div className="relative"><Input className="mt-2 text-slate-950" type={type} step={type==="number"?"any":undefined} value={String(value??"")} onChange={e=>set(e.target.value)}/>{suffix&&<span className="absolute right-3 top-4 text-sm font-semibold text-slate-600">{suffix}</span>}</div></div>}/* eslint-enable @typescript-eslint/no-unused-vars */
function SideTitle({ children }: {
    children: React.ReactNode;
}) { return <p className="mb-2 mt-6 text-xs font-bold uppercase tracking-[.18em] text-emerald-200 first:mt-0">{children}</p>; }
function Nav({ label, active, click, icon }: {
    label: string;
    active: boolean;
    click: () => void;
    icon?: React.ReactNode;
}) { return <button onClick={click} className={`mb-1 flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold ${active ? "bg-white text-[#123f32]" : "text-emerald-50 hover:bg-white/10"}`}><span className="[&>svg]:h-4 [&>svg]:w-4">{icon}</span>{label}</button>; }
function Metric({ label, value }: {
    label: string;
    value: number;
}) { return <div className="rounded-2xl border bg-white p-5"><p className="text-sm text-slate-700">{label}</p><p className="mt-2 text-3xl font-black">{value}</p></div>; }
