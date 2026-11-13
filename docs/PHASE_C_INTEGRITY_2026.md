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


## Investigación dirigida de pagos sin remesa en piloto

El siguiente comando consulta **únicamente los códigos** clasificados actualmente
como `NO_ORIGIN_IN_PILOT` (máximo 25 códigos distintos). Cada consulta en
Bolivia/Chile pasa por `START TRANSACTION READ ONLY` y `EXPLAIN`, con
máximo 50 filas por código. Solo exporta evidencia al directorio privado;
**no incorpora remesas automáticamente ni modifica producción/piloto**.

```bash
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  -v "$(pwd -W)/private-reports:/export" pilot-import \
  python -m scripts.pilot_phase_c_source_lookup_2026 \
  --through 2026-11-13 \
  --output /export/fase_c_busqueda_origen_2026.csv \
  --max-codes 25
```

Los resultados `ORIGIN_FOUND_IN_SOURCE` indican solamente que el código fue
localizado; usar `origin_rows_2025`, `origin_rows_2026` y
`origin_types_found` para investigar. Si un plan es rechazado, se informa
`LOOKUP_BLOCKED_OR_INCONCLUSIVE`, nunca «no existe». Los resultados
`NO_ORIGIN_FOUND_BY_CODE` tampoco demuestran ausencia definitiva. El
emparejamiento requiere validar modalidad, titularidad, fechas, pago y FX
antes de cualquier certificación.

Los códigos ambiguos (como los dos pagos bajo un código) y la modalidad
incompatible se mantienen en los reportes existentes; no se modifican ni se
declaran duplicados fraudulentos automáticamente.


## Regla operacional confirmada: devoluciones en Bolivia

Operaciones confirmó que **un valor no vacío de `pago.motivo` en Bolivia
identifica un pago de devolución local**, no un desembolso en destino.
Ejemplos: códigos `27691` y `43023`, ambos `id_operacion=4`.
No publicar los motivos completos, que contienen texto privado.

El extractor SELECT de Bolivia/pago ahora recoge
`p.motivo AS return_reason` en la evidencia `source_records.payload`.
La auditoría inversa los clasifica como
`RETURNED_LOCALLY_IN_BOLIVIA` con prioridad sobre
`NO_ORIGIN_IN_PILOT`. No se elimina ningún registro ni se modifica el
estado original de la remesa. Las devoluciones se muestran como categoría
independiente, no como pagos cruzados a Bolivia.

**Importante:** registros previamente importados no tienen esta columna en
el payload. Para capturar los dos casos confirmados, refrescarlos por código
en el piloto con el módulo ya validado, después de reconstruir la imagen:

```bash
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm pilot-import \
  python -m scripts.pilot_refresh_payment_code --code 27691
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm pilot-import \
  python -m scripts.pilot_refresh_payment_code --code 43023
```

Si el resultado de cada consulta es seguro y único, la variante
`--apply --acknowledge-sensitive-data` actualiza **solo el piloto**.
Después, generar nuevamente los reportes de Fase C. No supone que otros
pagos antiguos sin `return_reason` sean pagos normales: el dato aún no fue
capturado en ellos y requiere actualización antes de auditar masivamente
las devoluciones.


## Recuperación dirigida del año 2025 — opt-in

Con las devoluciones locales de Bolivia separadas, el módulo
`scripts/pilot_phase_c_recover_2025.py` calcula en vivo los casos
`NO_ORIGIN_IN_PILOT` restantes (máximo 25 códigos). Para cada código:

1. Comprueba que tenga un solo pago candidato en el piloto.
2. Consulta por código el origen en la base correspondiente mediante SELECT
   protegido por EXPLAIN y transacción READ ONLY.
3. Acepta únicamente un registro de origen, de 2025, con tipo compatible.
4. No incorpora registros ambiguos, fuera de 2025, con fecha nula o tipo
   incompatible; informa categorías `REVIEW_*`.
5. No modifica checkpoints históricos de 2026, ni considera estas recuperaciones
   evidencia de cobertura histórica total.

**Simulación obligatoria recomendada (sin escrituras):**

```bash
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  pilot-import python -m scripts.pilot_phase_c_recover_2025 \
  --through 2026-11-13 --max-codes 25
```

Si todos los candidatos están clasificados como `ELIGIBLE_2025_SOURCE`,
ejecutar explícitamente (solo piloto):

```bash
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  pilot-import python -m scripts.pilot_phase_c_recover_2025 \
  --through 2026-11-13 --max-codes 25 \
  --apply --acknowledge-sensitive-data
```

Los códigos se recalculan al iniciar cada ejecución: una operación pagada
entretanto o reclasificada como devolución no se importará como origen
pendiente si dejó de pertenecer a `NO_ORIGIN_IN_PILOT`.

Tras aplicar, repetir la auditoría inversa de Fase C. No afirmar 20/20
resueltos hasta que el log de simulación y el nuevo informe lo demuestren.

**Limitación:** el origen puede cambiar entre la simulación y la aplicación;
la ejecución con `--apply` vuelve a consultar, validar y verificar los
registros, sin usar ciegamente la evidencia anterior.


## Revisión de duplicados y modalidades con evidencia

`scripts/pilot_phase_c_case_evidence.py` implementa reglas puras para
clasificar **posibles** duplicaciones de registro y diferencias de modalidad.
No se conecta a bases, no cambia estados, ni modifica el catálogo de modalidades.

- Dos pagos de Bolivia con el mismo código, importe, moneda, comprobante,
  agencia, usuario, operación y comisión, creados en <=60 segundos, dan
  `SUSPECTED_DUPLICATE_RECORD_MANUAL_REVIEW`. Esto NO confirma doble
  liquidación. Operaciones/Contabilidad debe verificar el efecto en saldos,
  asientos, kardex y comprobantes antes de autorizar cualquier reversión.
- Igual código, importe y moneda, pero distinto tipo de pago respecto al
  contrato de modalidades: `REVIEW_MODALITY_MISMATCH_SAME_CURRENCY_AMOUNT`.
  Solo Operaciones puede confirmar un canal excepcional antes de ampliar
  `DESTINATION_PAYMENT_TYPES`.
- Nunca publicar datos de identidad, documentos o teléfonos procedentes de
  estas verificaciones; las pruebas usan referencias sintéticas.
- Las cinco observaciones permanecen en su estado de revisión hasta
  validación humana. No borrar uno de los pagos ni automatizar decisiones.
