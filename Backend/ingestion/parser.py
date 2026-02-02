import fitz  # PyMuPDF


def parse_pdf(pdf_path):
    """
    ✅ Production PDF Parser
    Extracts clean page-wise text chunks.

    Output format:
    [
        {
            "type": "text",
            "page": 1,
            "content": "...chunk..."
        }
    ]
    """

    doc = fitz.open(pdf_path)
    blocks = []

    for page_num in range(len(doc)):
        page = doc[page_num]

        text = page.get_text("text").strip()

        if text:
            chunks = text.split("\n\n")

            for chunk in chunks:
                if len(chunk.strip()) > 50:
                    blocks.append(
                        {
                            "type": "text",
                            "page": page_num + 1,
                            "content": chunk.strip()
                        }
                    )

    print(f"✅ Extracted {len(blocks)} text chunks")
    return blocks
