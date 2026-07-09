"""Structure-aware chunking.

Rather than one generic text splitter, each structural element extracted by
`app.services.pdf_processing` is chunked according to what preserves its
meaning best:
  - Tables: split by row-group, repeating the header row so every chunk is a
    readable, self-contained table.
  - Bullet/numbered lists: the lead-in sentence and its items are kept as one
    unit; if a list must be split, the lead-in is repeated in each split.
  - Prose paragraphs: token-budgeted with sliding-window overlap so a
    sentence near a chunk boundary still appears whole in at least one chunk.

Every final chunk is also prefixed with its section-heading path, so a chunk
is always self-contained even outside the context of the surrounding text.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

import tiktoken

_LIST_ITEM_PATTERN = re.compile(r"^\s*([•\-\*‣▪]|\d+[.)]|[A-Za-z][.)])\s+\S")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
DEFAULT_ENCODING = "cl100k_base"


@dataclass
class Atom:
    text: str
    content_type: str  # "prose" | "list"


@lru_cache(maxsize=4)
def _get_encoding(encoding_name: str):
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text: str, encoding_name: str = DEFAULT_ENCODING) -> int:
    return len(_get_encoding(encoding_name).encode(text))


def chunk_blocks(blocks: list[dict], chunk_size_tokens: int, overlap_tokens: int) -> list[dict]:
    """Turn extracted blocks (from pdf_processing) into final, embeddable
    chunks: [{text, content_type, page, section_heading, chunk_index}]."""

    chunks: list[dict] = []
    for block in blocks:
        page = block["page"]
        section_heading = block.get("section_heading")

        if block["content_type"] == "table":
            for table_text in _chunk_table_block(block["text"], chunk_size_tokens):
                chunks.append(_finalize_chunk(table_text, "table", page, section_heading))
            continue

        units = _split_text_into_units(block["text"])
        atoms: list[Atom] = []
        for unit in units:
            atoms.extend(_unit_to_atoms(unit, chunk_size_tokens))
        for packed in _pack_atoms(atoms, chunk_size_tokens, overlap_tokens):
            chunks.append(_finalize_chunk(packed.text, packed.content_type, page, section_heading))

    for idx, chunk in enumerate(chunks):
        chunk["chunk_index"] = idx
    return chunks


def _finalize_chunk(text: str, content_type: str, page: int, section_heading: str | None) -> dict:
    header = f"[Section: {section_heading}]\n" if section_heading else ""
    return {
        "text": f"{header}{text}".strip(),
        "content_type": content_type,
        "page": page,
        "section_heading": section_heading,
    }


# --------------------------------------------------------------------------
# Prose / list unit detection
# --------------------------------------------------------------------------


def _is_list_item_line(line: str) -> bool:
    return bool(_LIST_ITEM_PATTERN.match(line.strip()))


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(text.strip()) if s.strip()]


def _split_text_into_units(text: str) -> list[dict]:
    """Split a page's prose text (paragraph breaks already reconstructed
    from layout by pdf_processing) into prose or list units.

    PDF layout engines commonly render each bullet as its own visually
    separated paragraph (one per line, with spacing between them), so list
    detection has to work at two levels: (1) classify each raw paragraph as
    prose or list-items, then (2) merge a run of consecutive list-item
    paragraphs - and any immediately preceding lead-in line ending in ':' -
    into a single logical list unit.
    """

    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    classified = []
    for para in raw_paragraphs:
        lines = [line.strip() for line in para.split("\n") if line.strip()]
        list_item_lines = [line for line in lines if _is_list_item_line(line)]
        non_list_lines = [line for line in lines if not _is_list_item_line(line)]

        if list_item_lines and len(list_item_lines) >= max(1, len(lines) - 1):
            classified.append(
                {"kind": "list_items", "lead_in": non_list_lines[0] if non_list_lines else None, "items": list_item_lines}
            )
        else:
            classified.append({"kind": "prose", "text": para})

    units: list[dict] = []
    i = 0
    while i < len(classified):
        item = classified[i]

        if item["kind"] == "prose" and item["text"].rstrip().endswith(":") and _next_is_list(classified, i):
            lead_in = item["text"]
            items: list[str] = []
            i += 1
            while i < len(classified) and classified[i]["kind"] == "list_items":
                items.extend(_all_item_lines(classified[i]))
                i += 1
            units.append({"content_type": "list", "lead_in": lead_in, "items": items})
            continue

        if item["kind"] == "list_items":
            lead_in = item["lead_in"]
            items = list(item["items"])
            i += 1
            while i < len(classified) and classified[i]["kind"] == "list_items" and classified[i]["lead_in"] is None:
                items.extend(classified[i]["items"])
                i += 1
            units.append({"content_type": "list", "lead_in": lead_in, "items": items})
            continue

        units.append({"content_type": "prose", "text": item["text"]})
        i += 1

    return units


def _next_is_list(classified: list[dict], index: int) -> bool:
    return index + 1 < len(classified) and classified[index + 1]["kind"] == "list_items"


def _all_item_lines(list_item_paragraph: dict) -> list[str]:
    lead_in = [list_item_paragraph["lead_in"]] if list_item_paragraph.get("lead_in") else []
    return lead_in + list(list_item_paragraph["items"])


def _unit_to_atoms(unit: dict, chunk_size_tokens: int) -> list[Atom]:
    if unit["content_type"] == "prose":
        return _prose_unit_to_atoms(unit["text"], chunk_size_tokens)
    return _list_unit_to_atoms(unit.get("lead_in"), unit["items"], chunk_size_tokens)


def _prose_unit_to_atoms(text: str, chunk_size_tokens: int) -> list[Atom]:
    if count_tokens(text) <= chunk_size_tokens:
        return [Atom(text=text, content_type="prose")]

    # Paragraph too large on its own - fall back to sentence-level atoms.
    # Kept at sentence granularity (not pre-grouped) so `_pack_atoms` can
    # both bin-pack them up to the token budget AND create a proper
    # sliding-window overlap of only a few trailing sentences, rather than
    # being forced to carry a whole oversized pre-grouped block forward.
    sentences = _split_sentences(text)
    if not sentences:
        return [Atom(text=text, content_type="prose")]
    return [Atom(text=sentence, content_type="prose") for sentence in sentences]


def _list_unit_to_atoms(lead_in: str | None, items: list[str], chunk_size_tokens: int) -> list[Atom]:
    full_text = (f"{lead_in}\n" if lead_in else "") + "\n".join(items)
    if count_tokens(full_text) <= chunk_size_tokens:
        return [Atom(text=full_text, content_type="list")]

    # List too long for one chunk - split by item groups, repeating the
    # lead-in in every split so each chunk still says what the list is for.
    lead_in_tokens = count_tokens(lead_in) if lead_in else 0
    atoms: list[Atom] = []
    buffer: list[str] = []
    buffer_tokens = lead_in_tokens
    for item in items:
        item_tokens = count_tokens(item)
        if buffer and buffer_tokens + item_tokens > chunk_size_tokens:
            group_text = (f"{lead_in}\n" if lead_in else "") + "\n".join(buffer)
            atoms.append(Atom(text=group_text, content_type="list"))
            buffer, buffer_tokens = [], lead_in_tokens
        buffer.append(item)
        buffer_tokens += item_tokens
    if buffer:
        group_text = (f"{lead_in}\n" if lead_in else "") + "\n".join(buffer)
        atoms.append(Atom(text=group_text, content_type="list"))
    return atoms


def _pack_atoms(atoms: list[Atom], chunk_size_tokens: int, overlap_tokens: int) -> list[Atom]:
    """Greedy bin-packing of atoms into token-budgeted chunks, carrying the
    trailing ~overlap_tokens worth of atoms forward into the next chunk."""

    packed: list[Atom] = []
    current: list[Atom] = []
    current_tokens = 0

    def flush() -> None:
        if not current:
            return
        text = "\n\n".join(a.text for a in current)
        content_type = "list" if all(a.content_type == "list" for a in current) else "prose"
        packed.append(Atom(text=text, content_type=content_type))

    for atom in atoms:
        atom_tokens = count_tokens(atom.text)
        if current and current_tokens + atom_tokens > chunk_size_tokens:
            flush()
            overlap_atoms: list[Atom] = []
            overlap_count = 0
            for prev in reversed(current):
                prev_tokens = count_tokens(prev.text)
                if overlap_atoms and overlap_count + prev_tokens > overlap_tokens:
                    break
                overlap_atoms.insert(0, prev)
                overlap_count += prev_tokens
            current, current_tokens = overlap_atoms, overlap_count
        current.append(atom)
        current_tokens += atom_tokens
    flush()
    return packed


# --------------------------------------------------------------------------
# Table chunking
# --------------------------------------------------------------------------


def _chunk_table_block(markdown_text: str, chunk_size_tokens: int) -> list[str]:
    lines = [line for line in markdown_text.split("\n") if line.strip()]
    if len(lines) < 2:
        return [markdown_text] if markdown_text.strip() else []

    header_line, separator_line, *body_lines = lines
    if count_tokens(markdown_text) <= chunk_size_tokens or not body_lines:
        return [markdown_text]

    header_tokens = count_tokens(header_line) + count_tokens(separator_line)
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_tokens = header_tokens
    for row in body_lines:
        row_tokens = count_tokens(row)
        if buffer and buffer_tokens + row_tokens > chunk_size_tokens:
            chunks.append("\n".join([header_line, separator_line, *buffer]))
            buffer, buffer_tokens = [], header_tokens
        buffer.append(row)
        buffer_tokens += row_tokens
    if buffer:
        chunks.append("\n".join([header_line, separator_line, *buffer]))
    return chunks
