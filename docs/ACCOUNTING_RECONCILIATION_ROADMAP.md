# Próxima fase: conciliación contable Bolivia–Chile

**Alcance:** fuera de la fase operativa. Este documento es una guía de
implementación basada en el POC y el legado PHP, no una liquidación certificada.

## Fuentes y contratos que deben validarse

- Bolivia `co_asientos` y libros auxiliares; verificar permisos, índices,
  estructura y reglas reales de cierre antes de incorporar nuevos extractores.
- POC: `Reconciliation.Domain/RemittanceStatus.cs` y
  `Reconciliation.Application/Services/RemittanceService.cs`.
- Asociar asiento con `codigo`, período, agencia, tipo de documento, moneda,
  cuenta y naturaleza débito/crédito; **no emparejar sólo por texto**.
- No reutilizar el monto de la remesa de origen como importe de pago en destino:
  `monto`, `total_cambio`, `envio`, `total_clp`, `total_bob` representan
  conceptos distintos. Establecer contrato de importes y reglas FX primero.

## Patrones de conceptos encontrados en el POC (no reglas de verdad universal)

| Dirección/caso | Patrón de concepto observado |
|---|---|
| Bolivia → Chile pendiente | `%ENVIO DE%` |
| Bolivia → Chile pagada | `PAGO EN DESTINO%` |
| Chile → Bolivia pagada (pendiente de cobro) | `%PENDIENTES DE COBRO DEL PAGO DE REMESA%` |
| Chile → Bolivia pagada (comprobante) | `%PAGO DE REMESA CGR%` |

El POC también filtra documentos de tipo `EC-ER` en uno de los casos;
validar criterios exactos con contabilidad y muestras reales.

## Plan de trabajo

1. Obtener contratos de tablas, fechas de contabilización y catálogo de
   conceptos/cuentas por país y por producto (4/16, 3/5/6/8, 4/7).
2. Añadir extractores únicamente SELECT, cursores reanudables y registros de
   evidencia contable inmutables por versión; migración central separada.
3. Vincular operación y pago operacional con sus asientos sin colapsar
   movimientos que compartan código.
4. Validar casos: pendiente, pagado, anulado, devuelto, en proceso,
   pago tardío, asiento faltante, múltiples asientos y reverso.
5. Comparar importes sólo con moneda, tipo de cambio, comisión, impuesto,
   redondeos CLP y tolerancia **aprobados** para cada concepto.
6. Construir saldos de apertura, movimientos del día, cierres y arrastre
   por fecha contable; distinguir fecha de pago vs modificación de remesa.
7. Validar conjuntamente los reportes del POC:
   Daily Operations, Accounting Validation, General Reconciliation.
8. Aprobar formalmente resultados contra cierres históricos y casos
   anonimizados antes de exponer saldos como conciliados.

## No incluido en el motor operacional actual

- Extracción de `co_asientos`, equivalencia de cuentas o doble partida.
- Tasas de cambio y conversión automática o tolerancias financieras.
- Certificación de liquidación, balance diario ni conciliación general.
- Reconstrucción exacta de estados históricos: los eventos observados por
  el ETL no equivalen a auditoría completa del legado.

## Seguridad

Las bases CGR permanecen **solo lectura** desde el conector. No consultar
producción para pruebas CI ni publicar códigos, nombres, documentos o secretos.
