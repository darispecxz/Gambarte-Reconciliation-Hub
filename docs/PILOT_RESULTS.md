# Primera importación piloto — 2026-11-12

## Alcance y resultados

- Proyecto Compose independiente `gambarte-pilot`; volumen
  `gambarte-pilot_pilot_mariadb_data`, distinto del volumen central.
- Origen Bolivia `remesa`, ventana de 60 días, máximo de 50 filas.
  Lectura dentro de `START TRANSACTION READ ONLY`, `ROLLBACK` y cierre.
- Primera importación: 50 filas cambiadas y commit de un solo lote.
- Auditoría: 50 `source_records`, 50 `source_versions`, 50
  `remittances`, 50 `source_links` y 50 `remittance_events`.
  Cero pagos, cursores y ejecuciones de sincronización.
- Cero identidades duplicadas, proyecciones/enlaces faltantes, huérfanos,
  diferencias de proyección o hashes de última versión inconsistentes.
- Segunda importación idéntica: 0 filas cambiadas, 50 sin cambios;
  los recuentos de registros, versiones y eventos permanecieron en 50.
- Prueba sintética en transacción con rollback: un cambio de estado
  produjo la segunda versión y `OBSERVED_STATUS_CHANGE`. La auditoría
  posterior confirmó que no dejó filas adicionales.
- Chile remesas superó además dos páginas de preflight (100 filas,
  0.275 y 0.240 s, clave compuesta en orden, sin duplicados).
- Vistas previas posteriores: Bolivia pagos, Chile pagos y Chile
  remesas, 50 filas cada una. El marcador piloto se verificó y la
  auditoría posterior conservó exactamente las 50 filas iniciales.
- Segundo lote autorizado: 50 pagos Bolivia. Auditoría combinada:
  100 `source_records`, 100 `source_versions`, 50 `remittances`,
  50 `payments`, 100 `source_links` y 50 `remittance_events`.
  Cero faltantes, duplicados, huérfanos o diferencias normalizadas.
  La segunda ejecución de pagos cambió 0 filas y mantuvo los recuentos.
- Tercer lote: Chile pagos. Preflight de dos páginas: 100 filas,
  0.208 y 0.204 s; clave en orden, sin duplicados. Vista previa de
  50 filas y destino piloto verificado. Importación: 50 filas nuevas.
  Auditoría: 150 `source_records`, 150 `source_versions`,
  50 `remittances`, 100 `payments`, 150 `source_links` y
  50 `remittance_events`; cero faltantes, duplicados, huérfanos o
  diferencias normalizadas. Segunda ejecución: 0 cambios.
- Cuarto lote: Chile remesas. Preflight de dos páginas: 100 filas,
  0.285 y 0.243 s, clave primaria compuesta en orden y sin duplicados.
  Vista previa de 50 filas; importación: 50 nuevas (46 PAID,
  4 CANCELLED). Auditoría: 200 `source_records`, 200
  `source_versions`, 100 `remittances`, 100 `payments`, 200
  `source_links`, 100 `remittance_events`, cero anomalías y cero
  identidades Chile inconsistentes con `op:codigo:id_destino`.
  Segunda ejecución: 0 cambios; recuentos intactos.
- Los cuatro datasets están disponibles exclusivamente para lotes
  manuales acotados en el piloto. La base central y los workers no se usan.
- Suite sin integración con base de datos: 78 aprobadas, 1 omitida.

La prueba no constituye cobertura histórica ni conciliación operativa o
contable. Las transiciones reales posteriores de las fuentes aún no han
sido observadas. No se habilitaron los workers.

## Candidatos por código en la muestra piloto

La extracción filtró filas creadas **o modificadas** en los 60 días
anteriores a cada ejecución, y después tomó las primeras 50 por clave
primaria ascendente. No seleccionó las 50 operaciones más recientes.
Rangos de `occurred_at` (fecha de creación en origen), comprobados en
solo lectura sobre el piloto:

| Dataset | Primera fecha | Última fecha |
|---|---|---|
| Bolivia remesas | 2026-08-25 11:27:39 | 2026-09-16 08:10:48 |
| Bolivia pagos | 2026-09-14 09:34:18 | 2026-09-14 15:47:56 |
| Chile remesas | 2026-09-07 09:28:24 | 2026-11-11 15:51:33 |
| Chile pagos | 2026-09-13 13:39:36 | 2026-09-17 12:00:34 |

Las fechas anteriores al corte de 60 días son posibles porque la fila
fue modificada dentro de la ventana. Las fechas de origen son valores
locales sin zona horaria normalizada.

`scripts.pilot_candidates` consulta exclusivamente la base piloto en
`START TRANSACTION READ ONLY` y termina con `ROLLBACK`. Solo imprime
recuentos agregados; no publica códigos ni importes.

| Dirección | Códigos de origen | Origen ambiguo | Un pago en muestra | Más de un pago | Remesa PAID + un pago |
|---|---:|---:|---:|---:|---:|
| BO→CL | 50 | 0 | 38 | 0 | 38 |
| CL→BO | 50 | 0 | 1 | 0 | 1 |

En BO→CL, 12 códigos de remesa no tienen pago en la muestra;
en CL→BO, 49. Hay asimismo 12 y 49 filas de pago, respectivamente,
sin remesa de origen dentro de esta pequeña muestra. Estos recuentos
**no prueban pagos u orígenes faltantes**: cada dataset contiene solo
sus primeras 50 filas elegibles, sin cursores de cobertura. Las
direcciones de negocio permanecen sin aprobación y el motor de
conciliación está bloqueado por `SOURCE_MAPPING_VERIFIED=false`.
Ningún candidato se persiste como `MATCHED`.

## Clasificación operativa provisional

`scripts.pilot_reconcile` aplicó reglas conservadoras en memoria,
leyendo solo el piloto con `START TRANSACTION READ ONLY` y `ROLLBACK`.
Los tipos por país son una hipótesis provisional; el script no activa
`SOURCE_MAPPING_VERIFIED`, no escribe `ReconciliationRun` ni declara
cobertura o montos conciliados.

| Dirección | Par único por código | Sin pago en esta muestra | Cerrada en esta muestra |
|---|---:|---:|---:|
| BO→CL | 38 | 12 | 0 |
| CL→BO | 1 | 45 | 4 |

`PROVISIONAL_CODE_PAIR` exige remesa `PAID`, un solo origen por
`codigo`, un pago en destino y metadatos monetarios presentes; no
compara importes. `NO_PAYMENT_IN_SAMPLE` no significa pago faltante.
Para Chile→Bolivia también exige los pares de tipos confirmados:
remesa 3 → pago 4, o remesa 5/6/8 → pago 7.
Las cuatro remesas cerradas no se consideran candidatas. Pruebas
dirigidas: 12 aprobadas. Auditoría posterior: los 200 registros,
200 versiones y 100 eventos permanecieron intactos.

## Secuencia para ampliar de forma gradual

1. Mantener una importación manual limitada por dataset, con la misma
   verificación de proyecto, host, nombre de base y marcador piloto.
   Agregar Bolivia pagos, Chile pagos y finalmente Chile remesas;
   revisar plan SQL y dos páginas antes de cada ampliación.
2. Para pagos recientes con remesas de origen anteriores a la ventana,
   diseñar recuperación puntual por `codigo` con límite de candidatos,
   tipos permitidos y clasificación de ambigüedad. No asumir unicidad
   global ni importar una coincidencia forzada.
   Analizar por separado remesas recientes todavía pendientes y pagos
   recientes asociados a remesas antiguas. Una remesa reciente sin pago
   puede estar siguiendo su ciclo normal; no clasificarla como pago
   faltante por su mera ausencia en la muestra. Antes de cualquier
   `PAYMENT_MISSING`, exigir cobertura verificada del destino y una
   regla de plazo de pago aprobada para la modalidad correspondiente.
3. Mantener 60 días de backfill inicial y 7 de solapamiento como
   hipótesis provisional. Medir la cola de antigüedad y correcciones
   históricas antes de afirmar cobertura; un intervalo fijo no basta
   para todos los pagos tardíos.
4. El cursor keyset progresa de forma estricta dentro de una página,
   pero las páginas del worker usan transacciones de fuente distintas.
   Cambios concurrentes de fecha, estado o clave pueden quedar fuera
   de una ventana ya recorrida. Registrar inicio, fin, recuento y
   posición de cada ventana, y comparar totales acotados antes de
   declarar una cobertura completa.
5. Reanudar solo desde un cursor confirmado junto con el lote central.
   Antes de múltiples réplicas, añadir un lease o bloqueo por dataset
   y probar interrupciones tras lectura, antes de commit y tras commit.
6. Comparar presencia y estado operativo primero. `MATCHED` indica
   evidencia de correspondencia; importes, FX y asientos pertenecen a
   la futura conciliación contable y requieren contratos aprobados.

No ejecutar importación masiva ni activar `ENABLE_SOURCE_ETL` o
`SOURCE_MAPPING_VERIFIED` con estos resultados.
