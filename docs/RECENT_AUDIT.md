# Diagnóstico reciente de solo lectura — 2026-11-12

Todas las consultas de origen se hicieron dentro de `START TRANSACTION
READ ONLY`, finalizaron con `ROLLBACK` y cerraron la conexión. No se
escribió en Bolivia, Chile, la base central ni el piloto. Los resultados
son muestras y no certifican cobertura ni pagos faltantes.

## Planes antes del muestreo

Ventana: siete días por fecha de creación, máximo 150 filas por dataset.

| Fuente | Acceso / índice | Filas estimadas | Decisión |
|---|---|---:|---|
| Bolivia remesas | range / índice de fecha | 86 | Muestra ejecutada |
| Bolivia pagos | range / índice de fecha | 460 | Muestra ejecutada |
| Chile pagos | range / `id_operacion` | 29.524 | Muestra ejecutada |
| Chile remesas | range / PRIMARY, `Using filesort` | 398.520 | No ejecutar consulta de muestra |

`scripts.recent_status_audit` detiene automáticamente muestras cuyo
plan estima más de 50.000 filas. El plan de Chile remesas requiere una
alternativa de extracción o una copia de análisis; no se crearán
índices ni se cambiará el esquema original.

## Remesas creadas recientemente

Bolivia remesas, tipos 4/16: 86 filas de los últimos siete días,
muestra no truncada. Estado fuente 0 (PENDING): 21; estado 1 (PAID):
65. Un estado pendiente reciente sin pago es parte posible del ciclo
normal y no implica discrepancia. No se hizo una consulta directa
equivalente a Chile remesas por el costo estimado.

## Pagos creados recientemente y edad de sus orígenes

| Dirección | Pagos muestreados | Muestra truncada | Origen de 30–60 días | Origen de más de 60 días |
|---|---:|---|---:|---:|
| BO→CL | 93 | No | 5 | 0 |
| CL→BO | 150 | Sí | 0 en muestra | 0 en muestra |

BO→CL: edad máxima del origen al auditar, 41,12 días; mayor diferencia
observada entre creación de remesa y pago, 40,89 días. No aparecieron
códigos ambiguos ni orígenes sin encontrar dentro de los tipos
seleccionados en estas muestras. CL→BO alcanzó el límite de 150:
no extrapolar sus proporciones a toda la semana.

Los importes no se compararon. Las fechas entre países son locales y
no están normalizadas a una zona horaria común. La ausencia de pago
no se evalúa aquí; `PAYMENT_MISSING` requiere cobertura del destino
y una regla de plazo de pago aprobada por modalidad.
