# VINTO OFF-04.1 — Editor y borradores cifrados de Calidad (laboratorio sintético)

**Estado:** candidato de ensayo aislado, PR Draft apilado sobre OFF-03C.4 (#225, `69ac7250b9226cc2a8df03f446d67b17476839ba`). Seguimiento: #226.
**NO autoriza capturas industriales, cola `queued`, envío, aprobación ni sincronización.** Sin cambios en PostgreSQL, VPS, flags de producción, permisos ni migraciones. SEC-HOST-01 A0.3 sigue diferido (#223).

## 1. Auditoría y componentes reutilizados

| Componente | Uso en OFF-04.1 |
|---|---|
| `offline-store.ts` (`vinto-offline-v1`, stores `drafts`/`outbox`, índice `ownerDevice`) | Se reutiliza **sin cambiar versión ni stores**. Se añade `saveSealedDraftRevision` (compare-and-swap por revisión). No escribe nunca en `outbox`. |
| `offline-vault.ts` (`sealLocalDraft`/`openLocalDraft`, AES-GCM con AAD de propietario, navegador, borrador, contexto, formulario y versión) | Cifrado de todo el contenido del borrador. |
| `offline-profile-store.ts` / `offline-scope-store.ts` / `offline-quality-store.ts` | Perfil único por navegador, alcance firmado y paquete verificado desde los que se arma el contexto. |
| `offline-quality-verify.ts` | Define el tipo de la definición. **Barrera crítica intacta:** exige `capture_eligible === false` y `captures_enabled === false`. Los paquetes de consulta no se convierten en permiso de captura; el editor ni los modifica ni los reinterpreta. |
| `offline-renewal.ts` (`readRenewalStatus`) | El laboratorio se bloquea si el alcance tiene revocación conocida o estado ilegible. |

Estados `queued`, `outbox` y cualquier endpoint de FastAPI quedan **fuera**: el código del editor no los importa ni los referencia (verificado por pruebas estáticas).

## 2. Contratos publicados de P1-18 / 22 / 26 / 27 y homologación pendiente

Revisión de `backend/seed_data/forms/*.json` (versión semilla; la versión vigente la publica `vinto_config`):

| Formulario | Campos | Tipos | Particularidades |
|---|---|---|---|
| P1-18 | 10 | text, time, decimal, textarea | todos manuales |
| P1-22 | 5 | text, decimal, textarea | todos manuales |
| P1-26 | 6 | text, decimal, textarea | **1 calculado** y 1 campo con opciones cerradas |
| P1-27 | 24 | text, decimal, textarea | todos manuales |

**No se asume que los cuatro puedan capturarse offline.** Pendiente de homologación industrial (no resuelto aquí): rangos, unidades y precisión por campo; fórmula del campo calculado de P1-26 (el editor lo muestra no editable y nunca infiere la fórmula); reglas entre campos o dependencias de opciones; contexto de OT/asignación/turno (Calidad por máquina es independiente); y la autoridad central de actor, concesión y versión. El primer formulario de ensayo es **sintético**.

## 3. Diseño

### Compuerta de laboratorio (desactivado por defecto)
- El editor vive en una página aparte, `/offline-lab.html`, y su runtime `offline-draft-lab.js`. **Solo se generan con `OFFLINE_DRAFT_LAB=1`** (`scripts/build-offline-boot.mjs`). Una compilación normal **borra** cualquier archivo de laboratorio residual; ambos están en `.gitignore`, no se enlazan desde `offline.html` y no entran en la lista de precarga del Service Worker (esa lista no cambia).
- La página se cachea a sí misma la primera vez que se abre con conexión (caché `vinto-off04lab-v1`); el Service Worker solo sirve esas rutas desde caché. Sin compilación de laboratorio no existen y devuelven 404.
- **Solo definiciones sintéticas:** el editor únicamente acepta definiciones cuyo nombre empieza por `SINTÉTICO` y cuya nota empieza por `Synthetic QA-only`. Una definición real publicada se rechaza (`ineligible`).
- Aviso permanente «LABORATORIO — DATOS SINTÉTICOS», casilla obligatoria de confirmación y ausencia de cualquier botón de envío/sincronización/cola.

### Esquema del borrador (sellado con AES-GCM dentro del registro existente)
Registro en `drafts` (en claro solo metadatos ya previstos por el contrato): `id` (UUID estable), `ownerId`, `deviceKey`, `formCode`, `formVersion`, `contextId` (UUID determinista de máquina + formulario + snapshot de alcance), `savedAt`, `revision` (entero monótono) y `sealed`.

Contenido cifrado (`vinto.offline.quality-draft.v1`, claves exactas): `status: "draft"`, `synthetic: true`, `draft_id`, `author_user_id` (autor original), `device_key`, `machine_code`, `form_code`, `form_version`, `form_checksum`, `definition_sha256`, `package_id`, `scope_snapshot_id`, `revision`, `created_local`/`updated_local` (fecha local **informativa**, no prueba vigencia) y `values`. Al abrir se comprueba que cifrado y metadatos coinciden (id, autor, navegador, formulario, versión, revisión y contexto); cualquier diferencia ⇒ `corrupt`.

### Validación (solo lo que dice la definición)
Obligatoriedad, tipo (text, textarea, decimal, integer, boolean, date, time) y listas de opciones cerradas. Los decimales se guardan como texto normalizado (coma→punto), nunca como `float`. **Los campos `source=calculated` no se editan ni se guardan**; una clave calculada o desconocida invalida el guardado. Un borrador **incompleto** (faltan obligatorios) sí puede guardarse y queda `draft`; un valor mal tipado nunca.
Reglas **no cubiertas** (registradas para la homologación): rangos y unidades, fórmulas, dependencias entre campos, contexto OT/turno y cualquier autoridad central.

### Persistencia y concurrencia
- `saveQualityDraft` resuelve **solo después de `tx.oncomplete`**; nunca informa un guardado inexistente. Los fallos de cuota (`quota`), de escritura o de cifrado se informan como «NO se guardó» y no consumen la revisión.
- **Compare-and-swap en la misma transacción:** se compara la revisión esperada con la almacenada. Si otra pestaña guardó antes ⇒ `conflict`, sin sobrescribir; la interfaz ofrece «Cargar versión guardada». Dos pestañas que crean el mismo id ⇒ una gana y la otra recibe `conflict`.
- Un borrador solo es editable contra **la misma definición** (versión, checksum y hash). Si la definición cambió tras una renovación, queda de solo lectura (`stale_definition`) y nunca se migra en silencio; los borradores nuevos usan la definición nueva.
- Un borrador alterado o ilegible se **lista como dañado**, no se oculta ni impide abrir los demás, y no se modifica. Frase errónea y cifrado alterado producen el mismo `locked` (la bóveda no los distingue por diseño).
- La clave solo vive en memoria durante la sesión de la página y se descarta con «Bloquear».
- No existe borrado de borradores en este incremento.

## 4. Pruebas (todas con datos sintéticos, sin API ni servidor)

- **Node** (`scripts/off-04-draft-schema.test.mjs`, 10): validación por tipo y opción, normalización, campos calculados no editables, payload estricto, contexto determinista, definición coincidente y contratos estáticos (sin `fetch`/XHR/beacon/WebSocket, sin `outbox`/`queued`, sin `innerHTML`, sin modificar los indicadores de captura, laboratorio opt-in).
- **Chrome IndexedDB** (`scripts/off-04-drafts-browser.py`, 11 casos): creación y edición; validación sin guardado; cifrado sin texto en claro ni `outbox`; recuperación tras cerrar y reabrir; frase incorrecta; cifrado y metadatos manipulados; identidad distinta; navegadores aislados; almacenamiento lleno y errores de escritura; conflicto entre pestañas (también con una carrera determinista dentro de la transacción); ausencia de llamadas de red; cambio de definición; definición no sintética rechazada. Una mutación que quita la comparación de revisión de la transacción **hace fallar** el caso de conflicto.
- **Chrome UI** (`scripts/off-04-lab-browser-smoke.py`, 8 casos): página de laboratorio, desbloqueo obligatorio, edición y guardado, cierre del navegador y reapertura **sin conexión** desde el Service Worker, recuperación y edición, conflicto entre pestañas y bloqueo; cero tráfico `/api/`.
- Regresiones: Node y Chrome de OFF-02, 03A, 03B, 03B.3, 03C.2/03C.3 y 03C.4.

## 5. Riesgos residuales y límites

- **Datos sintéticos por convención técnica, no por prueba criptográfica:** el editor rechaza definiciones no marcadas como sintéticas, pero el usuario podría teclear datos reales en un campo de texto libre; el aviso y la confirmación son controles de proceso.
- **La fecha local es informativa** (reloj del dispositivo, manipulable).
- **Sin cuota garantizada:** si el navegador descarta datos del sitio, los borradores se pierden (política de OFF-01: no recuperables ante limpieza de datos).
- **Sin borrado ni exportación** de borradores; sin política de retención.
- **Un mismo `locked`** para clave errónea y cifrado alterado (heredado de la bóveda).
- **Reversión local total:** restaurar blobs cifrados antiguos de IndexedDB no se detecta (anclaje externo pendiente, como en #225).
- Las pruebas locales usaron Chromium de Playwright; **QA físico del móvil no ejecutado.**
- La compilación de laboratorio no debe usarse en entornos operativos; un control de despliegue que lo verifique (`test ! -e public/offline-lab.html`) queda en la CI de este PR.

## 6. Siguiente incremento (OFF-04.2)

Transición explícita y reversible `draft` → `queued` con cola inmutable, `capture_id` estable y estado persistente tras reinicio, **sin envío**; requiere antes un contrato aprobado de captura offline distinto del de solo lectura (#226: OFF-04.5), homologar al menos un formulario real con reglas explícitas, y una política de retención y limpieza de borradores.
