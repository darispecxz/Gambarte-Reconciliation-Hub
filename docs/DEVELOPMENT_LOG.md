# Bitácora de desarrollo

## 2026-11-11 — Etapa A: Bootstrap
- Proyecto FastAPI, SQLAlchemy, MariaDB Docker, API básica y ETL exploratorio.
- Revisión de código de Bolivia y Chile y POC .NET.
- Documento de mapeos provisional, sin conexión real a producción.

## 2026-11-11 — Etapa B: Conciliación operativa
1. Nueva rama `feat/operational-reconciliation-phase-b`, basada en `feat/initial-fastapi-mvp`.
2. Nueva migración `0002_operational_reconciliation`: `sync_cursors`, `source_links`, `remittances`, `payments`, `remittance_events`, `reconciliation_matches`.
3. Migración inicial `0001` congelada en DDL explícito: el `create_all` inicial impedía instalar `0002` en una BD vacía.
4. Extracción `LIMIT/OFFSET` sustituida por keyset `(source_pk, operation_type)` y checkpoint transaccional.
5. ETL real deshabilitado hasta verificar mapeos, usuarios SQL de lectura y origen principal Chile `tmp_reporte_remesa`.
6. Ingesta idempotente por firma SHA256, registro de versiones y proyección operativa en la misma transacción.
7. Eventos de cambio `OBSERVED_*` que distinguen fecha observada de evento real no demostrado.
8. Motor que exige sincronización completa y reciente; clasifica `MATCHED`, `PENDING`, `MISSING_ORIGIN`, `MISSING_DESTINATION`, `PAYMENT_MISSING`, `MANUAL_REVIEW`, `STATUS_MISMATCH`, `INSUFFICIENT_DATA`.
9. Nuevas rutas API para pagos, cambios observados, ejecuciones, evidencias y cursores.
10. Pipeline CI con servicio MariaDB temporal, migraciones y pruebas de dominios/DB.
11. Docker `migrate` aplica Alembic antes del resto de servicios.

### Diferencias con el POC
- No usa .NET ni depende del despliegue de Azure.
- El saldo financiero no se infiere con `chile_paid - bolivia_paid`.
- No compara cantidades entre monedas ni importes de rol no confirmado.
- Se conservan diferencias por ejecución y evidencia enlazada a origen.
- No marca duplicado todo registro de pago múltiple sin análisis de pagos parciales.

### Verificaciones pendientes
- Ejecución real de Docker/CI, conectividad y validación de esquemas.
- Cobertura histórica completa y semántica de estados/importes.
- Leases/locking al escalar workers.
- Integración de caja, contabilidad y liquidaciones financieras en fases siguientes.
