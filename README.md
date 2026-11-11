# Gambarte Reconciliation Hub

Servicio independiente de conciliación de remesas Bolivia–Chile. **MVP en desarrollo:** FastAPI + Python + MariaDB + workers CLI + Docker Compose. Los sistemas CGR originales no se modifican.

## Objetivo

1. Extraer datos de Bolivia (`remesa`, `pago`) y Chile (`tmp_reporte_remesa` como fuente consolidada; `pago` para verificar pagos).
2. Normalizar y conservar referencias, moneda e importes **sin convertir o compensar valores de distintas monedas**.
3. Detectar diferencias operativas y generar ejecuciones auditables y consultables desde la API.
4. Extender posteriormente a la validación contable, conciliación financiera, compensaciones, transferencias y cierres formales.

## Estado y límites

Este repositorio comienza con un MVP técnico independiente. Los esquemas reales, códigos de operación, conectividad y reglas financieras necesitan validación antes de habilitar producción. **No se registran liquidaciones ni se cambian estados en las bases de origen**. Consultar [arquitectura](docs/ARCHITECTURE.md), [mapeos](docs/SOURCE_MAPPING.md), [bitácora de desarrollo](docs/DEVELOPMENT_LOG.md), [operación](docs/OPERATIONS.md) y [mejoras](docs/ROADMAP.md).

## Desarrollo local

```bash
cp .env.example .env
# Elegir valores seguros en .env; nunca enviarlo al repositorio.
docker compose up -d --build
docker compose run --rm api alembic upgrade head
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/docs
docker compose run --rm api pytest -q
```

**Nota:** la API arranca sin credenciales de Bolivia/Chile. Los extractores se habilitan al configurar las conexiones y validar los mapeos de la versión desplegada. Endpoint /docs debe protegerse o deshabilitarse al exponer el servicio públicamente.

## API inicial

- `GET /api/v1/health`
- `GET /api/v1/sync/status`
- `GET /api/v1/remittances?limit=50&offset=0`
- `POST /api/v1/reconciliations`: genera un trabajo; requiere credencial administrativa para operaciones
- `GET /api/v1/reconciliations/{run_id}`
- `GET /api/v1/reconciliations/{run_id}/discrepancies`

Este repositorio es **público**: no incluir credenciales, datos de clientes, extractos de producción ni configuraciones privadas.
