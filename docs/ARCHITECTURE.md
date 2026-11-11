# Arquitectura técnica

## Objetivo
Gambarte Reconciliation Hub es un servicio independiente para reconciliar remesas de Bolivia y Chile. Se implementa en **Python / FastAPI / MariaDB 11.4 / Docker Compose**, sin modificar inicialmente los sistemas CGR.

## Clean Architecture / módulos
- `app/domain`: entidades inmutables, reglas puras y aritmética decimal.
- `app/application`: casos de uso de conciliación.
- `app/integrations`: adaptadores de extracción de esquemas existentes.
- `app/infrastructure`: SQLAlchemy, ingesta, historial, modelos.
- `app/api`: presentación HTTP, autorización y contratos.
- `app/workers`: extracción y conciliación fuera de peticiones HTTP.

La API usa exclusivamente la base central. El ETL consulta los orígenes mediante usuarios SQL **SELECT only**. El motor de conciliación crea resultados reproducibles por `run_id` para el conjunto de datos de la ejecución; faltan marcas de corte inmutables para reproducibilidad completa.

## Fuentes
- Bolivia: `remesa` y `pago`; se añadirán `saldo_caja`, `co_asientos`, `co_partidas` y referencias entre operación y asiento.
- Chile: **`tmp_reporte_remesa` es la fuente principal y consolidada**, alimentada desde remesas y `deposito_bancario`. Para evidencia adicional de pago se consulta `pago`.
- Estas definiciones vienen de los proyectos históricos y deben cotejarse con estructuras actuales y datos sintéticos.

## Persistencia inicial
- `source_records`: estado normalizado y última versión de cada fila de origen.
- `source_versions`: copias por hash cada vez que cambia el registro.
- `sync_runs`: bitácora de sincronización.
- `reconciliation_runs` y `discrepancies`: ejecuciones y hallazgos.

## Restricciones de seguridad
- No credenciales ni PII en Git.
- No publicar MariaDB ni conectar los sistemas antiguos directamente a Internet sin VPN/TLS.
- Las bases originales no reciben escrituras desde este servicio.
- La API exige `X-API-Key` para todo excepto health; /docs solo en desarrollo.
- No generar saldos financieros con restas de remesas de distintas monedas.
- Es necesario mejorar autorización por roles, auditoría y rate limits para producción.

## Estado
**Scaffold funcional, no apto todavía para conciliaciones financieras reales.** Se requiere validar códigos de operación, direcciones, depósitos bancarios, pagos parciales, registros contables y frescura de fuentes.
