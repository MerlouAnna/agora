"""
Scenario measurement
====================
Four tables. The delivery figures the registry holds against the ones the terms document
prints, read out of the document itself. Every delivery date the code can produce, worked
out a second time from those same figures. The six requests in
tests/data/scenario_eval.json, whose answers were derived from the catalogue with SQL
before the builder was trusted with them — which product each strategy has to pick, what
it costs, when it lands, and what could go wrong with it. And the validator over every
scenario those requests build, which has to stay silent.

Reads data/docs and data/catalog.db. No service, no model, no cost.

Run from the repository root:  python -m tools.measure_scenarios
"""

import json
import logging
import re
import sys
from pathlib import Path

from services.data_service import delivery, discounts, repository
from services.data_service.categories import Category, Warehouse
from services.data_service.database import SessionLocal
from services.data_service.delivery import Store, Zone
from services.data_service.models import Product
from services.offer_service import scenario_builder as builder
from services.offer_service import validation
from services.offer_service.rag import policies
from services.offer_service.requirements import CustomerRequirements

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "scenario_eval.json"
ZONES = (Zone.ATTICA, Zone.THESSALONIKI, Zone.MAINLAND, Zone.ISLANDS)
COLUMNS = {
    "Αττική": Zone.ATTICA,
    "Θεσσαλονίκη": Zone.THESSALONIKI,
    "Υπόλοιπη ηπειρωτική Ελλάδα": Zone.MAINLAND,
    "Νησιά": Zone.ISLANDS,
}


def as_printed() -> dict:
    """Every figure of both documents, parsed out of them rather than out of the code."""
    held = {passage.id: passage.text for passage in policies.read_all()}

    transit = {}
    for line in held["oroi-paradosis#1"].splitlines():
        if "|" not in line or not re.match(r"^(ATH|THE|PAT)-\d\d", line.strip()):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        transit[Warehouse(cells[0].split()[0])] = dict(
            zip(ZONES, [int(cell) for cell in cells[1:]], strict=True)
        )

    carriage = {}
    for line in held["oroi-paradosis#4"].splitlines():
        found = re.match(r"^(.+?)\s*\|\s*(\d+)\s*€", line.strip())
        if found and found.group(1) in COLUMNS:
            carriage[COLUMNS[found.group(1)]] = float(found.group(2))

    tiers = []
    for line in held["politiki-ekptoseon#1"].splitlines():
        found = re.match(r"^(Έως|[\d.]+)[^|]*\|\s*(\d+)%$", line.strip())
        if found is None:
            continue
        floor = 0.0 if found.group(1) == "Έως" else float(found.group(1).replace(".", ""))
        tiers.append((floor, int(found.group(2)) / 100))

    return {
        "transit": transit,
        "shipping": carriage,
        "tiers": tiers,
        "caps": {
            Category(found.group(1)): int(found.group(2)) / 100
            for found in re.finditer(
                r"^([A-Z]+)\s*\|\s*(\d+)%$", held["politiki-ekptoseon#2"], re.MULTILINE
            )
        },
        "self_approved": int(_says(r"Έκπτωση έως (\d+)% εγκρίνεται", held["politiki-ekptoseon#4"]))
        / 100,
        "free_from": float(_says(r"(\d+) € και άνω", held["oroi-paradosis#4"])),
        "lead": {
            found.group(1): int(found.group(2))
            for found in re.finditer(
                r"(SUP-\d\d)\s*·[^|]+\|\s*(\d+)\s*ημέρες", held["oroi-paradosis#5"]
            )
        },
        "receiving": int(_says(r"συν (\d+) εργάσιμη ημέρα για παραλαβή", held["oroi-paradosis#5"])),
        "transfer": int(_says(r"προσθέτει (\d+) εργάσιμη ημέρα", held["oroi-paradosis#3"])),
        "to_island": int(_says(r"Προσθέτει (\d+) εργάσιμες ημέρες", held["oroi-paradosis#3"])),
        "move_cost": float(_says(r"(\d+) € ανά παραγγελία", held["oroi-paradosis#3"])),
        "reliability": float(
            _says(r"κάτω από (0,\d+)", held["oroi-paradosis#6"]).replace(",", ".")
        ),
        "cut_off": _says(r"cut-o\S* είναι (\d\d:\d\d)", held["oroi-paradosis#2"]),
    }


def _says(pattern: str, text: str) -> str:
    found = re.search(pattern, text, re.IGNORECASE)
    if found is None:
        sys.exit(f"the delivery terms no longer say {pattern!r} — this tool cannot read them")

    return found.group(1)


def registry(printed: dict) -> list[tuple]:
    """The document's own figures against the ones the registry holds."""
    checks = [
        ("transfer, mainland", printed["transfer"], delivery.TRANSFER_DAYS),
        ("transfer, to an island", printed["to_island"], delivery.TRANSFER_DAYS_TO_ISLAND),
        ("transfer cost", printed["move_cost"], delivery.TRANSFER_COST),
        ("receiving day", printed["receiving"], delivery.RECEIVING_DAYS),
        ("free carriage from", printed["free_from"], delivery.SHIPPING_FREE_FROM),
        ("urgent reliability", printed["reliability"], delivery.URGENT_RELIABILITY),
        ("cut-off", printed["cut_off"], delivery.CUT_OFF.strftime("%H:%M")),
    ]
    for warehouse, row in printed["transit"].items():
        for zone, days in row.items():
            checks.append(
                (
                    f"transit {warehouse.value} → {zone.value}",
                    days,
                    delivery.TRANSIT[warehouse][zone],
                )
            )
    for zone, cost in printed["shipping"].items():
        checks.append((f"carriage {zone.value}", cost, delivery.SHIPPING[zone]))
    for at, (printed_tier, held_tier) in enumerate(
        zip(printed["tiers"], discounts.VOLUME_TIERS, strict=True)
    ):
        checks.append((f"volume band {at}", printed_tier, held_tier))
    for category, ceiling in discounts.CATEGORY_CAPS.items():
        checks.append((f"{category.value} ceiling", printed["caps"].get(category), ceiling))
    checks.append(
        ("the salesperson's own limit", printed["self_approved"], discounts.SELF_APPROVED)
    )
    for code, days in printed["lead"].items():
        checks.append((f"{code} lead time", days, _lead(code)))

    return checks


def _lead(code: str) -> int | None:
    with SessionLocal() as db:
        for row in repository.get_suppliers(db):
            if str(row.code) == code:
                return int(row.lead_time_days)

    return None


def dates(printed: dict) -> list[tuple]:
    """Every delivery date the code can produce, worked out again from the document.

    Which warehouses serve which zone is ours and not the document's, so the expected
    figures take that as given: the arithmetic on top of it is what is being measured.
    """
    checks = []
    for zone in ZONES:
        served = delivery.SERVES[zone]
        direct = printed["transit"][served[0]][zone]
        moved = printed["to_island"] if zone == Zone.ISLANDS else printed["transfer"]

        for warehouse, row in printed["transit"].items():
            if zone == delivery.SAME_DAY_ZONE and warehouse in delivery.SAME_DAY_FROM:
                wanted = 0
            elif warehouse in served:
                wanted = row[zone]
            else:
                wanted = moved + row[zone]
            checks.append(
                (
                    f"{zone.value} from {warehouse.value}",
                    wanted,
                    delivery.working_days(zone, warehouse),
                )
            )

        for code, lead in printed["lead"].items():
            checks.append(
                (
                    f"{zone.value} ordered from {code}",
                    lead + printed["receiving"] + direct,
                    delivery.working_days(zone, None, lead_time=lead),
                )
            )

    return checks


def table(title: str, checks: list[tuple]) -> int:
    logger.info("")
    logger.info("%s — %d cases", title, len(checks))
    wrong = 0
    for name, printed, held in checks:
        if printed != held:
            wrong += 1
            logger.info("   ✘ %-36s the document says %s, the code says %s", name, printed, held)

    logger.info("   %d of %d agree", len(checks) - wrong, len(checks))
    return wrong


def catalogue() -> tuple[dict, dict]:
    """The products and the suppliers as the database holds them, read once for both tables."""
    with SessionLocal() as db:
        suppliers = {
            str(row.code): {
                "code": str(row.code),
                "lead_time_days": int(row.lead_time_days),
                "reliability_score": float(row.reliability_score),
            }
            for row in repository.get_suppliers(db)
        }
        rows = {
            row.sku: row.model_dump() for row in repository.summarize(db, db.query(Product).all())
        }

    return rows, suppliers


def offers(cases: list[dict], rows: dict, suppliers: dict) -> int:
    """Build each request and compare every field with the answer derived beforehand."""
    logger.info("")
    logger.info(
        "the scenario eval — %d requests, %d scenarios derived by hand",
        len(cases),
        sum(len(case["scenarios"]) for case in cases),
    )
    logger.info("%-28s %-8s %s", "request", "built", "differences")

    wrong = 0
    for case in cases:
        asked = CustomerRequirements(request=case["request"], **case["requirements"])
        candidates = [rows[sku] for sku in case["candidates"]]
        built = builder.build(asked, candidates, suppliers, Store(case["store"]))
        differs = _differences(case, built)
        wrong += len(differs)

        logger.info(
            "%-28s %-8s %s",
            case["id"],
            f"{len(built)}/{len(case['scenarios'])}",
            "—" if not differs else f"{len(differs)}",
        )
        for said in differs:
            logger.info("      ✘ %s", said)

    logger.info("   %d differences from what was derived", wrong)
    return wrong


def checked(cases: list[dict], rows: dict, suppliers: dict) -> int:
    """The validator over every scenario the builder built, which has to stay silent.

    A clean offer must raise nothing at all, and the one warning the eval can predict is
    the approval its own `needs_approval` records. Anything else is a validator crying
    wolf at real data, which no unit test over a hand-built product would show.
    """
    logger.info("")
    logger.info("the validator over what was built")

    said = []
    checks = warnings = 0
    for case in cases:
        asked = CustomerRequirements(request=case["request"], **case["requirements"])
        store = Store(case["store"])
        built = builder.build(asked, [rows[sku] for sku in case["candidates"]], suppliers, store)
        report = validation.validate(
            built,
            asked,
            store,
            catalogue=lambda skus: [rows[sku] for sku in skus if sku in rows],
            registry=lambda: list(suppliers.values()),
        )
        wanted = {one["sku"] for one in case["scenarios"] if one["needs_approval"]}

        for verdict in report.verdicts:
            sku = verdict.scenario.lines[0].sku
            checks += len(verdict.checks)
            warnings += len(verdict.failed)
            for check in verdict.failed:
                if check.severity == validation.Severity.FATAL:
                    said.append(f"{case['id']} · {sku} · {check.name} — {check.said}")
                elif "salesperson" not in check.name:
                    said.append(f"{case['id']} · {sku} · unexpected warning: {check.name}")
            asks = any("salesperson" in check.name for check in verdict.failed)
            if asks != (sku in wanted):
                said.append(
                    f"{case['id']} · {sku} · approval {asks} where the eval says {not asks}"
                )

    for one in said:
        logger.info("   ✘ %s", one)
    logger.info(
        "   %d checks over %d scenarios, %d raised, %d unaccounted for",
        checks,
        sum(len(case["scenarios"]) for case in cases),
        warnings,
        len(said),
    )
    return len(said)


def _differences(case: dict, built: list) -> list[str]:
    """Field by field, in the order the strategies were meant to produce them."""
    said = []
    if len(built) != len(case["scenarios"]):
        said.append(f"{len(built)} scenarios, not {len(case['scenarios'])}")

    for wanted, made in zip(case["scenarios"], built, strict=False):
        if made.lines[0].sku != wanted["sku"]:
            said.append(f"{made.lines[0].sku} where {wanted['sku']} was derived")
            continue

        held = {
            "strategies": [strategy.value for strategy in made.strategies],
            "allocation": [
                [source.warehouse.value if source.warehouse else None, source.quantity]
                for source in made.lines[0].sources
            ],
            "availability": made.availability.value,
            "days": made.days,
            "risk": made.risk.value,
            "fit": made.fit,
            "net": made.net,
            "discount_rate": made.discount_rate,
            "discount": made.discount,
            "needs_approval": made.needs_approval,
            "shipping": made.shipping,
            "total": made.total,
            "transfer_cost": made.transfer_cost,
        }
        for field in held:
            if held[field] != wanted[field]:
                said.append(f"{wanted['sku']} {field}: {held[field]} not {wanted[field]}")

    return said


def run() -> None:
    printed = as_printed()
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    rows, suppliers = catalogue()

    wrong = table("the registry against the two documents", registry(printed))
    wrong += table("every delivery date, worked out twice", dates(printed))
    wrong += offers(cases, rows, suppliers)
    wrong += checked(cases, rows, suppliers)

    logger.info("")
    logger.info("%s", "nothing disagrees" if not wrong else f"{wrong} disagreements")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    run()
