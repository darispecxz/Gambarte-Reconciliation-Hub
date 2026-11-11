# Operación y despliegue (entorno de pruebas)

## Arranque
1. `cp .env.example .env`.
2. Cambiar **API_KEY**, DB_PASSWORD y MARIADB_ROOT_PASSWORD por valores aleatorios robustos.
3. `docker compose up -d --build`.
4. `docker compose run --rm api alembic upgrade head`.
5. `curl http://127.0.0.1:8000/api/v1/health`.
6. `curl -H "X-API-Key: <clave>" http://127.0.0.1:8000/api/v1/sync/status`.
7. `docker compose run --rm api pytest -q`.

## Antes de fuentes reales
- Obtener únicamente usuarios SQL de lectura.
- Confirmar disponibilidad y TLS/VPN; no exponer puertos 3306 a internet.
- Probar consultas con LIMIT en copias de datos o entornos de prueba.
- Validar índices, claves, fechas y tipos de operación.
- Revisar privilegios de los contenedores y preservar MariaDB mediante backups probados.
- Configurar `ENVIRONMENT=production` para deshabilitar docs públicos; TLS a través de proxy.
- Monitorizar `sync_runs` y errores.
- No considerar hallazgos preliminares equivalentes a cierres o saldos financieros.

## Recuperación
Revisar `docker compose logs etl reconciler`; no eliminar `source_versions`. La ingesta utiliza clave (origen, dataset, id) y hash para evitar duplicados por relectura. Para recargas históricas, añadir rangos configurables sin sobreescribir el historial.
