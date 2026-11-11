# Contrato de conciliación operativa, etapa B

Referencias: POC `poc-conciliaciones-remesas` (RemittanceStatus.cs,
RemittanceRepository.cs, ChileRemittanceRepository.cs, RemittanceService.cs);
ZIP de PHP Bolivia y Chile. Ver `SOURCE_MAPPING.md` para moneda y esquema.

## Dirección, identidad y extracción

| Dirección | Origen (remesa) | Pago en destino | Tipos |
|---|---|---|---|
| BO→CL | Bolivia `remesa` | Chile `pago` | Remesa 4 histórica / 16 vigente; pagos Chile 3/5/6/8 según POC |
| CL→BO | Chile `tmp_reporte_remesa` | Bolivia `pago` | Remesa Chile 3/5/6/8; pagos Bolivia 4 (ventanilla), 7 (depósito) |

La clave de cruce es el **mismo `codigo`** entre origen y destino,
pero su unicidad histórica debe verificarse; si hay varias filas no forzar
una relación 1:1. No exigir remesa espejo en el país que paga.

La vista `tmp_reporte_remesa` consolida productos distintos; en el
PHP de Chile se observaron las tablas `remesa` (3),
`deposito_bancario` (5,6) y `prestamo_bancario` (8).
El significado de cada subtipo requiere validación de negocio. Los
códigos `abr_ori`/`abr_des` son agencias, no países.

## Estados

- Bolivia: 0 PENDING, 1 PAID, 2 RETURNED, 5 CANCELLED.
- Chile: 0 PENDING, 1 PAID, 2 RETURNED, 3 RETURNED_SC,
  4 CHANGED, 5 CANCELLED, 6 TO_RETURN, 7 PROCESSING, 8 SAVINGS.
- El POC trata código negativo en Chile como cancelación.
  Conservamos ese código original; no se intenta emparejar con el positivo.
- Estados intermedios y finales no equivalen a PAID.

## Decisiones de conciliación (solo presencia operativa)

| Resultado | Regla |
|---|---|
| MATCHED | Origen PAID + un pago del otro país con mismo código |
| PENDING | Estado de origen no pagado, sin pago en destino |
| STATUS_MISMATCH | Pago en destino y origen aún no pagado, o dirección conflictiva |
| PAYMENT_MISSING | Origen PAID y pago no encontrado, con cobertura de origen de pagos suficiente |
| PENDING_AS_OF | Solo hay pago posterior al corte |
| CLOSED | Devuelta/anulada, sin pago vigente identificado |
| MANUAL_REVIEW | Más de un pago, código ambiguo o pago sobre operación cerrada |
| INSUFFICIENT_DATA | Dirección/moneda/fecha no comprobada, datos o cobertura histórica incompletos |

Una coincidencia **NO certifica importes**. Montos en origen y destino
pueden ser distintos por moneda, rol económico y cambio.

## Cierre histórico

`POST /api/v1/reconciliations?cutoff_at=YYYY-MM-DDTHH:MM:SS`
guarda la fecha de corte (naive, hora local de fuentes; no UTC)
y sólo considera remesas creadas hasta entonces. Pagos con fecha
posterior se muestran en `payments_after_cutoff_ids` y clasifican
`PENDING_AS_OF` cuando son los únicos pagos.

**Límite fuerte:** los estados actuales son snapshots; no se reconstruye
el estado exacto que tenían al cierre. Sin historial íntegro de pagos,
ausencia al corte es `INSUFFICIENT_DATA`, jamás ausencia certificada.
Los `OBSERVED_*` son cambios vistos por el ETL, no bitácora completa.

## Fallback entre países

PHP Chile paga localmente y notifica a Bolivia mediante `wsa.php`;
PHP Bolivia registra pagos locales y notifica a Chile `ws/ws.php`.
Fallos o retrasos entre pasos generan estados no sincronizados.
Nuestro motor **no reintenta ni escribe** en sistemas fuente: detecta
`STATUS_MISMATCH` para revisión y deja evidencia identificable.

## Seguridad y activación

`ENABLE_SOURCE_ETL=false` y `SOURCE_MAPPING_VERIFIED=false`
por defecto. Antes de activar: validar que los 4 tipos de Chile, los
IDs de origen, las claves `(id_remesa,id_operacion)` únicas de la vista,
las fechas y la cobertura de cambios cumplen el contrato. Las
operaciones documentadas son defaults de allowlist, NO certificación
de disponibilidad productiva.

Próxima fase: `docs/ACCOUNTING_RECONCILIATION_ROADMAP.md`.
