# Operación y seguridad — Etapa B

## Instalación de pruebas
```bash
cp .env.example .env
# Cambiar API_KEY, DB_PASSWORD y MARIADB_ROOT_PASSWORD
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/v1/health
docker compose run --rm api python -m pytest -q
```

El servicio `migrate` aplica `alembic upgrade head` automáticamente antes de iniciar `api`, `etl` y `reconciler`.

**Migración 0004**: valida que no existan remesas Chile importadas con
la identidad vieja `op:id_remesa`. Si existen, fallará intencionalmente:
realizar copia de seguridad y plan de reindexación, sin borrar datos
ni forzar la migración. Los campos de cursor Chile cambian a
`op,codigo,id_destino`; reanudar una posición antigua no es seguro.

El ETL no se habilita automáticamente: `ENABLE_SOURCE_ETL=false` y `SOURCE_MAPPING_VERIFIED=false`. Primero revisar `SOURCE_MAPPING.md`.

## Acceso
API requiere cabecera `X-API-Key` excepto `/health`. No exponer directamente a internet sin reverse proxy HTTPS, segmentación de red, credenciales rotadas y control de acceso. En `ENVIRONMENT=production` se deshabilita OpenAPI público.

## Operación
- `docker compose logs -f etl reconciler`
- `docker compose logs migrate`
- `GET /api/v1/sync/status`: últimas ejecuciones.
- `GET /api/v1/sync/cursors`: última cobertura, avance y si existe una ventana inacabada.
- `POST /api/v1/reconciliations`: encola ejecución, devuelve ID.
- `POST /api/v1/reconciliations?cutoff_at=2026-10-31T23:59:59`: corte histórico conservador con fecha local; no se reconstruyen estados históricos del legado.
- `GET /api/v1/reconciliations/{id}/matches`: evidencias por operación.
- Un proceso de ingesta fallido deja el cursor en progreso; el siguiente intenta continuar desde la última página confirmada.

## Preproducción
- Validar con pruebas sintéticas la cadena de migraciones 0001→0002→0003→0004 y reinstalación desde cero.
- Preferir cuentas SQL SELECT-only en Bolivia y Chile, nunca root. Si el hosting no permite crear otro usuario, se habilitó una defensa adicional por sesión: cada consulta de origen se ejecuta dentro de `START TRANSACTION READ ONLY` y siempre se hace `ROLLBACK`; esto **no reemplaza** permisos SELECT a nivel servidor ni impide que las credenciales reutilizadas se empleen desde otro programa.
- Proteger secretos mediante variables/secret manager del servidor, y no comitear `.env`.
- Mantener DB central en red interna Docker; volumen persistente, respaldos cifrados, pruebas de restauración.
- Ejecución en una sola instancia por worker hasta implementar leases.
- Configurar `MAX_SOURCE_AGE_MINUTES` acorde a frecuencia del ETL; fuente fallida bloquea la conciliación.
- La API no genera balances financieros, no modifica remesas originales y no aprueba liquidaciones.

## Diagnóstico
Si una solicitud queda `BLOCKED`, revisar `/sync/status` y `/sync/cursors`. No interpretar `MISSING_DESTINATION` fuera de la cobertura registrada. Correr backfill histórico después de validar fechas y claves.

## Pruebas dentro de Docker
Tras cambiar Dockerfile o pyproject, reconstruir la imagen en lugar de usar la anterior:

```bash
docker compose build --no-cache api
docker compose run --rm api python -m pytest -q
```

El Dockerfile copia el código antes de ejecutar `pip install .[dev]`. `PYTHONPATH=/service` permite localizar `app` desde el ejecutable pytest y `cache_dir=/tmp/gambarte-pytest-cache` evita escribir archivos de cache en la carpeta `/service` que pertenece a root. El contenedor se sigue ejecutando con UID 10001, no con root.

## Validación cruzada de pagos tardíos (solo lectura)

Antes de activar los workers ETL se puede ejecutar desde el contenedor
`api` un **muestreo limitado** por fecha de pago:

```bash
docker compose run --rm api python -m scripts.audit_payment_age --days 7 --sample 150
```

- BO→CL: pagos de Chile `pago` 3/5/6/8 con operaciones de origen
  Bolivia `remesa` 4/16 mediante `codigo`.
- CL→BO: pagos de Bolivia `pago` 4/7 con origen
  Chile `tmp_reporte_remesa` 3/5/6/8 mediante `codigo`.
- Selecciona como máximo 150 pagos recientes **por dirección**, consulta
  códigos en bloques de 20 y solo muestra contadores agregados.
- Si `sample_is_capped=True`, el resultado es una muestra truncada y
  no se debe extrapolar como porcentaje del período completo.
- Imprime pagos con origen de más de 30 días, 7–30 días, <=7 días,
  códigos ambiguos, sin origen dentro de tipos seleccionados, o fechas
  inconsistentes. Una ausencia de origen **no prueba un error**:
  puede haber modalidades distintas, códigos no globalmente únicos
  o registros cancelados/reconstruidos.
- Las fechas entre bases pueden tener zonas horarias diferentes:
  valores cercanos al límite deben revisarse antes de atribuir días exactos.
- Abre transacciones `START TRANSACTION READ ONLY` en ambas fuentes,
  termina con ROLLBACK y cierra las conexiones, sin activar el ETL.
- Si encuentra demasiadas filas por código, detiene el proceso en vez
  de clasificar registros incompletos.
- No certifica saldos, importes, ausencia de pagos ni integridad total.
  No garantiza estabilidad de dos bases remotas durante la muestra.
- Ejecutarlo fuera de las horas pico: la búsqueda de origen por `codigo`
  puede requerir escaneos si no existen índices adecuados. Revisar
  `EXPLAIN` y permisos SELECT-only antes de ampliar el volumen.

**No activar** `ENABLE_SOURCE_ETL` ni `SOURCE_MAPPING_VERIFIED`
hasta revisar estos resultados y la cobertura del backfill/solapamiento.

## Desglose de antigüedad para dimensionar el backfill

El mismo diagnóstico imprime bandas adicionales `paid_between_30_and_60_days_after_origin`,
`paid_between_60_and_90_days_after_origin`,
`paid_more_than_90_days_after_origin` y `max_lag_days`
(máximo observado **entre los pagos de más de 30 días** de la muestra).
No se modifica ninguna fuente ni se revelan códigos.

```bash
git pull origin feat/operational-reconciliation-phase-b
docker compose build api
docker compose run --rm api python -m scripts.audit_payment_age --days 7 --sample 150
```

La muestra BO→CL de 101 pagos de la semana, fechada 2026-11-11,
mostró 6 pagos cuyo origen superaba 30 días; CL→BO fue una muestra
truncada de 150. **No decidir 90 días de backfill sin observar el
desglose**. Una importación retrospectiva completa tampoco resuelve
todos los casos futuros: pagos antiguos con origen fuera de la ventana
necesitan recuperación específica y control de cobertura.

## Preflight de extractores: una página, sin ETL ni persistencia

Antes de permitir una importación limitada, ejecutar el diagnóstico que
utiliza la **misma SQL de los cuatro extractores** (no SQL simplificada).
No inicia el worker, no realiza `ingest()`, no escribe registros ni
cursores centrales, solo usa `START TRANSACTION READ ONLY` y rollback.
Rechaza la ejecución si `ENABLE_SOURCE_ETL` o
`SOURCE_MAPPING_VERIFIED` son true.

Primero inspeccionar solo el plan de Chile:

```bash
docker compose run --rm api python -m scripts.preflight_source --source CHILE --dataset remittance --days 60 --limit 50 --explain-only
```

Si el plan es razonable, ejecutar **una sola página**:

```bash
docker compose run --rm api python -m scripts.preflight_source --source CHILE --dataset remittance --days 60 --limit 50
```

Luego revisar de manera independiente los otros tres datasets:

```bash
docker compose run --rm api python -m scripts.preflight_source --source BOLIVIA --dataset remittance --days 60 --limit 50 --explain-only
docker compose run --rm api python -m scripts.preflight_source --source BOLIVIA --dataset payment --days 60 --limit 50 --explain-only
docker compose run --rm api python -m scripts.preflight_source --source CHILE --dataset payment --days 60 --limit 50 --explain-only
```

Solo después de revisar los planes, retirar `--explain-only`
individualmente. Usa un máximo de 100 filas por ejecución, 90 días
de retrospectiva y transacciones de solo lectura. Muestra acceso,
índice, filas estimadas, elapsed, total y estados agregados. No mostrar
códigos, cantidades de dinero ni identidades de clientes. Los tiempos
son medidas de una sola página, no un benchmark de todo el ETL.
SQL de otros países/tipos aún podría tener columnas o índices
incompatibles: este preflight debe exponer esos errores sin activar
ingesta.

## Cobertura por antigüedad al momento de importar

`scripts.audit_payment_age` ahora distingue expresamente
`max_lag_days` (diferencia *pago menos creación*) y
`max_origin_age_days_at_audit` (*NOW() de la DB de origen menos
creación*). La segunda determina si un backfill de 30/60/90 días
incluiría los orígenes encontrados en la muestra. `sample_is_capped`
advierte de truncamiento.

Este muestreo no comprueba modificaciones históricas ni asegura
que todos los documentos se puedan recuperar, y un backfill
retrospectivo finito no reemplaza reconciliación de cobertura y
resolución puntual segura de pagos tardíos.

**Fase siguiente aún pendiente:** una importación explícita, de un
solo dataset, a una DB central aislada y con límites de filas,
sin worker automático. Debe esperar a que todos los preflight estén
revisados y se haya validado la identidad/reglas de negocio.
