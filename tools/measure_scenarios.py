"""
Scenario measurement
====================
Three tables. The delivery figures the registry holds against the ones the terms document
prints, read out of the document itself. Every delivery date the code can produce, worked
out a second time from those same figures. And the five requests in
tests/data/scenario_eval.json, whose answers were derived from the catalogue with SQL
before the builder was trusted with them — which product each strategy has to pick, what
it costs, when it lands, and what could go wrong with it.

Reads data/docs and data/catalog.db. No service, no model, no cost.

Run from the repository root:  python -m tools.measure_scenarios
"""

import json
import logging
import re
import sys
from pathlib import Path

from services.data_service import delivery, repository
from services.data_service.categories import Warehouse
from services.data_service.database import SessionLocal
from services.data_service.delivery import Store, Zone
from services.data_service.models import Product
from services.offer_service import scenario_builder as builder
from services.offer_service.rag import policies
from services.offer_service.requirements import CustomerRequirements

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "scenario_eval.json"
ZONES = (Zone.ATTICA, Zone.THESSALONIKI, Zone.MAINLAND, Zone.ISLANDS)
COLUMNS = {"Αττική": Zone.ATTICA, "Θεσσαλονίκη": Zone.THESSALONIKI,
           "Υπόλοιπη ηπειρωτική Ελλάδα": Zone.MAINLAND, "Νησιά": Zone.ISLANDS}


def as_printed() -> dict:
    """Every delivery figure, parsed out of the terms document rather than the code."""
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

    return {
        "transit": transit,
        "shipping": carriage,
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
            checks.append((f"transit {warehouse.value} → {zone.value}", days,
                           delivery.TRANSIT[warehouse][zone]))
    for zone, cost in printed["shipping"].items():
        checks.append((f"carriage {zone.value}", cost, delivery.SHIPPING[zone]))
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

        for warehouse in printed["transit"]:
            if zone == delivery.SAME_DAY_ZONE and warehouse in delivery.SAME_DAY_FROM:
                wanted = 0
            elif warehouse in served:
                wanted = direct
            else:
                wanted = moved + direct
            checks.append((f"{zone.value} from {warehouse.value}", wanted,
                           delivery.working_days(zone, warehouse)))

        for code, lead in printed["lead"].items():
            checks.append((f"{zone.value} ordered from {code}",
                           lead + printed["receiving"] + direct,
                           delivery.working_days(zone, None, lead_time=lead)))

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


def offers() -> int:
    """Build each request and compare every field with the answer derived beforehand."""
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]

    with SessionLocal() as db:
        suppliers = {
            str(row.code): {"code": str(row.code), "lead_time_days": int(row.lead_time_days),
                            "reliability_score": float(row.reliability_score)}
            for row in repository.get_suppliers(db)
        }
        rows = {row.sku: row.model_dump()
                for row in repository.summarize(db, db.query(Product).all())}

    logger.info("")
    logger.info("the scenario eval — %d requests, %d scenarios derived by hand",
                len(cases), sum(len(case["scenarios"]) for case in cases))
    logger.info("%-28s %-8s %s", "request", "built", "differences")

    wrong = 0
    for case in cases:
        asked = CustomerRequirements(request=case["request"], **case["requirements"])
        candidates = [rows[sku] for sku in case["candidates"]]
        built = builder.build(asked, candidates, suppliers, Store(case["store"]))
        differs = _differences(case, built)
        wrong += len(differs)

        logger.info("%-28s %-8s %s", case["id"], f"{len(built)}/{len(case['scenarios'])}",
                    "—" if not differs else f"{len(differs)}")
        for said in differs:
            logger.info("      ✘ %s", said)

    logger.info("   %d differences from what was derived", wrong)
    return wrong


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
            "shipping": made.shipping,
            "total": made.total,
            "transfer_cost": made.transfer_cost,
        }
        for field, expected in ((key, wanted[key]) for key in held):
            if held[field] != expected:
                said.append(f"{wanted['sku']} {field}: {held[field]} not {expected}")

    return said


def run() -> None:
    printed = as_printed()
    wrong = table("the registry against the terms document", registry(printed))
    wrong += table("every delivery date, worked out twice", dates(printed))
    wrong += offers()

    logger.info("")
    logger.info("%s", "nothing disagrees" if not wrong else f"{wrong} disagreements")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    run()
