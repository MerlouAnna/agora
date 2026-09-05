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

from services import usage
from services.config import settings
from services.data_service.generation import validator
from services.data_service.ingestion.parsers import normalize_sku

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
SERVICE = "data_service"
PURPOSE = "product-descriptions"

_client = None

SYSTEM = """Γράφεις τα κείμενα που εμφανίζονται στο e-shop ενός έλληνα χονδρέμπορου
ηλεκτρολογικού και δικτυακού υλικού.

Για κάθε προϊόν παίρνεις τη γραμμή του ERP (`erp`) — στεγνή, με κάθε τεχνικό
χαρακτηριστικό γραμμένο ακριβώς όπως το διαβάζουν τα συστήματά μας — τη μάρκα και τα
`specs`. Γράψε το κείμενο του καταστήματος.

Κανόνες:
- Μία με δύο προτάσεις, 120 έως 200 χαρακτήρες.
- Κάθε τιμή των `specs` πρέπει να εμφανίζεται στο κείμενό σου γραμμένη με τον ίδιο
  ακριβώς τρόπο που εμφανίζεται στο `erp`. Η μονάδα μένει κολλητά στον αριθμό: γράφεις
  «μήκους 20m», όχι «μήκους 20 μέτρων».
- Ανάφερε τη μάρκα.
- Μην προσθέσεις χαρακτηριστικό που δεν υπάρχει στο `erp` και μην αλλάξεις κανένα νούμερο.
- Κλείσε με το πού ταιριάζει το προϊόν: χρήση, χώρος, τύπος εγκατάστασης.
- Χωρίς τιμή, χωρίς bullets, χωρίς υπερθετικά («κορυφαίο», «απόλυτη ποιότητα»).
- Οι περιγραφές του ίδιου batch δεν πρέπει να μοιάζουν μεταξύ τους. Άλλαξε το άνοιγμα της
  πρότασης, τη σειρά των στοιχείων και το πού εστιάζεις. Δύο προϊόντα της ίδιας κατηγορίας
  δεν πρέπει να διαβάζονται σαν παραλλαγές της ίδιας πρότασης.
- Επίστρεψε το sku ακριβώς όπως το πήρες.

Παραδείγματα:

erp: «Καλώδιο ρεύματος 3x2.5mm 20m 1500W IP44 εξωτερικού χώρου» — Elektra
→ «Καλώδιο ρεύματος Elektra 3x2.5mm σε μήκος 20m, με στεγανότητα IP44 και αντοχή έως
1500W, για παροχές σε εξωτερικούς χώρους και προσωρινές εγκαταστάσεις.»

erp: «Καλώδιο δικτύου CAT6a S/FTP 10m» — Nordion
→ «Το CAT6a S/FTP της Nordion είναι πλήρως θωρακισμένο και σε μήκος 10m καλύπτει
οριζόντια καλωδίωση ορόφου, εκεί όπου οι παρεμβολές από ισχυρά ρεύματα είναι δεδομένες.»

erp: «Τροφοδοτικό 750W 80+ Gold ATX» — Kyma
→ «Τροφοδοτικό ATX 750W της Kyma με πιστοποίηση 80+ Gold, για σταθμούς εργασίας που
δουλεύουν συνεχόμενα και χρειάζονται χαμηλή κατανάλωση στο ρελαντί.»

erp: «UPS line-interactive 1500VA / 900W αυτονομία 20 λεπτά» — Voltera
→ «Μονάδα αδιάλειπτης παροχής Voltera τοπολογίας line-interactive, 1500VA / 900W με
αυτονομία 20 λεπτά, ιδανική για σταθμούς εργασίας, δικτυακό εξοπλισμό και ταμειακά.»

erp: «Switch 24 θυρών 1000Mbps PoE managed» — Delta Line
→ «Switch Delta Line 24 θυρών 1000Mbps, managed και με PoE σε κάθε θύρα, για
εγκαταστάσεις όπου κάμερες και access points τροφοδοτούνται από το ίδιο το δίκτυο.»

erp: «Ρευματολήπτης CEE 32A IP67» — Kyma
→ «Βιομηχανικός ρευματολήπτης CEE 32A της Kyma με προστασία IP67, κατάλληλος για
εργοτάξια και υπαίθριες παροχές όπου η σκόνη και το νερό είναι μόνιμο ζήτημα.»

Αν σου δοθεί πεδίο `fix`, η προηγούμενη απάντησή σου για αυτό το προϊόν απορρίφθηκε γι'
αυτόν τον λόγο. Διόρθωσέ τον."""


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


def client():
    """The OpenAI client, built once.

    The import is what costs: the SDK declares a few hundred models and pulling it in takes
    long enough on a cold start to look like a hang, so it happens behind a log line and
    only once per process.
    """
    global _client

    if _client is None:
        if not settings.openai_api_key:
            raise ModelUnavailable("no OPENAI_API_KEY in the environment")

        logger.info("loading the OpenAI client")
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)
        logger.info("client ready, talking to %s", settings.llm_model)

    return _client


def _ask_model(requests: list[dict]) -> dict[str, str]:
    """One call for the whole batch, with the answers keyed by a SKU we recognise."""
    talk = client()

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
