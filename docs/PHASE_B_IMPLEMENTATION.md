# Implementación etapa B — Conciliación operativa

## Objetivos y estado

Se añadieron seis tablas a la BD **exclusiva de conciliación**: `sync_cursors`, `source_links`, `remittances`, `payments`, `remittance_events`, `reconciliation_matches`. Las cinco tablas MVP existentes permanecen.

**Código implementado en rama de revisión; no hay conexión real a Bolivia/Chile ni certificado de producción.**

## Tabla a tabla

| Tabla | Clave | Uso |
|---|---|---|
| sync_cursors | UNIQUE(source,dataset) | Ventana de consulta, avance por (PK, tipo), reinicio tras fallos y último éxito |
| source_links | UNIQUE(source_record_id,entity_type,entity_id) | Relación verificable de dato importado a proyección |
| remittances | UNIQUE(source_record_id) | Una fila por operación fuente, sin unir países solo por código |
| payments | UNIQUE(source_record_id) | Pagos individuales, soporte de múltiples pagos |
| remittance_events | UNIQUE(source_version_id) | Cambios observados, no eventos históricos inventados |
| reconciliation_matches | (run_id,remittance_id) consultable | Resultado de comparación con evidencia por ejecución |

## Flujo

1. Adaptador lee solo los campos necesarios en origen.
2. Paginación keyset `(id, operation_type)` y extracción por fecha con superposición.
3. Persistencia transaccional en `source_records` + `source_versions` y proyección normalizada.
4. A cada cambio de remesa se registra un evento `OBSERVED_*` con `observed_at` real. El sistema no inventa la fecha exacta del pago si no la conserva.
5. Los cursores se guardan con el mismo commit que las páginas importadas. Fallos reanudan desde la última página confirmada.
6. El motor no se ejecuta si falta una fuente, existe un error reciente, la sincronización está en curso, la ventana no está cubierta o las fuentes están desactualizadas.
7. Una reconciliación registra un `reconciliation_matches` por operación primaria, con resultado y evidencia. Las discrepancias son un subconjunto consultable.

## Reglas de resultado

- `MATCHED`: remesa de origen con estado PAID, dirección verificada y evidencia de pago en destino; puede no existir una remesa espejo en el país pagador. **No certifica importes ni obligaciones**.
- `PAYMENT_MISSING`: pago ausente de una operación PAID cubierta por sincronización.
- `MISSING_ORIGIN` / `MISSING_DESTINATION`: operación no encontrada en ventana respaldada por sincronización.
- `STATUS_MISMATCH`: estados incompatibles o dirección contradictoria.
- `PENDING`: todavía no corresponde cerrar operación.
- `MANUAL_REVIEW`: varias contrapartes/pagos; pagos parciales legítimos no se declaran duplicados automáticamente.
- `INSUFFICIENT_DATA`: dirección, moneda, identidad o cobertura insuficiente.

## Advertencias de precisión (muy importantes)

- Los mapeos antiguos de estados (`estado`) e `id_operacion` son **provisionales**. El motor de fuentes reales se activa únicamente al poner `ENABLE_SOURCE_ETL=true` y `SOURCE_MAPPING_VERIFIED=true` tras revisar la BD actual.
- En Chile `tmp_reporte_remesa` **consolida `remesa` y `deposito_bancario`**; nunca reemplazarla por la tabla remesa individual.
- `id_remesa + id_operacion` es una identidad de extracción provisional; validar unicidad de depósitos.
- Un código puede colisionar. No se combinan automáticamente dos operaciones en una sola fila; se registra ambigüedad si hay varias candidatas.
- `monto` de remesa y `monto` de pago pueden tener distinto significado, incluso cuando ambas monedas parecen iguales; se posterga la validación monetaria hasta confirmar importes contractuales de destino.
- Los extractores no aplican conversiones con tasas fijas ni cambian los sistemas CGR.
- Los estados `MATCHED` son únicamente conciliaciones de evidencia operativa, nunca certificaciones contables o de liquidación.
- Las ventanas retrospectivas no equivalen a CDC: correcciones con fecha vieja pueden requerir backfill histórico específico.
- Una única instancia de ETL/reconciler; introducir leases para múltiples réplicas.

## Pruebas

- `pytest tests/test_operational.py tests/test_safety.py tests/test_domain.py`
- `RUN_DB_TESTS=1 pytest tests/test_integration_db.py` requiere MariaDB dedicada con `alembic upgrade head`.
- GitHub Actions ejecuta pruebas de integración con una MariaDB **efímera**.
- La ejecución de pruebas en los sistemas CGR reales no está incluida.

## Pendientes para producción

Validar esquema, monedas, direcciones, identidad de depósitos y fechas de creación/modificación, cobertura completa, operaciones parciales y transferencias, concurrencia de workers, observabilidad, RBAC y auditoría administrativa. El reporte financiero y validación contable pertenecen a etapas posteriores.

## Corrección durante revisión CI
- FastAPI se distribuye como paquete `app` explícito mediante setuptools; `migrations` no se empaqueta como aplicación. Corrige el error inicial de instalación editable.
- Una remesa de origen **no necesita una segunda fila remesa en destino**. El pago en destino constituye evidencia operativa, de acuerdo con los patrones observados en el POC. Sin pago, se genera `PAYMENT_MISSING`; no se genera `MISSING_DESTINATION` por ausencia del espejo.
- La dirección de remesas registradas en Bolivia no se adivina: definir `BOLIVIA_TO_CHILE_OPERATION_TYPES` únicamente después de validar tipos y destinos reales.

## Resultado CI comprobado (2026-11-11)
GitHub Actions (rama de esta etapa): **24 pruebas aprobadas**, instalación editable completada y migraciones `0001_initial`→`0002_operational` aplicadas sobre MariaDB 11.4 efímera. Esto comprueba instalación y pruebas sintéticas, **no** conectividad ni datos reales de CGR.
