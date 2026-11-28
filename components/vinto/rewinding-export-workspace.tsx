"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CentralStatus } from "@/components/vinto/central-status";
import { RewindingExportHistory } from "@/components/vinto/rewinding-export-history";
import { Panel } from "@/components/vinto/panels";
import { failureMessage } from "@/lib/vinto/orders";
import { useResource } from "@/lib/vinto/use-central";
import {
    addRewindingExportPackage,
    createRewindingExportDraft,
    discardRewindingExportDraft,
    getRewindingExportDraft,
    generateRewindingExport,
    saveRewindingExportPdf,
    listRewindingExportChildren,
    listRewindingExportDrafts,
    listRewindingExportMothers,
    listRewindingExportProducts,
    listRewindingExportPvs,
    previewRewindingExportDraft,
    removeRewindingExportPackage,
    updateRewindingExportDraft,
    updateRewindingExportPackage,
} from "@/lib/vinto/rewinding-export-api";
import {
    REWINDING_EXPORT_SLOTS,
    buildRewindingExportDraftPayload,
    buildRewindingExportPackagePayload,
    formatRewindingExportCuts,
    formatRewindingExportFormat,
    rewindingExportChildLabel,
    rewindingExportContextDifferences,
    validateRewindingExportPackage,
    type RewindingExportDraft,
    type RewindingExportPackage,
    type RewindingExportPreview,
    type RewindingExportSelection,
    type RewindingExportSlot,
} from "@/lib/vinto/rewinding-export";

type Props = {
    scope: string;
    canCreate: boolean;
    canReadOwn: boolean;
    onSessionLost: () => void;
};

const EMPTY_PACKAGES: RewindingExportPackage[] = [];
const emptySelection = (): RewindingExportSelection => ({});
const isFailure = (result: { ok: boolean; kind?: string }, onSessionLost: () => void): string => {
    if (result.ok) return "";
    if (result.kind === "session") {
        onSessionLost();
        return "La sesión dejó de ser válida.";
    }
    if (result.kind === "forbidden") return "Tu usuario no tiene permiso para esta operación.";
    return result.kind ? failureMessage(result.kind as Parameters<typeof failureMessage>[0]) : "No se pudo completar la operación.";
};

export function RewindingExportWorkspace({ scope, canCreate, canReadOwn, onSessionLost }: Props) {
    const pvs = useResource("rewinding-export-pvs:" + scope, canCreate, signal => listRewindingExportPvs(signal), onSessionLost, true);
    const [pvReference, setPvReference] = useState("");
    const products = useResource("rewinding-export-products:" + scope + ":" + pvReference, canCreate && pvReference !== "",
        signal => listRewindingExportProducts(pvReference, signal), onSessionLost, true);
    const [articleId, setArticleId] = useState("");
    const mothers = useResource("rewinding-export-mothers:" + scope + ":" + pvReference + ":" + articleId,
        canCreate && pvReference !== "" && articleId !== "",
        signal => listRewindingExportMothers(pvReference, articleId, signal), onSessionLost, true);
    const [motherCaptureId, setMotherCaptureId] = useState("");
    const children = useResource("rewinding-export-children:" + scope + ":" + motherCaptureId,
        canCreate && motherCaptureId !== "", signal => listRewindingExportChildren(motherCaptureId, signal), onSessionLost, true);
    const drafts = useResource("rewinding-export-drafts:" + scope, canReadOwn, signal => listRewindingExportDrafts(signal), onSessionLost);

    const [draft, setDraft] = useState<RewindingExportDraft | null>(null);
    const [truckNumber, setTruckNumber] = useState("");
    const [orderNumber, setOrderNumber] = useState("");
    const [observations, setObservations] = useState("");
    const [selection, setSelection] = useState<RewindingExportSelection>(emptySelection);
    const [editingPackageId, setEditingPackageId] = useState<string | null>(null);
    const [removeCandidate, setRemoveCandidate] = useState<RewindingExportPackage | null>(null);
    const [discardOpen, setDiscardOpen] = useState(false);
    const [preview, setPreview] = useState<RewindingExportPreview | null>(null);
    const [busy, setBusy] = useState(false);
    const [actionError, setActionError] = useState("");
    const [notice, setNotice] = useState("");
    const inFlight = useRef(false);
    const generationKey = useRef<string | null>(null);
    const generation = useRef<AbortController | null>(null);
    useEffect(() => () => generation.current?.abort(), []);
    const [generationOpen, setGenerationOpen] = useState(false);
    const [generationPending, setGenerationPending] = useState(false);
    const [historyVersion, setHistoryVersion] = useState(0);

    const packageList = draft?.packages ?? EMPTY_PACKAGES;
    const selectedMother = mothers.view.status === "ready"
        ? mothers.view.data.find(item => item.mother_capture_id === motherCaptureId) ?? null
        : null;
    const editingPackage = packageList.find(item => item.id === editingPackageId) ?? null;
    const usedChildIds = useMemo(() => new Set(packageList
        .filter(item => item.id !== editingPackageId)
        .flatMap(item => item.children.map(child => child.bobbin_id))), [packageList, editingPackageId]);
    const childOptions = children.view.status === "ready" ? children.view.data : [];
    const availableForSlots = childOptions.filter(child => child.mother_capture_id === motherCaptureId && !usedChildIds.has(child.bobbin_id));
    const selectedCount = REWINDING_EXPORT_SLOTS.filter(slot => Boolean(selection[slot])).length;
    const contextReference = packageList.find(item => item.id !== editingPackageId)?.mother ?? null;
    const contextDifferences = selectedMother && contextReference
        ? rewindingExportContextDifferences(contextReference, selectedMother)
        : [];
    const canEditDraft = canCreate && draft?.status === "draft";

    function setSlot(slot: RewindingExportSlot, value: string) {
        setSelection(previous => ({ ...previous, [slot]: value || undefined }));
        setPreview(null);
        setActionError("");
        setNotice("");
    }
    function resetPackageEditor() {
        setMotherCaptureId("");
        setSelection(emptySelection());
        setEditingPackageId(null);
        setActionError("");
    }
    function applyDraft(value: RewindingExportDraft) {
        setDraft(value);
        setPvReference(value.pv_reference);
        setArticleId(value.article.id);
        setTruckNumber(value.truck_number);
        setOrderNumber(value.order_number);
        setObservations(value.observations);
        setPreview(null);
        setNotice("Borrador cargado desde el servidor.");
        setActionError("");
        resetPackageEditor();
    }
    async function runAction(action: () => Promise<void>) {
        if (inFlight.current) return;
        inFlight.current = true;
        setBusy(true);
        setActionError("");
        setNotice("");
        try {
            await action();
        } catch (error) {
            setActionError(error instanceof Error ? error.message : "No se pudo completar la operación.");
        } finally {
            inFlight.current = false;
            setBusy(false);
        }
    }
    async function saveHeader(reportId: string): Promise<RewindingExportDraft | null> {
        const result = await updateRewindingExportDraft(reportId, {
            truck_number: truckNumber.trim(),
            order_number: orderNumber.trim(),
            observations,
        });
        if (!result.ok) {
            setActionError(isFailure(result, onSessionLost));
            return null;
        }
        setDraft(result.data);
        setPreview(null);
        return result.data;
    }
    async function openDraft(reportId: string) {
        await runAction(async () => {
            const result = await getRewindingExportDraft(reportId);
            if (!result.ok) throw new Error(isFailure(result, onSessionLost));
            applyDraft(result.data);
        });
    }
    async function addOrUpdatePackage() {
        if (!selectedMother || children.view.status !== "ready") {
            setActionError("Selecciona una bobina madre y espera a que se carguen sus crías.");
            return;
        }
        const errors = validateRewindingExportPackage({
            mother: selectedMother,
            availableChildren: availableForSlots,
            selection,
            existingPackages: packageList,
            editingPackageId,
        });
        if (errors.length) {
            setActionError(errors.join(" "));
            return;
        }
        if (contextDifferences.length) {
            setActionError("No se puede mezclar en un mismo reporte: " + contextDifferences.join(", ") + ". Selecciona una madre con el mismo contexto.");
            return;
        }
        const payload = buildRewindingExportPackagePayload({ mother: selectedMother, availableChildren: availableForSlots, selection });
        await runAction(async () => {
            let currentDraft = draft;
            if (!currentDraft) {
                const create = await createRewindingExportDraft(buildRewindingExportDraftPayload({
                    pv_reference: pvReference, article_id: articleId, truck_number: truckNumber,
                    order_number: orderNumber, observations,
                }));
                if (!create.ok) throw new Error(isFailure(create, onSessionLost));
                currentDraft = create.data;
                setDraft(currentDraft);
                drafts.refresh();
            } else {
                const saved = await saveHeader(currentDraft.id);
                if (!saved) throw new Error("No se pudo guardar la cabecera del borrador.");
                currentDraft = saved;
            }
            const result = editingPackageId
                ? await updateRewindingExportPackage(currentDraft.id, editingPackageId, payload)
                : await addRewindingExportPackage(currentDraft.id, payload);
            if (!result.ok) throw new Error(isFailure(result, onSessionLost));
            setDraft(result.data);
            setPreview(null);
            drafts.refresh();
            resetPackageEditor();
            setNotice(editingPackageId ? "Paquete actualizado en el borrador." : "Paquete agregado al borrador.");
        });
    }
    async function beginEditPackage(item: RewindingExportPackage) {
        setPreview(null);
        setEditingPackageId(item.id);
        setMotherCaptureId(item.mother_capture_id);
        const next: RewindingExportSelection = {};
        for (const child of item.children) next[child.package_slot] = child.bobbin_id;
        setSelection(next);
        setActionError("");
        setNotice("Editando el paquete " + item.package_number + ". Las crías se volverán a validar al guardar.");
    }
    async function confirmRemovePackage() {
        if (!draft || !removeCandidate) return;
        await runAction(async () => {
            const result = await removeRewindingExportPackage(draft.id, removeCandidate.id);
            if (!result.ok) throw new Error(isFailure(result, onSessionLost));
            setDraft(result.data);
            setRemoveCandidate(null);
            setPreview(null);
            if (editingPackageId === removeCandidate.id) resetPackageEditor();
            drafts.refresh();
            setNotice("Paquete retirado del borrador. La disponibilidad se volverá a consultar al seleccionar crías.");
        });
    }
    async function savePreview() {
        if (!draft) return;
        await runAction(async () => {
            const saved = await saveHeader(draft.id);
            if (!saved) throw new Error("No se pudo guardar la cabecera antes de validar.");
            const result = await previewRewindingExportDraft(saved.id);
            if (!result.ok) throw new Error(isFailure(result, onSessionLost));
            setPreview(result.data);
            setNotice(result.data.valid
                ? "Vista previa validada. Puedes confirmar la generación del PDF."
                : "La vista previa detectó condiciones que debes revisar.");
        });
    }
    async function confirmGeneration() {
        if (!canCreate || !draft || !preview?.valid || !generationOpen || inFlight.current) return;
        const reportId = draft.id;
        await runAction(async () => {
            generationKey.current ??= crypto.randomUUID();
            const controller = new AbortController();
            generation.current = controller;
            try {
                const result = await generateRewindingExport(reportId, generationKey.current, controller.signal);
                if (controller.signal.aborted) return;
                if (!result.ok) {
                    const uncertain = result.status === 0 || result.status >= 500 || result.status === 200;
                    setGenerationPending(uncertain);
                    if (uncertain) {
                        setHistoryVersion(version => version + 1);
                        throw new Error("No se pudo confirmar la respuesta. Reintenta con la misma solicitud o consulta el historial.");
                    }
                    generationKey.current = null;
                    setGenerationOpen(false);
                    setPreview(null);
                    drafts.refresh();
                    setHistoryVersion(version => version + 1);
                    throw new Error(result.status === 413 ? "El PDF supera 25 MiB." : isFailure(result, onSessionLost));
                }
                generationKey.current = null;
                setGenerationPending(false);
                setGenerationOpen(false);
                startNewDraft();
                drafts.refresh();
                pvs.refresh();
                products.refresh();
                mothers.refresh();
                children.refresh();
                setHistoryVersion(version => version + 1);
                setNotice("El PDF original está disponible en Mis reportes de exportación.");
                saveRewindingExportPdf(reportId, result.data);
            } catch (error) {
                if (!controller.signal.aborted) throw error;
            } finally {
                generation.current = null;
            }
        });
    }
    async function discardDraft() {
        if (!draft) return;
        await runAction(async () => {
            const result = await discardRewindingExportDraft(draft.id);
            if (!result.ok) throw new Error(isFailure(result, onSessionLost));
            setDraft(null);
            setDiscardOpen(false);
            setPreview(null);
            setTruckNumber("");
            setOrderNumber("");
            setObservations("");
            resetPackageEditor();
            drafts.refresh();
            setNotice("Borrador descartado. No se reservaron crías.");
        });
    }
    function startNewDraft() {
        setDraft(null);
        setPvReference("");
        setArticleId("");
        setTruckNumber("");
        setOrderNumber("");
        setObservations("");
        setPreview(null);
        resetPackageEditor();
    }

    if (!canCreate && !canReadOwn) return null;

    return (
        <div className="mt-6 space-y-5" data-rewinding-export="workspace">
            <Panel title="Reporte de Bobinas Refiladas para Exportación"
                note="Selecciona PV, producto, bobina madre y crías liberadas por Calidad. Las crías se reservan al confirmar la generación del PDF.">
                <fieldset disabled={generationOpen}>
                {canReadOwn ? (
                    <div className="mb-5 rounded-xl border bg-slate-50 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <h3 className="font-bold">Mis borradores</h3>
                                <p className="text-xs text-slate-600">Se recuperan desde el servidor; no se guardan en el navegador.</p>
                            </div>
                            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={drafts.refresh}>Actualizar</Button>
                        </div>
                        {drafts.view.status === "loading" || drafts.view.status === "idle" ? (
                            <p className="mt-3 text-sm text-slate-600" role="status">Consultando borradores…</p>
                        ) : drafts.view.status === "error" ? (
                            <div className="mt-3"><CentralStatus state={drafts.view} onRetry={drafts.refresh} title="No se pudieron consultar los borradores"/></div>
                        ) : drafts.view.data.length === 0 ? (
                            <p className="mt-3 text-sm text-slate-600">No tienes borradores pendientes.</p>
                        ) : (
                            <ul className="mt-3 divide-y">
                                {drafts.view.data.map(item => (
                                    <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                                        <div className="text-sm">
                                            <p className="font-semibold">{item.pv_reference} · {item.article_code}</p>
                                            <p className="text-xs text-slate-600">{item.machine_code ?? "Máquina pendiente"} · {item.package_count} paquetes · {new Date(item.created_at).toLocaleString("es-PE", { timeZone: "America/La_Paz" })}</p>
                                        </div>
                                        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void openDraft(item.id)}>
                                            {draft?.id === item.id ? "Borrador abierto" : "Abrir borrador"}
                                        </Button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                ) : null}

                {draft ? (
                    <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                        <div>
                            <Badge className="bg-emerald-700">Borrador abierto</Badge>
                            <p className="mt-1 text-sm font-semibold">{draft.pv_reference} · {draft.article.code}</p>
                            <p className="text-xs text-slate-700">ID técnico: {draft.id}</p>
                        </div>
                        <Button type="button" variant="outline" size="sm" disabled={busy || !canCreate} onClick={startNewDraft}>Nuevo reporte</Button>
                    </div>
                ) : null}

                {canCreate ? (
                    <div className="space-y-5">
                        <section aria-labelledby="rbe-context-title">
                            <h3 id="rbe-context-title" className="font-bold">1. Contexto del reporte</h3>
                            <div className="mt-3 grid gap-4 md:grid-cols-3">
                                <div>
                                    <Label htmlFor="rbe-pv">PV *</Label>
                                    <select id="rbe-pv" className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm" value={pvReference}
                                        disabled={busy || Boolean(draft) || pvs.view.status !== "ready"} onChange={event => {
                                            setPvReference(event.target.value); setArticleId(""); setMotherCaptureId(""); setSelection(emptySelection()); setPreview(null);
                                        }}>
                                        <option value="">Seleccionar PV…</option>
                                        {pvs.view.status === "ready" ? pvs.view.data.map(item => <option key={item.pv_reference} value={item.pv_reference}>{item.pv_reference} · {item.eligible_mothers} madres elegibles</option>) : null}
                                    </select>
                                    {pvs.view.status === "loading" ? <p className="mt-1 text-xs text-slate-600" role="status">Consultando PV con crías elegibles…</p> : null}
                                    {pvs.view.status === "error" ? <p className="mt-1 text-xs text-red-700">{pvs.view.kind === "forbidden" ? "Acceso no permitido." : failureMessage(pvs.view.kind)}</p> : null}
                                    {pvs.view.status === "ready" && pvs.view.data.length === 0 ? <p className="mt-1 text-xs text-slate-600">No hay PV con madres que tengan crías elegibles.</p> : null}
                                </div>
                                <div>
                                    <Label htmlFor="rbe-product">Producto *</Label>
                                    <select id="rbe-product" className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm" value={articleId}
                                        disabled={busy || Boolean(draft) || !pvReference || products.view.status !== "ready"} onChange={event => {
                                            setArticleId(event.target.value); setMotherCaptureId(""); setSelection(emptySelection()); setPreview(null);
                                        }}>
                                        <option value="">Seleccionar producto…</option>
                                        {products.view.status === "ready" ? products.view.data.map(item => <option key={item.article_id} value={item.article_id}>{item.code} · {item.description}</option>) : null}
                                    </select>
                                    {products.view.status === "loading" ? <p className="mt-1 text-xs text-slate-600">Consultando productos del PV…</p> : null}
                                    {products.view.status === "error" ? <p className="mt-1 text-xs text-red-700">{products.view.kind === "forbidden" ? "Acceso no permitido." : failureMessage(products.view.kind)}</p> : null}
                                    {products.view.status === "ready" && products.view.data.length === 0 ? <p className="mt-1 text-xs text-slate-600">Este PV no tiene productos con crías elegibles.</p> : null}
                                </div>
                                <div>
                                    <Label htmlFor="rbe-mother">Bobina madre *</Label>
                                    <select id="rbe-mother" className="mt-1 h-10 w-full rounded-md border bg-white px-3 text-sm" value={motherCaptureId}
                                        disabled={busy || Boolean(editingPackageId) || !articleId || mothers.view.status !== "ready"} onChange={event => {
                                            setMotherCaptureId(event.target.value); setSelection(emptySelection()); setEditingPackageId(null); setPreview(null);
                                        }}>
                                        <option value="">Seleccionar madre…</option>
                                        {mothers.view.status === "ready" ? mothers.view.data.map(item => (
                                            <option key={item.mother_capture_id} value={item.mother_capture_id}>
                                                {item.mother_label} · {item.machine.code} · {item.operating_date} · {item.work_order.number}
                                            </option>
                                        )) : null}
                                    </select>
                                    {mothers.view.status === "loading" ? <p className="mt-1 text-xs text-slate-600">Consultando madres del PV y producto…</p> : null}
                                    {mothers.view.status === "error" ? <p className="mt-1 text-xs text-red-700">{mothers.view.kind === "forbidden" ? "Acceso no permitido." : failureMessage(mothers.view.kind)}</p> : null}
                                    {mothers.view.status === "ready" && mothers.view.data.length === 0 ? <p className="mt-1 text-xs text-slate-600">No hay madres elegibles para este PV y producto.</p> : null}
                                </div>
                            </div>
                        </section>

                        {selectedMother ? (
                            <section className="rounded-xl border bg-slate-50 p-4" aria-labelledby="rbe-mother-details">
                                <h3 id="rbe-mother-details" className="font-bold">Datos automáticos de la madre</h3>
                                <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                                    <div><dt className="text-xs text-slate-500">Máquina</dt><dd className="font-semibold">{selectedMother.machine.code}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Destino</dt><dd className="font-semibold">{selectedMother.destination}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Formato</dt><dd className="font-semibold">{formatRewindingExportFormat(selectedMother)}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Cortes</dt><dd className="font-semibold">{formatRewindingExportCuts(selectedMother)}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Diámetro</dt><dd className="font-semibold">{selectedMother.diametro}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Tubete</dt><dd className="font-semibold">{selectedMother.tubete}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Ayudante</dt><dd className="font-semibold">{selectedMother.ayudante ?? "—"}</dd></div>
                                    <div><dt className="text-xs text-slate-500">Operador original</dt><dd className="font-semibold">{selectedMother.operator?.display_name ?? "No resuelto; no se podrá generar"}</dd></div>
                                </dl>
                                {children.view.status === "loading" ? <p className="mt-3 text-sm text-slate-600" role="status">Consultando crías liberadas y disponibles…</p> : null}
                                {children.view.status === "error" ? <p className="mt-3 text-sm text-red-700" role="alert">{children.view.kind === "forbidden" ? "Acceso no permitido." : failureMessage(children.view.kind)}</p> : null}
                                {children.view.status === "ready" && children.view.data.length === 0 ? <p className="mt-3 text-sm text-slate-600">Esta madre no tiene crías liberadas y disponibles.</p> : null}
                            </section>
                        ) : null}

                        {selectedMother && children.view.status === "ready" ? (
                            <section aria-labelledby="rbe-package-title">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                        <h3 id="rbe-package-title" className="font-bold">2. Conformar paquete</h3>
                                        <p className="text-xs text-slate-600">Cría A obligatoria; B–E opcionales. Cada cría se muestra con su posición y peso de origen.</p>
                                    </div>
                                    {editingPackage ? <Badge variant="outline">Editando paquete {editingPackage.package_number}</Badge> : null}
                                </div>
                                <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                                    {REWINDING_EXPORT_SLOTS.map(slot => {
                                        const selectedInOtherSlot = new Set(REWINDING_EXPORT_SLOTS
                                            .filter(other => other !== slot)
                                            .flatMap(other => selection[other] ? [selection[other] as string] : []));
                                        const options = availableForSlots.filter(child => !selectedInOtherSlot.has(child.bobbin_id) || child.bobbin_id === selection[slot]);
                                        return (
                                            <div key={slot}>
                                                <Label htmlFor={"rbe-child-" + slot}>Cría {slot}{slot === "A" ? " *" : ""}</Label>
                                                <select id={"rbe-child-" + slot} className="mt-1 h-10 w-full rounded-md border bg-white px-2 text-sm"
                                                    value={selection[slot] ?? ""} disabled={busy}
                                                    onChange={event => setSlot(slot, event.target.value)}>
                                                    <option value="">Sin seleccionar</option>
                                                    {options.map(child => (
                                                        <option key={child.bobbin_id} value={child.bobbin_id}>{rewindingExportChildLabel(child)}</option>
                                                    ))}
                                                </select>
                                            </div>
                                        );
                                    })}
                                </div>
                                <div className="mt-3 flex flex-wrap items-center gap-3">
                                    <span className="text-xs text-slate-600">{selectedCount} de 5 crías seleccionadas</span>
                                    <Button type="button" className="bg-[#146b4f]" disabled={busy || !canCreate} onClick={() => void addOrUpdatePackage()}>
                                        {busy ? "Guardando…" : editingPackage ? "Guardar cambios del paquete" : "Agregar paquete"}
                                    </Button>
                                    {editingPackage ? <Button type="button" variant="outline" disabled={busy} onClick={resetPackageEditor}>Cancelar edición</Button> : null}
                                </div>
                                {contextDifferences.length ? <p className="mt-2 text-sm text-amber-800" role="alert">La madre seleccionada difiere en: {contextDifferences.join(", ")}.</p> : null}
                            </section>
                        ) : null}

                        <section aria-labelledby="rbe-manual-title">
                            <h3 id="rbe-manual-title" className="font-bold">3. Datos del reporte</h3>
                            <div className="mt-3 grid gap-4 md:grid-cols-3">
                                <div><Label htmlFor="rbe-truck">N.° camión *</Label><Input id="rbe-truck" value={truckNumber} maxLength={80} disabled={busy || Boolean(draft && !canEditDraft)} onChange={event => { setTruckNumber(event.target.value); setPreview(null); }} className="mt-1"/></div>
                                <div><Label htmlFor="rbe-order">N.° orden *</Label><Input id="rbe-order" value={orderNumber} maxLength={80} disabled={busy || Boolean(draft && !canEditDraft)} onChange={event => { setOrderNumber(event.target.value); setPreview(null); }} className="mt-1"/></div>
                                <div><Label htmlFor="rbe-date">Fecha (automática)</Label><Input id="rbe-date" value="Se asigna al generar el reporte" readOnly disabled className="mt-1"/></div>
                                <div className="md:col-span-3"><Label htmlFor="rbe-observations">Observaciones generales</Label><textarea id="rbe-observations" value={observations} maxLength={2000} rows={3} disabled={busy || Boolean(draft && !canEditDraft)}
                                    onChange={event => { setObservations(event.target.value); setPreview(null); }} className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"/></div>
                            </div>
                            {draft ? (
                                <div className="mt-3 flex flex-wrap gap-2">
                                    <Button type="button" variant="outline" disabled={busy || !canEditDraft} onClick={() => void runAction(async () => {
                                        const saved = await saveHeader(draft.id);
                                        if (!saved) throw new Error("No se pudo guardar la cabecera.");
                                        setNotice("Camión, orden y observaciones guardados.");
                                    })}>Guardar datos</Button>
                                    <Button type="button" className="bg-[#146b4f]" disabled={busy || !canEditDraft || draft.packages.length === 0} onClick={() => void savePreview()}>Vista previa</Button>
                                    <Button type="button" variant="outline" disabled={busy || !canEditDraft} onClick={() => setDiscardOpen(true)}>Descartar borrador</Button>
                                    <Button type="button" disabled={busy || !canEditDraft || !preview?.valid} onClick={() => setGenerationOpen(true)}>Generar PDF</Button>
                                </div>
                            ) : null}
                            {draft ? <p className="mt-2 text-xs text-slate-600">El borrador no reserva crías.</p> : <p className="mt-2 text-xs text-slate-600">Camión y orden pueden quedar vacíos mientras el reporte esté en Borrador; serán obligatorios para generar.</p>}
                        </section>

                        {draft ? (
                            <section aria-labelledby="rbe-packages-title">
                                <h3 id="rbe-packages-title" className="font-bold">4. Paquetes del borrador ({draft.packages.length})</h3>
                                {draft.packages.length === 0 ? <p className="mt-2 text-sm text-slate-600">Aún no hay paquetes.</p> : (
                                    <div className="mt-3 space-y-3">
                                        {draft.packages.map(item => (
                                            <div key={item.id} className="rounded-xl border p-4">
                                                <div className="flex flex-wrap items-start justify-between gap-3">
                                                    <div>
                                                        <p className="font-semibold">Paquete {item.package_number} · Madre {item.mother_label_snapshot}</p>
                                                        <p className="text-xs text-slate-600">{item.mother.machine.code} · {item.mother.operating_date} · {item.mother.work_order.number}</p>
                                                    </div>
                                                    <div className="flex gap-2">
                                                        <Button type="button" size="sm" variant="outline" disabled={busy || !canEditDraft} onClick={() => void beginEditPackage(item)}>Editar</Button>
                                                        <Button type="button" size="sm" variant="outline" disabled={busy || !canEditDraft} onClick={() => setRemoveCandidate(item)}>Retirar</Button>
                                                    </div>
                                                </div>
                                                <div className="mt-3 grid gap-2 sm:grid-cols-5">
                                                    {REWINDING_EXPORT_SLOTS.map(slot => {
                                                        const child = item.children.find(value => value.package_slot === slot);
                                                        return <div key={slot} className="rounded-md bg-slate-50 p-2 text-sm"><p className="text-xs text-slate-500">Cría {slot}</p><p className="font-semibold">{child ? "N.° " + child.position + " · " + child.weight_kg + " kg" : "—"}</p></div>;
                                                    })}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </section>
                        ) : null}

                        {preview ? (
                            <section className="rounded-xl border p-4" aria-labelledby="rbe-preview-title">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <h3 id="rbe-preview-title" className="font-bold">Vista previa de validación</h3>
                                    <Badge variant="outline" className={preview.valid ? "border-emerald-300 text-emerald-800" : "border-amber-300 text-amber-800"}>{preview.valid ? "Sin bloqueantes" : "Requiere correcciones"}</Badge>
                                </div>
                                <p className="mt-2 text-sm text-slate-700">{preview.package_count} paquetes · {preview.child_count} crías</p>
                                {preview.warnings.length ? <div className="mt-3"><p className="text-sm font-semibold">Advertencias informativas</p><ul className="mt-1 list-disc pl-5 text-sm text-amber-900">{preview.warnings.map((item, index) => <li key={item.code + index}>{item.message}</li>)}</ul></div> : <p className="mt-3 text-sm text-slate-600">Sin advertencias de origen.</p>}
                                {preview.blocking_errors.length ? <div className="mt-3"><p className="text-sm font-semibold text-red-800">Validaciones bloqueantes</p><ul className="mt-1 list-disc pl-5 text-sm text-red-800">{preview.blocking_errors.map((item, index) => <li key={item.code + index}>{item.message}</li>)}</ul></div> : null}
                            </section>
                        ) : null}
                    </div>
                ) : (
                    <p className="text-sm text-slate-700">Tu permiso permite consultar borradores propios, pero no crear ni modificarlos.</p>
                )}

                </fieldset>
                {generationOpen && (
                    <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3" role="alertdialog" aria-label="Confirmar generación del PDF">
                        <p className="text-sm font-semibold">¿Generar el PDF y reservar las crías seleccionadas?</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                            <Button type="button" size="sm" disabled={busy} onClick={() => void confirmGeneration()}>
                                {generationPending ? "Reintentar generación" : "Confirmar generación"}
                            </Button>
                            {!generationPending && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setGenerationOpen(false)}>Cancelar</Button>}
                        </div>
                    </div>
                )}
                {actionError ? <p className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{actionError}</p> : null}
                {notice ? <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" role="status" aria-live="polite">{notice}</p> : null}
                {removeCandidate ? (
                    <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3" role="alertdialog" aria-label="Confirmar retirada de paquete">
                        <p className="text-sm font-semibold">¿Retirar el paquete {removeCandidate.package_number} del borrador?</p>
                        <p className="mt-1 text-xs text-slate-700">La retirada queda en el historial del borrador; no genera una reserva.</p>
                        <div className="mt-3 flex gap-2">
                            <Button type="button" size="sm" className="bg-amber-700" disabled={busy} onClick={() => void confirmRemovePackage()}>Confirmar retirada</Button>
                            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setRemoveCandidate(null)}>Cancelar</Button>
                        </div>
                    </div>
                ) : null}
                {discardOpen ? (
                    <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3" role="alertdialog" aria-label="Confirmar descarte del borrador">
                        <p className="text-sm font-semibold">¿Descartar este borrador?</p>
                        <p className="mt-1 text-xs text-slate-700">Se conservará el historial del borrador y no se reservarán crías.</p>
                        <div className="mt-3 flex gap-2">
                            <Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => void discardDraft()}>Descartar</Button>
                            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setDiscardOpen(false)}>Cancelar</Button>
                        </div>
                    </div>
                ) : null}
            </Panel>
            {canReadOwn && <RewindingExportHistory scope={scope} own refreshKey={historyVersion} onSessionLost={onSessionLost}/>}
        </div>
    );
}
