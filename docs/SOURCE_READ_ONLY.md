# Protección de lectura para las bases originales

## Propósito

Las credenciales de Hostinger pueden pertenecer al usuario que también escribe
en las bases originales. Cuando el hosting no permite crear usuarios adicionales,
el adaptador de **Gambarte Reconciliation Hub** añade dos controles de defensa
en profundidad:

1. El SQL admitido debe ser una única consulta `SELECT` sin bloqueo, definida
   en el código del adaptador. No se acepta SQL arbitrario de usuarios o API.
2. Cada página de datos se consulta dentro de `START TRANSACTION READ ONLY`
   (MariaDB) y finaliza siempre con `ROLLBACK`, incluso si ocurre una excepción.

Se utilizó `START TRANSACTION READ ONLY` por transacción, en lugar de cambiar
el estado global de la sesión: esto limita el alcance al lote actual.

## Limitaciones importantes

**No es un usuario SQL de solo lectura.** Las credenciales compartidas siguen
teniendo cualquier permiso concedido por Hostinger. Otro proceso, o código
cambiado, podría abrir una sesión con escrituras. MariaDB rechaza modificaciones
normales mientras la transacción READ ONLY está activa, pero no es un sandbox
contra todo tipo de funciones o efectos secundarios del servidor. La garantía
fuerte sigue siendo un usuario restringido a SELECT o una réplica de solo lectura.

- Mantener `ENABLE_SOURCE_ETL=false` y
  `SOURCE_MAPPING_VERIFIED=false` hasta confirmar tablas y consultas.
- No compartir claves SQL con el frontend ni imprimirlas en logs.
- Restringir acceso por IP, red/VPN y TLS cuando el hosting lo permita.
- Nunca ejecutar migraciones Alembic contra Bolivia o Chile: la conexión de
  Alembic apunta exclusivamente a `gambarte_reconciliation`.
- La configuración `source_engine()` no debe usarse para otras operaciones;
  los extractores deben consumir exclusivamente el contexto
  `read_only_transaction()`.
- Cada llamada `fetch_page()` abre su propia transacción y termina con rollback;
  no conserva bloqueos ni altera el estado de las bases fuente.

## Verificación

`pytest tests/test_source_readonly.py -q`

La CI usa una MariaDB **temporal** con permisos de escritura para comprobar que
un `UPDATE` falla dentro de `START TRANSACTION READ ONLY`. No se intenta
ninguna escritura sobre las bases de Bolivia o Chile.
