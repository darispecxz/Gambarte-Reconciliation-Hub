"""Management-ready 2026 *sample* operational report from isolated pilot only.

No source connections, no API/worker activation, no reconciliation certification.
All report output is aggregate. HTML is stored only on an explicitly mounted
local /export directory; never committed to source control.
"""
import argparse
from collections import Counter
from datetime import date, datetime
from html import escape
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL

from app.core.config import get_settings
from app.infrastructure.models import Payment, Remittance
from scripts.pilot_import import PILOT_DB, PILOT_HOST, check_marker
from scripts.pilot_reconcile import summarize

EXPORT_DIR = Path("/export")
MONTH_NAMES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
SOURCE_NAMES = {
    "BOLIVIA": "Bolivia",
    "CHILE": "Chile",
}
LABELS = {
    "PROVISIONAL_CODE_PAIR": "Par único por código (provisional)",
    "NO_PAYMENT_IN_SAMPLE": "Sin pago en la muestra",
    "PENDING_IN_SAMPLE": "Pendiente de origen",
    "CLOSED_IN_SAMPLE": "Anulada / devuelta",
    "INSUFFICIENT_DATA": "Datos insuficientes",
    "INSUFFICIENT_UNVERIFIED_PAYMENT_MAPPING": "Modalidad no verificada",
    "MANUAL_REVIEW_AMBIGUOUS_CODE": "Código ambiguo / pagos múltiples",
    "MANUAL_REVIEW_UNEXPECTED_PAYMENT_TYPE": "Tipo de pago fuera de contrato",
    "MANUAL_REVIEW_CLOSED_WITH_PAYMENT": "Operación cerrada con pago",
    "MANUAL_REVIEW_STATUS_WITH_PAYMENT": "Estado incompatible con pago",
}


def inside_period(occurred_at, year, through):
    return occurred_at is not None and (
        date(year, 1, 1) <= occurred_at.date() <= through
    )


def build_summary(remittances, payments, year=2026, through=None):
    if through is None:
        through = date.today()
    if year != 2026 or through.year != year:
        raise ValueError("Report limited to calendar year 2026 and cutoff inside year")
    rems = [r for r in remittances if inside_period(r.occurred_at, year, through)]
    pays = [p for p in payments if inside_period(p.occurred_at, year, through)]
    month_rows = []
    for month in range(1, through.month + 1):
        item = {"name": MONTH_NAMES[month - 1], "month": month}
        for source in SOURCE_NAMES:
            item[source + "_remittances"] = sum(
                1 for r in rems if r.source == source and r.occurred_at.month == month)
            item[source + "_payments"] = sum(
                1 for p in pays if p.source == source and p.occurred_at.month == month)
        month_rows.append(item)
    statuses = {
        source: dict(sorted(Counter(r.status for r in rems if r.source == source).items()))
        for source in SOURCE_NAMES
    }
    # Summary deliberately uses only 2026 records: 2025 origin of a 2026
    # payout requires a separate cross-year recovery, not a fabricated match.
    classifications = summarize(rems, pays)
    return {
        "year": year, "through": through.isoformat(), "as_of_label": through.strftime("%d/%m/%Y"),
        "totals": {
            "remittances": len(rems), "payments": len(pays),
            "bolivia_remittances": sum(r.source == "BOLIVIA" for r in rems),
            "chile_remittances": sum(r.source == "CHILE" for r in rems),
            "bolivia_payments": sum(p.source == "BOLIVIA" for p in pays),
            "chile_payments": sum(p.source == "CHILE" for p in pays),
        },
        "statuses": statuses,
        "monthly": month_rows,
        "directions": {
            key: {
                "origins": value["origins"],
                "payments_in_sample": value["payments_in_sample"],
                "categories": dict(sorted(value["categories"].items())),
            }
            for key, value in classifications.items()
        },
        "certified": False, "coverage": "NO VERIFICADA",
        "source": "Muestra aislada; no representa la totalidad de operaciones 2026",
    }


def render_html(summary):
    esc = lambda obj: escape(str(obj), quote=True)
    totals = summary["totals"]
    monthly = "\n".join(
        "<tr><td>" + esc(m["name"]) + "</td>" + "".join(
            "<td class='num'>" + esc(m[key]) + "</td>" for key in
            ("BOLIVIA_remittances", "CHILE_remittances",
             "BOLIVIA_payments", "CHILE_payments")
        ) + "</tr>" for m in summary["monthly"]
    )
    rows = []
    for direction, label in (("BO_TO_CL", "Bolivia → Chile"),
                             ("CL_TO_BO", "Chile → Bolivia")):
        item = summary["directions"][direction]
        for category, count in sorted(item["categories"].items()):
            rows.append(
                "<tr><td>" + esc(label) + "</td><td>" +
                esc(LABELS.get(category, category)) +
                "</td><td class='num'>" + esc(count) + "</td></tr>"
            )
    classifications = "\n".join(rows) or "<tr><td colspan='3'>Sin casos evaluados</td></tr>"
    statuses = "\n".join(
        "<tr><td>" + esc(SOURCE_NAMES[source]) + "</td><td>" + esc(status) +
        "</td><td class='num'>" + esc(count) + "</td></tr>"
        for source, status_counts in summary["statuses"].items()
        for status, count in status_counts.items()
    ) or "<tr><td colspan='3'>Sin estados observados</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conciliación operativa 2026 | Gambarte</title>
<style>
:root {{color-scheme:light;--navy:#102540;--ink:#192d43;--muted:#617186;--line:#dce4ec;--bg:#f3f6fa}}
* {{box-sizing:border-box}} body {{margin:0;background:var(--bg);font:15px/1.55 Arial,sans-serif;color:var(--ink)}}
main {{max-width:1090px;margin:36px auto;padding:0 24px}} header {{background:var(--navy);color:white;padding:36px;border-radius:16px}}
h1 {{margin:8px 0;font-size:31px;line-height:1.2}} h2 {{font-size:21px;margin:0 0 14px}}
.eyebrow {{letter-spacing:.13em;text-transform:uppercase;font-size:12px;opacity:.85}}
.subtitle {{color:#dce5ef}} .warning {{margin:20px 0;padding:18px;border-left:5px solid #b65b16;background:#fff4e6;color:#653e14}}
.cards {{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}}
.card,.panel {{background:white;border:1px solid var(--line);border-radius:13px;padding:22px}}
.number {{font-weight:700;font-size:32px;line-height:1.25}} .label {{font-size:12px;color:var(--muted)}}
.panel {{margin:18px 0}} table {{width:100%;border-collapse:collapse;font-size:14px}}
th {{text-align:left;background:#f4f7fb}} td,th {{border-bottom:1px solid var(--line);padding:10px 12px}}
.num {{text-align:right;font-variant-numeric:tabular-nums}}
.footer {{font-size:13px;color:var(--muted);padding:12px 0 25px}}
@media(max-width:750px){{.cards{{grid-template-columns:repeat(2,1fr)}} main{{padding:0 12px}}}}
@media print{{body{{background:white}} main{{margin:0;max-width:none}} header{{border-radius:0}}
.panel,.card{{break-inside:avoid}} .warning{{break-inside:avoid}}}}
</style></head>
<body><main>
<header><div class="eyebrow">Gambarte Bolivia · Control interno</div>
<h1>Conciliación operativa Bolivia–Chile · 2026</h1>
<div class="subtitle">Fecha de corte: {esc(summary["as_of_label"])} · Alcance: del 01/01/2026 al corte indicado</div>
</header>
<div class="warning"><strong>INFORME PRELIMINAR — NO CERTIFICADO.</strong>
Los valores reflejan exclusivamente registros presentes en una base piloto aislada.
No se ha demostrado cobertura completa de Bolivia ni Chile durante 2026.
Los pares por código no prueban la conciliación de importes, saldos ni liquidaciones.
No utilizar para cierre contable, certificación regulatoria o afirmación de ausencia de pagos.</div>
<div class="cards">
<div class="card"><div class="label">Remesas incluidas (muestra 2026)</div><div class="number">{totals["remittances"]}</div></div>
<div class="card"><div class="label">Pagos incluidos (muestra 2026)</div><div class="number">{totals["payments"]}</div></div>
<div class="card"><div class="label">Pares provisionales por código</div><div class="number">{sum(x["categories"].get("PROVISIONAL_CODE_PAIR",0) for x in summary["directions"].values())}</div></div>
<div class="card"><div class="label">Cobertura 2026</div><div class="number" style="font-size:19px">NO VERIFICADA</div></div>
</div>
<section class="panel"><h2>Resumen mensual de registros disponibles</h2>
<table><thead><tr><th>Mes</th><th class="num">BO remesas</th><th class="num">CL remesas</th><th class="num">BO pagos</th><th class="num">CL pagos</th></tr></thead>
<tbody>{monthly}</tbody></table>
<p class="footer">La fecha corresponde a creación en origen. No se ha normalizado la zona horaria entre ambos países.</p></section>
<section class="panel"><h2>Clasificación operativa de la muestra</h2>
<table><thead><tr><th>Dirección</th><th>Clasificación</th><th class="num">Operaciones</th></tr></thead>
<tbody>{classifications}</tbody></table>
<p class="footer">«Sin pago en la muestra» no equivale a pago faltante. «Par único» significa coincidencia preliminar por código y tipo permitido.</p></section>
<section class="panel"><h2>Estados de remesas observados</h2>
<table><thead><tr><th>País</th><th>Estado normalizado</th><th class="num">Registros</th></tr></thead><tbody>{statuses}</tbody></table></section>
<section class="panel"><h2>Alcance, limitaciones y decisiones requeridas</h2>
<ol><li>Validar el contrato de operaciones y modalidades entre Bolivia y Chile, especialmente los tipos de pago en Chile.</li>
<li>Completar una extracción histórica trazable de enero al corte de 2026, incluyendo correcciones tardías y movimientos asociados de años anteriores.</li>
<li>Verificar integridad, fechas y cobertura por conjunto de datos antes de calcular tasas de conciliación.</li>
<li>Definir plazos de pago y reglas de reversa antes de declarar «pagos faltantes».</li>
<li>Separar conciliación de presencia operativa de conciliación monetaria y contable.</li></ol>
</section>
<div class="footer">Generado mediante lectura transaccional READ ONLY del piloto. No se ejecutaron escrituras en las bases Bolivia, Chile ni la central habitual.</div>
</main></body></html>"""


def run(year=2026, through=None, output=None):
    today = date.today()
    through = through or today
    if year != 2026 or through.year != year or through > today:
        raise ValueError("Use a completed or current 2026 cutoff, not a future date")
    settings = get_settings()
    if ((settings.db_host, settings.db_name) != (PILOT_HOST, PILOT_DB)
            or settings.enable_source_etl or settings.source_mapping_verified):
        raise RuntimeError("Report requires isolated pilot and disabled workers")
    if output is not None:
        destination = Path(output)
        if not destination.is_absolute() or destination.parent.resolve() != EXPORT_DIR:
            raise ValueError("Output must be a file directly under /export")
        if not EXPORT_DIR.is_dir():
            raise RuntimeError("Mount a private local export directory at /export")
        if destination.suffix.lower() != ".html":
            raise ValueError("HTML output only")

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
                remittances = connection.execute(select(
                    Remittance.source, Remittance.code, Remittance.operation_type,
                    Remittance.status, Remittance.amount, Remittance.currency,
                    Remittance.occurred_at,
                )).all()
                payments = connection.execute(select(
                    Payment.source, Payment.code, Payment.operation_type,
                    Payment.amount, Payment.currency, Payment.occurred_at,
                )).all()
                summary = build_summary(remittances, payments, year, through)
            finally:
                connection.rollback()
    finally:
        engine.dispose()

    print(f"year={year} through={summary['through']} coverage=NOT_CERTIFIED")
    print(f"sample_remittances={summary['totals']['remittances']} "
          f"sample_payments={summary['totals']['payments']}")
    for direction, item in summary["directions"].items():
        print(f"{direction}_provisional_pairs="
              f"{item['categories'].get('PROVISIONAL_CODE_PAIR', 0)}")
    if output is not None:
        destination.write_text(render_html(summary), encoding="utf-8")
        print("html_created=True local_private_export=True")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026, choices=(2026,))
    parser.add_argument("--through", type=date.fromisoformat,
                        help="Inclusive report cutoff YYYY-MM-DD; default today")
    parser.add_argument("--output", default=None,
                        help="Optional private HTML path directly under /export")
    args = parser.parse_args()
    run(args.year, args.through, args.output)


if __name__ == "__main__":
    main()
