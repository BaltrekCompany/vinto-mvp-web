# VINTO — Puertas de seguridad del host antes de habilitar API QA

**Estado: revisión pendiente.** Este documento público registra únicamente decisiones de control. Las evidencias que detallan superficies expuestas, direcciones, puertos, ubicaciones de credenciales y configuraciones sensibles deben mantenerse **fuera del repositorio público** y de sus comentarios.

## Alcance

No se deben modificar ni desplegar servicios, contenedores, firewall, configuración o credenciales por el mero hecho de aprobar este documento. La auditoría de inventario OFF-03D.7C6C1 se completó en solo lectura y encontró condiciones de endurecimiento del host que requieren clasificación y tratamiento separado. La identidad y los permisos QA continúan protegidos por los gates D7C6B/C; D3B4 permanece no autorizado.

## Controles obligatorios previos a publicar QA

| Control | Verificación solicitada | Criterio de cierre |
|---|---|---|
| HOST-NET-01 | Inventario de acceso externo a servicios de datos y sus consumidores legítimos, sin publicar direcciones ni detalles de explotación | Superficie de red no necesaria restringida, sin romper conexiones autorizadas; prueba negativa desde origen externo |
| HOST-SEC-02 | Auditoría de propietario, modo y ACL de archivos de configuración de servicios actuales, sin leer valores | Modificación y lectura limitadas al usuario de servicio o custodio autorizado; pruebas de continuidad |
| QA-NET-03 | Política de acceso privado a hostname QA antes de añadir rutas a la API | Denegación por defecto verificada desde cliente NO autorizado y acceso positivo desde cliente autorizado |
| QA-APP-04 | Servicio de API QA bajo identidad propia, puerto de loopback y conexiones de DB aisladas | Instancia real verifica rol de negocio, rol de identidad dedicado, modo endurecido y bloqueo de escrituras operativas |
| QA-FUNC-05 | Prueba funcional de los dos roles y rutas de autenticación/administración en QA | D3B3 PASS con evidencia QA sin secretos antes de solicitar corte D3B4 |

## Secuencia de decisión

1. **Auditoría acotada en solo lectura:** identificar consumidores y dependencias de los recursos del host; corroborar rutas de control de acceso (red/cloud/host), identidad real del proceso y permisos efectivos. Registrar datos técnicos solo en un canal privado aprobado, no en GitHub público.
2. **Plan de contención con no regresión:** definir el mecanismo mínimo para limitar acceso indebido sin interferir con servicios activos. En entornos Docker, verificar eficacia real de firewall de host y de controles de publicación; no asumir que activar una herramienta concreta protege automáticamente contenedores publicados.
3. **Aprobaciones independientes:** a) cambio de alcance de red y b) ajuste de permisos de configuración. No ejecutar acciones mutantes ni rotaciones de credenciales por defecto.
4. **Validación de cambios:** disponibilidad de servicios existentes, acceso desde orígenes autorizados, rechazo desde orígenes no autorizados, revisión de registros de errores sin secretos y procedimiento explícito de reversión.
5. **Preparación de QA:** mantener el hostname en estado sin proxy hasta que QA-NET-03 esté aprobado. Después diseñar y solicitar aprobación independiente para instalar una API exclusiva QA y comprobar QA-APP-04 / QA-FUNC-05.

## Reglas de seguridad

- Ningún valor de variables, contenido de archivos sensibles, cadena de conexión, secreto, IP operativa, puerto específico expuesto, token o instrucción de acceso debe incluirse en este documento o el PR.
- No ejecutar acciones destructivas o que cambien topología (reinicio Docker, modificación de binding, DROP, REVOKE, reglas de firewall, rotación) sin identificar consumidores, ventana de cambio y aprobación específica.
- Separar las incidencias de endurecimiento del host del desarrollo funcional offline. El código y las pruebas CI pueden continuar en Draft; el despliegue público de QA no.
- La decisión previa de omitir un respaldo de la base QA no equivale a aprobación de cambios en host o servicios de otros entornos.

**Resultado de esta documentación:** solo planning y criterios de autorización. Sin escritura en VPS, sin despliegue y sin merge a main.
