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

## Validaciones confirmadas (11-11-2026, consultas READ ONLY)

- Se verificó la existencia de columnas usadas por las consultas de
  Bolivia `remesa` y `pago`; Chile `tmp_reporte_remesa` y `pago`.
- **Contrato de negocio confirmado:** el origen guarda la remesa; el destino
  guarda el pago; el campo `codigo` coincide entre origen y destino.
  **BO→CL** cruza Bolivia.`remesa` con Chile.`pago`.
  **CL→BO** cruza Chile.`tmp_reporte_remesa` con Bolivia.`pago`.
  No exigir remesa espejo en el país pagador. Comprobar ambigüedad del código.
- Bolivia `moneda`: 1=USD, 2=BOB, 3=CLP (catalogadas también otras monedas).
- Chile `moneda`: 1=USD, 2=CLP, 3=BOB; 18=USD (remesa dólares),
  19=BOB (remesa bolivianos), 20=USD (cambio BO-CL).
  Los IDs 18/19/20 tienen **modalidades de negocio distintas**; el ID fuente
  se preserva como evidencia; no fusionar modalidades.
- Chile `tmp_reporte_remesa.moneda` es VARCHAR (ejemplo observado BOB),
  mientras que Chile `pago.mon_rec` y Bolivia `mon_rec` son IDs numéricos.
- **`abr_ori` y `abr_des` de Chile son localidades/agencias**, por ejemplo
  AGR, AIQ, ASP, ZFR, CBA, LPM. NO equivalen a códigos de país.
- Consultas agregadas de siete días observaron Bolivia remesa tipo 16
  (estado 0 y 1), pagos Bolivia tipos 3/4/7, Chile remesa tipos 3/5 y
  pagos Chile tipo 3. Observar un tipo NO demuestra que sea exclusivo de
  remesas transfronterizas; **no habilitar automáticamente**.
- No se ha confirmado la semántica de estados, la unicidad de código,
  la combinación única en vista Chile ni el significado contractual
  de los importes. Evitar etiquetar MATCHED como conciliación de montos.
- Las abreviaturas literales ARG y GYP se conservan como aparecen en el
  catálogo de Chile, sin cambiarlas a ARS/PYG por suposición.

## Implementación protegida

`app/integrations/source.py` mantiene diccionarios de monedas **separados**
por país, mientras la evidencia `raw.currency_id` conserva el identificador
original. Direcciones se asignan exclusivamente por listas de tipos
**aprobadas** y `SOURCE_MAPPING_VERIFIED=true`:

```dotenv
BOLIVIA_TO_CHILE_OPERATION_TYPES=
CHILE_TO_BOLIVIA_OPERATION_TYPES=
SOURCE_MAPPING_VERIFIED=false
ENABLE_SOURCE_ETL=false
```

Estos valores deben seguir vacíos hasta analizar cada tipo de operación
y confirmar estados, singularidad y cobertura. El motor ya cruza
`(país_destino, codigo)` con pagos y conserva IDs de evidencia. Un
`PAYMENT_MISSING` solo debe informarse si la ventana del dataset
**pagos del destino** cubre la fecha de la remesa.
