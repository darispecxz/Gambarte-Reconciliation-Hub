"""Aggregate, read-only integrity audit of the isolated pilot."""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.core.config import get_settings
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker


QUERIES = {
    "source_records": "SELECT COUNT(*) FROM source_records",
    "source_versions": "SELECT COUNT(*) FROM source_versions",
    "remittance_versions": "SELECT COUNT(*) FROM source_versions v JOIN source_records s ON s.id = v.record_id WHERE s.dataset = 'remittance'",
    "remittances": "SELECT COUNT(*) FROM remittances",
    "payments": "SELECT COUNT(*) FROM payments",
    "source_links": "SELECT COUNT(*) FROM source_links",
    "remittance_events": "SELECT COUNT(*) FROM remittance_events",
    "sync_cursors": "SELECT COUNT(*) FROM sync_cursors",
    "sync_runs": "SELECT COUNT(*) FROM sync_runs",
    "wrong_dataset": "SELECT COUNT(*) FROM source_records WHERE source NOT IN ('BOLIVIA', 'CHILE') OR dataset NOT IN ('remittance', 'payment')",
    "chile_remittance_identity_mismatch": "SELECT COUNT(*) FROM source_records WHERE source = 'CHILE' AND dataset = 'remittance' AND NOT (source_id <=> CONCAT(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.operation_type')), ':', JSON_UNQUOTE(JSON_EXTRACT(payload, '$.code')), ':', JSON_UNQUOTE(JSON_EXTRACT(payload, '$.cursor_destination'))))",
    "duplicate_identity": "SELECT COUNT(*) FROM (SELECT source, dataset, source_id FROM source_records GROUP BY source, dataset, source_id HAVING COUNT(*) > 1) x",
    "missing_remittance_projection": "SELECT COUNT(*) FROM source_records s LEFT JOIN remittances r ON r.source_record_id = s.id WHERE s.dataset = 'remittance' AND r.id IS NULL",
    "missing_payment_projection": "SELECT COUNT(*) FROM source_records s LEFT JOIN payments p ON p.source_record_id = s.id WHERE s.dataset = 'payment' AND p.id IS NULL",
    "duplicate_remittance_projection": "SELECT COUNT(*) FROM (SELECT source_record_id FROM remittances GROUP BY source_record_id HAVING COUNT(*) > 1) x",
    "duplicate_payment_projection": "SELECT COUNT(*) FROM (SELECT source_record_id FROM payments GROUP BY source_record_id HAVING COUNT(*) > 1) x",
    "projection_mismatch": "SELECT COUNT(*) FROM remittances r JOIN source_records s ON s.id = r.source_record_id WHERE r.source <> s.source OR r.code <> s.code OR r.status <> s.status OR NOT (r.amount <=> s.amount) OR NOT (r.currency <=> s.currency)",
    "payment_projection_mismatch": "SELECT COUNT(*) FROM payments p JOIN source_records s ON s.id = p.source_record_id WHERE p.source <> s.source OR p.code <> s.code OR NOT (p.amount <=> s.amount) OR NOT (p.currency <=> s.currency)",
    "missing_remittance_link": "SELECT COUNT(*) FROM remittances r LEFT JOIN source_links l ON l.source_record_id = r.source_record_id AND l.entity_type = 'REMITTANCE' AND l.entity_id = r.id WHERE l.id IS NULL",
    "missing_payment_link": "SELECT COUNT(*) FROM payments p LEFT JOIN source_links l ON l.source_record_id = p.source_record_id AND l.entity_type = 'PAYMENT' AND l.entity_id = p.id WHERE l.id IS NULL",
    "orphan_link": "SELECT COUNT(*) FROM source_links l LEFT JOIN remittances r ON l.entity_type = 'REMITTANCE' AND r.id = l.entity_id AND r.source_record_id = l.source_record_id LEFT JOIN payments p ON l.entity_type = 'PAYMENT' AND p.id = l.entity_id AND p.source_record_id = l.source_record_id WHERE r.id IS NULL AND p.id IS NULL",
    "orphan_version": "SELECT COUNT(*) FROM source_versions v LEFT JOIN source_records s ON s.id = v.record_id WHERE s.id IS NULL",
    "missing_version": "SELECT COUNT(*) FROM source_records s LEFT JOIN source_versions v ON v.record_id = s.id WHERE v.id IS NULL",
    "orphan_event": "SELECT COUNT(*) FROM remittance_events e LEFT JOIN source_versions v ON v.id = e.source_version_id LEFT JOIN remittances r ON r.id = e.remittance_id WHERE v.id IS NULL OR r.id IS NULL OR v.record_id <> r.source_record_id",
    "missing_event": "SELECT COUNT(*) FROM source_versions v JOIN source_records s ON s.id = v.record_id LEFT JOIN remittance_events e ON e.source_version_id = v.id WHERE s.dataset = 'remittance' AND e.id IS NULL",
    "version_hash_mismatch": "SELECT COUNT(*) FROM source_records s WHERE s.payload_hash <> (SELECT v.payload_hash FROM source_versions v WHERE v.record_id = s.id ORDER BY v.id DESC LIMIT 1)",
}


def run():
    settings = get_settings()
    if (settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB):
        raise RuntimeError("Audit refuses non-pilot target")
    engine = create_engine(URL.create(
        "mysql+pymysql", host=settings.db_host, port=settings.db_port,
        username=settings.db_user, password=settings.db_password,
        database=settings.db_name, query={"charset": "utf8mb4"},
    ), connect_args={"connect_timeout": 10, "read_timeout": 30})
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql("START TRANSACTION READ ONLY")
                check_marker(connection)
                results = {name: connection.execute(text(sql)).scalar_one()
                           for name, sql in QUERIES.items()}
            finally:
                connection.rollback()
    finally:
        engine.dispose()
    for name, count in results.items():
        print(f"{name}={count}")
    failures = {name: count for name, count in results.items()
                if name not in {"source_records", "source_versions",
                                "remittance_versions", "remittances", "payments",
                                "source_links", "remittance_events"} and count}
    if failures:
        raise RuntimeError("Pilot integrity audit failed")
    if not (results["source_records"] == results["remittances"]
            + results["payments"] == results["source_links"]
            and results["remittance_versions"] == results["remittance_events"]
            and results["source_versions"] >= results["source_records"]):
        raise RuntimeError("Pilot record, projection, version or event counts disagree")
    print("pilot_integrity=True read_only=True")
    return results


if __name__ == "__main__":
    run()
