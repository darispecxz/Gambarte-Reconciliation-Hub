# Roadmap y mejoras priorizadas

## P0 — requisitos para producción
- [x] Migración 0002 y tablas de conciliación operativa.
- [x] ETL keyset con cursor de reanudación por página.
- [x] Proyecciones normalizadas y trazabilidad por source_links.
- [x] Eventos observados y resultados individuales por ejecución.
- [x] API de búsqueda de remesas, pagos, eventos y coincidencias.
- [x] Validación de frescura de sincronización y bloqueo de fuentes fallidas.
- [x] Pruebas de dominio + CI MariaDB temporal (código configurado; comprobar ejecución).
- [ ] Confirmar esquemas y campos reales de Chile/Bolivia, incluidas las columnas de `tmp_reporte_remesa` y `pago`.
- [ ] Confirmar estados, direcciones y tipos de operación; mejorar correlación por más de `codigo`.
- [ ] Comparación de importes con concepto, moneda de pago esperada y tolerancia verificada.
- [ ] Garantizar fuente y vista consistentes con snapshot/CDC y backfills profundos.
- [ ] Concurrencia de workers: `GET_LOCK`, leases con heartbeat o claims transaccionales.
- [ ] Control de acceso por rol/token, límites HTTP, rotación de API keys, auditoría de administración.
- [ ] Alertas de jobs fallidos, SLO, logs estructurados, métricas y trazas.
- [ ] Prueba de Docker local y ensayos de recuperación; respaldo/restauración programados.
- [ ] Pruebas con muestras sintéticas basadas en operación real, no con datos personales.

## P1 — completar controles operativos
- [ ] Validar múltiples pagos y depósitos parciales; tolerancias CLP/BOB/USD.
- [ ] Revisar anulaciones que alteran código y estados de remesa.
- [ ] Cruces de movimientos de caja `saldo_caja` Bolivia y `saldo_unidad` Chile.
- [ ] Reportes diarios de envío, pendiente, pagado, devuelto, anulado.
- [ ] CSV/Excel/PDF de resultados y diferencias.
- [ ] Reproducibilidad temporal con snapshot de origen y corte común.

## P2 — contabilidad y finanzas
- [ ] Integración de `co_asientos` y `co_partidas`, Debe/Haber y vínculo estructurado.
- [ ] Reglas de contrato de corresponsalía y comisiones por participación.
- [ ] Obligaciones CL↔BO por moneda, contraparte y fecha de devengo.
- [ ] Libro de compensaciones con aplicaciones dobles, transferencias y comprobantes.
- [ ] Saldos iniciales auditados, cierres diarios inmutables y aprobaciones.

## P3 — plataforma
- [ ] Webhooks firmados y API para automatizaciones externas.
- [ ] Dashboard central de operaciones y discrepancias.
- [ ] Escalado horizontal con una cola y garantías de entrega.
