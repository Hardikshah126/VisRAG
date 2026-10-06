import logging

import pymupdf  # PyMuPDF

from ingestion.chunker import chunk_text

logger = logging.getLogger(__name__)


def parse_pdf(pdf_path):
    """
    Extract page-wise text chunks.

    Text is read in reading order as layout blocks (rather than splitting on
    blank lines, which PyMuPDF rarely emits), then packed into overlapping,
    sentence-aware chunks that fit the embedding model's input window.

    Output: [{"type": "text", "page": 1, "content": "..."}, ...]
    """
    blocks = []

    with pymupdf.open(pdf_path) as doc:
        for page_index in range(len(doc)):
            layout_blocks = doc[page_index].get_text("blocks", sort=True)

            # block = (x0, y0, x1, y1, text, block_no, block_type); type 0 is text
            page_text = "\n\n".join(
                b[4].strip() for b in layout_blocks if b[6] == 0 and b[4].strip()
            )

            for chunk in chunk_text(page_text):
                blocks.append({"type": "text", "page": page_index + 1, "content": chunk})

    logger.info("Extracted %d text chunks", len(blocks))
    return blocks
