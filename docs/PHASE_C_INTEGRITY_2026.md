# Fase C — Integridad y cobertura (2026)

Rama: `feat/phase-c-integrity-coverage`. Solo piloto aislado; sin conexiones a
Bolivia/Chile desde estos reportes. **No certifica cobertura externa ni
conciliación financiera.** No programar ejecución automática todavía.

## Ejecutar

```bash
git checkout feat/phase-c-integrity-coverage
docker compose -f compose.pilot.yaml --profile pilot build pilot-import

MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  -v "$(pwd -W)/private-reports:/export" pilot-import \
  python -m scripts.pilot_phase_c_integrity_2026 \
  --through 2026-11-13 --output /export/fase_c_pagos_sin_origen_2026.csv

MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  -v "$(pwd -W)/private-reports:/export" pilot-import \
  python -m scripts.pilot_phase_c_source_links_2026 \
  --output /export/fase_c_integridad_local_2026.csv
```

Primera ejecución crea cuatro archivos privados:

- `fase_c_pagos_sin_origen_2026.csv`: pagos sin remesa compatible,
  múltiples candidatos o tipo de pago incompatible (no implica error real).
- `fase_c_pagos_sin_origen_2026_cobertura.csv`: estado mensual de los 44
  checkpoints históricos, sincronizaciones recientes y conteo en el piloto.
- `fase_c_pagos_sin_origen_2026_resumen.csv`: conteos de pareo inverso y
  clases de cobertura.
- `fase_c_integridad_local_2026.csv`: relación fuente guardada/proyección
  normalizada de ambos países y datasets.

## Interpretación

- `NO_ORIGIN_IN_PILOT` **no** significa pago sin remesa en producción.
  Puede tratarse de desfase temporal, ventana incompleta, origen 2025 no
  importado, un tipo de origen no habilitado o datos fuera del piloto.
- `PROVISIONAL_INVERSE_PAIR` es solo compatibilidad de código/tipo,
  sin verificar beneficiario, monto, FX o liquidación.
- `LOCAL_LINK_COUNTS_MATCH_NOT_CERTIFIED` solo acredita consistencia
  interna de la carga.
- `LOCAL_ONLY_SOURCE_COUNT_UNVERIFIED` indica que no hay conteo externo
  independiente que compruebe integridad histórica.
- `pilot_backfill_progress.rows_seen` es **histórico** y puede diferir
  del número actual de proyecciones luego de la actualización incremental.
  No inferir huecos ni duplicados de esa diferencia.
- El campo `coverage_certified` permanece `False` por diseño.

## Pendientes reales antes de certificar

1. Validar conteos externos por mes/país/dataset usando planes seguros en
   cada origen. Un `EXPLAIN` rechazado no debe forzarse.
2. Definir estrategia de extracción/verificación para modificaciones tardías
   de meses históricos y pagos posteriores al corte.
3. Revisar modalidades y códigos repetidos con Operaciones.
4. Verificar el alcance de años anteriores en pagos cuyo origen no se
   encuentra en el piloto.
5. Ejecutar los reportes nuevamente después de cada ciclo incremental.

No subir los CSV privados al repositorio, enviarlos por correo o compartir
sus códigos e importes públicamente.
