# VINTO CV-P113-02 — Solo dos campos obligatorios

**Estado (12/11/2026):** correctivo P1-13 v4 en la rama `fix/cv-p113-v4-only-two-required`. Mantener el PR, las pruebas y el deploy bajo control de cambios. **No integrado ni desplegado**, release de la VPS reportado `aaf54a0ed9780c40d9a58a32daa604d883dcf854`.

## Confirmación funcional del cliente
Los **únicos campos obligatorios** del formulario «Producción diaria de servilletas y especiales» son:
1. `tipo_bobina` — material de la receta del artículo de la OT (ejemplo artículo 11203: BC-1229-210, 9570 y 9632, **todos** visibles, incluidos empaque/sobreempaque).
2. `numero_bobina` — texto libre con número de bobina.

Son **opcionales**: saldo inicial, ingreso, saldo final, cantidad de jabas, hora inicio pallet, hora fin pallet y observaciones. La cabecera OT, línea, producto, máquina y turno/fecha proviene de la asignación autenticada.

## Comportamiento acordado
- Nueva **versión 4 aditiva** de P1-13. La versión 3 está **publicada y ya tiene capturas reales de QA** (datos ficticios). Nunca modificar directamente la v3 ni hacer backfill.
- Los tres saldos son opcionales individualmente; calcular el consumo = inicial + ingreso − final **solo cuando estén presentes los tres**; caso contrario mostrar «—», nunca «0.00 kg» inventado.
- Sin `cantidad_jabas` se guarda la captura de bobina, **sin fila de production_pallet, número, total ni consumo de correlativo**. Así los dos únicos campos obligatorios bastan para registrar.
- Si `cantidad_jabas` está presente, debe ser entero positivo y el backend obtiene el peso nominal del catálogo versionado, calcula el total y genera el pallet atómicamente. Las horas siguen siendo opcionales aunque se genere un pallet.
- Si falta peso homologado (p. ej. artículo 11503 con unidad de inventario `UN`), se bloquea solo la creación del pallet; la captura sin jabas sigue permitida siempre que exista receta válida.
- Lectura de capturas P1-13 v3 **requiere** pallet histórico; P1-13 v4 admite pallet nulo únicamente si no se informó jabas. P1-12 v4 no cambia.
- No nuevas migraciones SQL, no modificación de recetas, pesos, permisos, auditoría o inventario. Los campos existentes con datos válidos se guardan tal cual. Opcionales omitidos no se rellenan artificialmente.

## Plan de control
- Backend PostgreSQL17: pruebas de bobina con dos campos, horas/saldos parciales, pallets con/sin horas, jabas inválidas, idempotencia, permisos y ocho máquinas.
- Frontend: dos asteriscos, lectura posterior sin pallet, ausencia de consumo y peso inventados, mismos 3 materiales del artículo 11203.
- QA integral CI de GitHub + revisión formal. Solo entonces solicitar autorización de merge.
- Despliegue posterior por el usuario: `ssh -p 1724 ubuntu@51.79.65.225`; candidato SHA exacto y artifact checksum, respaldo verificado, `check-release=0` (sin SQL), dry-run del importador con **1 form_version + 8 form_version_machine + 9 fields = 18 nuevas filas**, sin conflictos; luego `--apply` y activación controlada.
- **No** repetir importación de P1-13 v3 ni migración 0031, ambas ya aplicadas; el bundle v4 agrega una nueva definición publicada. Rollback de código no revierte la publicación v4.

Para reanudar desde otro chat: leer esta nota y los comentarios de PR; verificar último SHA de GitHub y `current` de la VPS, evitar asumir PASS sin evidencias.
