"""Runs real Camelot, to catch API drift in the (fast-moving) Camelot dependency
that the mocked API tests cannot see."""

import pymupdf as fitz
import pytest

pytest.importorskip("camelot")

from ingestion.table_parser import extract_tables  # noqa: E402

BODY = "Plain body text that is not a table. " * 20


def _pdf(path, with_table: bool):
    doc = fitz.open()
    page = doc.new_page()
    if with_table:
        rows = [
            ["Region", "Q1", "Q2", "Q3"],
            ["North", "120", "135", "150"],
            ["South", "80", "95", "99"],
            ["East", "60", "70", "88"],
        ]
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                page.insert_text((72 + c * 100, 120 + r * 24), cell, fontsize=11)
    page.insert_textbox(fitz.Rect(72, 300, 540, 500), BODY, fontsize=11)
    doc.save(path)


def test_extracts_real_table(tmp_path):
    pdf = str(tmp_path / "t.pdf")
    _pdf(pdf, with_table=True)
    tables = extract_tables(pdf)
    assert len(tables) == 1
    assert tables[0]["page"] == 1
    assert tables[0]["table_data"][0] == ["Region", "Q1", "Q2", "Q3"]
    assert "North | 120 | 135 | 150" in tables[0]["content"]


def test_body_text_is_not_reported_as_a_table(tmp_path):
    # Camelot's stream mode returns a one-column "table" for plain paragraphs;
    # our filter must drop it.
    pdf = str(tmp_path / "t.pdf")
    _pdf(pdf, with_table=False)
    assert extract_tables(pdf) == []


def test_camelot_failure_degrades_to_no_tables(tmp_path, monkeypatch):
    import camelot

    pdf = str(tmp_path / "t.pdf")
    _pdf(pdf, with_table=True)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(camelot, "read_pdf", boom)
    assert extract_tables(pdf) == []
