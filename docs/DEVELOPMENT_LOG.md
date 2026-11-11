# Bitácora de desarrollo

## 2026-11-11 — Entrega inicial
1. Creación de README y primer commit para inicializar el repositorio vacío.
2. Rama `feat/initial-fastapi-mvp` para revisar la primera implementación.
3. Estructura modular de capas separadas (dominio, aplicación, adaptadores, infraestructura y API).
4. Docker Compose: API, ETL, conciliador y MariaDB 11.4.
5. Modelo persistente para filas de origen, versiones por hash, ejecuciones y discrepancias.
6. Extractores SQL de lectura Bolivia/Chile basados en el POC. **Chile utiliza tmp_reporte_remesa**.
7. API con health, estado ETL, remesas, creación y consulta de conciliaciones, discrepancias.
8. Motor operativo inicial (pagada sin pago; múltiples pagos; diferencia misma moneda) y bloqueo cuando falta sincronización.
9. Pruebas unitarias para reglas puras y cantidades decimales.
10. Documentación de mapeos, arquitectura, operación y roadmap.

## Alcance NO realizado
- No se conectó a producción ni se procesaron datos reales.
- No se probaron aún los contenedores con una base real.
- No se implementó conciliación contable ni el libro financiero.
- No se validaron las tablas Chile/Bolivia contra la versión productiva.
- No se implementaron compensaciones, transferencias, asientos ni cierre financiero.

## Riesgos abiertos
- Consulta ETL con LIMIT/OFFSET: debe cambiarse a keyset con snapshot o watermark consistente.
- Ingesta reconsulta 30 días, pero no captura modificaciones anteriores: se requiere recarga histórica programada.
- `codigo` puede colisionar entre operaciones o sufrir cambios tras anulación; definir correlación compuesta.
- Chile podría incluir operaciones BOL→CL y CL→BO; confirmar antes de usar dirección.
- Falta esquema financiero, tolerancias por moneda y firmas de aprobación.
- Fallos simultáneos y workers múltiples requieren leases/locks persistentes.
- Falsos positivos si las fuentes se sincronizaron en momentos diferentes.
