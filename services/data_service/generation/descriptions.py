"""
E-shop descriptions from the model
==================================
The code decides what a product is; the model only writes the text a customer reads. Every
line it sends back is checked against the specifications that were asked for, and whatever
fails goes back with the reason attached — three rounds at most, after which the product is
dropped rather than described by a machine. Two hundred products phrased from the same
handful of templates read as near-identical to an embedding model, and a catalogue whose
own index cannot tell its rows apart is not worth generating.

Nothing here writes to the catalogue, and the call to the model is a parameter, so the
repair loop can be exercised without one.
"""

import json
import logging
import time
from collections.abc import Callable

from pydantic import BaseModel

from services import config, usage
from services.config import settings
from services.data_service.generation import validator
from services.data_service.ingestion.parsers import normalize_sku

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
SERVICE = "data_service"
PURPOSE = "product-descriptions"

SYSTEM = """# ROLE

You write the product copy for the online shop of a Greek wholesaler of electrical and
network supplies. Your reader is a professional buyer — an electrician, a network
technician, a procurement officer — not a consumer.

# OUTPUT LANGUAGE

Write in Greek. Only these instructions are in English.

# INPUT

A JSON list of products. Each one has:

- `sku` — the code
- `brand` — the manufacturer
- `erp` — the ERP line: terse, with every technical characteristic written **exactly** the
  way our systems read it
- `specs` — the same characteristics as separate key/value pairs
- `fix` — present **only** when your previous answer for this product was refused; it says
  why

# TASK

Write one shop description per product. Return the `sku` exactly as you received it. When
`fix` is present, correct what it names.

# RULES

## Accuracy — these are not negotiable

A parser reads your text and looks for the characteristics again. If it cannot find them,
the description is thrown away.

1. Every value in `specs` appears in your text written **exactly** the way it appears in
   `erp`.
2. The unit stays glued to the number: «μήκους 20m», never «μήκους 20 μέτρων».
3. Do not add a characteristic that is not in `erp`.
4. Do not change any number.

## Form

5. One or two sentences, 120 to 200 characters.
6. Name the brand.
7. Close with where the product fits: the use, the space, the kind of installation.
8. No price, no bullets, no superlatives («κορυφαίο», «απόλυτη ποιότητα»).

## Variety — the hard part

These texts go into a vector index. Two descriptions that read as variations of the same
sentence make it useless.

9. Make the subject of the sentence whatever sets **this** product apart. Two cables that
   differ only in wattage are written around the wattage; two that differ in IP rating,
   around where they can be installed.
10. Rotate the angle: how it is sold (a roll, a cut length), what job it does (a permanent
    supply, a temporary line, an extension), who installs it, which number is the critical
    one here and why, where you would **not** use it.
11. Do not reuse the same word for a space or a condition within the batch — σκόνη, βροχή,
    υγρασία, βεράντα, αυλή, εργοτάξιο, γραφείο, rack. The same goes for the verbs: do not
    write «αντέχει έως X και ταιριάζει σε Y» every time.
12. Do not copy the ending of the ERP line. «εξωτερικού χώρου» does not become «ιδανικό
    για εξωτερικές εγκαταστάσεις» — say something specific.
13. Sometimes one sentence, sometimes two. Sometimes open with the use and close with the
    characteristics, sometimes the other way round.

# EXAMPLES

| erp | brand | description |
|---|---|---|
| Καλώδιο ρεύματος 3x2.5mm 20m 1500W IP44 εξωτερικού χώρου | Elektra | Καλώδιο ρεύματος Elektra 3x2.5mm σε μήκος 20m, με στεγανότητα IP44 και αντοχή έως 1500W, για παροχές σε εξωτερικούς χώρους και προσωρινές εγκαταστάσεις. |
| Καλώδιο δικτύου CAT6a S/FTP 10m | Nordion | Το CAT6a S/FTP της Nordion είναι πλήρως θωρακισμένο και σε μήκος 10m καλύπτει οριζόντια καλωδίωση ορόφου, εκεί όπου οι παρεμβολές από ισχυρά ρεύματα είναι δεδομένες. |
| Τροφοδοτικό 750W 80+ Gold ATX | Kyma | Τροφοδοτικό ATX 750W της Kyma με πιστοποίηση 80+ Gold, για σταθμούς εργασίας που δουλεύουν συνεχόμενα και χρειάζονται χαμηλή κατανάλωση στο ρελαντί. |
| UPS line-interactive 1500VA / 900W αυτονομία 20 λεπτά | Voltera | Μονάδα αδιάλειπτης παροχής Voltera τοπολογίας line-interactive, 1500VA / 900W με αυτονομία 20 λεπτά, ιδανική για σταθμούς εργασίας, δικτυακό εξοπλισμό και ταμειακά. |
| Switch 24 θυρών 1000Mbps PoE managed | Delta Line | Switch Delta Line 24 θυρών 1000Mbps, managed και με PoE σε κάθε θύρα, για εγκαταστάσεις όπου κάμερες και access points τροφοδοτούνται από το ίδιο το δίκτυο. |
| Ρευματολήπτης CEE 32A IP67 | Kyma | Βιομηχανικός ρευματολήπτης CEE 32A της Kyma με προστασία IP67, κατάλληλος για εργοτάξια και υπαίθριες παροχές όπου η σκόνη και το νερό είναι μόνιμο ζήτημα. |

The last two show rule 9 at work: the same category, an entirely different sentence.

# BEFORE YOU ANSWER

Read your own list back. If two texts could be swapped without anyone noticing, rewrite
one of them from a different angle."""


class ModelUnavailable(RuntimeError):
    """The description model could not be reached."""


class Description(BaseModel):
    sku: str
    text: str


class DescriptionBatch(BaseModel):
    descriptions: list[Description]


class Outcome(BaseModel):
    """What came back from the model once the checks had run."""

    texts: dict[str, str]
    rounds_used: int
    rejected: list[str]


def write(
    items: list[dict],
    ask: Callable[[list[dict]], dict[str, str]] | None = None,
    rounds: int = MAX_ROUNDS,
) -> Outcome:
    """Have the model write each product's shop text, and keep only what survives the check.

    Args:
        items: One entry per product — sku, category, brand, the specs the code chose and
            the ERP line those specs are written into.
        ask: What actually talks to the model. Replaced in tests.
        rounds: How many times a description may be sent back before it is given up on.

    Returns:
        The descriptions that passed, how many rounds it took, and the SKUs that never
        produced a usable one.
    """
    ask = ask or _ask_model

    pending = {item["sku"]: item for item in items}
    accepted: dict[str, str] = {}
    problems: dict[str, str] = {}
    used = 0

    while pending and used < rounds:
        used += 1
        answers = ask(
            [_request(item, problems.get(sku)) for sku, item in pending.items()]
        )
        problems = {}

        for sku, item in list(pending.items()):
            problem = validator.check(item["category"], item["specs"], answers.get(sku))
            if problem is None:
                accepted[sku] = answers[sku].strip()
                del pending[sku]
            else:
                problems[sku] = problem

        if problems:
            logger.info("round %d — %d descriptions sent back", used, len(problems))

    return Outcome(texts=accepted, rounds_used=used, rejected=sorted(pending))


def _request(item: dict, problem: str | None) -> dict:
    request = {
        "sku": item["sku"],
        "brand": item["brand"],
        "specs": {key: str(value) for key, value in item["specs"].items()},
        "erp": item["erp"],
    }

    if problem is not None:
        request["fix"] = problem

    return request


def _ask_model(requests: list[dict]) -> dict[str, str]:
    """One call for the whole batch, with the answers keyed by a SKU we recognise."""
    talk = config.openai_client(ModelUnavailable)

    started = time.monotonic()
    try:
        completion = talk.chat.completions.parse(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(requests, ensure_ascii=False)},
            ],
            response_format=DescriptionBatch,
        )
    except Exception as exc:
        usage.record(
            SERVICE,
            PURPOSE,
            settings.llm_model,
            duration_ms=_elapsed(started),
            ok=False,
            detail=str(exc)[:300],
        )
        raise ModelUnavailable(f"{settings.llm_model} did not answer: {exc}") from exc

    spent = completion.usage
    usage.record(
        SERVICE,
        PURPOSE,
        completion.model,
        prompt_tokens=spent.prompt_tokens if spent else 0,
        completion_tokens=spent.completion_tokens if spent else 0,
        duration_ms=_elapsed(started),
    )

    batch = completion.choices[0].message.parsed
    if batch is None:
        return {}

    answers = {}
    for description in batch.descriptions:
        sku = normalize_sku(description.sku)
        if sku is None:
            logger.info("dropped a line returned under %r", description.sku)
            continue
        answers[sku] = description.text

    return answers


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
