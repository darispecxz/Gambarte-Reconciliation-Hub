# Cierre operativo preliminar — enero 2026

Informe generado el 13 de noviembre de 2026 utilizando **archivos de conciliación de origen ya exportados**, sin consultas nuevas a producción.

## Universo y corte

| Cohorte de cierre | Cantidad |
|---|---:|
| Enero con pago antes del cierre | 2.833 |
| Diciembre con pago en enero | 20 |
| Enero con pago posterior al cierre | 53 |
| Anuladas (`CANCELLED` en piloto; códigos negativos) | 8 |
| Devueltas (`RETURNED` en piloto; códigos positivos) | 3 |
| **Total** | **2.917** |

**Total con pago durante enero:** 2.853 (2.833 + 20). No sumar las 53 operaciones pagadas en febrero a los pagos del período enero.

## Clasificación monetaria

| Evidencia | Casos |
|---|---:|
| Mismo tipo de moneda, importes nominales iguales, *no certificados* | 2.600 |
| FX: `remesa.total_clp = pago.total` | 219 |
| FX: diferencia estrictamente mayor a cero y hasta ±10 CLP | 87 |
| FX: diferencia superior a ±10 CLP | 0 |
| Sin pago identificado; revisión de estado | 11 |

Las 306 conversiones corresponden a BOB→CLP (254), BOB→USD (25), USD→CLP (27). Las 87 diferencias toleradas están en la ruta BOB→CLP.

En todos los 306 pares FX, los importes fuente coinciden con el piloto, la cotización CLP/USD coincide numéricamente y `pago.total` coincide con `ROUND(pago.monto * pago.tipo_cambio, 0)`.

De los 306: 284 pagados en enero desde enero, 14 emitidos en diciembre y pagados en enero, 8 pagados después del cierre. Las diferencias toleradas: 86 de enero y una de diciembre pagada en enero; ninguna posterior al cierre.

## Riesgos/limitaciones

- El rango operativo de **±10 CLP inclusive** fue confirmado por GAMBARTE; esta tolerancia no modifica campos originales ni prueba entrega, liquidación o saldo físico.
- Los 2.600 casos de igualdad nominal no tienen aún verificación individual de los importes del sistema original equivalente a los 306 FX; **no confundir igualdad nominal con certificación**.
- Los 11 `CLOSED_STATUS_REVIEW` estaban exclusivamente en Chile→Bolivia, pero el resumen consolidado perdió una clasificación previamente disponible: 8 `CANCELLED` (códigos negativos) y 3 `RETURNED` (positivos). El origen de la verificación son `detalle_conciliacion_enero_2026.csv`, `conciliacion_bidireccional_enero_2026.csv` y `conciliacion_enero_con_pagos_febrero.csv` con coincidencia de ID piloto origen. No son 11 pagos pendientes; su estado cerrado tampoco demuestra reintegro efectivamente ejecutado.
- La fecha de modificación de remesa no reconstruye un estado histórico as-of si hubo modificaciones posteriores.
- El informe no investiga fuentes de auditoría ajenas a remesa y pago.

## Insumos de referencia

- `private-reports/cierre_operativo_enero_2026.csv`: 2.917 operaciones y criterio temporal.
- `private-reports/validacion_rutas_monetarias_v2.csv`: clasificación monetaria.
- `private-reports/validacion_importes_iguales_enero_2026.csv`: 2.600 comparaciones nominales.
- `private-reports/conciliacion_monetaria_306_enero_2026.csv`: contraste indexado del total CLP, fórmula, tasa, evidencia de importe.

Las rutas anteriores son archivos privados **no incorporados al repositorio**. La versión de consulta HTML/CSV debe conservarse dentro del almacenamiento privado para reportes.

## Rectificación de estados del cierre (noviembre de 2026)

Las remesas CL_TO_BO identificadas mediante los registros originales del piloto son:

| Estado | Códigos |
|---|---|
| `CANCELLED` | -3946978, -4389715, -4766568, -6113512, -6782133, -7794111, -9079751, -9483331 |
| `RETURNED` | 2481233, 2693535, 3673787 |

Con esto, la clasificación operativa es **2.853 pagos en enero, 53 posteriores, 8 anuladas y 3 devueltas**. El indicador `SIN_PAGO_IDENTIFICADO_REVISAR_ESTADO`/`CASO_PENDIENTE_DE_REVISION` del resumen anterior era una pérdida de información y queda sustituido. Esto no certifica el flujo de devolución del dinero.
