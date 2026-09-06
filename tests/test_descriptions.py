from services.data_service.categories import Category
from services.data_service.generation import descriptions, validator

ITEM = {
    "sku": "DAT-2001",
    "category": Category.DATA,
    "brand": "Nordion",
    "specs": {"standard": "CAT6a", "shielding": "S/FTP", "length_m": 10},
    "erp": "Καλώδιο δικτύου CAT6a S/FTP 10m",
}

GOOD = "Το CAT6a S/FTP της Nordion, σε μήκος 10m, καλύπτει οριζόντια καλωδίωση ορόφου εκεί όπου οι παρεμβολές είναι δεδομένες."
WRONG_LENGTH = "Το CAT6a S/FTP της Nordion, σε μήκος 5m, καλύπτει οριζόντια καλωδίωση ορόφου εκεί όπου οι παρεμβολές είναι δεδομένες."
NO_SHIELDING = "Το CAT6a της Nordion, σε μήκος 10m, καλύπτει οριζόντια καλωδίωση ορόφου εκεί όπου οι παρεμβολές είναι δεδομένες."


def test_a_changed_number_is_caught():
    assert "length_m" in validator.check(ITEM["category"], ITEM["specs"], WRONG_LENGTH)


def test_a_dropped_spec_is_caught():
    assert "shielding" in validator.check(ITEM["category"], ITEM["specs"], NO_SHIELDING)


def test_a_rejected_description_goes_back_with_the_reason():
    asked = []

    def ask(requests):
        asked.append(requests[0].get("fix"))
        return {ITEM["sku"]: GOOD if len(asked) > 1 else WRONG_LENGTH}

    outcome = descriptions.write([ITEM], ask=ask)

    assert outcome.rounds_used == 2
    assert outcome.texts[ITEM["sku"]] == GOOD
    assert asked[0] is None
    assert "length_m" in asked[1]


def test_the_loop_gives_up_rather_than_looping():
    outcome = descriptions.write([ITEM], ask=lambda requests: {ITEM["sku"]: WRONG_LENGTH})

    assert outcome.rounds_used == descriptions.MAX_ROUNDS
    assert outcome.rejected == [ITEM["sku"]]
    assert outcome.texts == {}
