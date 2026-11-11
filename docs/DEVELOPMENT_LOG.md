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

## Resultado de integración CI
- Corregido paquete setuptools: solo `app` se publica; los directorios de migraciones y pruebas no se detectan como paquetes de distribución.
- Ajustado matching para permitir remesa de origen + pago en destino aunque no exista remesa espejo en el destino.
- GitHub Actions: **24 passed**, migraciones ejecutadas sobre MariaDB 11.4 temporal el 2026-11-11. No hubo integración real con DB CGR.

## 2026-11-11 — Corrección de pruebas locales Docker
- Diagnóstico de `ModuleNotFoundError: No module named app` durante `docker compose run --rm api pytest -q`.
- Causa: `Dockerfile` instalaba `pyproject.toml` **antes** de copiar `app`, a diferencia de GitHub Actions (que instalaba el proyecto completo).
- Corrección: copiar el código primero, instalar el paquete completo y definir PYTHONPATH, caché pytest escribible y comando `python -m pytest`.
- Reforzada CI: construir la imagen Docker y ejecutar pytest dentro de ella con usuario no root, además de las pruebas de integración MariaDB fuera de Docker.

## 2026-11-11 — Validaciones reales de estructura y mapeo (sin escritura)

- Bolivia y Chile MariaDB accesibles por Docker con transacciones READ ONLY.
- Catálogos de moneda independientes confirmados; Bolivia ID 2=BOB,
  Chile ID 2=CLP. En vista Chile moneda es texto y en pagos es FK numérica.
- Relación de negocio confirmada: remesa en origen, pago en país destino,
  clave `codigo` compartida; sin obligación de remesa espejo.
- La consulta Bolivia remesa→pago local no encontró registros en siete días,
  consistente con el flujo entre países.
- Ajustado normalizador y listas de tipos aprobados, sin inferir direcciones
  desde abreviaturas de localidad. Regla de cobertura del pago faltante
  evalúa la sincronización del dataset destino `payment`, no `remittance`.
- ETL sigue deshabilitado por defecto hasta completar estados, unicidad,
  semántica de tipos y validación con casos controlados.
