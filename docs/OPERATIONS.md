# Operación y seguridad — Etapa B

## Instalación de pruebas
```bash
cp .env.example .env
# Cambiar API_KEY, DB_PASSWORD y MARIADB_ROOT_PASSWORD
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/v1/health
docker compose run --rm api pytest -q
```

El servicio `migrate` aplica `alembic upgrade head` automáticamente antes de iniciar `api`, `etl` y `reconciler`.

El ETL no se habilita automáticamente: `ENABLE_SOURCE_ETL=false` y `SOURCE_MAPPING_VERIFIED=false`. Primero revisar `SOURCE_MAPPING.md`.

## Acceso
API requiere cabecera `X-API-Key` excepto `/health`. No exponer directamente a internet sin reverse proxy HTTPS, segmentación de red, credenciales rotadas y control de acceso. En `ENVIRONMENT=production` se deshabilita OpenAPI público.

## Operación
- `docker compose logs -f etl reconciler`
- `docker compose logs migrate`
- `GET /api/v1/sync/status`: últimas ejecuciones.
- `GET /api/v1/sync/cursors`: última cobertura, avance y si existe una ventana inacabada.
- `POST /api/v1/reconciliations`: encola ejecución, devuelve ID.
- `GET /api/v1/reconciliations/{id}/matches`: evidencias por operación.
- Un proceso de ingesta fallido deja el cursor en progreso; el siguiente intenta continuar desde la última página confirmada.

## Preproducción
- Validar con pruebas sintéticas la migración 0001→0002 y reinstalación desde cero.
- Preferir cuentas SQL SELECT-only en Bolivia y Chile, nunca root. Si el hosting no permite crear otro usuario, se habilitó una defensa adicional por sesión: cada consulta de origen se ejecuta dentro de `START TRANSACTION READ ONLY` y siempre se hace `ROLLBACK`; esto **no reemplaza** permisos SELECT a nivel servidor ni impide que las credenciales reutilizadas se empleen desde otro programa.
- Proteger secretos mediante variables/secret manager del servidor, y no comitear `.env`.
- Mantener DB central en red interna Docker; volumen persistente, respaldos cifrados, pruebas de restauración.
- Ejecución en una sola instancia por worker hasta implementar leases.
- Configurar `MAX_SOURCE_AGE_MINUTES` acorde a frecuencia del ETL; fuente fallida bloquea la conciliación.
- La API no genera balances financieros, no modifica remesas originales y no aprueba liquidaciones.

## Diagnóstico
Si una solicitud queda `BLOCKED`, revisar `/sync/status` y `/sync/cursors`. No interpretar `MISSING_DESTINATION` fuera de la cobertura registrada. Correr backfill histórico después de validar fechas y claves.
