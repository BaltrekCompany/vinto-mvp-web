"use client";

import { SectorCentral, type SectorCentralProps } from "@/components/vinto/sector-central";

// Conversión CENTRAL (M6-A, candidato): el shell común por sector configurado para CONVERSION. Sin lógica propia: solo se muestra lo que el backend verifica (sector operativo, concesión, máquinas
// y formularios publicados). Sin disponibilidad se informa «Conversión no está habilitado»; nunca se usan OT, asignaciones o registros de localStorage ni datos demo como respaldo, y los
// registros legacy que existan en el navegador ni se leen ni se borran ni se convierten.
export const ConversionCentral = (props: SectorCentralProps) => <SectorCentral {...props} code="CONVERSION"/>;
