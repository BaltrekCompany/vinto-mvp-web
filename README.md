# VINTO Captura Digital — Propuesta 1

MVP autónomo para digitalizar los formatos de Producción y Calidad VINTO sin depender de la integración inicial con Expertus.

## Cobertura

- 25 formularios To-Be configurables.
- 602 campos activos derivados de la matriz campo por campo.
- 3 reportes: bobinas por camión, consolidado de papel higiénico y consolidado de servilletas.
- Registro de paradas excluido de este módulo por decisión del proyecto.
- Fecha operativa nocturna para Bobinas/Rebobinado y Conversión.
- PIN provisional, máquina precargada, UUID local, borradores y cola offline.
- Sin catálogos inventados y sin escritura a Expertus.

## Estructura

- `lib/vinto/form-definitions.ts`: formularios y campos versionados.
- `lib/vinto/types.ts`: contrato común del motor.
- `app/page.tsx`: captura, navegación, reportes y almacenamiento local.

## Ejecución

```bash
pnpm install
pnpm dev
```

Validación:

```bash
pnpm run build
```

La persistencia de esta propuesta es local al equipo. La base central, autenticación corporativa, catálogos oficiales y el conector Expertus se habilitan después sin cambiar el contrato del motor.
