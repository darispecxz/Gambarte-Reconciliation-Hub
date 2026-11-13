# Conteos de cobertura mensual con bloqueo seguro

La vista chilena `tmp_reporte_remesa` generó, el 13 de noviembre de
2026, `EXPLAIN type=ALL, key=None, rows=398594` para un `COUNT(*)`
de enero. El guardia bloqueó correctamente la consulta; no se debe
desactivar, forzar un conteo sin índice ni tomar el checkpoint como
conteo certificado.

El archivo `scripts/pilot_monthly_counts_safe_2026.py` ejecuta las diez
comparaciones de enero/febrero/marzo, **continúa** después de un plan
bloqueado y genera un CSV privado indicando coincidencias, bloqueos
y otros errores. El código de salida es 3 si quedaron bloqueos de
seguridad, 2 si hubo otros errores, 0 si los diez conteos coincidieron.
Nunca etiqueta un bloqueo como igualdad.

```bash
git pull origin feat/operational-reconciliation-phase-b
docker compose -f compose.pilot.yaml --profile pilot build pilot-import
MSYS_NO_PATHCONV=1 docker compose -f compose.pilot.yaml --profile pilot run --rm \
  -v "$(pwd -W)/private-reports:/export" \
  pilot-import python -m scripts.pilot_monthly_counts_safe_2026 \
  --output /export/conteos_cobertura_febrero_2026.csv
```

Los conteos bloqueados para Chile remittance **permanecen sin verificar**.
La resolución futura requiere una estrategia de conteo indexado con
`EXPLAIN` seguro específico para esa vista, sin scans completos y sin
consultas de alta carga sobre producción.

El conteo es puntual, no prueba cobertura de operaciones abiertas
antes del mes anterior, pagos tardíos más allá de marzo, ni entrega.
