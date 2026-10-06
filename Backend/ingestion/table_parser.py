import logging
from typing import List, Optional

import pymupdf  # PyMuPDF

import config

logger = logging.getLogger(__name__)

# Camelot's "stream" flavour happily reports ordinary paragraphs as tables, so
# candidates are filtered with simple structural heuristics.
MIN_ROWS = 2
MIN_COLS = 2
MIN_FILLED_RATIO = 0.5
MAX_CELL_CHARS = 200
MAX_MEAN_CELL_CHARS = 80


def clean_rows(raw_rows) -> List[List[str]]:
    """Stringify cells, then drop fully empty rows and columns."""
    rows = [[str(cell).strip() for cell in row] for row in raw_rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return []
    keep = [i for i in range(max(len(r) for r in rows)) if any(i < len(r) and r[i] for r in rows)]
    return [[row[i] if i < len(row) else "" for i in keep] for row in rows]


def is_plausible_table(rows: List[List[str]]) -> bool:
    if len(rows) < MIN_ROWS or not rows[0] or len(rows[0]) < MIN_COLS:
        return False
    cells = [cell for row in rows for cell in row]
    filled = [cell for cell in cells if cell]
    if len(filled) / len(cells) < MIN_FILLED_RATIO:
        return False
    if max(len(c) for c in filled) > MAX_CELL_CHARS:
        return False
    return sum(len(c) for c in filled) / len(filled) <= MAX_MEAN_CELL_CHARS


def table_to_text(rows: List[List[str]]) -> str:
    """Readable, token-efficient form for embedding and for the LLM prompt
    (instead of a Python list repr)."""
    return "\n".join(" | ".join(row) for row in rows)


def extract_tables(pdf_path, max_pages: Optional[int] = None):
    """
    Extract tables with Camelot (stream mode), scanning at most ``max_pages``
    pages. A Camelot failure degrades to "no tables" rather than failing the
    whole upload.

    Returns blocks:
        {"type": "table", "page": X, "caption": "...",
         "table_data": [[cells]], "content": "row | row\\n..."}
    """
    import camelot  # slow import; only needed here

    limit = max_pages or config.MAX_TABLE_PAGES
    with pymupdf.open(pdf_path) as doc:
        last_page = min(len(doc), limit)
    if last_page == 0:
        return []

    logger.info("Running Camelot table extraction on pages 1-%d...", last_page)
    try:
        tables = camelot.read_pdf(pdf_path, pages=f"1-{last_page}", flavor="stream")
    except Exception:
        logger.exception("Camelot failed; continuing without tables")
        return []

    table_blocks = []
    for table in tables:
        rows = clean_rows(table.df.values.tolist())
        if not is_plausible_table(rows):
            continue
        table_blocks.append(
            {
                "type": "table",
                "page": int(table.page),
                "caption": f"Table {len(table_blocks) + 1} (page {int(table.page)})",
                "table_data": rows,
                "content": table_to_text(rows),
            }
        )

    logger.info("Camelot found %d candidates, kept %d tables", tables.n, len(table_blocks))
    return table_blocks
