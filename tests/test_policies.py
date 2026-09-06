import pytest

from services.offer_service.rag import policies


@pytest.fixture(scope="module")
def shipped():
    """The ten documents, read once for the whole file — parsing PDFs is not free."""
    return policies.read_all()


def section(passages, document: str, heading: str):
    return next(
        passage
        for passage in passages
        if passage.metadata["document"] == document and passage.metadata["section"] == heading
    )


def test_every_document_we_ship_is_readable(shipped):
    """The PDFs are committed, so a re-render that breaks one has to fail here."""
    assert len({passage.metadata["document"] for passage in shipped}) == 10
    assert all(passage.text.strip() for passage in shipped)


def test_a_table_comes_back_as_rows_not_as_run_together_text(shipped):
    """Read as running text the discount tiers arrive as `Έως 799,99 €0%`."""
    tiers = section(shipped, "politiki-ekptoseon", "Κλιμάκια έκπτωσης όγκου")

    assert "Έως 799,99 € | 0%" in tiers.text
    assert "15.000 € και άνω | 8%" in tiers.text


def test_a_passage_names_its_document_in_its_own_text(shipped):
    """A passage is retrieved alone, so it has to be findable by the document's name."""
    limits = section(shipped, "politiki-ekptoseon", "Ανώτατο όριο έκπτωσης ανά κατηγορία")

    assert limits.text.startswith("Πολιτική Εκπτώσεων ·")
    assert limits.metadata["kind"] == "policy"
    assert limits.metadata["effective"] == "1 Σεπτεμβρίου 2026"


def test_a_datasheet_carries_the_product_it_describes(shipped):
    sheet = [p for p in shipped if p.metadata["document"] == "datasheet-UPS-1014"]

    assert {p.metadata["sku"] for p in sheet} == {"UPS-1014"}
    assert all(p.metadata["kind"] == "datasheet" for p in sheet)
    assert any("35 λεπτά" in p.text for p in sheet)


def test_a_file_that_is_not_a_pdf_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.pdf").write_text("αυτό δεν είναι PDF", encoding="utf-8")

    assert policies.read_all(tmp_path) == []
