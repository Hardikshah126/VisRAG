import hashlib
import logging
import os

import pymupdf  # PyMuPDF

import config

logger = logging.getLogger(__name__)


def extract_figures(pdf_path: str, doc_id: str):
    """
    Extract embedded images from the PDF into ``extracted/<doc_id>/``.

    Filtering keeps retrieval from filling up with junk:
    - images smaller than MIN_FIGURE_PX (icons, bullets, rules) are skipped
    - each image object (xref) is taken once, so a logo repeated in every page
      header is not stored per page
    - byte-identical images are de-duplicated
    - everything is re-encoded as PNG so browsers can always display it
      (the raw stream may be JPX/CMYK), and soft masks are applied so
      transparent images keep their transparency

    ``doc_id`` is a server-generated uuid hex, so it is safe as a directory name.

    Returns blocks:
        {"type": "image", "page": 3, "file_path": "<doc_id>/figure1_page3.png",
         "caption": "Figure 1 (page 3)", "figure_index": 1}
    ``file_path`` is relative to ``config.EXTRACTED_DIR``.
    """
    out_dir = config.EXTRACTED_DIR / doc_id
    os.makedirs(out_dir, exist_ok=True)

    figure_blocks = []
    seen_xrefs: set = set()
    seen_hashes: set = set()

    logger.info("Extracting figures from %s...", doc_id)

    with pymupdf.open(pdf_path) as doc:
        for page_index in range(len(doc)):
            page_num = page_index + 1

            for img in doc[page_index].get_images(full=True):
                if len(figure_blocks) >= config.MAX_FIGURES:
                    logger.warning("Figure cap (%d) reached; skipping the rest", config.MAX_FIGURES)
                    return figure_blocks

                xref, smask = img[0], img[1]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    pix = pymupdf.Pixmap(doc, xref)
                    if min(pix.width, pix.height) < config.MIN_FIGURE_PX:
                        continue
                    if pix.colorspace is None:  # stencil mask, not a picture
                        continue
                    if pix.colorspace.n >= 4:  # CMYK -> RGB
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    if smask:
                        pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
                    data = pix.tobytes("png")
                except Exception:
                    logger.warning("Skipping unreadable image xref=%s on page %d", xref, page_num, exc_info=True)
                    continue

                if len(data) < config.MIN_FIGURE_BYTES:
                    continue
                digest = hashlib.sha1(data).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)

                index = len(figure_blocks) + 1
                filename = f"figure{index}_page{page_num}.png"
                with open(out_dir / filename, "wb") as f:
                    f.write(data)

                figure_blocks.append(
                    {
                        "type": "image",
                        "page": page_num,
                        "file_path": f"{doc_id}/{filename}",
                        "caption": f"Figure {index} (page {page_num})",
                        "figure_index": index,
                    }
                )

    logger.info("Total extracted figures: %d", len(figure_blocks))
    return figure_blocks
