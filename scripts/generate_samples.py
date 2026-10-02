"""
Generate three sample notice images for NoticeLens.
Each image is designed to produce good Textract + pipeline results.

Run from repo root:
    python scripts/generate_samples.py
Output: frontend/samples/sample-{1,2,3}.png
"""
from __future__ import annotations
import os, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Output directory ──────────────────────────────────────────────────────────
OUT_DIR = Path(__file__).parent.parent / "frontend" / "samples"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Layout constants ──────────────────────────────────────────────────────────
W, H       = 900, 1200
MARGIN_L   = 72
MARGIN_R   = W - 72
LINE_H_SM  = 20   # small body text
LINE_H_MD  = 24   # medium
LINE_H_LG  = 28   # heading

BG          = (252, 251, 248)    # off-white, aged paper feel
INK         = (18,  18,  18)
MUTED       = (90,  90,  90)
RULE_COL    = (180, 175, 165)
HEADER_BG   = (32,  58,  100)    # dark navy header band
HEADER_FG   = (255, 255, 255)


def load_fonts():
    """Try system fonts; fall back to PIL default."""
    candidates_regular = [
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/verdana.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    candidates_bold = [
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/verdanab.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    def first(paths, size):
        for p in paths:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        return ImageFont.load_default()

    return {
        "sm":   first(candidates_regular, 15),
        "body": first(candidates_regular, 17),
        "md":   first(candidates_regular, 19),
        "h2":   first(candidates_bold,    20),
        "h1":   first(candidates_bold,    24),
        "hdr":  first(candidates_bold,    22),
    }


def new_page():
    img = Image.new("RGB", (W, H), BG)
    # Subtle noise texture
    import random
    px = img.load()
    rng = random.Random(42)
    for y in range(H):
        for x in range(W):
            v = rng.randint(-3, 3)
            r, g, b = px[x, y]
            px[x, y] = (
                max(0, min(255, r + v)),
                max(0, min(255, g + v)),
                max(0, min(255, b + v)),
            )
    return img, ImageDraw.Draw(img)


def draw_header_band(draw, fonts, org_name: str, tagline: str):
    draw.rectangle([(0, 0), (W, 90)], fill=HEADER_BG)
    draw.text((MARGIN_L, 18), org_name,  font=fonts["hdr"], fill=HEADER_FG)
    draw.text((MARGIN_L, 52), tagline,   font=fonts["sm"],  fill=(200, 210, 230))


def draw_rule(draw, y: int):
    draw.line([(MARGIN_L, y), (MARGIN_R, y)], fill=RULE_COL, width=1)


def wrapped_lines(text: str, font, max_width: int, draw) -> list[str]:
    """Wrap text to fit max_width pixels."""
    words = text.split()
    lines_out, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            if current:
                lines_out.append(current)
            current = word
    if current:
        lines_out.append(current)
    return lines_out


def write_para(draw, fonts, y: int, text: str, font_key="body",
               color=INK, indent=0, line_spacing=6) -> int:
    """Write a paragraph, returning new y position."""
    font = fonts[font_key]
    max_w = MARGIN_R - MARGIN_L - indent
    for ln in wrapped_lines(text, font, max_w, draw):
        draw.text((MARGIN_L + indent, y), ln, font=font, fill=color)
        y += draw.textbbox((0, 0), ln, font=font)[3] + line_spacing
    return y + 2


def write_line(draw, fonts, y: int, text: str, font_key="body",
               color=INK, x=None, indent=0) -> int:
    font = fonts[font_key]
    draw.text(((x or MARGIN_L) + indent, y), text, font=font, fill=color)
    return y + draw.textbbox((0, 0), text, font=font)[3] + 4


# ─────────────────────────────────────────────────────────────────────────────
# Sample 1 — Bank letter requiring documents by a future date with a fee
# ─────────────────────────────────────────────────────────────────────────────
def sample_1(fonts):
    img, draw = new_page()
    draw_header_band(draw, fonts,
        "NATIONAL SAVINGS BANK",
        "Head Office · No. 255, Galle Road, Colombo 03")

    y = 110
    # Reference block
    y = write_line(draw, fonts, y, "Ref: NSB/KYC/2026/4471",       "sm", MUTED)
    y = write_line(draw, fonts, y, "Date: 20 September 2026",       "sm", MUTED)
    y += 10
    draw_rule(draw, y); y += 14

    # Addressee
    y = write_line(draw, fonts, y, "Mr. A. Perera",                 "body")
    y = write_line(draw, fonts, y, "45/B, Temple Road, Nugegoda",   "body")
    y = write_line(draw, fonts, y, "Sri Lanka",                     "body")
    y += 12

    # Subject
    y = write_line(draw, fonts, y, "Sub: Mandatory KYC Document Submission — Account No. 7842-001193", "h2")
    y += 8
    draw_rule(draw, y); y += 14

    # Salutation
    y = write_line(draw, fonts, y, "Dear Mr. Perera,", "body")
    y += 8

    # Body paragraphs
    y = write_para(draw, fonts, y,
        "As part of our compliance with the Financial Intelligence Unit (FIU) directives "
        "and the Bank of Ceylon Act, all account holders are required to update their "
        "Know Your Customer (KYC) records by 15 November 2026.",
    )
    y += 4
    y = write_para(draw, fonts, y,
        "Failure to submit the required documents by the above date will result in "
        "a temporary restriction on your account until compliance is achieved. "
        "A processing fee of LKR 500 is applicable for late submissions received "
        "after 15 November 2026."
    )
    y += 8

    # Documents required
    y = write_line(draw, fonts, y, "Documents Required:", "h2")
    y += 4
    for doc in [
        "1. Original National Identity Card (NIC) or valid Passport",
        "2. Proof of address (utility bill not older than 3 months)",
        "3. Latest bank statement from any other bank (if applicable)",
        "4. One recent passport-size photograph",
        "5. Completed KYC Application Form (available at any branch)",
    ]:
        y = write_line(draw, fonts, y, doc, "body", indent=16)
    y += 8

    y = write_para(draw, fonts, y,
        "You must visit any National Savings Bank branch in person with the originals "
        "and submit certified copies. Postal submissions will not be accepted."
    )
    y += 4
    y = write_para(draw, fonts, y,
        "Please contact our Customer Services Centre on 0112 039 300 or visit "
        "www.nsb.lk for further information."
    )
    y += 16

    # Signature block
    draw_rule(draw, y); y += 12
    y = write_line(draw, fonts, y, "Yours faithfully,",       "body")
    y += 32
    draw_rule(draw, y); y += 6
    y = write_line(draw, fonts, y, "D. S. Wickramasinghe",   "h2")
    y = write_line(draw, fonts, y, "Deputy General Manager — Retail Banking", "sm", MUTED)
    y = write_line(draw, fonts, y, "National Savings Bank",  "sm", MUTED)

    # Footer rule
    draw_rule(draw, H - 40)
    draw.text((MARGIN_L, H - 30),
        "National Savings Bank · Incorporated under the National Savings Bank Act No. 30 of 1971",
        font=fonts["sm"], fill=MUTED)

    img.save(OUT_DIR / "sample-1.png", "PNG", dpi=(150, 150))
    print("Saved sample-1.png")


# ─────────────────────────────────────────────────────────────────────────────
# Sample 2 — University notice: deadline + required documents
# ─────────────────────────────────────────────────────────────────────────────
def sample_2(fonts):
    img, draw = new_page()
    draw_header_band(draw, fonts,
        "UNIVERSITY OF KELANIYA",
        "Faculty of Science · Department of Computer Science")

    y = 110
    y = write_line(draw, fonts, y, "Circular No: UOK/FoS/CS/2026/17",  "sm", MUTED)
    y = write_line(draw, fonts, y, "Date: 01 October 2026",             "sm", MUTED)
    y += 10
    draw_rule(draw, y); y += 14

    y = write_line(draw, fonts, y, "TO ALL FINAL YEAR UNDERGRADUATE STUDENTS", "h2")
    y += 10

    y = write_line(draw, fonts, y,
        "Sub: Submission of Research Project Registration Forms — Academic Year 2026/27",
        "h2")
    y += 8
    draw_rule(draw, y); y += 14

    y = write_para(draw, fonts, y,
        "All final year undergraduate students registered for the BSc Computer Science "
        "degree programme are hereby notified that the deadline for submission of "
        "Research Project Registration Forms for the academic year 2026/27 is "
        "31 October 2026."
    )
    y += 4
    y = write_para(draw, fonts, y,
        "Students must submit the completed registration forms along with the following "
        "supporting documents to the Department Office on or before the above date. "
        "Submissions received after 31 October 2026 will not be accepted under any "
        "circumstances."
    )
    y += 8

    y = write_line(draw, fonts, y, "Required Documents:", "h2")
    y += 4
    for doc in [
        "1. Completed Research Project Registration Form (Form CS-RP-01)",
        "2. Proposed research title and a 300-word abstract",
        "3. Letter of acceptance from the proposed supervisor (on official letterhead)",
        "4. Copy of student identity card",
        "5. Academic transcript for Years 1 to 3",
        "6. Two passport-size photographs",
    ]:
        y = write_line(draw, fonts, y, doc, "body", indent=16)
    y += 8

    y = write_para(draw, fonts, y,
        "Students are required to present original documents for verification at the "
        "time of submission. Incomplete submissions will be returned without processing."
    )
    y += 4
    y = write_para(draw, fonts, y,
        "The registration fee of LKR 1,200 must be paid at the Finance Division "
        "and the receipt attached to the submission."
    )
    y += 16

    draw_rule(draw, y); y += 12
    y = write_line(draw, fonts, y, "By Order of the Head of Department,",    "body")
    y += 32
    draw_rule(draw, y); y += 6
    y = write_line(draw, fonts, y, "Prof. K. M. Dissanayake",                "h2")
    y = write_line(draw, fonts, y, "Head, Department of Computer Science",   "sm", MUTED)
    y = write_line(draw, fonts, y, "University of Kelaniya",                 "sm", MUTED)

    draw_rule(draw, H - 40)
    draw.text((MARGIN_L, H - 30),
        "University of Kelaniya, Dalugama, Kelaniya 11600, Sri Lanka  ·  Tel: +94 11 291 4476",
        font=fonts["sm"], fill=MUTED)

    img.save(OUT_DIR / "sample-2.png", "PNG", dpi=(150, 150))
    print("Saved sample-2.png")


# ─────────────────────────────────────────────────────────────────────────────
# Sample 3 — Utility notice: amount due, reference number, relative deadline
# ─────────────────────────────────────────────────────────────────────────────
def sample_3(fonts):
    img, draw = new_page()
    draw_header_band(draw, fonts,
        "CEYLON ELECTRICITY BOARD",
        "Western Province Distribution Branch · Consumer Services")

    y = 110
    y = write_line(draw, fonts, y, "Notice Ref: CEB/WP/DSC/2026/88231",     "sm", MUTED)
    y = write_line(draw, fonts, y, "Consumer Account No: 07-4412-009-0",     "sm", MUTED)
    y = write_line(draw, fonts, y, "Issue Date: 10 October 2026",            "sm", MUTED)
    y += 10
    draw_rule(draw, y); y += 14

    y = write_line(draw, fonts, y, "Mr. / Ms. Account Holder",               "body")
    y = write_line(draw, fonts, y, "Service Address: As per CEB records",    "body")
    y += 10

    y = write_line(draw, fonts, y,
        "Sub: Notice of Outstanding Electricity Bill — Payment Required Within 14 Days",
        "h2")
    y += 8
    draw_rule(draw, y); y += 14

    y = write_para(draw, fonts, y,
        "This is an official notice from the Ceylon Electricity Board informing you "
        "that your electricity account has an outstanding balance. You are required "
        "to settle the amount due within 14 days of the date of this notice."
    )
    y += 8

    # Amount table
    y = write_line(draw, fonts, y, "Statement of Outstanding Amount:", "h2")
    y += 6
    rows = [
        ("Arrears (previous balance)",      "LKR  4,820.00"),
        ("Current bill (Sep 2026)",          "LKR  3,150.00"),
        ("Late payment surcharge (5%)",      "LKR    241.00"),
        ("──────────────────────────────",   "────────────"),
        ("TOTAL AMOUNT DUE",                 "LKR  8,211.00"),
    ]
    col2_x = 560
    for label, amount in rows:
        draw.text((MARGIN_L + 16, y), label,  font=fonts["body"], fill=INK)
        draw.text((col2_x,         y), amount, font=fonts["body"], fill=INK)
        y += LINE_H_MD + 4
    y += 8

    y = write_para(draw, fonts, y,
        "Failure to pay the total amount due of LKR 8,211.00 within 14 days will "
        "result in disconnection of your electricity supply without further notice. "
        "A reconnection fee of LKR 2,500 will be charged in addition to the "
        "outstanding balance."
    )
    y += 4
    y = write_para(draw, fonts, y,
        "Payment may be made at any CEB Regional Office, through internet banking "
        "or mobile banking applications, or at any People's Bank branch islandwide. "
        "Please quote your Consumer Account No. 07-4412-009-0 when making payment."
    )
    y += 4
    y = write_para(draw, fonts, y,
        "If you have already made payment, please disregard this notice and retain "
        "the payment receipt for your records. For disputes, you must submit a written "
        "complaint with your meter reading records within 7 days of this notice."
    )
    y += 16

    draw_rule(draw, y); y += 12
    y = write_line(draw, fonts, y, "Yours faithfully,",                         "body")
    y += 32
    draw_rule(draw, y); y += 6
    y = write_line(draw, fonts, y, "R. P. Jayawardena",                         "h2")
    y = write_line(draw, fonts, y, "Regional Manager — Consumer Services",      "sm", MUTED)
    y = write_line(draw, fonts, y, "Ceylon Electricity Board, Western Province", "sm", MUTED)

    draw_rule(draw, H - 40)
    draw.text((MARGIN_L, H - 30),
        "CEB Hotline: 1987  ·  www.ceb.lk  ·  Disconnection queries: 0112 320 320",
        font=fonts["sm"], fill=MUTED)

    img.save(OUT_DIR / "sample-3.png", "PNG", dpi=(150, 150))
    print("Saved sample-3.png")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    fonts = load_fonts()
    sample_1(fonts)
    sample_2(fonts)
    sample_3(fonts)
    print(f"\nAll samples written to {OUT_DIR}")
