# Contrato financiero pendiente de confirmar — enero de 2026

## Alcance

La conciliación no puede equiparar sin prueba `pago.monto` con los pesos
chilenos entregados, aunque `pago.mon_rec` identifique CLP. El reporte
de enero contiene 306 casos de monedas diferentes: 254 BOB→CLP,
25 BOB→USD y 27 USD→CLP. Solo 12 tienen consulta dirigida a campos
originales; todos permanecen `NOT_CERTIFIED`.

## Evidencia observada en las fuentes históricas

- Los 12 pares dirigidos coinciden en sus importes numéricos con el piloto.
- En 12/12, `remesa.tipo_cambio_clp` coincide numéricamente con
  `pago.tipo_cambio`; esto **no verifica su aplicación como fórmula**.
- Los cuatro USD→CLP examinados presentan `pago.monto` igual al valor
  USD enviado y `pago.mon_rec=2` en Chile (CLP). No considerar
  `pago.monto` como CLP efectivo por ese solo dato.
- Las 11 remesas sin evidencia de pago y los pagos fuera de enero
  permanecen en cohortes separadas.

## Pista de código — Gambarte POS moderno, NO evidencia histórica

Repositorio: `darispecxz/gambarte-api`,
`app/Modules/Cajero/Services/CajeroRemesaService.php`
(consultado en noviembre de 2026).

- En el registro de remesas, `monto`, `total_cambio`,
  `tipo_cambio_clp` y `total_clp` se almacenan como conceptos
  separados (aprox. líneas 1385–1391 y 1502–1557).
- El cálculo actual usa `comisionData['total_clp']` como primera
  opción; tiene alternativa `round(monto * tipo_cambio_clp)`.
- Si la comisión está incluida en el importe, la implementación
  actual distingue importe bruto y neto (aprox. líneas 2111–2125).
- **Estas reglas no se trasladan automáticamente a las transacciones
  legacy de enero de 2026.**

## Contrato requerido para autorizar el cálculo financiero

Para cada modalidad y sentido, confirmar a partir del código PHP que
efectivamente escribió los registros históricos, o mediante documento
contractual / comprobante real verificable:

1. Unidad exacta y semántica de `remesa.monto`,
   `remesa.total_cambio`, `remesa.tipo_cambio_clp`,
   `pago.monto`, `pago.mon_rec` y `pago.tipo_cambio`.
2. Si `total_clp` existía y se utilizaba en la versión histórica,
   así como la fuente que representaba el efectivo entregado.
3. Base de comisión, condición incluido/separado, deducciones y
   orden de redondeo; no inferir a partir de cocientes.
4. Diferencias de tratamiento entre BOB→CLP, BOB→USD y USD→CLP.
5. Fecha efectiva del pago frente a la fecha de actualización de la
   remesa, normalizadas por zona horaria y período de corte.

## Regla de seguridad del motor

Mientras el contrato no esté demostrado:

- `VALID_CURRENCY_ROUTE_FINANCIAL_PENDING` significa solo que la
  combinación de monedas está permitida.
- `SOURCE_AMOUNTS_MATCH_PILOT` valida la reproducción de la cifra
  numérica almacenada, **no** la conversión o entrega.
- No computar diferencia de liquidación, saldos de caja, tipos de cambio
  implícitos, ni marcar `FINANCIALLY_RECONCILED`.
- No modificar las bases de origen ni usar tablas ajenas al flujo
  `remesa` / `pago` para suplir evidencia faltante.


## Evidencia nueva: archivos históricos PHP Bolivia y Chile

Se inspeccionaron localmente los archivos fuente aportados al proyecto:
`bo_cgr_php-main.zip` y `cgr_chile_2-main.zip`. Son **copias de código**;
no se ha acreditado que coincidan exactamente con lo desplegado en enero de 2026.

**Chile — `controller/remesa.controller.php`, aprox. líneas 261–302.**

- En el pago de remesa, `pago.id_operacion=3`, `pago.id_tipo_pago=1`.
- Si el destino de pago es CLP (ID 2):
  `pago.monto = REQUEST['monto_env_clp']`, y
  `pago.tipo_cambio = REQUEST['tipo_cambio_clp']`.
  El saldo de unidad CLP se descuenta usando el dato **distinto**
  `REQUEST['monto_clp']`; no confundirlo con `pago.monto`.
- Si el destino es USD, `pago.monto = REQUEST['monto_env_usd']`,
  mientras el saldo de la unidad USD descuenta `REQUEST['monto_usd']`.
- Ambas ramas guardan `pago.total = round(pago.monto * pago.tipo_cambio, 0)`.
- `model/pago.php`, líneas 13–32, confirma que **se persiste**
  `pago.total`.
- `view/remesa/pago_clp.php`, líneas 7–18, identifica
  `monto_env_clp` como **MONTO A PAGAR [USD]** y
  `monto_clp` como **CONFIRMAR MONTO [CLP]**.
  Esto sustenta la advertencia: `pago.monto` no es una cantidad CLP
  aunque `pago.mon_rec=2`.

**Bolivia — `registra_remesa.php` aprox. líneas 66–95,
317–337, 852–896.**

- El código separa `monto`, `total_cambio`,
  `tipo_cambio_clp` y `total_clp`.
- En el flujo revisado calcula `total_clp = monto * tipo_cambio_clp`,
  y valida un cálculo basado en `confirma * tipoCambioChileBackend`.
- Hay reglas de normalización de moneda antes del INSERT de `remesa`.
  No asumir que `monto` en todas las modalidades es BOB.

**Siguiente prueba controlada:** leer únicamente por clave primaria
`remesa.total_clp` (Bolivia) y `pago.total` (Chile) para las doce
operaciones ya muestreadas. Contrastar `pago.total` con el redondeo
del producto `pago.monto * pago.tipo_cambio`. Separar el resultado
`FORMULA_DIFF_REVIEW` de la comparación entre ambos totales, que
**todavía no certifica el efectivo entregado ni una conciliación**.

Herramienta: `scripts/pilot_legacy_payment_total_2026.py`.
