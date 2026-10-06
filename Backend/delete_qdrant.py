"""Drop a Qdrant collection (destructive!).

    python delete_qdrant.py                      # configured collection, asks first
    python delete_qdrant.py --collection NAME    # another collection, e.g. the old
                                                 # single-vector "visrag_multimodal"
    python delete_qdrant.py --yes                # skip the confirmation prompt
"""

import argparse
import logging

import config
from storage.qdrant_client import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collection", default=config.COLLECTION_NAME)
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    if not args.yes:
        print(f"This permanently deletes collection '{args.collection}' at {config.QDRANT_URL}.")
        if input(f"Type the collection name ({args.collection}) to confirm: ").strip() != args.collection:
            print("Aborted.")
            return

    get_client().delete_collection(args.collection)
    logger.info("Deleted collection '%s'", args.collection)


if __name__ == "__main__":
    main()
