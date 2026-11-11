# Roadmap / mejoras

## P0 — antes de despliegue operacional
- [ ] Verificar fuente `tmp_reporte_remesa`, datos de depósitos, direcciones, IDs y códigos.
- [ ] Confirmar esquema e índices reales de remesa/pago en Bolivia y Chile.
- [ ] Sustituir LIMIT/OFFSET por paginación keyset con cursor persistido y watermark.
- [ ] Crear backfill histórico, reconciliación retrospectiva y control de lotes incompletos.
- [ ] Correlación robusta por sistema, tipo, dirección, identidad original y versión.
- [ ] Comprobar frescura/consistencia de fuentes antes de reportar hallazgos.
- [ ] Distinguir pagos parciales legítimos de duplicados.
- [ ] Test de integración MariaDB + migraciones + ETL con datos sintéticos.
- [ ] Autenticación por servicio y roles, rate limits, auditoría y rotación de secretos.
- [ ] Leases para jobs; idempotencia y recuperación ante crash/reinicio.
- [ ] Instrumentación, alertas, backups y ensayos de restauración.

## P1 — conciliación operativa
- [ ] Historial de envío, pago, anulación y devolución, fechas y estados de corte.
- [ ] Cruces de caja Bolivia `saldo_caja` y Chile `saldo_unidad`.
- [ ] Conciliación de depósito bancario con evidencia de pago.
- [ ] Reglas de tolerancia por moneda y cotizaciones históricas explícitas.
- [ ] Reportes diarios, excepciones y PDF/Excel.
- [ ] Comparación controlada del reporte agosto 2025.

## P2 — contable y financiera
- [ ] Extraer `co_asientos` y `co_partidas`, vinculaciones de operación-asiento, Debe/Haber.
- [ ] Cuentas por cobrar/pagar entre Bolivia y Chile y comisiones separadas.
- [ ] Obligaciones bilaterales y saldos iniciales certificados por moneda.
- [ ] Compensaciones con doble aplicación simétrica y aprobaciones.
- [ ] Transferencias bancarias con confirmación y conciliación de extractos.
- [ ] Cierres diarios auditables e inmutables.

## P3 — automatización
- [ ] Webhooks firmados y contratos OpenAPI para consumidores externos.
- [ ] Tablero de auditoría y métricas.
- [ ] CI/CD con pruebas obligatorias, despliegue progresivo y rollback.
