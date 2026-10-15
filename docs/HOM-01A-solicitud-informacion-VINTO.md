# HOM-01A · Solicitud de información a VINTO

**Esta es una solicitud, no una confirmación de que estos documentos existen.** Ninguno de los siguientes documentos está hoy en el repositorio ni se ha recibido de VINTO. No se fija ningún plazo de entrega: las fechas las acuerda VINTO. Las referencias entre paréntesis apuntan al tema ejecutivo de la matriz [HOM-01A-go-live-integral.md](HOM-01A-go-live-integral.md).

## 1. Maestros

- Lista oficial de las máquinas de Bobinas (MP1, MP3), Rebobinado y Conversión, con código técnico y nombre visible. (E2)
- Lista oficial de artículos y su relación con cada máquina, para los tres sectores, con unidades y clases de material. (E3)
- Maestro de pesos nominales por artículo, si es obligatorio su uso. (E3)
- Recetas por artículo, con vigencia, si se usan en Conversión. (E3)

## 2. Turnos

- Horarios de los turnos de Bobinas, Rebobinado y Conversión, con su vigencia (fecha desde la que rigen) y zona horaria. (E4)
- Confirmación de si el horario es el mismo para todas las máquinas de un sector o varía por máquina. (E4)
- Confirmación de si la fecha operativa del turno nocturno es la del día en que empieza el turno. (E4)

## 3. Formularios reales llenos

- Fichas reales y llenas (en papel o del sistema que use VINTO hoy) de: F3, P1-06, P1-19 y P1-20 (Bobinas); P1-10 y P1-29 (Rebobinado); P1-16, P1-12, P1-13 y P1-11 (Conversión). (B3, C2, C3, D1–D4)
- Para cada una: confirmación de si el formulario candidato implementado (pantalla simplificada) corresponde a la ficha real, o si la ficha real tiene más campos, otra cardinalidad u otra estructura.

## 4. Fórmulas y unidades

- Fórmula de la humedad derivada de P1-19 y de los promedios de P1-20, con un ejemplo numérico. (B3)
- Unidades oficiales de espesor, gramaje, crepado y resistencias de P1-20. (B3)
- Fórmula del total de merma de P1-16, del peso total de pallet de P1-12 y del saldo de consumo de P1-13, cada una con ejemplo numérico. (D1–D3)
- Unidad, rango y número de decimales de los pesos y cantidades de los tres sectores. (E6)

## 5. Procedimientos de Calidad

- Procedimiento vigente de liberación y rechazo de bobinas: quién decide, con qué mediciones, qué límites por magnitud y por artículo, y qué motivo se exige. (B1, B2)
- Confirmación de si quien mide puede decidir sobre la misma bobina o deben ser personas distintas. (B2)
- Confirmación de si una decisión de Calidad puede revertirse, por quién y con qué motivo. (B2)
- Procedimiento para una bobina rechazada: destino, registro y si entra a un nuevo ciclo de medición. (E1)

## 6. Reglas de identificación y consumo

- Confirmación de si Rebobinado y Conversión exigen que la bobina de origen esté liberada por Calidad antes de procesarla o consumirla. (E1)
- Para la genealogía de Rebobinado (P1-07): qué identifica el número de bobina en la ficha, cómo se identifica la bobina madre, y si cada «cría» es una bobina con identidad propia. (C4, C5)
- Para Conversión: cómo se identifica la bobina que se consume en P1-11 y P1-13, y cómo se evita contarla dos veces. (D3)

## 7. Firmas y aprobaciones

- Confirmación de si las fichas de Rebobinado (P1-10, P1-29) y de Conversión (P1-16, P1-12) exigen firma de operador, de un responsable, o ambas, y qué efecto tiene esa firma. (E7)
- Significado de «grupo» y «encargado de turno» en las fichas de Conversión, si aplica. (E7)

## 8. Criterios UAT

- Quiénes participan en la validación de usuario (UAT) por cada sector. (B9)
- Qué casos de prueba se van a ejecutar. (B9)
- Quién firma la aprobación final del UAT y con qué criterio se considera aprobado. (B9)

## 9. Alcance de reportes, datos históricos y offline

- Lista de los reportes que se exigen para el GO-LIVE y, de los que no se exigen, una confirmación por escrito de que quedan fuera de alcance. (B5)
- Si el reporte «bobinas por camión» se exige: qué es un camión en este contexto y de dónde sale ese dato. (B5)
- Confirmación de si se exige operación sin conexión a internet en planta y, si es así, con qué garantías (sin pérdida de datos, sin duplicados). (B6)
- Qué se hace con los registros que hoy existen únicamente en los navegadores de los operadores (no en la base de datos central): conservarlos sin mostrarlos, descartarlos, o importarlos. (E8)
- Confirmación de si se requiere integración con Expertus (lectura de órdenes, escritura de resultados) para el GO-LIVE. (B6)

## 10. Usuarios y autorización

- Lista nominal de los usuarios del GO-LIVE, con su perfil (Jefatura, Supervisión, Operación, Calidad) y el sector al que tienen acceso. (B4)
- Nombre y cargo de la persona con autoridad para aprobar el alcance del GO-LIVE y para autorizar la activación de cada sector. (B4, G8 de la matriz de lanzamiento)

---

**Nota sobre una pieza mencionada en documentos previos.** Se ha hecho referencia a una matriz de homologación («M1-B2-c1») que, según la documentación interna de Baltrek, existiría fuera de este repositorio. Si VINTO cuenta con ese documento, se solicita su entrega: podría responder varias de las preguntas anteriores. Mientras no se aporte, se considera **evidencia pendiente** y no se presume su contenido.
