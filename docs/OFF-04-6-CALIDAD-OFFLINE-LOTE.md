# OFF-04.6 — Calidad offline integral (diez formularios)

Alcance: captura offline de los formularios de Calidad **por máquina** (P1-18, P1-22, P1-26, P1-27) y **por bobina** (P1-19, P1-20, P1-21, P1-24, P1-25, P1-28), reutilizando el motor de OFF-04.5B (almacén cifrado, cola, sincronización, receptor aislado). No se creó un motor ni una PWA por formulario. Todo es **sintético y aislado**: QA con bandera apagada por defecto, sin datos industriales, sin PostgreSQL real, sin despliegue.

## 1. Revisión de compatibilidad (primera actividad de desarrollo)

Se ejecuta como pruebas de contrato (`backend/tests/test_off046_form_contracts.py`), no como informe aparte: para cada formulario se contrasta el contrato publicado (semilla versionada) con lo que exportan el emisor firmado y la captura central.

| Formulario | Tipo | Versión | Campos manuales (obligatorios) | Calculados por el servidor | Compatible |
|---|---|---|---|---|---|
| VINTO-P1-18 | máquina | 2 | 10 (8) | — | Sí |
| VINTO-P1-22 | máquina | 2 | 5 (4) | — | Sí |
| VINTO-P1-26 | máquina | 3 | 5 (3) | `porcentaje_cantidad_de_seco` | Sí (regla `percent_two_decimals_half_up`) |
| VINTO-P1-27 | máquina | 2 | 24 (22) | — | Sí |
| VINTO-P1-19 | bobina | 1 | 7 (6) | — | Sí |
| VINTO-P1-20 | bobina | 1 | 12 (11) | — | Sí |
| VINTO-P1-21 | bobina | 2 | 82 (0; perfil por posiciones completas) | 4 (promedios y posiciones usadas) | Sí (`profile_mean…`, `profile_complete_positions_count`) |
| VINTO-P1-24 | bobina | 5 | 12 (9) | 2 promedios | Sí (`mean_two_decimals_half_up`) |
| VINTO-P1-25 | bobina | 4 | 13 (11) | 2 promedios | Sí |
| VINTO-P1-28 | bobina | 1 | 7 (6) | — | Sí (número de bobina declarado debe coincidir) |

Diferencias compatibles resueltas en el mismo incremento: (a) el vocabulario de cálculo del paquete firmado solo conocía un método; se añadieron `percent_two_decimals_half_up`, `mean_two_decimals_half_up`, `profile_mean_two_decimals_half_up` y `profile_complete_positions_count`, construidos desde las mismas constantes que usa el flujo en línea (`PERCENT_RULES`, `MEAN_RULES`, perfil P1-21); (b) el emisor sintético y el verificador del dispositivo estaban fijados a P1-22 y a una operación; ahora usan el registro (`offline_quality/registry.py`) derivado de las políticas de autorización en línea; (c) la concesión QA pasó a fijar la versión de la semilla (error `grant_version_not_seed` si no coincide).

## 2. Diseño

* **El dispositivo nunca calcula.** Los campos calculados son de solo lectura ("calculado por el servidor al sincronizar"); un valor enviado para ellos se rechaza en cliente y en servidor. El resultado calculado llega en la respuesta del receptor (`server_calculated`).
* **Validación central al reconectar** (`offline_quality/central.py`): reutiliza el código en línea (`_prepare_values`, comprobaciones de bobina) en modo solo lectura. Contenido inválido → recepción técnica **sin** aceptación: recibo en revisión (202) con códigos estables y sin eco de valores. Si el validador no está disponible → revisión, nunca aceptación silenciosa. Versión de formulario distinta → `unknown_form_version`.
* **Contexto histórico de bobina**: se prepara **en línea** (`POST /api/offline/bobbin-context`, exige concesión por bobina) y se guarda cifrado en un almacén propio del dispositivo. Resumen (digest) sobre campos inmutables; `context_version = sha256("vinto-offline-bobbin-context-v1" ∖ snapshot ∖ bobina ∖ digest)` (64 hex; cabe en el CHECK existente, **sin cambio de esquema**). El borrador y la cola enlazan la bobina; la referencia viaja dentro del contenido sellado y hasheado.
* **Autoría, versiones, idempotencia**: sin cambios del motor; el autor original es la sesión real del receptor; misma captura ⇒ un solo recibo.
* **Separación de conceptos**: recepción técnica ≠ aceptación operativa ≠ aprobación industrial. Aprobaciones, liberaciones, rechazos y decisiones industriales **no existen offline** (las rutas siguen fuera del guard #219 y del piloto).
* **Autorizaciones**: las concesiones sintéticas QA (`OFFLINE_QA_PILOT_GRANTS`, `OFFLINE_QA_PILOT_BOBBINS`) están separadas de las industriales; `MAX_GRANTS` 40.
* El guard #219 **no** se amplió.

## 3. Pruebas

| Capa | Archivo | Qué prueba |
|---|---|---|
| Contratos de los diez formularios | `test_off046_form_contracts.py` (24) | paquetes exportables, cálculos, versiones, operaciones |
| Receptor por lote | `test_off046_batch_receiver.py` (56) | captura completa, obligatorios, tipos, opciones, duplicados, permisos, versión, bobina, cálculos del servidor, conservación ante error |
| Contexto de bobina (PG real desechable) | `test_off046_bobbin_context_db.py` (5) | contra una bobina F3 real |
| Cliente (Node, fixture firmada en Python) | `scripts/off-04-6-quality-batch.test.mjs` (8) | 10 paquetes verifican, borrador/clave de contexto, paridad byte a byte de `context_version` y hash con el backend |
| Chrome real (un origen) | `scripts/off-04-6-quality-batch-e2e-browser.py` (8) | por formulario: preparación en línea, bobina, captura offline, reinicio sin red, sincronización, un recibo aceptado, cálculos del servidor, duplicado, bobina inválida → revisión |
| Regresión | suites OFF existentes, e2e 06B (15), autorización y Calidad en línea | sin cambios de comportamiento |

## 4. Pendientes de decisión funcional (no inventados; no bloquean el resto)

1. **Promoción de recepciones a capturas operativas** (`vinto_txn`) y quién las revisa/acepta: hoy el receptor registra la recepción técnica y la validación central; no crea capturas operativas.
2. **Cambio de contexto de bobina** entre preparación y sincronización: se trata de forma conservadora (cualquier cambio → revisión central). Falta la regla de negocio que distinga cambios tolerables.
3. **Habilitar `/api/offline/bobbin-context` real** bajo el guard #219 en QA: requiere decisión explícita (hoy solo en el piloto aislado).
4. **Bobinas reales en QA**: la base QA no contiene bobinas industriales; el piloto usa un registro sintético (`OFFLINE_QA_PILOT_BOBBINS`).
5. **Nuevo artefacto PWA**: el laboratorio y el arranque cambiaron; los hashes del artefacto aprobado en OFF-04.5B ya no aplican y una publicación futura necesita un conjunto nuevo aprobado.

## 5. Fuera de alcance (respetado)

Sin activar banderas QA/producción, sin tocar PostgreSQL real, Nginx, firewall, usuarios ni concesiones, sin despliegue ni merge, sin SEC-HOST-01, sin datos industriales.
