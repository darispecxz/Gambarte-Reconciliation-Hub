# Presentación a Gerencia — Conciliación Operativa Bolivia–Chile, gestión 2026

**Fecha de preparación:** 12 de noviembre de 2026.
**Período solicitado:** del 01/01/2026 hasta la fecha de corte explícita (no asumir diciembre cerrado).
**Naturaleza:** conciliación de presencia, estado y códigos entre los sistemas; NO es conciliación monetaria, FX ni cierre contable.

## Resumen ejecutivo

Se construyó una plataforma independiente que consulta los sistemas de Bolivia y
Chile en modo de solo lectura. La prueba piloto documentada en
`docs/PILOT_RESULTS.md` registra 200 filas (50 por dataset), 200 versiones,
100 remesas y 100 pagos, con idempotencia verificada en el entorno aislado.
En la pequeña muestra se identificaron 38 candidatos BO→CL y 1 CL→BO
por código. **No son 39 operaciones conciliadas de toda la gestión 2026.**
La muestra se eligió por orden de clave primaria y no por representatividad
temporal; algunas filas son de agosto y septiembre. No extrapolar porcentajes.

## Entregable ejecutable

`scripts.management_report_2026` genera un HTML imprimible con:
- registro mensual por país y dataset, fecha de creación 2026;
- estados de remesas registrados en la muestra;
- clasificación provisional por dirección y tipo de operación;
- advertencia visible: cobertura 2026 NO VERIFICADA;
- decisiones pendientes y exclusiones contables.

Se limita a `pilot-db` del proyecto Compose independiente, exige marcador
de origen piloto y ETL/mapping deshabilitados; abre transacción READ ONLY y
no imprime códigos ni importes. Para generar reporte local:

```bash
git pull origin feat/operational-reconciliation-phase-b
mkdir -p private-reports
# Asegurar que la carpeta esté excluida de git antes de guardar datos.
docker compose -f compose.pilot.yaml --profile pilot build pilot-import
docker compose -f compose.pilot.yaml --profile pilot run --rm \
  -v "${PWD}/private-reports:/export" pilot-import \
  python -m scripts.management_report_2026 \
  --year 2026 --through 2026-11-12 \
  --output /export/conciliacion_operativa_2026_preliminar.html
```

**ATENCIÓN:** verificar que `private-reports/` está ignorado por Git
(por ejemplo agregar la ruta a `.git/info/exclude` local antes de generar),
proteger accesos y no compartir el HTML fuera de la organización sin autorización.

## Qué falta para presentar resultados completos 2026

1. **Definir corte y alcance:** del 01/01/2026 al día de la extracción;
   identificar remesas originadas antes de 2026 y pagadas en 2026
   por separado; no omitirlas del análisis de pagos del año.
2. **Contrato de tipos:** revisión formal de cada remesa y pago
   transfronterizo. En Chile pagos 5/6/8 no se observaron en el
   muestreo acotado; evitar conclusiones basadas solo en defaults POC.
3. **Extracción histórica 2026:** procedimiento paginado y reanudable,
   con límite y plan SQL revisado por dataset, en etapas y fuera de horas pico.
   No cargar todos los meses sin plan de índices, estimación de volumen,
   autorización de responsable de datos y espacio suficiente en piloto.
4. **Cobertura verificable:** inventario de fechas/tipos, conteos de
   origen y destino reconciliados por mes, exclusiones y anulaciones,
   actualizaciones posteriores y reconciliación con el legado.
5. **Candidatos y excepciones:** comparar `codigo` + modalidad,
   no asumir unicidad global; rechazar repetidos, reversas y
   múltiples pagos hasta revisión; jamás certificar ausencia de pago
   sin cobertura íntegra y plazo aprobado.
6. **Trazabilidad:** exportar agregado gerencial y reporte privado por
   código únicamente con permiso, con referencias origen/destino,
   evidencia y revisión de excepciones.
7. **Validación formal:** operaciones y riesgos aprueban muestras
   individuales, plazos, estados y porcentajes; TI certifica el
   procedimiento técnico y la auditoría.
8. **Separar operativo de contable:** no prometer suma de diferencias,
   saldos, tipo de cambio, liquidación o cuadratura monetaria
   mientras no exista contrato contable adicional.

## Mensaje sugerido para Gerencia

> Se implementó y verificó una primera etapa técnica de conciliación
> operativa Bolivia–Chile mediante una base aislada y acceso de solo
> lectura a los sistemas originales. Esta etapa permite identificar
> correspondencias por código, estados y modalidades, y separar
> excepciones para su análisis. La consolidación de toda la gestión
> 2026 aún requiere validar reglas de negocio y completar una
> extracción histórica con cobertura comprobada. Los resultados
> preliminares no equivalen a cierre contable ni a certificación de
> pagos faltantes.

**No cambiar** `ENABLE_SOURCE_ETL=false` ni
`SOURCE_MAPPING_VERIFIED=false` con la evidencia disponible.
