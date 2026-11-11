# Mapeos de origen: revisión obligatoria

Los SQL de `app/integrations/source.py` derivan del POC .NET y los ZIP de PHP. No se ha validado su compatibilidad con bases actuales.

| Sistema | Tabla | Campos usados | Observaciones |
|---|---|---|---|
| Bolivia | `remesa` | id_remesa, codigo, estado, monto, mon_rec, id_operacion, fechas | id_operacion provisional: 4, 16 |
| Bolivia | `pago` | id_pago, codigo, monto, mon_rec, id_operacion, fec_crea_pago | id_operacion provisional: 4, 7 |
| Chile | `tmp_reporte_remesa` | id_remesa, codigo, envio, moneda, estado, abr_ori, abr_des, fechas | **Consolidación autoritativa de remesa y deposito_bancario** |
| Chile | `pago` | id_pago, codigo, monto, id_operacion, fec_crea_pago | Operaciones provisionales: 3, 5, 6, 8 |

## Importante
1. Confirmar qué direcciones representa realmente cada `id_operacion`. En el POC Chile contiene varias operaciones; NO puede deducirse únicamente por el país de origen.
2. Confirmar `id_remesa` único para registros de depósito bancario incorporados en `tmp_reporte_remesa`. Podría requerirse clave compuesta.
3. Confirmar si código cambia en anulaciones y cómo recuperar su identidad estable.
4. Comprobar que `fec_mod_remesa` cambia por cada modificación y definir un backfill completo.
5. Confirmar moneda/unidades de `monto`, `envio`, `total_cambio` y `pago.total`. No se introduce tipo de cambio fijo.
6. Documentar pagos parciales y múltiples movimientos legítimos.
7. Añadir mapeo de caja y contabilidad (co_asientos/co_partidas), con vínculos por IDs estructurados, no búsquedas parciales en conceptos.

Hasta cerrar estas verificaciones, los reportes del motor son **hallazgos preliminares**.
