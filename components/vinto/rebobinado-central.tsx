"use client";

import { SectorCentral, type SectorCentralProps } from "@/components/vinto/sector-central";

// Rebobinado CENTRAL (M4-A): el shell común por sector (sector-central.tsx) configurado para REBOBINADO. Sin lógica propia: la disponibilidad, las OT, las asignaciones, las capturas
// y los historiales son los mismos que antes; no usa localStorage, datos demo ni registros legacy como respaldo.
export type { RebobinadoModule } from "@/components/vinto/sector-central";
export const RebobinadoCentral = (props: SectorCentralProps) => <SectorCentral {...props} code="REBOBINADO"/>;
