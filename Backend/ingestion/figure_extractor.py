import os
import fitz  # PyMuPDF


def extract_figures(pdf_path: str):
    """
    ✅ Extract embedded images (figures) from PDF using PyMuPDF

    Saves figures into:

        extracted/figures/figure1_page3.png

    Returns blocks like:

    {
        type: "image",
        page: 3,
        caption: "Figure 1 extracted from page 3",
        file_path: "...",
        figure_index: 1
    }
    """

    os.makedirs("extracted/figures", exist_ok=True)

    doc = fitz.open(pdf_path)

    figure_blocks = []
    fig_counter = 1

    print("\n🖼️ Extracting real figures using PyMuPDF...")

    for page_index in range(len(doc)):
        page = doc[page_index]

        images = page.get_images(full=True)

        if len(images) > 0:
            print(f"✅ Page {page_index+1}: Found {len(images)} images")

        for img in images:
            xref = img[0]

            base_img = doc.extract_image(xref)
            img_bytes = base_img["image"]
            img_ext = base_img["ext"]

            page_num = page_index + 1

            img_path = (
                f"extracted/figures/figure{fig_counter}_page{page_num}.{img_ext}"
            )

            with open(img_path, "wb") as f:
                f.write(img_bytes)

            figure_blocks.append(
                {
                    "type": "image",
                    "page": page_num,
                    "file_path": img_path,
                    "caption": f"Figure {fig_counter} extracted from page {page_num}",
                    "figure_index": fig_counter,
                }
            )

            fig_counter += 1

    print(f"✅ Total extracted figures: {len(figure_blocks)}")

    return figure_blocks
