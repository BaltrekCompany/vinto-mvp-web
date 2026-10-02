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
# Integración local de Seguimiento con FastAPI

El indicador de registros consulta GET /api/captures/count por front. Cuando
responde la API, muestra los registros centrales y por separado los locales
del navegador. No suma ambos ni sincroniza capturas. Ante error, respuesta
inválida o timeout de cinco segundos, muestra el contador local y Reintentar.
Una respuesta central de cero es válida y conserva visible el contador local.
Las capturas, descargas CSV, OT y asignaciones siguen usando su flujo local.

NEXT_PUBLIC_API_URL configura la URL pública del backend (por defecto
http://127.0.0.1:8000). No contiene credenciales y sus cambios requieren
reconstruir el frontend. La URL de PostgreSQL pertenece solo al backend.

Detener pnpm start antes de reconstruir para liberar dist en Windows:

```powershell
pnpm run build
pnpm start
```

En http://127.0.0.1:8787, ingresar al MVP y abrir Seguimiento. Cambiar de
front verifica el filtro; Actualizar vuelve a consultar. Detener el backend
debe mostrar el contador local y Reintentar; reiniciarlo y reintentar restaura
el central. Con backend activo y PostgreSQL detenido, la API devuelve 503
y la interfaz usa el mismo fallback. Comprobar que las descargas y los
registros locales se conservan; no hay sincronización automática.
