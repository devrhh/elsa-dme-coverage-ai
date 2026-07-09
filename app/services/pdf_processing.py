"""PDF validation and layout-aware structural extraction.

Coverage PDFs are untrusted external input, so this module is deliberately
defensive: every function that touches file bytes validates before trusting
anything, and the actual parsing (`extract_structured_blocks`) is designed to
be run inside `app.core.timeouts.run_with_timeout` so a malformed or
adversarial PDF can never hang the request.

We use `pdfplumber` (not a plain linear text extractor) because it exposes
per-word position and font metadata, which lets us reconstruct structure that
naive text extraction throws away:
  - Headings: detected from relative font size / boldness, tracked as a
    heading stack so every block can carry a "section path".
  - Paragraph breaks: inferred from vertical gaps between lines (layout),
    rather than guessing from whitespace in a flattened text stream.
  - Tables: detected via `page.find_tables()` (line/position based) and
    serialized to Markdown, kept completely separate from prose so rows and
    columns are never scrambled.
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from app.core.exceptions import InvalidPdfError

PDF_MAGIC_BYTES = b"%PDF-"
_HEADING_MAX_WORDS = 12
_HEADING_MAX_CHARS = 150
_PARAGRAPH_GAP_MULTIPLIER = 1.6


@dataclass
class ExtractedBlock:
    content_type: str  # "text" | "table"
    text: str
    page: int
    section_heading: str | None


def validate_pdf_bytes(data: bytes, max_size_bytes: int) -> None:
    """Reject anything that isn't actually a PDF, or is too large, before we
    ever write it to disk or hand it to a parser."""

    if not data:
        raise InvalidPdfError("Uploaded file is empty.")
    if len(data) > max_size_bytes:
        raise InvalidPdfError(f"File exceeds the {max_size_bytes // (1024 * 1024)}MB upload limit.")
    if not data.startswith(PDF_MAGIC_BYTES):
        raise InvalidPdfError("File does not appear to be a valid PDF (missing %PDF- header).")


def save_pdf_file(data: bytes, org_id: uuid.UUID, document_id: uuid.UUID, upload_dir: str) -> str:
    org_dir = Path(upload_dir) / str(org_id)
    org_dir.mkdir(parents=True, exist_ok=True)
    file_path = org_dir / f"{document_id}.pdf"
    file_path.write_bytes(data)
    return str(file_path)


# --------------------------------------------------------------------------
# Structural extraction (runs inside a subprocess with a hard timeout - see
# app.services.ingestion / app.core.timeouts)
# --------------------------------------------------------------------------


def extract_structured_blocks(file_path: str, max_pages: int, max_chars: int) -> list[dict]:
    """Extract headings, paragraph-structured text, and tables from a PDF.

    Returns a list of plain dicts (must stay picklable - this runs in a
    subprocess): {content_type, text, page, section_heading}.
    `content_type` is "text" (prose/list content for app.services.chunking to
    further split) or "table" (already Markdown-serialized).
    """

    blocks: list[dict] = []
    total_chars = 0

    with pdfplumber.open(file_path) as pdf:
        pages = pdf.pages[:max_pages]

        page_data = []
        all_line_sizes: list[int] = []
        for page_number, page in enumerate(pages, start=1):
            tables = page.find_tables()
            table_bboxes = [t.bbox for t in tables]
            words = page.extract_words(extra_attrs=["size", "fontname"])
            words = [w for w in words if not _word_in_any_bbox(w, table_bboxes)]
            lines = _cluster_words_into_lines(words)
            # Merge lines and tables into one top-to-bottom reading-order
            # sequence per page. Processing all of a page's tables before any
            # of its text (as a naive two-pass approach would) means a
            # heading positioned directly above a table on the same page -
            # an extremely common PDF layout - would never get attached to
            # that table, since heading_stack wouldn't be updated yet.
            events = [{"kind": "line", "top": line["top"], "line": line} for line in lines]
            events += [{"kind": "table", "top": table.bbox[1], "table": table} for table in tables]
            events.sort(key=lambda e: e["top"])
            page_data.append({"page_number": page_number, "events": events})
            all_line_sizes.extend(round(line["avg_size"]) for line in lines if line["text"].strip())

        body_size = _most_common_size(all_line_sizes)
        heading_stack: dict[int, str] = {}

        for page_info in page_data:
            page_number = page_info["page_number"]

            text_lines: list[str] = []
            prev_bottom: float | None = None
            # Snapshot the heading path *before* the pending text_lines were
            # accumulated - a block must be flushed and re-tagged whenever a
            # new heading is crossed, otherwise text seen before a later
            # heading on the same page would incorrectly get attributed to it.
            pending_heading = _heading_path_str(heading_stack)

            def _flush_pending_text() -> None:
                nonlocal text_lines, total_chars
                if not text_lines:
                    return
                page_text = re.sub(r"\n{2,}", "\n\n", "\n".join(text_lines))
                if page_text.strip():
                    blocks.append(
                        {
                            "content_type": "text",
                            "text": page_text,
                            "page": page_number,
                            "section_heading": pending_heading,
                        }
                    )
                    total_chars += len(page_text)
                text_lines = []

            for event in page_info["events"]:
                if event["kind"] == "table":
                    # A table interrupts the current text flow - flush first
                    # so preceding text isn't misattributed to whatever
                    # heading happens to be active once the table itself is
                    # tagged below.
                    _flush_pending_text()
                    table = event["table"]
                    rows = table.extract()
                    markdown = _rows_to_markdown(rows)
                    if markdown.strip():
                        blocks.append(
                            {
                                "content_type": "table",
                                "text": markdown,
                                "page": page_number,
                                "section_heading": _heading_path_str(heading_stack),
                            }
                        )
                        total_chars += len(markdown)
                    # Reset so the next text line's paragraph-gap check is
                    # against the table's bottom edge, not a line from
                    # before the table (which would otherwise look like a
                    # huge, spurious gap).
                    prev_bottom = table.bbox[3]
                    pending_heading = _heading_path_str(heading_stack)
                    continue

                line = event["line"]
                text = line["text"].strip()
                if not text:
                    continue
                if _is_heading_line(text, line["avg_size"], line["is_bold"], body_size):
                    _flush_pending_text()
                    level = _heading_level(line["avg_size"], body_size)
                    heading_stack[level] = text
                    for lvl in list(heading_stack):
                        if lvl > level:
                            del heading_stack[lvl]
                    pending_heading = _heading_path_str(heading_stack)
                    continue

                gap = (line["top"] - prev_bottom) if prev_bottom is not None else 0
                if prev_bottom is not None and gap > body_size * _PARAGRAPH_GAP_MULTIPLIER:
                    text_lines.append("")  # paragraph break marker
                text_lines.append(text)
                prev_bottom = line["bottom"]

            _flush_pending_text()

            if total_chars > max_chars:
                break

    return blocks


def _word_in_any_bbox(word: dict, bboxes: list[tuple]) -> bool:
    if not bboxes:
        return False
    wx = (word["x0"] + word["x1"]) / 2
    wy = (word["top"] + word["bottom"]) / 2
    for x0, top, x1, bottom in bboxes:
        if x0 <= wx <= x1 and top <= wy <= bottom:
            return True
    return False


def _cluster_words_into_lines(words: list[dict], y_tolerance: float = 3.0) -> list[dict]:
    buckets: dict[int, list[dict]] = {}
    for word in words:
        key = round(word["top"] / y_tolerance)
        buckets.setdefault(key, []).append(word)

    lines = []
    for key in sorted(buckets.keys()):
        line_words = sorted(buckets[key], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in line_words)
        sizes = [w.get("size", 0) or 0 for w in line_words]
        avg_size = sum(sizes) / len(sizes) if sizes else 0
        is_bold = any("bold" in (w.get("fontname") or "").lower() for w in line_words)
        lines.append(
            {
                "text": text,
                "avg_size": avg_size,
                "is_bold": is_bold,
                "top": min(w["top"] for w in line_words),
                "bottom": max(w["bottom"] for w in line_words),
            }
        )
    return lines


def _most_common_size(sizes: list[int]) -> float:
    if not sizes:
        return 10.0
    return float(Counter(sizes).most_common(1)[0][0])


def _is_heading_line(text: str, avg_size: float, is_bold: bool, body_size: float) -> bool:
    if not text or len(text) > _HEADING_MAX_CHARS:
        return False

    size_ratio = (avg_size / body_size) if body_size else 1.0
    word_count = len(text.split())
    numbered_heading = bool(re.match(r"^(\d+(\.\d+)*[.)]?|[A-Z]\.)\s+\S", text))
    caps_heading = text.isupper() and word_count <= _HEADING_MAX_WORDS
    trailing_punctuation = text.rstrip().endswith((".", ",", ";"))

    if size_ratio >= 1.15:
        return True
    if is_bold and size_ratio >= 0.98 and not trailing_punctuation and (numbered_heading or caps_heading or word_count <= 10):
        return True
    if numbered_heading and word_count <= _HEADING_MAX_WORDS:
        return True
    return False


def _heading_level(avg_size: float, body_size: float) -> int:
    ratio = (avg_size / body_size) if body_size else 1.0
    if ratio >= 1.5:
        return 1
    if ratio >= 1.25:
        return 2
    return 3


def _heading_path_str(heading_stack: dict[int, str]) -> str | None:
    if not heading_stack:
        return None
    return " > ".join(heading_stack[level] for level in sorted(heading_stack.keys()))


def _rows_to_markdown(rows: list[list[str | None]]) -> str:
    cleaned = [[("" if cell is None else str(cell).strip().replace("\n", " ")) for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if not cleaned:
        return ""

    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in body:
        padded = row + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(padded[: len(header)]) + " |")
    return "\n".join(lines)
