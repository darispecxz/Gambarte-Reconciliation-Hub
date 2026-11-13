"""Read-only source column metadata for monetary field contract review.

Does not scan transaction tables, output personal data, or infer business meaning.
"""
import argparse
from app.core.config import get_settings
from app.integrations.source import read_only_transaction, validate_read_query
from scripts.pilot_import import connect_source, PILOT_HOST, PILOT_DB

QUERY="""SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE,COLUMN_TYPE,IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = :schema AND TABLE_NAME IN ('remesa','pago','tmp_reporte_remesa')
AND (COLUMN_NAME IN ('monto','mon_rec','envio','moneda','pago','recibo','cambio',
                     'importe','comision','comisión','tipo_cambio',
                     'id_forma_pago','id_tipo_pago','id_moneda')
     OR COLUMN_NAME LIKE '%monto%' OR COLUMN_NAME LIKE '%moneda%'
     OR COLUMN_NAME LIKE '%cambio%' OR COLUMN_NAME LIKE '%comis%'
     OR COLUMN_NAME LIKE '%envio%' OR COLUMN_NAME LIKE '%pago%')
ORDER BY TABLE_NAME,COLUMN_NAME"""


def run(source):
    if source not in ("BOLIVIA","CHILE"):
        raise ValueError("Choose BOLIVIA or CHILE")
    settings=get_settings()
    if (settings.db_host,settings.db_name)!=(PILOT_HOST,PILOT_DB):
        raise RuntimeError("Pilot environment required")
    if settings.enable_source_etl or settings.source_mapping_verified:
        raise RuntimeError("Automatic source ETL must remain disabled")
    validate_read_query(QUERY)
    schema=getattr(settings,source.lower()+"_db_name")
    engine=connect_source(settings,source)
    try:
        with read_only_transaction(engine) as con:
            result=con.execute(__import__("sqlalchemy").text(QUERY),{"schema":schema}).mappings().all()
    finally:
        engine.dispose()
    print(f"source={source} source_read_only=True metadata_only=True "
          f"transaction_rows_scanned=0 columns={len(result)} meaning_verified=False")
    for r in result:
        print(f"table={r['TABLE_NAME']} column={r['COLUMN_NAME']} "
              f"sql_type={r['COLUMN_TYPE']} nullable={r['IS_NULLABLE']}")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",required=True,choices=("BOLIVIA","CHILE"))
    run(p.parse_args().source)


if __name__=="__main__":
    main()
