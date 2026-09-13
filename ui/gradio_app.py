"""
Offer desk
==========
The salesperson's screen. It talks to the offer service over HTTP and holds no rule of its
own: everything here was decided by the services and is only laid out for reading.

Run from the repository root, with both services up:  python ui/gradio_app.py
"""

import os

import gradio as gr
import httpx

OFFER_SERVICE = os.environ.get("OFFER_SERVICE_URL", "http://localhost:8000")
TIMEOUT = 180.0

# The branches the service accepts. Anything else comes back as a 422 rather than an offer.
BRANCHES = ["ATHENS", "PIRAEUS", "THESSALONIKI", "PATRA", "TRIPOLI", "LARISA", "HERAKLION"]

EXAMPLES = [
    "Θέλω δέκα τροφοδοτικά 80+ Gold σε ATX, τουλάχιστον 750W.",
    "Πέντε τροφοδοτικά 80+ Platinum σε SFX, τουλάχιστον 750W.",
    "Σαράντα καλώδια CAT6a θωρακισμένα, τουλάχιστον 20 μέτρα, τα θέλουμε άμεσα.",
    "Οκτώ UPS από 2200VA και πάνω, με αυτονομία τουλάχιστον 12 λεπτά.",
    "Είκοσι ρευματολήπτες Schuko 16A.",
    "Ένα τροφοδοτικό, ό,τι έχετε.",
]

OFFERS = [
    "Προϊόν",
    "Ποσ.",
    "Αξία",
    "Έκπτ.",
    "Μεταφ.",
    "Σύνολο",
    "Παράδοση",
    "Έγκριση",
    "Απόθεμα",
    "Πώς επιλέχθηκε",
]
WIDTHS = ["22%", "5%", "8%", "7%", "8%", "9%", "10%", "7%", "10%", "14%"]

CHECKS = ["Προϊόν", "Προσφέρεται", "Τι δεν πέρασε"]

# The service speaks its own vocabulary. Nothing below is a rule — it is only how the
# screen says the same thing in the language the salesperson works in.
STOCK = {
    "same-day": "από το ράφι",
    "in-stock": "από το ράφι",
    "transfer": "από άλλη αποθήκη",
    "ordered": "κατόπιν παραγγελίας",
    "unknown": "άγνωστο",
}
CHOSEN = {
    "cheapest-acceptable": "φθηνότερο",
    "best-technical": "πιο κοντινό",
    "best-budget": "αξία χρήματος",
    "best-availability": "γρηγορότερο",
    "premium-alternative": "ανώτερο",
}
SPECS = {
    "amperage": "Ένταση (A)",
    "autonomy_min": "Αυτονομία (λεπτά)",
    "connector_type": "Τύπος",
    "cores": "Αγωγοί",
    "efficiency": "Απόδοση",
    "form_factor": "Μέγεθος",
    "ip_rating": "Στεγανότητα",
    "length_m": "Μήκος (μ)",
    "managed": "Διαχειριζόμενο",
    "poe": "PoE",
    "ports": "Θύρες",
    "section_mm": "Διατομή (mm²)",
    "shielding": "Θωράκιση",
    "speed_mbps": "Ταχύτητα (Mbps)",
    "standard": "Πρότυπο",
    "topology": "Τοπολογία",
    "va": "Ισχύς (VA)",
    "watt": "Ισχύς (W)",
}
LIMITS = {"eq": "", "gte": "τουλάχιστον", "gt": "πάνω από", "lte": "το πολύ", "lt": "κάτω από"}


def ask(request: str, branch: str, before_cut_off: bool) -> tuple:
    """One call to the service, and everything the screen shows comes out of the answer."""
    if not request.strip():
        return "Γράψε τι ζητάει ο πελάτης.", [], "", "", []

    try:
        answered = httpx.post(
            f"{OFFER_SERVICE}/offers/generate",
            json={"request": request, "store": branch, "before_cut_off": before_cut_off},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return f"### Η υπηρεσία δεν απαντά\n\n{exc}", [], "", "", []

    if answered.status_code != 200:
        return f"### {answered.status_code}\n\n{_said(answered)}", [], "", "", []

    body = answered.json()
    return panel(body), table(body), read(body), found(body), checks(body)


def panel(body: dict) -> str:
    """The answer, as the salesperson reads it before deciding what to send."""
    written = body.get("recommendation")
    if written is None:
        return f"### Καμία προσφορά\n\n{body.get('refused') or 'Δεν προέκυψε προσφορά.'}"

    lines = [f"### {_named(body, written['sku'])}", "", f"**Γιατί** — {written['because']}"]
    if written["watch_out"]:
        lines += ["", "**Πρόσεξε**"] + [f"- {one}" for one in written["watch_out"]]

    return "\n".join(lines + ["", "**Προς τον πελάτη**", "", f"> {written['text']}"])


def table(body: dict) -> list[list]:
    """The offers side by side, in the order the builder made them."""
    return [
        [
            f"{', '.join(row['skus'])} — {row['description']}",
            row["quantity"],
            money(row["net"]),
            money(row["discount"]),
            money(row["shipping"]),
            money(row["total"]),
            when(row["days"]),
            "ναι" if row["needs_approval"] else "—",
            STOCK.get(row["availability"], row["availability"]),
            ", ".join(CHOSEN.get(one, one) for one in row["strategies"]),
        ]
        for row in body["offers"]
    ]


def read(body: dict) -> str:
    """What the request came down to, which is what everything after it worked on."""
    asked = body["requirements"]
    lines = [f"**Κατηγορία** {asked.get('category', '—')}"]
    if asked.get("quantity"):
        lines.append(f"**Ποσότητα** {asked['quantity']}")
    if asked.get("immediate"):
        lines.append("**Άμεσα** ναι")
    for constraint in asked.get("constraints") or []:
        lines.append(f"**{_spec(constraint['key'])}** {_limit(constraint)}")

    return "\n\n".join(lines)


def _named(body: dict, sku: str) -> str:
    """The heading of the answer: what it is and what it costs, not a code on its own."""
    picked = next((row for row in body["offers"] if sku in row["skus"]), None)
    if picked is None:
        return sku

    return f"{sku} — {picked['description']} — {money(picked['total'])}"


def _spec(key: str) -> str:
    return SPECS.get(key, key)


def _limit(constraint: dict) -> str:
    """A condition as it was asked, without the field names and operators behind it."""
    said = LIMITS.get(constraint["op"], constraint["op"])
    return f"{said} {_plain(constraint['value'])}".strip()


def _plain(value) -> str:
    if isinstance(value, bool):
        return "ναι" if value else "όχι"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value)


def found(body: dict) -> str:
    """The products the search reached, before any of them was priced."""
    codes = (body["trace"].get("retrieve") or {}).get("candidates") or []
    return ", ".join(codes) if codes else "κανένα"


def checks(body: dict) -> list[list]:
    """Every scenario the builder made, and what the check said about it."""
    return [
        [
            row["sku"],
            "ναι" if row["offerable"] else "όχι",
            "; ".join(one["said"] for one in row["failed"]) or "—",
        ]
        for row in body["checked"]
    ]


def money(amount: float) -> str:
    """Euro the way the business documents write it: 1.602,63 €."""
    return f"{amount:,.2f}".replace(",", "|").replace(".", ",").replace("|", ".") + " €"


def when(days: int | None) -> str:
    if days is None:
        return "—"
    if days == 0:
        return "αυθημερόν"

    return "1 εργάσιμη" if days == 1 else f"{days} εργάσιμες"


def _said(answered: httpx.Response) -> str:
    try:
        return answered.json().get("detail", answered.text)
    except ValueError:
        return answered.text


def screen() -> gr.Blocks:
    with gr.Blocks(title="Agora — Γραφείο προσφορών") as app:
        gr.Markdown("# Agora\nΓράψε τι ζητάει ο πελάτης. Η προσφορά βγαίνει από τον κατάλογο.")

        with gr.Row():
            request = gr.Textbox(label="Το αίτημα", lines=2, scale=4)
            branch = gr.Dropdown(BRANCHES, value="ATHENS", label="Κατάστημα", scale=1)
            before_cut_off = gr.Checkbox(value=True, label="Παραγγελία πριν τις 13:00")

        gr.Examples(EXAMPLES, inputs=request, label="Παραδείγματα")
        run = gr.Button("Ετοιμασία προσφοράς", variant="primary")

        answer = gr.Markdown()
        offers = gr.Dataframe(headers=OFFERS, column_widths=WIDTHS, label="Οι προσφορές", wrap=True)

        with gr.Accordion("Πώς βγήκε αυτό", open=False):
            gr.Markdown("**Τι κατάλαβε από το αίτημα**")
            asked = gr.Markdown()
            gr.Markdown("**Τι βρήκε στον κατάλογο**")
            candidates = gr.Markdown()
            gr.Markdown("**Τι είπε ο έλεγχος**")
            checked = gr.Dataframe(headers=CHECKS, column_widths=["20%", "15%", "65%"], wrap=True)

        run.click(
            ask,
            inputs=[request, branch, before_cut_off],
            outputs=[answer, offers, asked, candidates, checked],
        )

    return app


if __name__ == "__main__":
    screen().launch()
