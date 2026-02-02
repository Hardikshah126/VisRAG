import camelot


def extract_tables(pdf_path):
    """
    ✅ Production Table Extraction

    Returns table blocks:

    {
        "type": "table",
        "page": X,
        "caption": "...",
        "table_data": [[rows]]
    }
    """

    print("\n📊 Running Camelot Table Extraction (STREAM mode)...")

    tables = camelot.read_pdf(
        pdf_path,
        pages="all",
        flavor="stream"
    )

    print(f"✅ Camelot detected {tables.n} tables")

    table_blocks = []

    for i, table in enumerate(tables):

        data = table.df.values.tolist()

        table_blocks.append(
            {
                "type": "table",
                "page": table.page,
                "caption": f"Extracted Table {i+1}",
                "table_data": data,
                "content": str(data)
            }
        )

    return table_blocks
