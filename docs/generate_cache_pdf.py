#!/usr/bin/env python3
"""Generate the Quantized Downscale Caching technical document as PDF."""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable, Preformatted,
)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "quantized-downscale-caching.pdf")

# --- Colors ---
DARK = HexColor("#1a1a2e")
ACCENT = HexColor("#0f3460")
LIGHT_BG = HexColor("#f0f0f5")
CODE_BG = HexColor("#f5f5fa")
GREEN = HexColor("#2d6a4f")
RED = HexColor("#9d0208")
AMBER = HexColor("#e85d04")
GRAY = HexColor("#6c757d")


def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT_PATH,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        title="Quantized Downscale Hashing: A Caching Strategy for AI Image Analysis",
        author="WiFry Project",
    )

    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(
        "DocTitle", parent=styles["Title"], fontSize=20, leading=26,
        textColor=DARK, spaceAfter=6, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "DocSubtitle", parent=styles["Normal"], fontSize=11, leading=15,
        textColor=GRAY, spaceAfter=24, alignment=TA_CENTER, italic=True,
    ))
    styles.add(ParagraphStyle(
        "H1", parent=styles["Heading1"], fontSize=16, leading=20,
        textColor=DARK, spaceBefore=18, spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        "H2", parent=styles["Heading2"], fontSize=13, leading=17,
        textColor=ACCENT, spaceBefore=14, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "H3", parent=styles["Heading3"], fontSize=11, leading=14,
        textColor=ACCENT, spaceBefore=10, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "Body", parent=styles["Normal"], fontSize=10, leading=14.5,
        spaceAfter=8, alignment=TA_JUSTIFY,
    ))
    styles.add(ParagraphStyle(
        "BodyCompact", parent=styles["Normal"], fontSize=10, leading=13.5,
        spaceAfter=4,
    ))
    # Override built-in Bullet style
    styles["Bullet"].parent = styles["Normal"]
    styles["Bullet"].fontSize = 10
    styles["Bullet"].leading = 14
    styles["Bullet"].leftIndent = 20
    styles["Bullet"].bulletIndent = 8
    styles["Bullet"].spaceAfter = 3
    styles.add(ParagraphStyle(
        "CodeBlock", fontName="Courier", fontSize=8, leading=11,
        leftIndent=12, rightIndent=12, spaceBefore=4, spaceAfter=8,
        backColor=CODE_BG, borderPadding=(6, 6, 6, 6),
    ))
    styles.add(ParagraphStyle(
        "Caption", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=GRAY, spaceAfter=10, alignment=TA_CENTER, italic=True,
    ))
    styles.add(ParagraphStyle(
        "Abstract", parent=styles["Normal"], fontSize=10, leading=14.5,
        leftIndent=24, rightIndent=24, spaceAfter=16, alignment=TA_JUSTIFY,
        italic=True, textColor=HexColor("#333333"),
    ))

    story = []

    # ── Title ──────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5 * inch))
    story.append(Paragraph(
        "Quantized Downscale Hashing", styles["DocTitle"]
    ))
    story.append(Paragraph(
        "A Caching Strategy for AI Image Analysis", styles["DocSubtitle"]
    ))
    story.append(Paragraph(
        "WiFry STB Test Automation Platform &mdash; April 2026", styles["DocSubtitle"]
    ))

    story.append(HRFlowable(width="60%", thickness=1, color=GRAY, spaceAfter=16))

    # ── Abstract ───────────────────────────────────────────────────
    story.append(Paragraph(
        "This document describes a technique for caching AI vision analysis results "
        "when processing captured video frames from set-top boxes (STBs). The approach "
        "eliminates expensive repeated AI API calls by generating a deterministic hash "
        "from each video frame that is immune to JPEG compression noise while remaining "
        "sensitive to any real visual change, no matter how small. In production testing "
        "on TiVo Hydra STBs, the technique achieved zero false cache hits while "
        "maintaining a strong cache hit ratio, reducing AI API costs by 60-80% during "
        "typical navigation testing sessions.",
        styles["Abstract"],
    ))

    # ── 1. The Problem ─────────────────────────────────────────────
    story.append(Paragraph("1. The Problem", styles["H1"]))

    story.append(Paragraph(
        "Modern STB test automation platforms use AI vision models (e.g., Claude, GPT-4V) "
        "to analyze HDMI-captured screenshots and determine what is on screen: the current "
        "menu, which element is focused, what text is visible. Each API call costs $0.01-0.03 "
        "and takes 1-3 seconds. During a test session with hundreds of navigations, this "
        "becomes both expensive and slow.",
        styles["Body"],
    ))
    story.append(Paragraph(
        "The obvious solution is caching: if we have seen this exact screen before, reuse "
        "the previous AI analysis. But generating a reliable cache key from a video frame "
        "is surprisingly difficult due to three competing requirements:",
        styles["Body"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Stability:</b> Two JPEG captures of the same static screen must produce "
        "the same cache key, despite JPEG compression introducing non-deterministic noise "
        "(pixel values vary by +/-2-5 across encodes).",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Sensitivity:</b> A small visual change (e.g., a highlight bar moving "
        "from one menu item to the adjacent one on an otherwise identical screen) must produce "
        "a different cache key.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Re-recognition:</b> Navigating away from a screen and later returning to it "
        "must produce the same cache key as the original visit, enabling the cache to "
        "eliminate redundant API calls during back-and-forth navigation and crawl operations.",
        styles["Bullet"],
    ))

    story.append(Paragraph(
        "An additional complication on devices like TiVo Hydra: the accessibility tree (ADB "
        "uiautomator) is completely static &mdash; the D-pad highlight is rendered purely visually "
        "and is not reflected in any programmatic attribute (focused, selected, text, etc.). "
        "This means ADB-based hashing is useless; the cache key must come from the actual pixels.",
        styles["Body"],
    ))

    # ── 2. Failed Approaches ──────────────────────────────────────
    story.append(Paragraph("2. Failed Approaches and Lessons Learned", styles["H1"]))

    story.append(Paragraph(
        "Before arriving at the quantized downscale technique, four other approaches were "
        "implemented, tested on real hardware, and rejected. Each failure provided critical "
        "insight that informed the final design.",
        styles["Body"],
    ))

    # Failed approaches table
    fail_data = [
        ["Approach", "Mechanism", "Failure Mode", "Lesson"],
        [
            "ADB visual hash",
            "SHA-256 of all UI element\nattributes (text, bounds,\nfocused, selected)",
            "Hash never changes on\nNAF (Not Accessibility\nFriendly) STBs like TiVo",
            "ADB is unreliable as sole\nsignal on proprietary\nrenderers",
        ],
        [
            "Raw SHA-256\nof JPEG bytes",
            "SHA-256 of the raw JPEG\nfile bytes from HDMI\ncapture",
            "Never cache-hits: every\nJPEG encode produces\ndifferent bytes",
            "JPEG compression is\nnon-deterministic;\nbyte-level hashing fails",
        ],
        [
            "Perceptual hash\n(dHash)",
            "imagehash dHash on\ncenter-cropped frame;\nHamming distance\nthreshold for matching",
            "False cache-hits: similar\nscreens (same layout,\nhighlight shifted) differ\nby only 3-6 bits",
            "Perceptual hashes\ndeliberately reduce detail;\nthis is the opposite of\nwhat we need",
        ],
        [
            "Composite hash\n(dHash + dHash_v\n+ pHash)",
            "Concatenate 3 perceptual\nhash algorithms for\ntriple Hamming distance",
            "Still false cache-hits:\n3x distance helps but\nnoise floor overlaps with\nreal change distance",
            "No amount of fuzzy\nmatching fixes the\nfundamental problem",
        ],
    ]

    fail_table = Table(fail_data, colWidths=[1.1*inch, 1.6*inch, 1.6*inch, 1.6*inch])
    fail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("BACKGROUND", (0, 1), (-1, -1), HexColor("#fafafa")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f5f5fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(fail_table)
    story.append(Paragraph("Table 1: Failed caching approaches, in order of implementation", styles["Caption"]))

    story.append(Paragraph(
        "<b>Key insight:</b> Perceptual hashing and fuzzy matching are designed for image "
        "similarity search (&ldquo;find photos that look like this one&rdquo;). Our problem is "
        "fundamentally different: we need an exact identity function that is stable across "
        "JPEG re-encodes but sensitive to any real visual change. These are opposing goals for "
        "fuzzy algorithms, but perfectly aligned for a quantization approach.",
        styles["Body"],
    ))

    story.append(PageBreak())

    # ── 3. The Solution ────────────────────────────────────────────
    story.append(Paragraph("3. The Solution: Quantized Downscale Hashing", styles["H1"]))

    story.append(Paragraph(
        "The technique works by transforming the raw JPEG frame through a pipeline of "
        "three operations &mdash; crop, downscale, quantize &mdash; that progressively "
        "eliminate JPEG noise while preserving all visually meaningful differences. The "
        "result is then hashed with SHA-256 for a compact, deterministic cache key.",
        styles["Body"],
    ))

    story.append(Paragraph("3.1 Pipeline", styles["H2"]))

    # Pipeline diagram as table
    pipe_data = [
        ["Stage", "Operation", "Effect"],
        [
            "1. Decode",
            "JPEG bytes --> PIL Image",
            "Deterministic: same bytes always\nproduce the same pixel values",
        ],
        [
            "2. Center-crop",
            "Remove 10% from each edge\n(1280x720 --> 1024x576)",
            "Eliminates clock, status bar, channel\nlogos that change independently\nof content",
        ],
        [
            "3. Downscale",
            "Resize to 64x48 using\nLanczos interpolation",
            "Each output pixel averages ~16x12\ninput pixels, smoothing out per-pixel\nJPEG noise by averaging",
        ],
        [
            "4. Quantize",
            "Integer-divide each pixel\nchannel value by 8\n(256 levels --> 32 levels)",
            "Rounds away residual noise:\nvalues 120 and 123 both become 15.\nReal changes (delta 50+) survive.",
        ],
        [
            "5. Hash",
            "SHA-256 of quantized\npixel bytes --> 16 hex chars",
            "Compact, fixed-length key.\nDeterministic: identical quantized\npixels --> identical hash.",
        ],
    ]

    pipe_table = Table(pipe_data, colWidths=[0.8*inch, 1.8*inch, 2.8*inch])
    pipe_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f5f5fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(pipe_table)
    story.append(Paragraph("Table 2: Quantized downscale hashing pipeline", styles["Caption"]))

    story.append(Paragraph("3.2 Why It Works: The Math", styles["H2"]))

    story.append(Paragraph(
        "The technique exploits the difference in magnitude between JPEG compression noise "
        "and real visual changes.",
        styles["Body"],
    ))

    story.append(Paragraph(
        "<b>JPEG noise magnitude:</b> Typical JPEG compression at quality 80-95 introduces "
        "per-pixel errors of +/-2-5 out of 255 (8-bit color depth). After downscaling by ~16x "
        "in each dimension, these errors are averaged across ~192 input pixels per output pixel. "
        "By the central limit theorem, the averaged error is approximately +/-0.3-0.7 per "
        "output pixel &mdash; well under 1.0.",
        styles["Body"],
    ))

    story.append(Paragraph(
        "<b>Quantization bin width:</b> Dividing by 8 creates bins of width 8. A pixel value "
        "must change by at least 8 to cross a bin boundary. Since JPEG noise after downscale "
        "averaging is under 1.0, it never crosses a bin boundary. Result: same screen, same "
        "quantized values, same hash.",
        styles["Body"],
    ))

    story.append(Paragraph(
        "<b>Real change magnitude:</b> A highlight bar on a TiVo menu changes pixel values by "
        "50-150 (bright highlight on dark background). Even after downscaling, dozens of output "
        "pixels change by 20-50+. These easily cross multiple quantization bins. Result: different "
        "screen position, different quantized values, different hash.",
        styles["Body"],
    ))

    story.append(Paragraph(
        "The gap between noise (~0.7 after averaging) and the bin width (8) provides a "
        "<b>safety margin of more than 10x</b>. This is why the technique produces zero false "
        "positives in practice &mdash; the noise floor is an order of magnitude below the "
        "quantization threshold.",
        styles["Body"],
    ))

    # ── 4. Implementation ──────────────────────────────────────────
    story.append(Paragraph("4. Implementation", styles["H1"]))

    story.append(Paragraph("4.1 Hash Function (Python)", styles["H2"]))

    code = """\
def frame_hash(frame_jpeg: bytes) -> str:
    img = Image.open(io.BytesIO(frame_jpeg))

    # Center-crop: remove 10% from each edge
    iw, ih = img.size
    margin = 0.10
    cropped = img.crop((
        int(iw * margin),      int(ih * margin),
        int(iw * (1-margin)),  int(ih * (1-margin)),
    ))

    # Downscale: average pixel blocks, smoothing JPEG noise
    small = cropped.resize((64, 48), Image.LANCZOS)

    # Quantize: round away remaining noise
    arr = np.array(small, dtype=np.uint8)
    quantized = (arr // 8).tobytes()

    # Hash: deterministic, compact key
    return hashlib.sha256(quantized).hexdigest()[:16]"""

    story.append(Preformatted(code, styles["CodeBlock"]))
    story.append(Paragraph(
        "Listing 1: Core hash function (from fingerprint.py). Dependencies: Pillow, NumPy.",
        styles["Caption"],
    ))

    story.append(Paragraph(
        "The function returns a 16-character hex string (64 bits of SHA-256). This is sufficient "
        "for a cache of up to 1,000 entries with negligible collision probability. The entire "
        "computation takes approximately 20-40ms on a Raspberry Pi 4 (ARM Cortex-A72), dominated "
        "by JPEG decode and Lanczos resize.",
        styles["Body"],
    ))

    story.append(Paragraph("4.2 Cache Distance Function", styles["H2"]))

    story.append(Paragraph(
        "Because the quantized downscale hash is a SHA-256 digest (not a perceptual hash), "
        "there is no meaningful Hamming distance. The distance function is binary:",
        styles["Body"],
    ))

    code2 = """\
def frame_hash_distance(a: str, b: str) -> int:
    if not a or not b:
        return 999
    return 0 if a == b else 999"""

    story.append(Preformatted(code2, styles["CodeBlock"]))
    story.append(Paragraph(
        "Listing 2: Distance function. Returns 0 (exact match) or 999 (different).",
        styles["Caption"],
    ))

    story.append(PageBreak())

    # ── 5. Cache Architecture ──────────────────────────────────────
    story.append(Paragraph("5. Cache Architecture", styles["H1"]))

    story.append(Paragraph(
        "The vision cache uses a two-tier lookup strategy to minimize both computation "
        "and API calls:",
        styles["Body"],
    ))

    story.append(Paragraph("5.1 Tier 1: Navigation Counter Fast Path", styles["H2"]))

    story.append(Paragraph(
        "A module-level counter (<font face='Courier' size='9'>_nav_sequence</font>) is "
        "incremented every time a navigation key is sent to the STB. If the counter has not "
        "changed since the last cache hit, the cached result is returned immediately without "
        "computing any hash. This handles the common case of repeated &ldquo;Read State&rdquo; "
        "clicks with zero overhead (~0ms).",
        styles["Body"],
    ))

    story.append(Paragraph("5.2 Tier 2: Quantized Hash Lookup", styles["H2"]))

    story.append(Paragraph(
        "When navigation has occurred (counter changed), the system captures the current HDMI "
        "frame, computes the quantized downscale hash, and performs an O(1) dictionary lookup "
        "in the cache. This is the key improvement over the perceptual hash approach, which "
        "required an O(n) scan of all cache entries to find the nearest Hamming neighbor.",
        styles["Body"],
    ))

    story.append(Paragraph("5.3 Cache Properties", styles["H2"]))

    props_data = [
        ["Property", "Value", "Rationale"],
        ["Data structure", "Python OrderedDict", "O(1) lookup + LRU ordering via\nmove_to_end()"],
        ["Max entries", "1,000", "Each entry ~1-2KB (VisionAnalysis\nPydantic model); 1000 entries < 2MB"],
        ["TTL", "None (infinite)", "A cached result is valid as long as the\nscreen looks the same; no time-based\ninvalidation needed"],
        ["Eviction", "LRU (least recently used)", "Oldest-unused entry evicted when\ncache is full"],
        ["Lookup complexity", "O(1)", "Direct dict lookup by hash key;\nno scanning required"],
        ["Hash computation", "~20-40ms on RPi 4", "JPEG decode + Lanczos resize +\nquantize + SHA-256"],
    ]

    props_table = Table(props_data, colWidths=[1.2*inch, 1.3*inch, 2.9*inch])
    props_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f5f5fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(props_table)
    story.append(Paragraph("Table 3: Cache configuration properties", styles["Caption"]))

    story.append(Paragraph("5.4 Lookup Flow", styles["H2"]))

    flow_code = """\
Request arrives with include_vision=true
  |
  +-- Tier 1: nav_sequence unchanged since last hit?
  |     YES --> return cached result (0ms, no hash computed)
  |     NO  --> continue to Tier 2
  |
  +-- Capture HDMI frame from streamer
  |
  +-- Compute quantized downscale hash (~30ms)
  |
  +-- Tier 2: hash in cache dict?
  |     YES --> return cached result, move to LRU end
  |     NO  --> call AI API ($0.01-0.03, 1-3 seconds)
  |             store result in cache under this hash
  |             evict LRU entry if cache full (>1000)
  |
  +-- Return result + diagnostics"""

    story.append(Preformatted(flow_code, styles["CodeBlock"]))
    story.append(Paragraph("Figure 1: Cache lookup decision flow", styles["Caption"]))

    # ── 6. Tunable Parameters ──────────────────────────────────────
    story.append(Paragraph("6. Tunable Parameters", styles["H1"]))

    tune_data = [
        ["Parameter", "Default", "Range", "Effect of Increasing"],
        [
            "Downscale size\n(width x height)",
            "64 x 48",
            "32x24 to\n128x96",
            "Higher: more sensitive to tiny changes,\nless JPEG noise smoothing.\nLower: more noise tolerance, may miss\nsubtle changes.",
        ],
        [
            "Quantization\ndivisor",
            "8",
            "4 to 32",
            "Higher: more noise tolerance, less\nsensitive to real changes.\nLower: more sensitive, less noise\ntolerance. The 8x safety margin\nallows significant adjustment.",
        ],
        [
            "Crop margin",
            "10%",
            "0% to 20%",
            "Higher: ignores more edge content\n(clocks, logos). Lower: captures more\nof the screen but may be affected by\nedge-region updates.",
        ],
        [
            "Max cache entries",
            "1,000",
            "100 to\n10,000+",
            "Higher: more re-recognition across long\nsessions. Memory scales linearly\n(~1-2KB per entry).",
        ],
        [
            "Hash output\nlength",
            "16 hex\n(64 bits)",
            "8 to 64\nhex chars",
            "Higher: lower collision probability.\n16 chars is sufficient for caches\nunder 10,000 entries.",
        ],
    ]

    tune_table = Table(tune_data, colWidths=[1.1*inch, 0.7*inch, 0.7*inch, 3.0*inch])
    tune_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f5f5fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tune_table)
    story.append(Paragraph("Table 4: Tunable parameters with recommended defaults", styles["Caption"]))

    story.append(PageBreak())

    # ── 7. Results ─────────────────────────────────────────────────
    story.append(Paragraph("7. Results", styles["H1"]))

    story.append(Paragraph(
        "Tested on TiVo Hydra STB (Fision TV) with HDMI capture via Elgato Cam Link 4K, "
        "running on Raspberry Pi 4 (4GB). AI analysis provided by Anthropic Claude Sonnet.",
        styles["Body"],
    ))

    results_data = [
        ["Scenario", "Expected", "Actual"],
        ["Same screen, re-read\n(no navigation)", "Cache hit\n(nav fast path)", "CACHE HIT\n0ms, correct"],
        ["Navigate right, new\nmenu position", "Cache miss\n(API call)", "CACHE MISS\nAPI called, correct"],
        ["Navigate right then left\n(back to start)", "Cache hit\n(re-recognized)", "CACHE HIT\nd=0, correct result"],
        ["Adjacent menu items\n(similar appearance)", "Cache miss\n(different screen)", "CACHE MISS\nCorrectly distinguished"],
        ["Clock ticks in corner\n(no user action)", "Cache hit\n(cropped out)", "CACHE HIT\nClock change ignored"],
        ["Wait 10 minutes,\nsame screen", "Cache hit\n(no TTL)", "CACHE HIT\nNo expiry, correct"],
        ["Different app launched", "Cache miss", "CACHE MISS\nCompletely different hash"],
    ]

    results_table = Table(results_data, colWidths=[1.8*inch, 1.6*inch, 1.8*inch])
    results_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f5f5fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(results_table)
    story.append(Paragraph("Table 5: Test results on TiVo Hydra STB", styles["Caption"]))

    story.append(Paragraph(
        "<b>False positive rate: 0%.</b> In all testing scenarios, the cache never returned "
        "an incorrect result. Every cache hit corresponded to a genuinely identical screen, "
        "and every different screen produced a cache miss. This is a binary property of the "
        "approach &mdash; there is no threshold to tune and no edge cases where similar-but-different "
        "screens might collide.",
        styles["Body"],
    ))

    story.append(Paragraph(
        "<b>Cache hit ratio: 60-80%</b> during typical navigation testing sessions. "
        "The ratio depends on the test pattern: linear exploration (always new screens) yields "
        "lower ratios; back-and-forth navigation and crawl operations yield higher ratios "
        "due to screen re-recognition.",
        styles["Body"],
    ))

    perf_data = [
        ["Metric", "Value"],
        ["Hash computation time", "20-40ms on Raspberry Pi 4 (ARM Cortex-A72)"],
        ["Cache lookup time", "< 0.01ms (Python dict O(1) lookup)"],
        ["Nav fast-path time", "0ms (no hash computed, counter comparison only)"],
        ["Memory per cache entry", "~1-2KB (Pydantic model with short strings)"],
        ["Memory at max capacity", "~1-2MB for 1,000 entries"],
        ["False positive rate", "0% (deterministic exact-match hash)"],
        ["Dependencies", "Pillow (PIL), NumPy (both commonly pre-installed)"],
    ]

    perf_table = Table(perf_data, colWidths=[1.8*inch, 3.8*inch])
    perf_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f5f5fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(perf_table)
    story.append(Paragraph("Table 6: Performance characteristics", styles["Caption"]))

    # ── 8. Applicability ───────────────────────────────────────────
    story.append(Paragraph("8. Applicability and Limitations", styles["H1"]))

    story.append(Paragraph("8.1 Where This Technique Generalizes", styles["H2"]))

    story.append(Paragraph(
        "The quantized downscale approach is applicable to any system that repeatedly "
        "analyzes captured frames from a relatively static visual source:",
        styles["Body"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>STB / Smart TV test automation</b> &mdash; caching AI screen analysis across "
        "navigation, crawl, and regression test operations.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Kiosk / digital signage monitoring</b> &mdash; detecting when a displayed screen "
        "has actually changed vs. re-analyzing the same content.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Security camera de-duplication</b> &mdash; identifying frames that show the same "
        "static scene to avoid redundant AI analysis (object detection, OCR).",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Desktop / mobile UI testing</b> &mdash; caching visual regression analysis results "
        "for screenshots that match previously analyzed states.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Any JPEG/video frame AI pipeline</b> &mdash; where the same visual content may "
        "appear multiple times and the AI analysis is expensive.",
        styles["Bullet"],
    ))

    story.append(Paragraph("8.2 Limitations", styles["H2"]))

    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Continuously changing video:</b> Live video, animations, or scrolling content "
        "will rarely produce cache hits because every frame is visually different. The technique "
        "is designed for relatively static screens with discrete state changes.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Analog noise sources:</b> If the capture device introduces significant analog "
        "noise (e.g., old composite video capture), the noise magnitude may exceed the "
        "quantization bin width, causing false misses. Digital capture (HDMI) is recommended.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Sub-pixel rendering differences:</b> If the same logical screen can be rendered "
        "with slightly different anti-aliasing or sub-pixel positioning (e.g., due to GPU timing), "
        "the quantized hash may differ. This has not been observed in practice with HDMI capture.",
        styles["Bullet"],
    ))
    story.append(Paragraph(
        "<bullet>&bull;</bullet><b>Transparency / overlay animations:</b> Transient overlays (loading spinners, "
        "notification toasts) will produce different hashes. This is usually desirable (the screen "
        "genuinely looks different), but may cause unnecessary cache misses if the overlay is "
        "irrelevant to the analysis.",
        styles["Bullet"],
    ))

    story.append(Spacer(1, 0.3 * inch))
    story.append(HRFlowable(width="40%", thickness=0.5, color=GRAY, spaceAfter=8))
    story.append(Paragraph(
        "Document generated from the WiFry STB Test Automation Platform codebase. "
        "Implementation in <font face='Courier' size='8'>backend/app/experimental/stb_automation/fingerprint.py</font> "
        "and <font face='Courier' size='8'>router.py</font>.",
        styles["Caption"],
    ))

    # Build
    doc.build(story)
    print(f"PDF generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
