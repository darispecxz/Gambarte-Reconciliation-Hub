# Arquitectura de Gambarte Reconciliation Hub

## Independencia
La aplicación es un monolito modular Python/FastAPI con tres procesos separados: API, ETL y reconciler. Una base MariaDB 11.4 central es propiedad exclusiva del servicio. El servicio no modifica tablas de los sistemas existentes.

## Dependencias
- `domain`: reglas puras y tipos de conciliación, sin I/O.
- `application`: orquestación de casos de uso.
- `integrations`: adaptadores SQL de las bases legadas, solo SELECT.
- `infrastructure`: persistencia central, ORM y controles de versiones.
- `api`: rutas HTTP, validación y API key.
- `workers`: tareas repetibles y asíncronas, sin solicitudes HTTP prolongadas.

## Modelo de información
1. `source_records` + `source_versions`: copia mínima de la evidencia importada y su historia observada.
2. `remittances`, `payments`, `remittance_events`: vistas normalizadas, con vínculo por `source_links`.
3. `sync_runs` + `sync_cursors`: registros de ETL y puntos de reanudación.
4. `reconciliation_runs`, `reconciliation_matches`, `discrepancies`: decisiones y hallazgos por ejecución.

El mismo `codigo` puede existir en varias operaciones o ambos países. No fusionar filas por código sin validar la dirección, el tipo y la correspondencia de origen. `remittance_events` utiliza etiquetas `OBSERVED_*`: no presenta como hecho histórico un cambio que solo fue detectado al sincronizar.

## Fuentes
- Bolivia: `remesa`, `pago`, después caja y contabilidad.
- Chile: **`tmp_reporte_remesa`** es la fuente más actualizada y consolida `remesa` y `deposito_bancario`; `pago` aporta evidencia adicional.
- El mapeo SQL de ambas DB se deriva de proyectos históricos y está **deshabilitado inicialmente**.

## Matching
Se procesa la operación del país de origen cuando la dirección está confirmada. Se compara con una contraparte de dirección compatible, se inspeccionan estados y evidencias de pago, y se obtiene una decisión con su evidencia. Los registros ambiguos van a `MANUAL_REVIEW`; los mapeos incompletos van a `INSUFFICIENT_DATA`.

`MATCHED` no implica monto conciliado. Sin confirmar cuál campo es monto de envío y cuál corresponde al desembolso de destino, sería peligroso compararlos incluso en la misma moneda.

## Límites de la fase B
- No hay libro de obligaciones, asientos, transferencias, compensaciones ni cierres regulatorios.
- No se ha validado integración con DB operativas reales.
- ETL usa keyset por PK+operación y una ventana retrospectiva de solapamiento: cambios antiguos con marcas de fecha erróneas pueden requerir backfill completo.
- Un solo worker de ETL y un solo reconciler: para escalado horizontal faltan locks/leasing transaccionales.
- No hay snapshot global atómico entre Bolivia y Chile; se registran fechas de sincronización, y se bloquea cuando hay fuentes recientes fallidas/desactualizadas.
- El almacenamiento JSON conserva únicamente columnas proyectadas, no información personal adicional.
- Cuentas fuente deben ser de lectura, idealmente a través de VPN/TLS.

## Migraciones
`0001_initial` define explícitamente las primeras 5 tablas (se corrigió el antiguo uso dinámico de `create_all` antes del primer despliegue). `0002_operational_reconciliation` crea las 6 tablas de la fase B. Ejecutar Alembic en el servicio `migrate` antes de API/workers.
