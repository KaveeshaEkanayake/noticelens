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
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

textract   = boto3.client("textract")
comprehend = boto3.client("comprehend")
translate  = boto3.client("translate")

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------
TEXTRACT_CONFIDENCE_THRESHOLD  = 80.0   # below this → low confidence word
COMPREHEND_CONFIDENCE_THRESHOLD = 0.85  # below this → needs verification

# 2 MB upload limit (enforced here as a second layer; API GW enforces at edge)
MAX_BYTES = 2 * 1024 * 1024

# ---------------------------------------------------------------------------
# CORS headers — returned on every response
# ---------------------------------------------------------------------------
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def respond(status: int, body: Any) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: dict, context: Any) -> dict:
    # Handle CORS preflight
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
        return respond(413, {"error": f"File too large. Maximum size is 2 MB."})

    # ── Step 1: Textract ──────────────────────────────────────────────────
    try:
        textract_resp = textract.detect_document_text(
            Document={"Bytes": image_bytes}
        )
    except textract.exceptions.UnsupportedDocumentException:
        return respond(422, {"error": "Unsupported document format. Please upload a PNG, JPEG, or single-page PDF."})
    except Exception as e:
        logger.error("Textract error: %s", e)
        return respond(502, {"error": f"Textract failed: {str(e)}"})

    blocks = textract_resp.get("Blocks", [])

    # Collect LINE blocks — each carries text, bounding box, and confidence
    lines: list[dict] = []
    full_text_parts: list[str] = []

    for block in blocks:
        if block["BlockType"] == "LINE":
            conf = block.get("Confidence", 0.0)
            geo  = block.get("Geometry", {}).get("BoundingBox", {})
            lines.append({
                "text":       block["Text"],
                "confidence": conf,
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
            "lines": [],
            "entities": [],
            "deadlines": [],
            "fees": [],
            "documents": [],
            "checklist": [],
            "summary": "No text could be extracted from this image.",
            "sinhala": None,
        })

    # ── Step 2: Comprehend entity detection ──────────────────────────────
    # Comprehend has a 5000 UTF-8 byte limit per call
    comprehend_input = full_text[:4900]
    try:
        comp_resp = comprehend.detect_entities(
            Text=comprehend_input,
            LanguageCode="en",
        )
        raw_entities = comp_resp.get("Entities", [])
    except Exception as e:
        logger.warning("Comprehend error (non-fatal): %s", e)
        raw_entities = []

    # Map entities back to the line they appear in (by text search)
    entities: list[dict] = []
    for ent in raw_entities:
        score      = ent.get("Score", 0.0)
        ent_text   = ent["Text"]
        ent_type   = ent["Type"]
        low_conf   = score < COMPREHEND_CONFIDENCE_THRESHOLD

        # Find the first line containing this entity text
        source_line = next(
            (ln for ln in lines if ent_text.lower() in ln["text"].lower()),
            None,
        )

        entities.append({
            "text":       ent_text,
            "type":       ent_type,
            "score":      round(score, 3),
            "low_confidence": low_conf,
            "source_line": source_line,
        })

    # ── Step 3: Our own extraction logic ─────────────────────────────────

    # Deadlines — DATE entities + deadline-context lines
    deadline_ctx_re = re.compile(
        r"\b(by|before|on or before|not later than|must.*by|deadline|expires|due date|submit.*by|renewal|arrears)\b",
        re.IGNORECASE,
    )
    deadlines: list[dict] = []
    for ent in entities:
        if ent["type"] == "DATE":
            src = ent.get("source_line")
            is_deadline_ctx = bool(deadline_ctx_re.search(src["text"])) if src else False
            deadlines.append({
                "value":       ent["text"],
                "source_line": src,
                "confidence":  "high" if (not ent["low_confidence"] and is_deadline_ctx) else
                               "med"  if not ent["low_confidence"] else "low",
            })

    # Fees — QUANTITY entities that look like currency amounts
    currency_re = re.compile(r"\b(LKR|Rs\.?|USD|EUR)\s*[\d,]+", re.IGNORECASE)
    fees: list[dict] = []
    for ln in lines:
        for m in currency_re.finditer(ln["text"]):
            fees.append({
                "value":       m.group(0),
                "source_line": ln,
                "confidence":  "low" if ln["low_ocr_confidence"] else "high",
            })

    # Required documents — keyword matching
    doc_re = re.compile(
        r"\b(national identity card|NIC|passport|birth certificate|title deed|survey plan|"
        r"marriage certificate|death certificate|medical certificate|fitness certificate|"
        r"application form|photographs?|receipts?|driving licence|permit|certificate|deed|"
        r"bank statement|proof of)\b",
        re.IGNORECASE,
    )
    documents: list[dict] = []
    seen_docs: set[str] = set()
    for ln in lines:
        for m in doc_re.finditer(ln["text"]):
            key = m.group(0).lower()
            if key not in seen_docs:
                seen_docs.add(key)
                documents.append({
                    "value":       m.group(0),
                    "source_line": ln,
                    "confidence":  "low" if ln["low_ocr_confidence"] else "high",
                })

    # Action checklist — lines with imperative verbs
    action_re = re.compile(
        r"\b(must|required to|shall|should|need to|have to|are to|submit|present|"
        r"appear|attend|pay|renew|register|provide|bring|carry|complete|contact)\b",
        re.IGNORECASE,
    )
    checklist: list[dict] = []
    for ln in lines:
        if action_re.search(ln["text"]) and len(ln["text"].split()) > 4:
            checklist.append({
                "value":       ln["text"][:160],
                "source_line": ln,
                "confidence":  "low" if ln["low_ocr_confidence"] else
                               "med" if len(ln["text"].split()) < 8 else "high",
            })

    # Simple summary: first non-header line with enough words
    header_re = re.compile(r"^(ref|date|circular|notice|ministry|department|no\.|issued)", re.IGNORECASE)
    summary = "No summary could be extracted."
    for ln in lines:
        words = ln["text"].split()
        if len(words) >= 8 and not header_re.match(ln["text"]):
            summary = ln["text"]
            break

    # ── Step 4: Optional Translate to Sinhala ────────────────────────────
    sinhala_summary: str | None = None
    if translate_to_sinhala and summary != "No summary could be extracted.":
        try:
            tr_resp = translate.translate_text(
                Text=summary[:500],
                SourceLanguageCode="en",
                TargetLanguageCode="si",
            )
            sinhala_summary = tr_resp["TranslatedText"]
        except Exception as e:
            logger.warning("Translate error (non-fatal): %s", e)

    # ── Build response ────────────────────────────────────────────────────
    return respond(200, {
        "lines":     lines,
        "entities":  entities,
        "deadlines": deadlines,
        "fees":      fees,
        "documents": documents,
        "checklist": checklist[:10],
        "summary":   summary,
        "sinhala":   sinhala_summary,
    })
