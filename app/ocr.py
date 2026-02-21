import io
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pytesseract

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover
    cv2 = None
    np = None
from dateutil import parser
from PIL import Image, ImageChops, ImageFilter, ImageOps
import pypdfium2 as pdfium
from pytesseract import Output

DATE_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b",
]

AMOUNT_TOKEN_PATTERN = re.compile(r"(\$?\s*[0-9]+(?:\.[0-9]{2}))(\s*%)?")
COMMON_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})
MAX_PDF_OCR_PAGES = 4
OCR_AUTO_CROP = os.getenv("OCR_AUTO_CROP", "true").strip().lower() == "true"
OCR_DESKEW = os.getenv("OCR_DESKEW", "false").strip().lower() == "true"
OCR_DESKEW_DEGREES = float(os.getenv("OCR_DESKEW_DEGREES", "3"))
OCR_DESKEW_STEP = float(os.getenv("OCR_DESKEW_STEP", "1.0"))
OCR_PERSPECTIVE = os.getenv("OCR_PERSPECTIVE", "true").strip().lower() == "true"
OCR_FAST_MODE = os.getenv("OCR_FAST_MODE", "true").strip().lower() == "true"
OCR_MAX_IMAGE_SIDE = int(os.getenv("OCR_MAX_IMAGE_SIDE", "1600"))
OCR_TESS_TIMEOUT_SEC = int(os.getenv("OCR_TESS_TIMEOUT_SEC", "10"))
OCR_OSD_TIMEOUT_SEC = int(os.getenv("OCR_OSD_TIMEOUT_SEC", "3"))




def _ocr_quality_score(text: str, avg_conf: float) -> float:
    low = (text or "").lower()
    letters = sum(ch.isalpha() for ch in low)
    digits = sum(ch.isdigit() for ch in low)
    keywords = ("total", "tax", "subtotal", "amount", "visa", "mastercard", "cashier", "order")
    hits = sum(1 for k in keywords if k in low)

    score = float(avg_conf or 0.0)
    score += min(35.0, letters / 55.0)
    score += min(20.0, digits / 45.0)
    score += hits * 10.0
    return score


def run_ocr(image_bytes: bytes) -> dict:
    base_image = Image.open(io.BytesIO(image_bytes))
    base_image = ImageOps.exif_transpose(base_image).convert("L")
    if max(base_image.size) > OCR_MAX_IMAGE_SIDE:
        scale = OCR_MAX_IMAGE_SIDE / max(base_image.size)
        base_image = base_image.resize((int(base_image.width * scale), int(base_image.height * scale)))

    candidates: list[Image.Image] = [base_image]
    if OCR_AUTO_CROP:
        cropped = _auto_crop_receipt(base_image)
        # Avoid duplicates
        if cropped.size != base_image.size:
            candidates.append(cropped)

    if OCR_FAST_MODE:
        configs = ["--oem 3 --psm 6", "--oem 3 --psm 4"]
        number_configs = ["--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.$%"]
    else:
        configs = ["--oem 3 --psm 6", "--oem 3 --psm 4", "--oem 3 --psm 11"]
        number_configs = [
            "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.$%",
            "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.$%",
        ]

    best_overall: dict | None = None
    best_overall_score = -1.0

    for candidate in candidates:
        oriented = _pick_best_rotation(candidate)
        if OCR_PERSPECTIVE:
            oriented = _perspective_correct(oriented)
        oriented = _orient_image(oriented)
        if OCR_DESKEW:
            oriented = _deskew_small_angles(oriented)

        variants = _build_variants(oriented)

        best_pass = {"text": "", "avg_confidence": 0.0, "lines": []}
        best_score = -1.0
        best_variant = variants[0]

        for variant in variants:
            for config in configs:
                parsed = _ocr_with_confidence(variant, config)
                score = _ocr_quality_score(parsed.get("text", ""), parsed.get("avg_confidence", 0.0))
                if score > best_score:
                    best_score = score
                    best_pass = parsed
                    best_variant = variant

        top_pass = _ocr_region(best_variant, 0.0, 0.35, configs)
        bottom_pass = _ocr_region(best_variant, 0.5, 1.0, configs)
        bottom_numbers_pass = _ocr_region(best_variant, 0.55, 1.0, number_configs)

        result = {
            "text": best_pass["text"],
            "lines": best_pass["lines"],
            "avg_confidence": best_pass["avg_confidence"],
            "top_text": top_pass["text"],
            "top_lines": top_pass["lines"],
            "top_confidence": top_pass["avg_confidence"],
            "bottom_text": bottom_pass["text"],
            "bottom_lines": bottom_pass["lines"],
            "bottom_confidence": bottom_pass["avg_confidence"],
            "bottom_numbers_text": bottom_numbers_pass["text"],
            "bottom_numbers_lines": bottom_numbers_pass["lines"],
            "bottom_numbers_confidence": bottom_numbers_pass["avg_confidence"],
        }

        overall_score = _ocr_quality_score(result.get("text", ""), result.get("avg_confidence", 0.0))
        overall_score += 0.6 * _ocr_quality_score(result.get("top_text", ""), result.get("top_confidence", 0.0))
        overall_score += 0.8 * _ocr_quality_score(result.get("bottom_text", ""), result.get("bottom_confidence", 0.0))
        overall_score += 1.0 * _ocr_quality_score(result.get("bottom_numbers_text", ""), result.get("bottom_numbers_confidence", 0.0))

        if overall_score > best_overall_score:
            best_overall_score = overall_score
            best_overall = result

    return best_overall or {
        "text": "",
        "lines": [],
        "avg_confidence": 0.0,
        "top_text": "",
        "top_lines": [],
        "top_confidence": 0.0,
        "bottom_text": "",
        "bottom_lines": [],
        "bottom_confidence": 0.0,
        "bottom_numbers_text": "",
        "bottom_numbers_lines": [],
        "bottom_numbers_confidence": 0.0,
    }





def _pick_best_rotation(image: Image.Image) -> Image.Image:
    """Pick the best of 0/90/180/270 by running a cheap OCR confidence pass.

    Tesseract confidence alone is often noisy; add text/keyword heuristics.
    """

    try:
        rotations = [
            image,
            image.rotate(90, expand=True, fillcolor=255),
            image.rotate(180, expand=True, fillcolor=255),
            image.rotate(270, expand=True, fillcolor=255),
        ]

        keywords = ("total", "tax", "subtotal", "visa", "mastercard", "amount")

        scored: list[tuple[float, Image.Image]] = []
        for candidate in rotations:
            work = candidate
            if max(work.size) > 1100:
                scale = 1100 / max(work.size)
                work = work.resize((int(work.width * scale), int(work.height * scale)))

            work = ImageOps.autocontrast(work)
            thr = _otsu_threshold(work)
            bin_img = work.point(lambda px: 0 if px < thr else 255, mode="1").convert("L")

            parsed = _ocr_with_confidence(bin_img, config="--oem 3 --psm 6")
            text = (parsed.get("text", "") or "").lower()

            # Heuristic: more letters/digits and receipt keywords means likely correct rotation.
            letters = sum(ch.isalpha() for ch in text)
            digits = sum(ch.isdigit() for ch in text)
            hits = sum(1 for k in keywords if k in text)

            score = float(parsed.get("avg_confidence", 0.0))
            score += min(35.0, letters / 55.0)
            score += min(20.0, digits / 45.0)
            score += hits * 8.0

            scored.append((score, candidate))

        best = max(scored, key=lambda t: t[0])[1]
        return best
    except Exception:
        return image
def run_ocr_pdf(pdf_bytes: bytes) -> dict:
    pages = _render_pdf_pages(pdf_bytes, max_pages=MAX_PDF_OCR_PAGES)
    if not pages:
        raise ValueError("PDF contains no renderable pages")

    per_page_results: list[dict] = []
    for page_image in pages:
        page_buffer = io.BytesIO()
        page_image.save(page_buffer, format="PNG")
        per_page_results.append(run_ocr(page_buffer.getvalue()))

    text_parts = [result.get("text", "") for result in per_page_results if result.get("text")]
    all_lines = [line for result in per_page_results for line in result.get("lines", [])]

    first = per_page_results[0]
    last = per_page_results[-1]
    avg_conf = sum(result.get("avg_confidence", 0.0) for result in per_page_results) / max(1, len(per_page_results))

    return {
        "text": "\n".join(text_parts),
        "lines": all_lines,
        "avg_confidence": round(avg_conf, 2),
        "top_text": first.get("top_text", ""),
        "top_lines": first.get("top_lines", []),
        "top_confidence": first.get("top_confidence", 0.0),
        "bottom_text": last.get("bottom_text", ""),
        "bottom_lines": last.get("bottom_lines", []),
        "bottom_confidence": last.get("bottom_confidence", 0.0),
    }


def render_pdf_preview_image(pdf_bytes: bytes, page_index: int = 0) -> bytes:
    if page_index < 0:
        raise ValueError("page_index must be >= 0")

    pages = _render_pdf_pages(pdf_bytes, max_pages=page_index + 1)
    if not pages or page_index >= len(pages):
        raise ValueError("PDF page is out of range")

    preview = io.BytesIO()
    pages[page_index].save(preview, format="PNG")
    return preview.getvalue()


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return int(len(document))
    finally:
        close_document = getattr(document, "close", None)
        if callable(close_document):
            close_document()


def _render_pdf_pages(pdf_bytes: bytes, *, max_pages: int) -> list[Image.Image]:
    document = pdfium.PdfDocument(pdf_bytes)
    rendered_pages: list[Image.Image] = []

    try:
        page_count = min(len(document), max_pages)
        for index in range(page_count):
            page = document[index]
            bitmap = None
            try:
                bitmap = page.render(scale=2.4)
                if hasattr(bitmap, "to_pil"):
                    pil_image = bitmap.to_pil()
                elif hasattr(bitmap, "to_pil_image"):
                    pil_image = bitmap.to_pil_image()
                else:
                    raise RuntimeError("Unsupported PDF bitmap conversion")

                rendered_pages.append(pil_image.convert("RGB"))
            finally:
                close_page = getattr(page, "close", None)
                if callable(close_page):
                    close_page()
                close_bitmap = getattr(bitmap, "close", None) if bitmap is not None else None
                if callable(close_bitmap):
                    close_bitmap()
    finally:
        close_document = getattr(document, "close", None)
        if callable(close_document):
            close_document()

    return rendered_pages

def extract_receipt_fields(ocr_result: dict) -> dict:
    main_lines = _normalize_lines(ocr_result.get("text", ""))
    top_lines = _normalize_lines(ocr_result.get("top_text", ""))
    bottom_lines = _normalize_lines(ocr_result.get("bottom_text", ""))
    bottom_number_lines = _normalize_lines(ocr_result.get("bottom_numbers_text", ""))

    combined_lines = _dedupe_lines(top_lines + main_lines + bottom_lines + bottom_number_lines)
    line_confidences = _build_line_confidence_map(
        [
            *ocr_result.get("lines", []),
            *ocr_result.get("top_lines", []),
            *ocr_result.get("bottom_lines", []),
            *ocr_result.get("bottom_numbers_lines", []),
        ]
    )

    merchant, merchant_conf = parse_merchant(top_lines + combined_lines, line_confidences)
    purchase_date, date_conf = parse_date(top_lines + combined_lines, line_confidences)
    total_amount, total_conf = parse_total(bottom_lines + combined_lines, line_confidences)
    sales_tax_amount, tax_conf = parse_sales_tax(bottom_lines + combined_lines, line_confidences)

    # Guardrail: sales tax should not be a large fraction of the total.
    # This avoids misreading tax *rate* (e.g. 8.25%) as the tax *amount*.
    if sales_tax_amount is not None and total_amount is not None:
        if sales_tax_amount < Decimal('0') or sales_tax_amount > (total_amount * Decimal('0.25')):
            sales_tax_amount = None
            tax_conf = 0.0


    subtotal_amount = _find_keyword_amount(_normalize_lines("\n".join(bottom_lines + combined_lines)), ["subtotal", "sub total"])
    if sales_tax_amount is None and subtotal_amount is not None and total_amount is not None:
        delta = total_amount - subtotal_amount
        if delta >= Decimal("0") and delta <= (total_amount * Decimal("0.25")):
            sales_tax_amount = delta
            tax_conf = max(tax_conf, 40.0)

    extraction_confidence = _compute_overall_confidence(
        pass_conf=max(
            ocr_result.get("avg_confidence", 0.0),
            ocr_result.get("top_confidence", 0.0),
            ocr_result.get("bottom_confidence", 0.0),
        ),
        merchant_conf=merchant_conf,
        date_conf=date_conf,
        total_conf=total_conf,
        tax_conf=tax_conf,
        has_total=total_amount is not None,
        has_date=purchase_date is not None,
        has_tax=sales_tax_amount is not None,
    )

    raw_text = "\n".join(_dedupe_lines([*top_lines, *main_lines, *bottom_lines]))
    return {
        "merchant": merchant,
        "purchase_date": purchase_date,
        "total_amount": total_amount,
        "sales_tax_amount": sales_tax_amount,
        "raw_ocr_text": raw_text,
        "extraction_confidence": extraction_confidence,
        "needs_review": extraction_confidence < 78.0,
    }


def parse_merchant(lines: list[str], line_confidences: dict[str, float]) -> tuple[str | None, float]:
    if not lines:
        return None, 0.0

    blacklist = ["invoice", "receipt", "order", "store", "thank", "date", "time", "cashier", "join", "earn", "points", "rewards"]
    for line in lines[:12]:
        low = line.lower()
        if any(token in low for token in blacklist):
            continue
        if sum(ch.isalpha() for ch in line) < 3:
            continue
        digit_count = sum(ch.isdigit() for ch in line)
        if digit_count > 8:
            continue

        # Allow trailing store numbers like "Taco Bell 027825" but store just the name.
        candidate = re.sub(r"\s+[0-9]{4,8}$", "", line).strip()
        if digit_count > 4 and candidate and sum(ch.isalpha() for ch in candidate) >= 3:
            return candidate[:200], _line_confidence(line, line_confidences)

        if digit_count > 4:
            continue
        return line[:200], _line_confidence(line, line_confidences)

    fallback = lines[0][:200]
    return fallback, _line_confidence(fallback, line_confidences)


def parse_date(lines: list[str], line_confidences: dict[str, float]) -> tuple[date | None, float]:
    keywords = ["date", "purchase", "transaction", "time"]

    ranked = sorted(
        lines,
        key=lambda line: 0 if any(k in line.lower() for k in keywords) else 1,
    )

    for line in ranked:
        candidate_line = _normalize_digits(line)
        for pattern in DATE_PATTERNS:
            for candidate in re.findall(pattern, candidate_line, flags=re.IGNORECASE):
                parsed = _safe_parse_date(candidate)
                if parsed:
                    return parsed, _line_confidence(line, line_confidences)

        parsed_inline = _safe_parse_date(candidate_line)
        if parsed_inline:
            return parsed_inline, _line_confidence(line, line_confidences)

    return None, 0.0


def parse_sales_tax(lines: list[str], line_confidences: dict[str, float]) -> tuple[Decimal | None, float]:
    tax_keywords = ["sales tax", "state tax", "tax", "hst", "gst", "vat"]

    candidates: list[tuple[Decimal, float, float]] = []
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if not any(keyword in line_lower for keyword in tax_keywords):
            continue

        amount = _extract_amount_from_line(line, prefer_non_percent=True, prefer_rightmost=True)
        if amount is None:
            continue

        proximity_boost = max(0.0, 12 - idx * 0.4)
        score = _line_confidence(line, line_confidences) + proximity_boost
        candidates.append((amount, _line_confidence(line, line_confidences), score))

    if not candidates:
        return None, 0.0

    amount, conf, _ = max(candidates, key=lambda item: item[2])
    return amount, conf


def parse_total(lines: list[str], line_confidences: dict[str, float]) -> tuple[Decimal | None, float]:
    reversed_lines = list(reversed(lines))

    priority_keywords = ["grand total", "amount due", "balance due", "total"]
    ignore_keywords = ["subtotal", "sub total", "tax", "change", "tender", "discount"]

    subtotal = _find_keyword_amount(reversed_lines, ["subtotal", "sub total"])
    tax = _find_keyword_amount(reversed_lines, ["sales tax", "state tax", "tax", "hst", "gst", "vat"])

    candidates: list[tuple[Decimal, float, float]] = []
    for idx, line in enumerate(reversed_lines[:80]):
        amount = _extract_amount_from_line(line, prefer_non_percent=True, prefer_rightmost=False)
        if amount is None:
            continue

        line_lower = line.lower()
        conf = _line_confidence(line, line_confidences)
        score = conf

        if any(keyword in line_lower for keyword in priority_keywords):
            score += 35
        if any(keyword in line_lower for keyword in ignore_keywords):
            score -= 18

        score += max(0.0, 14 - idx * 0.6)

        if subtotal is not None and tax is not None:
            delta = abs((subtotal + tax) - amount)
            if delta <= Decimal("0.03"):
                score += 28
            elif delta <= Decimal("0.20"):
                score += 8

        candidates.append((amount, conf, score))

    if not candidates:
        return None, 0.0

    amount, conf, _ = max(candidates, key=lambda item: item[2])
    return amount, conf


def _find_keyword_amount(lines: list[str], keywords: list[str]) -> Decimal | None:
    for line in lines:
        low = line.lower()
        if any(k in low for k in keywords):
            amount = _extract_amount_from_line(line, prefer_non_percent=True, prefer_rightmost=True)
            if amount is not None:
                return amount
    return None


def _safe_parse_date(value: str) -> date | None:
    try:
        parsed = parser.parse(value, dayfirst=False, fuzzy=True)
        if parsed.year < 2000 or parsed.year > 2100:
            return None
        return parsed.date()
    except (ValueError, OverflowError):
        return None


def _extract_amount_candidates(line: str) -> list[dict]:
    normalized = _normalize_digits(line)
    normalized = re.sub(r"(\d),(\d{2})(?!\d)", r"\1.\2", normalized)
    candidates: list[dict] = []

    for match in AMOUNT_TOKEN_PATTERN.finditer(normalized):
        token = match.group(1)
        percent_suffix = match.group(2)

        numeric_token = re.sub(r"[^0-9.]", "", token)
        if not numeric_token:
            continue

        try:
            value = Decimal(numeric_token)
        except (InvalidOperation, ValueError):
            continue

        if value < 0:
            continue

        candidates.append(
            {
                "value": value,
                "is_percent": bool(percent_suffix and percent_suffix.strip()),
                "has_currency": "$" in token,
                "start": match.start(),
            }
        )

    return candidates


def _extract_amount_from_line(
    line: str,
    *,
    prefer_non_percent: bool = True,
    prefer_rightmost: bool = False,
) -> Decimal | None:
    candidates = _extract_amount_candidates(line)
    if not candidates:
        return None

    filtered = candidates
    if prefer_non_percent:
        non_percent = [c for c in filtered if not c["is_percent"]]
        if non_percent:
            filtered = non_percent

    currency_candidates = [c for c in filtered if c["has_currency"]]
    if currency_candidates:
        filtered = currency_candidates

    if not filtered:
        return None

    if prefer_rightmost:
        selected = max(filtered, key=lambda c: c["start"])
        return selected["value"]

    selected = max(filtered, key=lambda c: c["value"])
    return selected["value"]


def _normalize_digits(value: str) -> str:
    return value.translate(COMMON_DIGIT_FIXES)


def _normalize_lines(text: str) -> list[str]:
    cleaned: list[str] = []
    for line in text.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if compact:
            cleaned.append(compact)
    return cleaned


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for line in lines:
        key = _normalize_for_match(line)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(line)
    return ordered


def _compute_overall_confidence(
    pass_conf: float,
    merchant_conf: float,
    date_conf: float,
    total_conf: float,
    tax_conf: float,
    has_total: bool,
    has_date: bool,
    has_tax: bool,
) -> float:
    weighted = (pass_conf * 0.32) + (merchant_conf * 0.14) + (date_conf * 0.2) + (total_conf * 0.22) + (tax_conf * 0.12)

    if not has_total:
        weighted -= 20
    if not has_date:
        weighted -= 10
    if not has_tax:
        weighted -= 5

    return max(0.0, min(100.0, round(weighted, 2)))


def _line_confidence(line: str, line_confidences: dict[str, float]) -> float:
    if not line_confidences:
        return 0.0

    normalized = _normalize_for_match(line)
    if not normalized:
        return 0.0

    if normalized in line_confidences:
        return line_confidences[normalized]

    for key, value in line_confidences.items():
        if normalized in key or key in normalized:
            return value

    return 0.0


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _build_line_confidence_map(lines: list[dict]) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for line in lines:
        text = line.get("text", "").strip()
        if not text:
            continue

        conf = float(line.get("confidence", 0.0))
        mapping[_normalize_for_match(text)] = conf
    return mapping


def _ocr_with_confidence(image: Image.Image, config: str) -> dict:
    try:
        data = pytesseract.image_to_data(
            image,
            config=config,
            output_type=Output.DICT,
            timeout=max(1, OCR_TESS_TIMEOUT_SEC),
        )
    except RuntimeError:
        return {"text": "", "avg_confidence": 0.0, "lines": []}

    confidences: list[float] = []
    grouped_lines: dict[tuple[int, int, int], list[tuple[str, float]]] = {}

    count = len(data.get("text", []))
    for idx in range(count):
        raw_text = (data["text"][idx] or "").strip()
        conf = _parse_conf(data["conf"][idx])

        if conf >= 0 and raw_text:
            confidences.append(conf)
            key = (data["block_num"][idx], data["par_num"][idx], data["line_num"][idx])
            grouped_lines.setdefault(key, []).append((raw_text, conf))

    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    lines: list[dict] = []
    for key in sorted(grouped_lines):
        parts = grouped_lines[key]
        line_text = " ".join(word for word, _ in parts)
        line_conf = round(sum(conf for _, conf in parts) / len(parts), 2)
        lines.append({"text": line_text, "confidence": line_conf})

    text = "\n".join(line["text"] for line in lines)
    return {"text": text, "avg_confidence": avg_conf, "lines": lines}


def _ocr_region(image: Image.Image, y_start_ratio: float, y_end_ratio: float, configs: list[str]) -> dict:
    width, height = image.size
    y0 = int(max(0, min(1, y_start_ratio)) * height)
    y1 = int(max(0, min(1, y_end_ratio)) * height)

    if y1 <= y0:
        return {"text": "", "avg_confidence": 0.0, "lines": []}

    region = image.crop((0, y0, width, y1))
    best = {"text": "", "avg_confidence": 0.0, "lines": []}
    best_score = -1.0
    for config in configs:
        parsed = _ocr_with_confidence(region, config)
        score = _ocr_quality_score(parsed.get("text", ""), parsed.get("avg_confidence", 0.0))
        if score > best_score:
            best = parsed
            best_score = score
    return best


def _parse_conf(value: str | int | float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else -1.0
    except (TypeError, ValueError):
        return -1.0


def _orient_image(image: Image.Image) -> Image.Image:
    try:
        osd = pytesseract.image_to_osd(image, timeout=max(1, OCR_OSD_TIMEOUT_SEC))
        match = re.search(r"Rotate: (\d+)", osd)
        if match:
            angle = int(match.group(1))
            if angle in {90, 180, 270}:
                return image.rotate(360 - angle, expand=True)
    except Exception:
        pass
    return image






def _order_quad_points(pts: "np.ndarray") -> "np.ndarray":
    # pts shape (4, 2)
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left
    rect[2] = pts[np.argmax(s)]  # bottom-right

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left
    return rect


def _perspective_correct(image: Image.Image) -> Image.Image:
    """Warp the receipt to a flat rectangle if a 4-corner contour is found."""

    if cv2 is None or np is None:
        return image

    try:
        # Work on a resized copy for contour detection.
        pil = image
        orig_w, orig_h = pil.size
        max_side = max(orig_w, orig_h)
        scale = 1.0
        if max_side > 1400:
            scale = 1400.0 / max_side
            pil = pil.resize((int(orig_w * scale), int(orig_h * scale)))

        gray = np.array(pil)
        if gray.ndim != 2:
            gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)

        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 60, 180)
        edges = cv2.dilate(edges, None, iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return image

        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:8]
        quad = None
        for c in contours:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2).astype("float32")
                break

        if quad is None:
            return image

        rect = _order_quad_points(quad)
        (tl, tr, br, bl) = rect

        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        max_w = int(max(width_a, width_b))

        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_h = int(max(height_a, height_b))

        if max_w < 300 or max_h < 300:
            return image

        dst = np.array(
            [
                [0, 0],
                [max_w - 1, 0],
                [max_w - 1, max_h - 1],
                [0, max_h - 1],
            ],
            dtype="float32",
        )

        M = cv2.getPerspectiveTransform(rect, dst)

        # Warp using the same resized image we detected on, then scale back by running OCR variants anyway.
        warped = cv2.warpPerspective(gray, M, (max_w, max_h), borderMode=cv2.BORDER_REPLICATE)
        warped_pil = Image.fromarray(warped).convert("L")

        return warped_pil
    except Exception:
        return image
def _auto_crop_receipt(image: Image.Image) -> Image.Image:
    """Best-effort crop to receipt content without extra deps (no OpenCV).

    First tries a bright-region bbox (good for receipts on dark backgrounds),
    then falls back to an edge-map bbox.
    """

    try:
        work = image
        if max(work.size) > 1800:
            scale = 1800 / max(work.size)
            work = work.resize((int(work.width * scale), int(work.height * scale)))

        # 1) Bright-region bbox (receipt paper is typically the brightest object).
        bright = ImageOps.autocontrast(work)
        bright_mask = bright.point(lambda px: 255 if px > 210 else 0)
        bbox = bright_mask.getbbox()

        # 2) Fallback to edge bbox if the bright bbox looks wrong.
        if not bbox or (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) < (work.width * work.height * 0.18):
            edges = work.filter(ImageFilter.FIND_EDGES)
            edges = ImageOps.autocontrast(edges)
            edges = edges.point(lambda px: 255 if px > 48 else 0)
            bbox = edges.getbbox()

        if not bbox:
            return image

        x0, y0, x1, y1 = bbox
        area = (x1 - x0) * (y1 - y0)
        if area < (work.width * work.height * 0.18):
            return image

        pad = int(max(work.size) * 0.02)
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(work.width, x1 + pad)
        y1 = min(work.height, y1 + pad)

        if work.size != image.size:
            sx = image.width / work.width
            sy = image.height / work.height
            x0 = int(x0 * sx)
            x1 = int(x1 * sx)
            y0 = int(y0 * sy)
            y1 = int(y1 * sy)

        return image.crop((x0, y0, x1, y1))
    except Exception:
        return image


def _otsu_threshold(image: Image.Image) -> int:
    # Image must be L mode.
    hist = image.histogram()
    total = sum(hist)
    if total <= 0:
        return 160

    sum_total = 0
    for i, h in enumerate(hist):
        sum_total += i * h

    sum_b = 0
    w_b = 0
    var_max = -1.0
    threshold = 160

    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break

        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > var_max:
            var_max = var_between
            threshold = i

    return threshold


def _deskew_small_angles(image: Image.Image) -> Image.Image:
    """Deskew small angles by maximizing horizontal projection variance."""

    try:
        max_deg = max(0.5, float(OCR_DESKEW_DEGREES))
        step = max(0.25, float(OCR_DESKEW_STEP))

        work = image
        if max(work.size) > 1200:
            scale = 1200 / max(work.size)
            work = work.resize((int(work.width * scale), int(work.height * scale)))

        # Build a high-contrast binary for scoring.
        enhanced = ImageOps.autocontrast(work)
        thr = _otsu_threshold(enhanced)
        binary = enhanced.point(lambda px: 0 if px < thr else 255)

        angles = []
        a = -max_deg
        while a <= max_deg + 1e-9:
            angles.append(round(a, 3))
            a += step

        best_angle = 0.0
        best_score = -1.0

        for angle in angles:
            rotated = binary.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
            w, h = rotated.size
            pixels = rotated.tobytes()
            row_sums = [0] * h
            # Count dark pixels per row (byte < 128).
            idx = 0
            for y in range(h):
                count = 0
                row = pixels[idx:idx + w]
                idx += w
                # rot is L; 0 is black.
                for b in row:
                    if b < 128:
                        count += 1
                row_sums[y] = count

            # Score by adjacent row difference (sharper lines => higher score).
            score = 0
            prev = row_sums[0] if row_sums else 0
            for v in row_sums[1:]:
                d = v - prev
                score += d * d
                prev = v

            if score > best_score:
                best_score = score
                best_angle = angle

        if abs(best_angle) < 0.01:
            return image

        # Apply to full-res image.
        return image.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    except Exception:
        return image


def _build_variants(image: Image.Image) -> list[Image.Image]:
    upscaled = image.resize((image.width * 2, image.height * 2)) if min(image.size) < 1600 else image.copy()

    autocontrast = ImageOps.autocontrast(upscaled)
    equalized = ImageOps.equalize(autocontrast)

    denoised = equalized.filter(ImageFilter.MedianFilter(size=3))

    # High-pass style enhancement to make faint thermal text pop.
    blurred = denoised.filter(ImageFilter.GaussianBlur(radius=1.2))
    highpass = ImageChops.subtract(denoised, blurred)
    highpass = ImageOps.autocontrast(highpass)

    sharpened = denoised.filter(ImageFilter.UnsharpMask(radius=2, percent=165, threshold=3))

    thr = _otsu_threshold(denoised)
    threshold_otsu = denoised.point(lambda px: 0 if px < thr else 255, mode="1")

    # Keep a couple fixed thresholds as fallbacks.
    threshold_145 = denoised.point(lambda px: 0 if px < 145 else 255, mode="1")
    threshold_170 = denoised.point(lambda px: 0 if px < 170 else 255, mode="1")

    variants = [denoised, sharpened, highpass, threshold_otsu, threshold_145, threshold_170]
    return variants[:3] if OCR_FAST_MODE else variants
