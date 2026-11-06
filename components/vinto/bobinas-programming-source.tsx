"use client";

import type { ComponentProps } from "react";
import { BobbinasProgramming, type Creation } from "@/components/vinto/bobinas-programming";
import { BOBINAS_SECTOR, articlesOf, sectorOf } from "@/lib/vinto/availability";
import { useAvailability, useResource, useWorkOrderCapabilities } from "@/lib/vinto/use-central";
import { getLineExecutionCapability } from "@/lib/vinto/line-execution-api";
import { capabilitiesOf } from "@/lib/vinto/work-order-capabilities";

type Props = Omit<ComponentProps<typeof BobbinasProgramming>, "catalog" | "creation"> & { scope: string };

// Programación de Bobinas con el catálogo que el BACKEND publica para la sesión (GET /api/production/machines?articles=true: sectores concedidos y operativos, máquinas activas y los artículos
// de la relación artículo-máquina que el backend valida al crear). La lista estática PRODUCTS_BY_MACHINE ya no alimenta la creación. Solo quien gestiona OT consulta el catálogo; sin respuesta
// del servidor la creación no se ofrece (las OT existentes siguen visibles). `machines` solo decide qué OT se listan en este frente.
export function BobbinasProgrammingSource({ scope, ...rest }: Props) {
    const availability = useAvailability(true, rest.canManageOrders, rest.onSessionLost, scope);
    // Necesitan la capacidad quien GESTIONA OT (crear: work_order.manage) y quien ACTIVA (activación masiva: assignment.manage); cada acción sigue dependiendo solo de su propio permiso.
    // loading/error/401/403/404/5xx/JSON inválido = apagado (flujo tradicional, sin botón masivo).
    const capabilityResource = useWorkOrderCapabilities(rest.canManageOrders || rest.canManageAssignments, rest.onSessionLost, scope);
    const capability = capabilitiesOf(capabilityResource.view);
    // Separate endpoint preserves the historical /capabilities response exactly.
    // Missing/invalid/error/unauthorized response leaves all E1-05 controls hidden.
    const executionCapability = useResource<boolean>(
        "work-order-line-execution-capability:" + scope,
        rest.canManageAssignments, signal => getLineExecutionCapability(signal), rest.onSessionLost, true);
    const executionEnabled = rest.canManageAssignments && executionCapability.view.status === "ready" && executionCapability.view.data === true;
    let creation: Creation | undefined;
    if (rest.canManageOrders) {
        const view = availability.view;
        const sector = view.status === "ready" ? sectorOf(view.data, BOBINAS_SECTOR) : null;
        if (view.status === "error") creation = "unavailable";
        else if (view.status !== "ready") creation = "loading";
        else if (!sector) creation = "unavailable";
        else creation = { machines: sector.machines.map(m => ({ code: m.code, name: m.name })), catalog: code => articlesOf(sector.machines.find(m => m.code === code)).map(a => ({ code: a.code, name: a.description })) };
    }
    // `key`: al llegar el catálogo el panel se monta de nuevo para que la primera fila tome la primera máquina ofrecida (el estado inicial del borrador se fija al montar).
    return <BobbinasProgramming key={typeof creation === "object" ? "catalog" : "wait"} {...rest} creation={creation} capabilities={capability.capabilities} executionEnabled={executionEnabled} capabilityStatus={capability.status} scope={scope} onCapabilitiesStale={capabilityResource.refresh}/>;
}
