"""
mongolian_law_chunker.py
========================
Splits Mongolian legal documents into clause / subclause chunks
and extracts file-level metadata.

Adds:
1. Recursive crawl of markdown files
2. Act name extraction
3. Entity type (first non-empty line)
4. Date (second non-empty line)
5. Ordinal from "ДУГААР ..." if present
6. Location after ordinal, or after date if no ordinal
7. Act category from parent directory
8. lawId from filename (e.g. 10429.md -> 10429)
9. link = https://legalinfo.mn/mn/detail?lawId=...
10. Issuer from trailing signature block, names separated by comma
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


# ─────────────────────────────────────────────────────────────────────────────
# Compiled regex patterns
# ─────────────────────────────────────────────────────────────────────────────

_RE_CHAPTER = re.compile(
    r'^(?:[А-ЯӨҮЁ]+ДУГААР|[А-ЯӨҮЁ]+ДҮГЭЭР|\d+\s*ДУГААР|\d+\s*ДҮГЭЭР)\s+БҮЛЭГ\b',
    re.MULTILINE,
)

_RE_ARTICLE = re.compile(
    r'^(?:(?:\d+[#_\w]*\s*|[А-ЯӨҮЁ]+)(?:ДУГААР|ДҮГЭЭР)\s+ЗҮЙЛ[\.\s])',
    re.MULTILINE,
)

_RE_CLAUSE_TOP = re.compile(
    r'^(\d{1,3})\.\s*(?!\d)(?=[А-ЯӨҮЁA-Z\"\'])',
    re.MULTILINE,
)

_RE_SUBCLAUSE = re.compile(
    r'^(\d{1,3}\.\d{1,3}(?:\.\d{1,3}(?:\.\d{1,3})?)?)\.\s*(?=[А-ЯӨҮЁA-Z\"\'])',
    re.MULTILINE,
)

_RE_NAMED_SECTION = re.compile(
    r'^(НЭГ|ХОЁР|ГУРАВ|ДӨРӨВ|ТАВ|ЗУРГАА|ДОЛОО|НАЙМ|ЕС|АРАВ)\.',
    re.MULTILINE,
)

_RE_SLASH_ITEM = re.compile(
    r'^(\d{1,2})/\s*(?=[А-ЯӨҮЁA-Z])',
    re.MULTILINE,
)

_RE_ORDINAL = re.compile(r'ДУГААР\s*[:\-]?\s*(.+)$')

_RE_DATE = re.compile(
    r'(?P<year>\d{4})\s*ОНЫ\s*'
    r'(?P<month>\d{1,2})\s*(?:ДУГААР|ДҮГЭЭР)?\s*САРЫН\s*'
    r'(?P<day>\d{1,2})(?:-НЫ|-НИЙ|-Н)?\s*ӨДӨР'
)

_RE_LOCATION = re.compile(
    r'(ХОТ|АЙМАГ|СУМ|ДҮҮРЭГ)$'
)

# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _split_by_pattern(pattern: re.Pattern, text: str) -> list[tuple[str | None, str]]:
    """
    Split *text* at every match of *pattern*.
    Returns (header_text | None, segment_text) tuples.
    """
    parts: list[tuple[str | None, str]] = []
    matches = list(pattern.finditer(text))
    if not matches:
        return [(None, text)]
    if matches[0].start() > 0:
        parts.append((None, text[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts.append((m.group(0).strip(), text[m.start():end]))
    return parts


def _iter_nonempty_lines(text: str) -> list[tuple[int, str]]:
    lines = []
    for idx, line in enumerate(text.splitlines()):
        s = line.strip()
        if s:
            lines.append((idx, s))
    return lines


def _first_nonempty_line(text: str) -> str:
    for _, line in _iter_nonempty_lines(text):
        return line
    return ""


def _extract_law_id(source_file: str) -> int | None:
    stem = Path(source_file).stem
    m = re.match(r"^(\d+)", stem)
    return int(m.group(1)) if m else None


def _normalize_spaces(s: str) -> str:
    return " ".join(s.split()).strip()


def _is_structure_line(line: str) -> bool:
    s = line.strip()
    return any(
        pattern.match(s)
        for pattern in (_RE_CHAPTER, _RE_ARTICLE, _RE_NAMED_SECTION, _RE_CLAUSE_TOP, _RE_SUBCLAUSE)
    )


def _looks_like_signature_line(line: str) -> bool:
    """
    Heuristic for signature / issuer lines at the end of the document.
    Examples:
      ДАРГА Н.ЧИНБАТ
      ГИШҮҮН Б.БАТБАЯР
      Д.ЭНХБАЯР
    """
    s = _normalize_spaces(line)
    if not s:
        return False

    # Common role words in signatures
    role_words = (
        "ДАРГА", "ОРЛОГЧ", "ГИШҮҮН", "САЙД", "ЗАХИРАЛ",
        "ЕРӨНХИЙ", "НАРИЙН", "ХЭЛТСИЙН", "ТЭРГҮҮН", "ДЭД"
    )
    if any(word in s for word in role_words):
        return True

    # Initial + surname / initials + surname
    if re.fullmatch(r"(?:[А-ЯӨҮЁ]\.){1,3}[А-ЯӨҮЁ][А-ЯӨҮЁA-Z\-]*", s):
        return True
    if re.fullmatch(r"[А-ЯӨҮЁ]\.[А-ЯӨҮЁ][А-ЯӨҮЁA-Z\-]*", s):
        return True

    # All-caps-ish single line with letters, spaces, dots
    if re.fullmatch(r"[А-ЯӨҮЁA-Z\.\-\s]{3,60}", s) and any(ch.isalpha() for ch in s):
        return True

    return False

def _is_role_line(line: str) -> bool:
    role_words = (
        "ДАРГА", "ОРЛОГЧ", "ГИШҮҮН", "САЙД", "ЗАХИРАЛ",
        "ЕРӨНХИЙ", "НАРИЙН", "ХЭЛТСИЙН", "ТЭРГҮҮН", "ДЭД"
    )
    s = line.strip()
    return any(word in s for word in role_words)


def _is_name_line(line: str) -> bool:
    s = line.strip()

    # Matches: Н.ЧИНБАТ, Б.БАТБАЯР etc.
    if re.fullmatch(r"(?:[А-ЯӨҮЁ]\.){1,3}[А-ЯӨҮЁ][А-ЯӨҮЁ\-]+", s):
        return True

    # Matches: full uppercase names
    if re.fullmatch(r"[А-ЯӨҮЁ]+\s?[А-ЯӨҮЁ\-]+", s):
        return True

    return False


def _split_names(line: str) -> list[str]:
    """
    Split a signature line into one or more issuer names.
    Keeps the line text, but separates multiple names if commas/semicolons exist.
    """
    parts = re.split(r"[;,]", line)
    cleaned = [_normalize_spaces(p) for p in parts if _normalize_spaces(p)]
    return cleaned

def _extract_signature_block(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines:
        return text, ""

    i = len(lines) - 1

    # Skip trailing empty lines
    while i >= 0 and not lines[i].strip():
        i -= 1

    if i < 0:
        return "", ""

    sig_lines = []
    found_role = False

    while i >= 0:
        s = lines[i].strip()

        if not s:
            if sig_lines:
                i -= 1
                continue
            break

        if _is_role_line(s):
            sig_lines.append(s)
            found_role = True
            i -= 1
            continue

        # Only allow name lines if we already found a role
        if found_role and _is_name_line(s):
            sig_lines.append(s)
            i -= 1
            continue

        break

    if not sig_lines:
        return text.rstrip(), ""

    # reverse back
    sig_lines.reverse()

    issuer_parts = []
    for line in sig_lines:
        issuer_parts.extend(_split_names(line))

    issuer = ", ".join(dict.fromkeys(issuer_parts))

    body = "\n".join(lines[: i + 1]).rstrip()

    return body, issuer

def _extract_metadata(text: str, source_file: str) -> tuple[dict, str]:
    """
    Extract file-level metadata and return:
      (metadata_dict, body_text_without_signature_block)

    Metadata keys:
      source, entity_type, date, ordinal, location, act_name,
      act_category, lawId, link, issuer, source_file
    """
    body_text, issuer = _extract_signature_block(text)
    lines = body_text.splitlines()

    nonempty = [(i, line.strip()) for i, line in enumerate(lines) if line.strip()]

    entity_type = nonempty[0][1] if len(nonempty) >= 1 else ""

    date = ""
    date_idx = None

    for i, line in nonempty:
        m = _RE_DATE.search(line)
        if m:
            y = int(m.group("year"))
            mth = int(m.group("month"))
            d = int(m.group("day"))

            # normalize → YYYY-MM-DD
            date = f"{y:04d}-{mth:02d}-{d:02d}"
            date_idx = i
            break
    ordinal = ""
    ordinal_idx = None
    location = ""
    location_idx = None

    # Find "ДУГААР ..." after the second non-empty line
    for i, line in nonempty[2:]:
        if "ДУГААР" in line:
            ordinal_idx = i
            m = _RE_ORDINAL.search(line)
            if m:
                ordinal = _normalize_spaces(m.group(1))
            else:
                # fallback: take whatever follows the word DUGAAR
                tail = line.split("ДУГААР", 1)[-1].strip(" .:-\t")
                ordinal = _normalize_spaces(tail)
            break

    location = ""
    location_idx = None

    def is_location(line: str) -> bool:
        return bool(_RE_LOCATION.search(line.strip()))

    # Try after ordinal first
    if ordinal_idx is not None:
        for i, line in nonempty:
            if i > ordinal_idx:
                if is_location(line):
                    location = line
                    location_idx = i
                break

    # Otherwise try after date
    if not location and date_idx is not None:
        for i, line in nonempty:
            if i > date_idx:
                if is_location(line):
                    location = line
                    location_idx = i
                break
    # Act name = text between the metadata header and the first structure line
    # We limit this to a few lines so it doesn't accidentally swallow content.
    header_end = location_idx + 1 if location_idx is not None else (nonempty[2][0] + 1 if len(nonempty) >= 3 else len(lines))
    act_name_lines: list[str] = []

    scan_limit = min(len(lines), max(header_end + 5, header_end))
    for idx in range(header_end, scan_limit):
        s = lines[idx].strip()
        if not s:
            if act_name_lines:
                break
            continue
        if _is_structure_line(s) or _looks_like_signature_line(s):
            break
        act_name_lines.append(s)

    act_name = _normalize_spaces(" ".join(act_name_lines))

    # If we still don't have a name, use the first meaningful line after metadata
    if not act_name:
        for idx in range(header_end, len(lines)):
            s = lines[idx].strip()
            if s and not _is_structure_line(s) and not _looks_like_signature_line(s):
                act_name = s
                break

    source_title = act_name or entity_type or _first_nonempty_line(body_text)

    source_path = Path(source_file) if source_file else Path("doc.md")
    act_category = source_path.parent.name if source_file else ""
    law_id = _extract_law_id(source_file) if source_file else None
    link = f"https://legalinfo.mn/mn/detail?lawId={law_id}" if law_id is not None else ""

    metadata = {
        "source": source_title,
        "entity_type": entity_type,
        "date": date,
        "ordinal": ordinal,
        "location": location,
        "act_name": act_name,
        "act_category": act_category,
        "lawId": law_id,
        "link": link,
    }

    return metadata, body_text


def _make_chunk(
    chunk_id: str,
    text_content: str,
    chunk_type: str,
    context_path: str,
    metadata: dict,
) -> dict | None:
    content = text_content.strip()
    if not content or len(content) < 10:
        return None

    return {
        "chunk_id": chunk_id,
        **metadata,
        "type": chunk_type,
        "context_path": context_path,
        "content": content,
        "char_count": len(content),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chunker
# ─────────────────────────────────────────────────────────────────────────────

def chunk_mongolian_law(text: str, source_file: str = "") -> list[dict]:
    """
    Parse a Mongolian legal document and return a list of chunk dicts.
    Each chunk includes the extracted file-level metadata.
    """
    metadata, body_text = _extract_metadata(text, source_file)

    stem = Path(source_file).stem if source_file else "doc"
    chunks: list[dict] = []
    counter = [0]

    def _next_id() -> str:
        counter[0] += 1
        return f"{stem}_{counter[0]:04d}"

    def emit(text_content: str, chunk_type: str, context_path: str) -> None:
        c = _make_chunk(_next_id(), text_content, chunk_type, context_path, metadata)
        if c:
            chunks.append(c)

    # Detect document structure
    has_articles = bool(_RE_ARTICLE.search(body_text))
    has_named_sections = bool(_RE_NAMED_SECTION.search(body_text))
    has_chapters = bool(_RE_CHAPTER.search(body_text))

    # STRATEGY 1 – Laws with ЗҮЙЛ (articles)
    if has_articles:
        chapter_parts = _split_by_pattern(_RE_CHAPTER, body_text) if has_chapters else [(None, body_text)]

        for ch_header, ch_text in chapter_parts:
            chapter_ctx = ch_header or ""

            article_parts = _split_by_pattern(_RE_ARTICLE, ch_text)

            for art_header, art_text in article_parts:
                if art_header is None and len(art_text.strip()) < 50:
                    continue

                article_ctx = f"{chapter_ctx} > {art_header}".strip(" >") if art_header else chapter_ctx
                subclause_parts = _split_by_pattern(_RE_SUBCLAUSE, art_text)

                if len(subclause_parts) > 1:
                    first = subclause_parts[0]
                    if first[0] is None and len(first[1].strip()) > 30:
                        emit(first[1], "article_preamble", article_ctx)

                    for sc_header, sc_text in subclause_parts:
                        if sc_header is None:
                            continue
                        emit(sc_text, "subclause", f"{article_ctx} > {sc_header}")
                else:
                    emit(art_text, "article", article_ctx)

    # STRATEGY 2 – Court interpretations with named sections
    elif has_named_sections:
        section_parts = _split_by_pattern(_RE_NAMED_SECTION, body_text)

        for sec_header, sec_text in section_parts:
            if sec_header is None:
                emit(sec_text, "preamble", metadata["source"])
                continue

            sec_ctx = f"{metadata['source']} > {sec_header}"
            subclause_parts = _split_by_pattern(_RE_SUBCLAUSE, sec_text)

            if len(subclause_parts) > 1:
                for sc_header, sc_text in subclause_parts:
                    if sc_header is None:
                        emit(sc_text, "section_preamble", sec_ctx)
                    else:
                        emit(sc_text, "subclause", f"{sec_ctx} > {sc_header}")
            else:
                emit(sec_text, "section", sec_ctx)

    # STRATEGY 3 – Resolutions / orders with top-level numbered clauses
    else:
        clause_parts = _split_by_pattern(_RE_CLAUSE_TOP, body_text)

        if len(clause_parts) <= 1:
            emit(body_text, "document", metadata["source"])
        else:
            if clause_parts[0][0] is None:
                emit(clause_parts[0][1], "preamble", metadata["source"])

            for cl_header, cl_text in clause_parts:
                if cl_header is None:
                    continue

                cl_ctx = f"{metadata['source']} > Заалт {cl_header}"
                slash_parts = _split_by_pattern(_RE_SLASH_ITEM, cl_text)

                if len(slash_parts) > 1:
                    if slash_parts[0][0] is None and len(slash_parts[0][1].strip()) > 20:
                        emit(slash_parts[0][1], "clause", cl_ctx)

                    for si_header, si_text in slash_parts:
                        if si_header is None:
                            continue
                        emit(si_text, "subitem", f"{cl_ctx} > {si_header}/")
                else:
                    emit(cl_text, "clause", cl_ctx)

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Recursive file processing
# ─────────────────────────────────────────────────────────────────────────────

def iter_markdown_files(root_dir: str | Path) -> Iterable[Path]:
    root = Path(root_dir)
    yield from sorted(p for p in root.rglob("*.md") if p.is_file())


def chunk_markdown_tree(root_dir: str | Path) -> list[dict]:
    """
    Recursively process every .md file under root_dir and return all chunks.
    """
    all_chunks: list[dict] = []
    for file_path in iter_markdown_files(root_dir):
        text = file_path.read_text(encoding="utf-8")
        all_chunks.extend(chunk_mongolian_law(text, source_file=str(file_path)))
    return all_chunks


# ─────────────────────────────────────────────────────────────────────────────
# CLI helper
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python mongolian_law_chunker.py <root_dir_or_file.md> [output.jsonl]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None

    if input_path.is_dir():
        chunks = chunk_markdown_tree(input_path)
        print(f"→ {len(chunks)} chunks extracted from directory '{input_path}'", file=sys.stderr)
    else:
        text = input_path.read_text(encoding="utf-8")
        chunks = chunk_mongolian_law(text, source_file=str(input_path))
        print(f"→ {len(chunks)} chunks extracted from '{input_path.name}'", file=sys.stderr)

    if output_path:
        with output_path.open("w", encoding="utf-8") as f:
            for ch in chunks:
                f.write(json.dumps(ch, ensure_ascii=False) + "\n")
        print(f"→ Written to '{output_path}'", file=sys.stderr)
    else:
        print(json.dumps(chunks, ensure_ascii=False, indent=2))
