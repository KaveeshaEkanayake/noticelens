"""
NoticeLens — Lambda handler
Pipeline: Textract detect-document-text → Comprehend detect-entities → our logic → optional Translate

SWAP POINT (future): replace individual service calls with Bedrock when quotas are available.
"""
import json
import base64
import boto3
import logging
import re
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

textract   = boto3.client("textract")
comprehend = boto3.client("comprehend")
translate  = boto3.client("translate")

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------
TEXTRACT_CONFIDENCE_THRESHOLD  = 80.0
COMPREHEND_CONFIDENCE_THRESHOLD = 0.85

MAX_BYTES = 2 * 1024 * 1024   # 2 MB

# Lines whose Top bounding-box value is below this are letterhead / header —
# skip them for summary and deadline extraction.
HEADER_ZONE_THRESHOLD = 0.15   # top 15% of page height

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}

# ---------------------------------------------------------------------------
# Compiled regexes (module-level for warm Lambda reuse)
# ---------------------------------------------------------------------------

# Date formats encountered in Sri Lankan government documents
# e.g. "03.02.2017", "30 October 2026", "2026-10-30", "30/10/2026", "30th October 2026"
_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{4}"                              # 03.02.2017 / 30/10/2026
    r"|\d{4}[./\-]\d{2}[./\-]\d{2}"                                  # 2026-10-30
    r"|\d{1,2}(?:st|nd|rd|th)?\s+"                                   # 30th October 2026
      r"(?:January|February|March|April|May|June|July|August|"
      r"September|October|November|December)\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

# Context signals that mark a date as a CITATION (not a deadline)
_CITATION_CTX_RE = re.compile(
    r"\b(dated|gazette|act\s+no|order\s+no|no\.\s*\d+\s+of\s+\d{4}|"
    r"issued\s+on|circular|notification|published|established|enacted|"
    r"constituted|promulgated|vide|pursuant\s+to|under\s+the|hereinafter)\b",
    re.IGNORECASE,
)

# Context signals that mark a date as a DEADLINE
_DEADLINE_CTX_RE = re.compile(
    r"\b(by|before|on\s+or\s+before|not\s+later\s+than|no\s+later\s+than|"
    r"must\s+be\s+submitted|must\s+be\s+received|deadline|due\s+date|"
    r"expires?|expiry|within\s+\d+|submit\s+by|file\s+by|respond\s+by|"
    r"appeal\s+within|pay\s+by|renew\s+by)\b",
    re.IGNORECASE,
)

# Relative deadline phrases: "within 14 days", "within one month", etc.
_RELATIVE_DEADLINE_RE = re.compile(
    r"\bwithin\s+"
    r"(?P<qty>one|two|three|four|five|six|seven|eight|nine|ten|"
    r"fourteen|fifteen|thirty|sixty|ninety|\d{1,3})"
    r"\s+(?P<unit>days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)

# Header / letterhead line patterns (for summary skip)
_HEADER_LINE_RE = re.compile(
    r"^("
    r"ref(?:erence)?[\s:./]|"
    r"date[\s:./]|"
    r"circular|"
    r"no\.\s*\d|"
    r"ministry|department|commission|authority|board|"
    r"p\.?\s*o\.?\s*box|"
    r"tel(?:ephone)?[\s:./]|fax[\s:./]|email[\s:./]|"
    r"(?:sir|madam|dear\s)|"                       # salutation
    r"\(constituted|"                              # parenthetical sub-title
    r"[A-Z0-9/\-]{6,}\s*$"                        # pure reference codes
    r")",
    re.IGNORECASE,
)

# Subject line markers
_SUBJECT_RE = re.compile(
    r"^(re\s*:|subject\s*:|sub\s*:|\bsub\b\s*[-–—])",
    re.IGNORECASE,
)

# Address / date / ref noise lines (short, often at top)
_ADDRESS_RE = re.compile(
    r"^(\d{1,4}[,.]?\s+[A-Z]|p\.?\s*o\.?\s*box|no\.\s*\d)",
    re.IGNORECASE,
)

# Currency amounts
_CURRENCY_RE = re.compile(
    r"\b(LKR|Rs\.?|USD|EUR)\s*[\d,]+(?:\.\d{1,2})?\b",
    re.IGNORECASE,
)

# Required documents — keyword anchors. The regex captures a leading keyword;
# we then extend rightward to pick up the full noun phrase (up to ~5 words).
# Grouping happens per source line — one entry per line maximum.
_DOC_KEYWORD_RE = re.compile(
    r"\b(national\s+identity\s+card|NIC\b|passport|birth\s+certificate|"
    r"title\s+deed|survey\s+plan|marriage\s+certificate|death\s+certificate|"
    r"medical\s+certificate|fitness\s+certificate|application\s+form|"
    r"photographs?|receipts?|driving\s+licen[cs]e?|permit|"
    r"bank\s+statement|proof\s+of(?:\s+\w+){0,3}|statutory\s+declaration|affidavit)\b",
    re.IGNORECASE,
)

# Action checklist verbs
_ACTION_RE = re.compile(
    r"\b(must|required\s+to|shall|should|need\s+to|have\s+to|are\s+to|"
    r"submit|present|appear|attend|pay|renew|register|provide|bring|"
    r"carry|complete|contact|appeal|apply|furnish)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "fourteen": 14, "fifteen": 15, "thirty": 30,
    "sixty": 60, "ninety": 90,
}


def _parse_date(text: str) -> date | None:
    """Try to parse a date string into a date object. Returns None on failure."""
    text = text.strip()

    # dd.mm.yyyy / dd/mm/yyyy / dd-mm-yyyy
    m = re.match(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})$", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # yyyy-mm-dd
    m = re.match(r"^(\d{4})[./\-](\d{2})[./\-](\d{2})$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # "30 October 2026" / "30th October 2026"
    m = re.match(
        r"^(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{4})$",
        text, re.IGNORECASE,
    )
    if m:
        try:
            return date(int(m.group(3)), _MONTH_MAP[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            pass

    return None


def _relative_to_days(qty_str: str, unit_str: str) -> int | None:
    """Convert a relative duration to days. Returns None if unrecognised."""
    qty_str = qty_str.lower()
    qty = _WORD_NUM.get(qty_str) or (int(qty_str) if qty_str.isdigit() else None)
    if qty is None:
        return None
    unit = unit_str.lower().rstrip("s")
    if unit == "day":
        return qty
    if unit == "week":
        return qty * 7
    if unit == "month":
        return qty * 30   # approximate
    if unit == "year":
        return qty * 365
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def respond(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _word_truncate(text: str, max_chars: int = 160) -> str:
    """Truncate text to at most max_chars, always on a word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")
    return truncated + "…"


def _is_header_zone(ln: dict) -> bool:
    """True if the line sits in the top 15% of the page (letterhead zone)."""
    return ln["bbox"]["top"] < HEADER_ZONE_THRESHOLD


def _classify_date(
    date_text: str,
    source_line: dict | None,
    doc_date: date | None,
    today: date,
) -> str:
    """
    Returns: "deadline" | "citation" | "doc_date" | "uncertain"

    Priority:
      1. If it looks like a citation context → citation
      2. If it looks like a deadline context → deadline (only future dates)
      3. If it's in the header zone → doc_date
      4. If it's in the past → citation
      5. Otherwise → uncertain
    """
    ctx_text = source_line["text"] if source_line else ""

    if _CITATION_CTX_RE.search(ctx_text):
        return "citation"

    parsed = _parse_date(date_text)

    if _DEADLINE_CTX_RE.search(ctx_text):
        if parsed and parsed < today:
            return "citation"   # deadline context but date is past → likely a cited deadline
        return "deadline"

    # No strong context signal
    if source_line and _is_header_zone(source_line):
        return "doc_date"

    if parsed:
        return "citation" if parsed < today else "uncertain"

    return "uncertain"


def _extract_doc_date(lines: list[dict], today: date) -> date | None:
    """
    Try to find the document date — the date in the header/reference block.
    We look at lines in the top 25% of the page for a parseable date.
    """
    for ln in lines:
        if ln["bbox"]["top"] > 0.25:
            break
        for m in _DATE_RE.finditer(ln["text"]):
            d = _parse_date(m.group(0))
            if d and d <= today:
                return d
    return None


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handler(event: dict, context: Any) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return respond(200, {})

    # ── Parse request body ────────────────────────────────────────────────
    try:
        raw_body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body)
            body = json.loads(raw_body)
        else:
            body = json.loads(raw_body)
    except Exception as e:
        return respond(400, {"error": f"Invalid request body: {e}"})

    image_b64: str = body.get("image", "")
    translate_to_sinhala: bool = body.get("translate", False)

    if not image_b64:
        return respond(400, {"error": "Missing 'image' field (base64-encoded PNG/JPEG/PDF)"})

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        return respond(400, {"error": "Field 'image' is not valid base64"})

    if len(image_bytes) > MAX_BYTES:
        return respond(413, {"error": "File too large. Maximum size is 2 MB."})

    # ── Step 1: Textract ──────────────────────────────────────────────────
    try:
        textract_resp = textract.detect_document_text(Document={"Bytes": image_bytes})
    except Exception as e:
        logger.error("Textract error: %s", e)
        err_str = str(e)
        if "UnsupportedDocument" in err_str:
            return respond(422, {"error": "Unsupported format. Upload PNG, JPEG, or single-page PDF."})
        return respond(502, {"error": f"Textract failed: {err_str}"})

    blocks = textract_resp.get("Blocks", [])
    lines: list[dict] = []
    full_text_parts: list[str] = []

    for block in blocks:
        if block["BlockType"] == "LINE":
            conf = block.get("Confidence", 0.0)
            geo  = block.get("Geometry", {}).get("BoundingBox", {})
            lines.append({
                "text":               block["Text"],
                "confidence":         conf,
                "bbox": {
                    "left":   geo.get("Left",   0),
                    "top":    geo.get("Top",    0),
                    "width":  geo.get("Width",  0),
                    "height": geo.get("Height", 0),
                },
                "low_ocr_confidence": conf < TEXTRACT_CONFIDENCE_THRESHOLD,
            })
            full_text_parts.append(block["Text"])

    full_text = "\n".join(full_text_parts)

    if not full_text.strip():
        return respond(200, {
            "lines": [], "entities": [], "deadlines": [], "fees": [],
            "documents": [], "checklist": [],
            "summary": "No text could be extracted from this image.",
            "sinhala": None,
        })

    # ── Step 2: Comprehend ────────────────────────────────────────────────
    comprehend_input = full_text[:4900]
    try:
        comp_resp = comprehend.detect_entities(Text=comprehend_input, LanguageCode="en")
        raw_entities = comp_resp.get("Entities", [])
    except Exception as e:
        logger.warning("Comprehend error (non-fatal): %s", e)
        raw_entities = []

    entities: list[dict] = []
    for ent in raw_entities:
        score    = ent.get("Score", 0.0)
        ent_text = ent["Text"]
        ent_type = ent["Type"]
        source_line = next(
            (ln for ln in lines if ent_text.lower() in ln["text"].lower()), None
        )
        entities.append({
            "text":            ent_text,
            "type":            ent_type,
            "score":           round(score, 3),
            "low_confidence":  score < COMPREHEND_CONFIDENCE_THRESHOLD,
            "source_line":     source_line,
        })

    # ── Step 3: Extraction logic ──────────────────────────────────────────
    today    = date.today()
    doc_date = _extract_doc_date(lines, today)

    # ── 3a: Summary ───────────────────────────────────────────────────────
    # Strategy:
    #   1. Prefer the line immediately after a subject heading (Re:/Subject:)
    #   2. Otherwise: first body line (top > 15%) with ≥60 chars that is not
    #      a header, address, date, or reference pattern.
    summary = "No summary could be extracted."
    body_lines = [ln for ln in lines if not _is_header_zone(ln)]

    # Pass 1: subject heading
    for i, ln in enumerate(body_lines):
        if _SUBJECT_RE.match(ln["text"]):
            # The subject content may be on the same line (after the marker)
            # or on the next line
            after_marker = re.sub(
                r"^(re\s*:|subject\s*:|sub\s*:|\bsub\b\s*[-–—])\s*",
                "", ln["text"], flags=re.IGNORECASE
            ).strip()
            if len(after_marker) >= 20:
                summary = after_marker
            elif i + 1 < len(body_lines):
                summary = body_lines[i + 1]["text"]
            break

    # Pass 2: first substantive body line
    if summary == "No summary could be extracted.":
        for ln in body_lines:
            t = ln["text"].strip()
            if (
                len(t) >= 60
                and not _HEADER_LINE_RE.match(t)
                and not _ADDRESS_RE.match(t)
                and not _DATE_RE.fullmatch(t)
                and not re.match(r"^[\d/\-. ]+$", t)   # pure numbers/dates
            ):
                summary = t
                break

    # ── 3b: Deadlines ─────────────────────────────────────────────────────
    deadlines: list[dict]     = []
    doc_dates_found: list[dict] = []
    uncertain_dates: list[dict] = []

    # Absolute dates from Comprehend DATE entities
    for ent in entities:
        if ent["type"] != "DATE":
            continue
        src = ent.get("source_line")
        # Skip academic-year patterns (e.g. "2026/27", "2025/26")
        if re.match(r"^\d{4}/\d{2}$", ent["text"].strip()):
            continue
        # Skip dates in the header zone (those become doc_dates via _extract_doc_date)
        if src and _is_header_zone(src):
            continue

        classification = _classify_date(ent["text"], src, doc_date, today)
        parsed = _parse_date(ent["text"])

        item = {
            "value":       ent["text"],
            "source_line": src,
            "confidence":  "low" if ent["low_confidence"] else "high",
            "inferred":    False,
        }

        if classification == "deadline":
            deadlines.append(item)
        elif classification == "doc_date":
            doc_dates_found.append(item)
        elif classification == "citation":
            pass   # silently drop citation dates
        else:
            # uncertain → needs verification
            item["confidence"] = "low"
            uncertain_dates.append(item)

    # Also scan raw text for dates not picked up by Comprehend
    # Build a set of (value, line_text) already captured to deduplicate
    captured = {
        (d["value"].lower(), d["source_line"]["text"] if d.get("source_line") else "")
        for d in deadlines + uncertain_dates
    }
    for ln in lines:
        if _is_header_zone(ln):
            continue
        for m in _DATE_RE.finditer(ln["text"]):
            date_text = m.group(0)
            # Skip academic-year patterns like "2026/27" or "2025/26"
            if re.match(r"^\d{4}/\d{2}$", date_text):
                continue
            # Skip if already captured from Comprehend for this line
            key = (date_text.lower(), ln["text"])
            if key in captured:
                continue
            classification = _classify_date(date_text, ln, doc_date, today)
            if classification == "deadline":
                deadlines.append({
                    "value":       date_text,
                    "source_line": ln,
                    "confidence":  "low" if ln["low_ocr_confidence"] else "med",
                    "inferred":    False,
                })
            elif classification == "uncertain":
                uncertain_dates.append({
                    "value":       date_text,
                    "source_line": ln,
                    "confidence":  "low",
                    "inferred":    False,
                })

    # Relative deadlines: "within 14 days", "within one month"
    for ln in lines:
        for m in _RELATIVE_DEADLINE_RE.finditer(ln["text"]):
            qty_str  = m.group("qty")
            unit_str = m.group("unit")
            days = _relative_to_days(qty_str, unit_str)
            phrase = m.group(0)

            computed_label: str | None = None
            if days is not None and doc_date:
                computed = doc_date + timedelta(days=days)
                computed_label = computed.strftime("%-d %B %Y") if hasattr(date, 'strftime') else str(computed)
                # strftime %-d is Linux; fall back gracefully on other platforms
                try:
                    computed_label = computed.strftime("%-d %B %Y")
                except ValueError:
                    computed_label = computed.strftime("%d %B %Y").lstrip("0")

            deadlines.append({
                "value":          phrase + (f" (approx. {computed_label})" if computed_label else ""),
                "source_line":    ln,
                "confidence":     "med",
                "inferred":       True,
                "inferred_note":  (
                    f"Computed from document date {doc_date.strftime('%d %B %Y')} + {days} days"
                    if (days is not None and doc_date) else
                    "Could not compute — document date not found"
                ),
            })

    # Deduplicate deadlines by (normalised value, source line text)
    seen_dl: set[tuple] = set()
    deduped_deadlines: list[dict] = []
    for d in deadlines:
        key = (d["value"].lower(), (d["source_line"]["text"] if d.get("source_line") else ""))
        if key not in seen_dl:
            seen_dl.add(key)
            deduped_deadlines.append(d)
    deadlines = deduped_deadlines

    # ── 3c: Fees ──────────────────────────────────────────────────────────
    fees: list[dict] = []
    seen_fees: set[str] = set()
    for ln in lines:
        for m in _CURRENCY_RE.finditer(ln["text"]):
            key = m.group(0).lower()
            if key not in seen_fees:
                seen_fees.add(key)
                fees.append({
                    "value":       m.group(0),
                    "source_line": ln,
                    "confidence":  "low" if ln["low_ocr_confidence"] else "high",
                })

    # ── 3d: Required documents ────────────────────────────────────────────
    # Group by source line: collect all keyword matches on a line, then emit
    # one document entry per line using the longest / most descriptive match
    # found on that line (avoids "NIC", "National Identity Card", "Passport"
    # appearing as three separate entries from the same line).
    documents: list[dict] = []
    seen_line_texts: set[str] = set()   # one entry per unique source line

    for ln in lines:
        matches = list(_DOC_KEYWORD_RE.finditer(ln["text"]))
        if not matches:
            continue
        line_key = ln["text"]
        if line_key in seen_line_texts:
            continue
        seen_line_texts.add(line_key)

        # Pick the longest match on this line as the representative label —
        # it tends to be the most descriptive (e.g. "National Identity Card"
        # beats "NIC"; "proof of address" beats "proof of").
        best = max(matches, key=lambda m: len(m.group(0)))
        value = best.group(0).strip()

        # Normalise: collapse internal whitespace
        value = re.sub(r"\s+", " ", value)

        documents.append({
            "value":       value,
            "source_line": ln,
            "confidence":  "low" if ln["low_ocr_confidence"] else "high",
        })

    # ── 3e: Action checklist ──────────────────────────────────────────────
    checklist: list[dict] = []
    for ln in lines:
        if _ACTION_RE.search(ln["text"]) and len(ln["text"].split()) > 4:
            checklist.append({
                "value":       _word_truncate(ln["text"], 160),
                "source_line": ln,
                "confidence":  "low" if ln["low_ocr_confidence"] else
                               "med" if len(ln["text"].split()) < 8 else "high",
            })

    sinhala_summary: str | None = None  # set inside translate block if enabled

    # ── Step 4: Batch translation to Sinhala ─────────────────────────────
    #
    # Strings to translate (translatable_values, indexed):
    #   [0]               summary
    #   [1..len(dl)]      deadline values
    #   [next..+fees]     fee source descriptions (NOT the amount itself —
    #                     amounts are numbers and must not change)
    #   [next..+docs]     document names
    #   [next..+check]    checklist values
    #
    # We join with a unique sentinel that Amazon Translate passes through
    # unchanged, then split on it to recover individual translations.
    #
    # We do NOT translate: dates, currency amounts, reference numbers, org
    # names, or source_line text (evidence must stay verbatim).
    #
    # Translate limit: 10,000 UTF-8 bytes per call. We keep one call by
    # capping each string and the overall batch.

    SENTINEL = " ||NL|| "  # unlikely to appear in natural text; Translate ignores it

    translations: dict[int, str] = {}   # index → translated string

    if translate_to_sinhala:
        # Build the ordered list of strings.
        #
        # WHAT GETS TRANSLATED:
        #   summary         → full sentence
        #   deadline values → the phrase (dates pass through Translate unchanged)
        #   fees            → NOT translated; amounts are kept as-is
        #   document names  → the label value (e.g. "National Identity Card")
        #   checklist items → the action sentence
        #
        # WHAT DOES NOT:
        #   fee values (currency amounts — never sent to Translate)
        #   source_line text (verbatim evidence — never touched)
        #   reference/account numbers (Translate preserves these naturally)

        to_translate: list[str] = []
        to_translate.append(summary[:400])                          # 0: summary
        dl_start  = len(to_translate)
        for d in deadlines:
            to_translate.append(_word_truncate(d["value"], 100))
        # fees: skip — amounts are opaque; no si field for fees
        doc_start = len(to_translate)
        for doc in documents:
            to_translate.append(_word_truncate(doc["value"], 80))
        chk_start = len(to_translate)
        for c in checklist[:10]:
            to_translate.append(_word_truncate(c["value"], 200))

        # Batch into ≤9 500-byte chunks (well under the 10 000-byte API limit)
        CHUNK_BYTES = 9000

        def _split_chunks(strings: list[str], sep: str, limit: int) -> list[str]:
            chunks, current, cur_size = [], [], 0
            for s in strings:
                seg = s + sep
                if cur_size + len(seg.encode()) > limit and current:
                    chunks.append(sep.join(current))
                    current, cur_size = [], 0
                current.append(s)
                cur_size += len(seg.encode())
            if current:
                chunks.append(sep.join(current))
            return chunks

        chunks = _split_chunks(to_translate, SENTINEL, CHUNK_BYTES)

        translated_flat: list[str] = []
        for chunk in chunks:
            try:
                tr_resp = translate.translate_text(
                    Text=chunk,
                    SourceLanguageCode="en",
                    TargetLanguageCode="si",
                )
                translated_flat.extend(tr_resp["TranslatedText"].split(SENTINEL))
            except Exception as e:
                logger.warning("Translate chunk error (non-fatal): %s", e)
                # Fall back: fill with empty strings so indices still align
                translated_flat.extend([""] * len(chunk.split(SENTINEL)))

        # Assign back by index
        for i, t in enumerate(translated_flat):
            if i < len(to_translate):
                translations[i] = t.strip()

        # Attach .si to each item
        sinhala_summary = translations.get(0) or None

        for i, d in enumerate(deadlines):
            si = translations.get(dl_start + i, "")
            if si:
                d["si"] = si

        # fees: no .si — amounts are kept exactly as extracted

        for i, doc in enumerate(documents):
            si = translations.get(doc_start + i, "")
            if si:
                doc["si"] = si

        for i, c in enumerate(checklist[:10]):
            si = translations.get(chk_start + i, "")
            if si:
                c["si"] = si

    # ── Build response ────────────────────────────────────────────────────    # Exclude from uncertain_dates anything already classified as a deadline,
    # and deduplicate by normalised value.
    deadline_values = {d["value"].lower() for d in deadlines}
    seen_uncertain: set[str] = set()
    filtered_uncertain: list[dict] = []
    for u in uncertain_dates:
        key = u["value"].lower()
        if key in deadline_values or key in seen_uncertain:
            continue
        seen_uncertain.add(key)
        filtered_uncertain.append(u)
    uncertain_dates = filtered_uncertain

    return respond(200, {
        "lines":           lines,
        "entities":        entities,
        "deadlines":       deadlines,
        "uncertain_dates": uncertain_dates,
        "fees":            fees,
        "documents":       documents,
        "checklist":       checklist[:10],
        "summary":         summary,
        "doc_date":        str(doc_date) if doc_date else None,
        "sinhala":         sinhala_summary,
    })
