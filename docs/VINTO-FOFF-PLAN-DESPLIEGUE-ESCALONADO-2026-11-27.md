# VINTO — Front Operativo Offline (FOFF): plan de entregas productivas por módulo

**Fecha:** 2026-11-27  
**Estado:** Diseño funcional aprobado por el responsable del proyecto; implementación pendiente de auditoría FOFF-01.  
**Proyecto:** VINTO MVP Web  
**Referencia:** [Memoria integral Calidad Offline](VINTO-CALIDAD-OFFLINE-MEMORIA-INTEGRAL-2026-11-26.md)

## 1. Decisión aprobada

Un solo acceso de captura offline para el frente operativo **Conversión, Rebobinado y Bobinas**, conservando las pantallas existentes. El operador verá exclusivamente módulos, máquinas/puntos de captura y formularios autorizados y publicados por el backend; los tres nombres de máquina visibles en la captura de referencia (GAMBINI, OMET_I, OMET_II) son ejemplos actuales, no un catálogo cerrado.

**Orden de liberación obligatorio:** Conversión → desplegar en producción → probar/corregir/aprobar → Rebobinado → desplegar en producción → probar/corregir/aprobar → Bobinas → desplegar en producción → probar/corregir/aprobar → prueba integral final.

La aprobación del diseño **no autoriza automáticamente** escrituras productivas, migraciones, merge ni despliegues sin los controles de cada etapa.

## 2. Fases y puertas de salida

| Fase | Entrega | Puerta para avanzar |
|---|---|---|
| FOFF-01 | Auditoría read-only de rutas, formularios, catálogo de máquinas, ofertas/grants, OT, bobinas, reglas de operación, base offline de Calidad y despliegue | Informe de dependencias, matriz de formularios reales y riesgos aprobados |
| FOFF-02 | Selector común de módulo, máquina/punto y formularios, preparación autorizada para offline | CI y permisos negativos PASS; interfaz existente intacta |
| FOFF-03 | **Conversión Offline**, PR(s) separados y despliegue productivo controlado | Pruebas automáticas + móvil real offline/reconexión PASS y aprobación funcional del usuario |
| FOFF-04 | **Rebobinado Offline**, PR(s) y despliegue controlado **solo tras cerrar FOFF-03** | Pruebas operativas propias, identidad madre/crías y sincronización PASS |
| FOFF-05 | **Bobinas Offline**, PR(s) y despliegue controlado **solo tras cerrar FOFF-04** | Pruebas de referencias, operaciones permitidas, idempotencia y sincronización PASS |
| FOFF-06 | QA integral transversal y documentación de cierre | Prueba encadenada y regresión completa PASS |

No combinar los tres módulos en una única entrega productiva. Si una fase falla, corregir y repetir sus pruebas antes de iniciar la siguiente.

## 3. Reglas técnicas y de seguridad

1. Reutilizar de Calidad Offline únicamente las piezas cuyo contrato sea compatible: PWA, caché del shell, bóveda AES-GCM/PBKDF2, identidad original, enrolamiento/grants firmados Ed25519, IndexedDB, autoguardado, cola, reintento, conciliación e idempotencia.
2. **No asumir** que los endpoints, autoridades CAPTURE, versiones de formulario, reglas de unicidad ni validador de Calidad sirvan sin cambios en producción/conversión/bobinas. Auditar primero, diseñar contratos específicos por módulo.
3. Preparación inicial online; captura sin red; reenvío con sesión válida del autor original. Frase local no reemplaza login central. No almacenar cookies, credenciales o claves privadas en documentación.
4. Máquina/formulario deben proceder del backend y de los permisos efectivos; nunca codificar la lista GAMBINI/OMET_I/OMET_II como exhaustiva. Sin oferta o permiso, no ofrecer captura.
5. Distinguir formularios de simple registro de mutaciones operativas (consumo de bobinas, inventario, asignaciones, órdenes, madres/crías, cantidades). Las mutaciones que no puedan reconciliarse de forma segura deberán permanecer online hasta tener contrato transaccional explícito y pruebas de concurrencia.
6. Usar IDs estables por captura y validación del servidor; ante versiones, contextos, permisos o stock modificados, conservar pendiente para revisión sin duplicar ni aplicar efectos silenciosos.
7. Mantener el flujo actual online y segmentación de usuarios. Los fallos del servidor deben fallar de modo seguro, preservando borradores locales.
8. Entorno de producción se puede usar para ensayos **solo mientras se verifique** ausencia de uso oficial/datos reales, con respaldo restaurable, reversión lista, impacto acotado y autorización de despliegue por fase. No confundir datos ficticios con ausencia de riesgos.
9. En cada fase documentar PR, SHA, Actions, migraciones, backups, despliegue, capturas de QA, incidencias, reparación y conformidad del usuario.

## 4. Matriz mínima de pruebas por módulo

- Preparación online para usuario autorizado; visibilidad negativa de módulos/máquinas/formularios sin permiso.
- Apertura y edición offline, cierre/reapertura en el mismo dispositivo, cifrado y autoguardado.
- Reintento automático tras reconexión; reintento manual; conciliación ante ACK perdido.
- Doble envío/reintento, concurrencia desde dispositivos distintos, permisos revocados, versión antigua y cambio de OT/estado de bobina; no duplicar efectos.
- Verificación en el módulo online y su historial luego del ACK; datos preservados si se requiere revisión.
- Regresión de Calidad Offline y de operaciones online existentes.

## 5. Inicio de FOFF-01

Realizar auditoría solo lectura de GitHub y, con Claude Code y autorización del usuario, de VPS. Levantar por módulo: rutas UI/backend, IDs de formularios, asignación de máquinas, grants, relaciones OT/bobina/madre, tablas/migraciones, operaciones transaccionales, escenarios offline permitidos, pruebas y mecanismo de despliegue. Entregar hallazgos y diseño técnico concreto antes del primer PR de código.

## 6. Referencia de lo ya validado

La memoria de Calidad Offline (26-nov-2026) describe el cierre con formularios originales, dispositivo compartido, caché PWA, bóveda cifrada, servidor que revalida identidad/permisos/contexto, 201/409/202 y pruebas móviles. Es un **patrón técnico de referencia**, no evidencia de que Conversión, Rebobinado o Bobinas ya funcionen offline.

**Estado al registrar este plan:** ninguna fase FOFF implementada, migrada ni desplegada por este documento.
