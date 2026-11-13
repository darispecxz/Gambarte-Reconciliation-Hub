# Flujo mensual de conciliación: preflight desde febrero 2026

El cierre de enero sigue siendo histórico y tiene cohortes específicas.
**No replicar sus totales, distribución monetaria ni tolerancias de otros
países** en períodos posteriores.

## Paso 1: cobertura histórica del piloto

El script `scripts/pilot_monthly_readiness_2026.py` comprueba los
checkpoints de extracción existentes para:

- Mes anterior: remesas y pagos de Bolivia y Chile (arrastre).
- Mes objetivo: remesas y pagos de ambos países.
- Mes siguiente: pagos de Bolivia y Chile (pagos después del corte).

En febrero, revisa enero/febrero/marzo. **No consulta sistemas fuente**,
solo el piloto Docker aislado. Un resultado
`READY_FOR_MANUAL_COVERAGE_VALIDATION` significa que las diez
extracciones terminaron su recorrido, **no** cobertura histórica certificada.

Ejemplo Git Bash (desde raíz del proyecto):

```bash
git pull origin feat/operational-reconciliation-phase-b
docker compose -f compose.pilot.yaml --profile pilot build pilot-import
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  -v "$(pwd -W)/private-reports:/export" \
  pilot-import python -m scripts.pilot_monthly_readiness_2026 \
  --month 2026-02 --output /export/preflight_febrero_2026.html
```

Este comando crea HTML y CSV privados, aun cuando falte cobertura.
`BLOCKED_INCOMPLETE_PILOT` es **un resultado esperado** si todavía
no se han extraído febrero o marzo. No crear reportes definitivos usando
cero como sustituto de faltantes.

## Paso 2: validación humana de cobertura

Una vez terminados los checkpoints, usar `pilot_month_count` para
EXPLAIN y, solo con plan seguro, conteos por fuente/mes. Confirmar
cobertura de fechas, pagos posteriores y operaciones originadas antes
del mes objetivo. No asumir que **solo** el mes anterior cubre todos
los casos arrastrados: operaciones más antiguas podrían seguir vigentes.

## Paso 3: conciliación y reporte

A partir del piloto validado, generar nuevo corte con los registros
completos del período. Separar: operaciones pagadas en mes; pagos
posteriores; anteriores pagados en mes; anuladas; devueltas. Para
la verificación CLP, usar tolerancia **±10 CLP inclusive** acordada
para las comparaciones que tengan significado monetario confirmado.
No aplicar esta holgura como tolerancia USD o BOB.

**Restricciones:** mantener `enable_source_etl=false` y
`source_mapping_verified=false`. Todas las fuentes de producción
solo lectura y por plan indexado. No cambiar los estados originales,
ni certificar entrega, balances o devolución efectiva con un
check de importes.
