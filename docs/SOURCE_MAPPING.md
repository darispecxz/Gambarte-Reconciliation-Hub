# Mapeo de fuentes: contrato provisional

Los sistemas originales consultados corresponden a una versión histórica de PHP. El código del ETL **no debe habilitarse hasta revisar esquemas reales y mapeos**.

| Fuente | Objeto | Atributos proyectados | Estado |
|---|---|---|---|
| Bolivia | remesa | id_remesa, codigo, estado, monto, mon_rec, id_operacion, fechas | Por verificar |
| Bolivia | pago | id_pago, codigo, monto, mon_rec, id_operacion, fec_crea_pago | Por verificar |
| Chile | tmp_reporte_remesa | id_remesa, codigo, estado, envio, moneda, id_operacion, abr_ori, abr_des, fechas | Fuente consolidada confirmada conceptualmente |
| Chile | pago | id_pago, codigo, monto, mon_rec, id_operacion, fec_crea_pago | Por verificar |

## Regla de Chile
`tmp_reporte_remesa` centraliza información de `remesa` y `deposito_bancario` y se debe utilizar como fuente principal del ETL. No sustituirla por lectura exclusiva de `remesa`.

## Comprobaciones necesarias antes de activar ETL
1. Verificar la unicidad de la combinación `(id_remesa, id_operacion)` dentro de la vista/tablas consolidadas, incluyendo depósitos bancarios.
2. Confirmar tipos de operación Bolivia `(4,16)`, pagos `(4,7)`, Chile `(3,5,6,8)`. Son hipótesis del POC, no verdad garantizada.
3. Confirmar si `estado=1` es realmente PAID para cada tipo de operación y en cada país, y documentar las transiciones.
4. Verificar `abr_ori`/`abr_des` y direcciones reales para Bolivia; actualmente los registros Bolivia no informan dirección por defecto.
5. Identificar código ISO asociado a `mon_rec` y `moneda`. Un entero (FK) no debe convertirse en código de moneda mediante supuestos.
6. Distinguir `monto`, `envio`, `total`, `total_cambio` y tipo de cambio. No comparar valores sin confirmar su misma función.
7. Confirmar fechas, anulaciones, correcciones y pago tardío; validar que la ventana retrospectiva detecta estos cambios.
8. Definir si `codigo` puede repetirse por tipo/dirección/año y si cambia por anulación.
9. Definir pagos parciales y operaciones con múltiples depósitos sin marcar falsos duplicados.
10. Confirmar permisos SELECT, TLS/red y índices para paginación keyset.
11. Ajustar `app/integrations/source.py` y pruebas contractuales; solo entonces activar `ENABLE_SOURCE_ETL=true` y `SOURCE_MAPPING_VERIFIED=true`.

## Enfoque de validación
Trabajar sobre una copia anonimizada o entorno de pruebas. Verificar columnas con `SHOW CREATE TABLE`, índices y un conjunto pequeño de casos conocidos (envío, pago, devolución, depósito, anulación); no copiar datos privados a GitHub. La herramienta no modifica registros de Bolivia/Chile.

## Configuración de dirección Bolivia
`BOLIVIA_TO_CHILE_OPERATION_TYPES` es una lista de IDs separados por comas y **vacía por defecto**. Configurarla tras verificar el alcance de los tipos con casos reales y controlar giros a destinos distintos de Chile. Las remesas sin dirección verificada se clasifican como `INSUFFICIENT_DATA`.
