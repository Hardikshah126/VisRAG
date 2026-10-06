import re
from typing import Iterator, List

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def _units(text: str, max_chars: int) -> Iterator[str]:
    """Split text into sentence-sized units, none longer than max_chars."""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        for sentence in _SENTENCE_BREAK.split(paragraph):
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                yield sentence[:cut]
                sentence = sentence[cut:].lstrip()
            if sentence:
                yield sentence


def chunk_text(
    text: str, max_chars: int = 900, overlap: int = 150, min_chars: int = 20
) -> List[str]:
    """Pack sentences into chunks of at most ``max_chars`` characters.

    ~900 chars is roughly 200 tokens, safely under MiniLM's 256-token input
    limit, so no chunk is silently truncated at embedding time. Consecutive
    chunks share up to ``overlap`` characters of trailing sentences so facts
    spanning a boundary stay retrievable. Only chunks shorter than
    ``min_chars`` are dropped (page numbers and the like), so headings and
    short list items survive by being packed alongside their neighbours.
    """
    chunks: List[str] = []
    current: List[str] = []

    for unit in _units(text, max_chars):
        if current and len(" ".join(current)) + 1 + len(unit) > max_chars:
            chunks.append(" ".join(current))

            tail: List[str] = []
            for previous in reversed(current):
                if len(" ".join([previous, *tail])) > overlap:
                    break
                tail.insert(0, previous)
            while tail and len(" ".join(tail)) + 1 + len(unit) > max_chars:
                tail.pop(0)
            current = tail

        current.append(unit)

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if len(c) >= min_chars]
