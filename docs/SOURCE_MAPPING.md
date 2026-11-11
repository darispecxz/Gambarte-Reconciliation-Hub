# Mapeo de fuentes: contrato provisional

Los contratos de esquema, estados y tipos fueron contrastados con consultas READ ONLY, el POC y PHP históricos. **No se ha aprobado todavía la activación del ETL ni la unicidad histórica de claves.**

| Fuente | Objeto | Atributos proyectados | Estado |
|---|---|---|---|
| Bolivia | remesa | id_remesa, codigo, estado, monto, mon_rec, id_operacion, fechas | Columnas verificadas |
| Bolivia | pago | id_pago, codigo, monto, mon_rec, id_operacion, id_forma_pago, id_tipo_pago, fec_crea_pago | Columnas verificadas |
| Chile | tmp_reporte_remesa | id_remesa, codigo, estado, envio, moneda, id_operacion, abr_ori, abr_des, fechas | Columnas verificadas; identidad compuesta pendiente |
| Chile | pago | id_pago, codigo, monto, mon_rec, id_operacion, id_forma_pago, id_tipo_pago, fec_crea_pago | Columnas verificadas |

## Regla de Chile
`tmp_reporte_remesa` centraliza información de `remesa` y `deposito_bancario` y se debe utilizar como fuente principal del ETL. No sustituirla por lectura exclusiva de `remesa`.

## Comprobaciones necesarias antes de activar ETL
1. Verificar la unicidad de la combinación `(id_remesa, id_operacion)` dentro de la vista/tablas consolidadas, incluyendo depósitos bancarios.
2. Tipos `(4,16)`, `(4,7)`, `(3,5,6,8)` confirmados en el POC y legado; **validar vigencia de cada subtipo e impacto de operaciones no bilaterales**.
3. Estados definidos en el POC; verificar transiciones y casos reales de pagos tardíos.
4. `abr_ori`/`abr_des` son agencias/localidades; nunca inferir dirección desde ellas.
5. Catálogos de moneda por país verificados en lectura; conservar siempre el ID original como evidencia.
6. Distinguir `monto`, `envio`, `total`, `total_cambio` y tipo de cambio. No comparar valores sin confirmar su misma función.
7. Confirmar fechas, anulaciones, correcciones y pago tardío; validar que la ventana retrospectiva detecta estos cambios.
8. Definir si `codigo` puede repetirse por tipo/dirección/año y si cambia por anulación.
9. Definir pagos parciales y operaciones con múltiples depósitos sin marcar falsos duplicados.
10. Confirmar permisos SELECT, TLS/red y índices para paginación keyset.
11. Ajustar `app/integrations/source.py` y pruebas contractuales; solo entonces activar `ENABLE_SOURCE_ETL=true` y `SOURCE_MAPPING_VERIFIED=true`.

## Enfoque de validación
Trabajar sobre una copia anonimizada o entorno de pruebas. Verificar columnas con `SHOW CREATE TABLE`, índices y un conjunto pequeño de casos conocidos (envío, pago, devolución, depósito, anulación); no copiar datos privados a GitHub. La herramienta no modifica registros de Bolivia/Chile.

## Configuración de dirección
`BOLIVIA_TO_CHILE_OPERATION_TYPES=4,16` y `CHILE_TO_BOLIVIA_OPERATION_TYPES=3,5,6,8` representan los grupos del POC. **No son autorización de ETL**; revisar giros a destinos fuera del circuito bilateral. Las remesas sin dirección aprobada se clasifican como `INSUFFICIENT_DATA`.

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
- El POC documenta los estados, pero siguen pendientes la unicidad histórica
  de código, la combinación única de la vista Chile, transiciones extremas
  y el significado contractual de importes. MATCHED no concilia montos.
- Las abreviaturas literales ARG y GYP se conservan como aparecen en el
  catálogo de Chile, sin cambiarlas a ARS/PYG por suposición.

## Implementación protegida

`app/integrations/source.py` mantiene diccionarios de monedas **separados**
por país, mientras la evidencia `raw.currency_id` conserva el identificador
original. Direcciones se asignan exclusivamente por listas de tipos
**aprobadas** y `SOURCE_MAPPING_VERIFIED=true`:

```dotenv
BOLIVIA_TO_CHILE_OPERATION_TYPES=4,16
CHILE_TO_BOLIVIA_OPERATION_TYPES=3,5,6,8
SOURCE_MAPPING_VERIFIED=false
ENABLE_SOURCE_ETL=false
```

Los IDs de negocio están documentados, pero las dos barreras de seguridad
permanecen desactivadas hasta validar singularidad y cobertura. El motor ya cruza
`(país_destino, codigo)` con pagos y conserva IDs de evidencia. Un
`PAYMENT_MISSING` solo debe informarse si la ventana del dataset
**pagos del destino** cubre la fecha de la remesa.

## Contrato POC y legado PHP (revisión ampliada)

Se confirma el alcance operativo: BO remesa 4 (histórica, hasta 2024)
y 16 (giro internacional actual), BO pago 4 (ventanilla) y 7
(depósito); CL remesa y pago tipos 3,5,6,8 según el POC. La vista
consolidada CL asocia 3 con `remesa`, 5/6 con `deposito_bancario`
y 8 con `prestamo_bancario` en el PHP. Esto NO confirma que todos
los subtipos se comporten de forma idéntica. El estado 7 de Chile
es `PROCESSING`; el estado 3 es `RETURNED_SC`. Código negativo
en Chile se considera anulado de acuerdo con el POC.

Las listas permitidas incluyen los valores POC, pero **no habilitan
el ETL por sí solas**: `ENABLE_SOURCE_ETL=false` y
`SOURCE_MAPPING_VERIFIED=false` siguen siendo las barreras.
Para reglas de decisión y futuras cuentas ver los archivos
`OPERATIONAL_RECONCILIATION.md` y
`ACCOUNTING_RECONCILIATION_ROADMAP.md`.
