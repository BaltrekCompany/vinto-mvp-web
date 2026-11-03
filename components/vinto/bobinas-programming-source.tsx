"use client";

import type { ComponentProps } from "react";
import { BobbinasProgramming, type Creation } from "@/components/vinto/bobinas-programming";
import { BOBINAS_SECTOR, articlesOf, sectorOf } from "@/lib/vinto/availability";
import { useAvailability } from "@/lib/vinto/use-central";

type Props = Omit<ComponentProps<typeof BobbinasProgramming>, "catalog" | "creation"> & { scope: string };

// Programación de Bobinas con el catálogo que el BACKEND publica para la sesión (GET /api/production/machines?articles=true: sectores concedidos y operativos, máquinas activas y los artículos
// de la relación artículo-máquina que el backend valida al crear). La lista estática PRODUCTS_BY_MACHINE ya no alimenta la creación. Solo quien gestiona OT consulta el catálogo; sin respuesta
// del servidor la creación no se ofrece (las OT existentes siguen visibles). `machines` solo decide qué OT se listan en este frente.
export function BobbinasProgrammingSource({ scope, ...rest }: Props) {
    const availability = useAvailability(true, rest.canManageOrders, rest.onSessionLost, scope);
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
    return <BobbinasProgramming key={typeof creation === "object" ? "catalog" : "wait"} {...rest} creation={creation}/>;
}
