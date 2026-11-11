# Gambarte Reconciliation Hub

API y motor de conciliación de remesas **independiente** de los sistemas CGR Bolivia/Chile. Python 3.12, FastAPI, SQLAlchemy, Alembic, MariaDB 11.4 y Docker Compose.

**Estado: etapa B implementada para revisión técnica, NO habilitada para operaciones financieras reales.** Se necesitan validar los mapeos de los dos países. Este repositorio es público: nunca guardar credenciales ni datos de clientes.

## Componentes

- **api**: API REST de consulta y ejecución bajo demanda.
- **etl**: importación incremental de fuentes antiguas, con checkpoints en MariaDB.
- **reconciler**: procesamiento de conciliaciones por lotes desde los datos centralizados.
- **mariadb**: BD central `gambarte_reconciliation` independiente de ambas CGR.
- **migrate**: contenedor one-shot que aplica migraciones antes del arranque.

## Arranque local

```bash
cp .env.example .env
# Editar .env: API_KEY, DB_PASSWORD y MARIADB_ROOT_PASSWORD
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/v1/health
docker compose run --rm api python -m pytest -q
```

La migración 0004 adapta el cursor Chile al PRIMARY real
`(id_operacion,codigo,id_destino)` y detiene la actualización si se
detectan registros Chile con la identidad antigua. Consultar
[conciliación operativa](docs/OPERATIONAL_RECONCILIATION.md).

El ETL **no** intenta consultar bases reales por defecto: `ENABLE_SOURCE_ETL=false` y `SOURCE_MAPPING_VERIFIED=false`. Ver [mapeos](docs/SOURCE_MAPPING.md) antes de habilitarlo.

```bash
curl -H "X-API-Key: <clave>" http://127.0.0.1:8000/api/v1/sync/status
curl -H "X-API-Key: <clave>" http://127.0.0.1:8000/api/v1/remittances
curl -H "X-API-Key: <clave>" http://127.0.0.1:8000/api/v1/payments
curl -H "X-API-Key: <clave>" -X POST http://127.0.0.1:8000/api/v1/reconciliations
```

En `ENVIRONMENT=development` la documentación FastAPI está disponible localmente en `/docs`; se deshabilita en otros entornos. La API requiere `X-API-Key` salvo en `/health`.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | /api/v1/health | Salud DB |
| GET | /api/v1/sync/status | Últimos intentos ETL |
| GET | /api/v1/sync/cursors | Posición y cobertura por fuente |
| GET | /api/v1/remittances | Remesas normalizadas con filtros |
| GET | /api/v1/remittances/{id} | Detalle |
| GET | /api/v1/remittances/{id}/events | Cambios observados |
| GET | /api/v1/payments | Evidencia de pagos |
| POST | /api/v1/reconciliations | Solicitar trabajo asíncrono; `?cutoff_at=YYYY-MM-DDTHH:MM:SS` opcional |
| GET | /api/v1/reconciliations | Ejecuciones |
| GET | /api/v1/reconciliations/{id} | Estado/resultado |
| GET | /api/v1/reconciliations/{id}/matches | Evidencias y decisiones |
| GET | /api/v1/reconciliations/{id}/discrepancies | Excepciones |

## Documentación

- [Arquitectura y límites](docs/ARCHITECTURE.md)
- [Mapeo de fuentes y reglas pendientes](docs/SOURCE_MAPPING.md)
- [Contrato de conciliación operativa](docs/OPERATIONAL_RECONCILIATION.md)
- [Siguiente etapa: conciliación contable](docs/ACCOUNTING_RECONCILIATION_ROADMAP.md)
- [Etapa B: implementación y decisiones](docs/PHASE_B_IMPLEMENTATION.md)
- [Bitácora de desarrollo](docs/DEVELOPMENT_LOG.md)
- [Operación y seguridad](docs/OPERATIONS.md)
- [Roadmap](docs/ROADMAP.md)

## Advertencias

`tmp_reporte_remesa` es la fuente consolidada principal de Chile, incluyendo `remesa` y `deposito_bancario`. Los extractores preservan los datos y no modifican sistemas originales. Un `MATCHED` de esta fase comprueba presencia/estado/evidencia, **no monto final, comisión, contabilidad ni obligación bilateral**. Antes de producción verificar identidad, estados, direcciones, monedas, cobertura histórica y pagos parciales.
