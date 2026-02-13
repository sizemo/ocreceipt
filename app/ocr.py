import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pytesseract
from dateutil import parser
from PIL import Image, ImageFilter, ImageOps
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


def run_ocr(image_bytes: bytes) -> dict:
    base_image = Image.open(io.BytesIO(image_bytes)).convert("L")
    oriented = _orient_image(base_image)

    variants = _build_variants(oriented)
    configs = ["--oem 3 --psm 6", "--oem 3 --psm 4", "--oem 3 --psm 11"]

    best_pass = {"text": "", "avg_confidence": 0.0, "lines": []}
    best_variant = variants[0]

    for variant in variants:
        for config in configs:
            parsed = _ocr_with_confidence(variant, config)
            if parsed["avg_confidence"] > best_pass["avg_confidence"]:
                best_pass = parsed
                best_variant = variant

    top_pass = _ocr_region(best_variant, 0.0, 0.35, configs)
    bottom_pass = _ocr_region(best_variant, 0.5, 1.0, configs)

    return {
        "text": best_pass["text"],
        "lines": best_pass["lines"],
        "avg_confidence": best_pass["avg_confidence"],
        "top_text": top_pass["text"],
        "top_lines": top_pass["lines"],
        "top_confidence": top_pass["avg_confidence"],
        "bottom_text": bottom_pass["text"],
        "bottom_lines": bottom_pass["lines"],
        "bottom_confidence": bottom_pass["avg_confidence"],
    }




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


def render_pdf_preview_image(pdf_bytes: bytes) -> bytes:
    pages = _render_pdf_pages(pdf_bytes, max_pages=1)
    if not pages:
        raise ValueError("PDF contains no renderable pages")

    preview = io.BytesIO()
    pages[0].save(preview, format="PNG")
    return preview.getvalue()


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

    combined_lines = _dedupe_lines(top_lines + main_lines + bottom_lines)
    line_confidences = _build_line_confidence_map(
        [*ocr_result.get("lines", []), *ocr_result.get("top_lines", []), *ocr_result.get("bottom_lines", [])]
    )

    merchant, merchant_conf = parse_merchant(top_lines + combined_lines, line_confidences)
    purchase_date, date_conf = parse_date(top_lines + combined_lines, line_confidences)
    total_amount, total_conf = parse_total(bottom_lines + combined_lines, line_confidences)
    sales_tax_amount, tax_conf = parse_sales_tax(bottom_lines + combined_lines, line_confidences)

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

    blacklist = ["invoice", "receipt", "order", "store", "thank", "date", "time", "cashier"]
    for line in lines[:12]:
        low = line.lower()
        if any(token in low for token in blacklist):
            continue
        if sum(ch.isalpha() for ch in line) < 3:
            continue
        if sum(ch.isdigit() for ch in line) > 4:
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
    for idx, line in enumerate(reversed_lines[:26]):
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
    data = pytesseract.image_to_data(image, config=config, output_type=Output.DICT)

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
    for config in configs:
        parsed = _ocr_with_confidence(region, config)
        if parsed["avg_confidence"] > best["avg_confidence"]:
            best = parsed
    return best


def _parse_conf(value: str | int | float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else -1.0
    except (TypeError, ValueError):
        return -1.0


def _orient_image(image: Image.Image) -> Image.Image:
    try:
        osd = pytesseract.image_to_osd(image)
        match = re.search(r"Rotate: (\d+)", osd)
        if match:
            angle = int(match.group(1))
            if angle in {90, 180, 270}:
                return image.rotate(360 - angle, expand=True)
    except Exception:
        pass
    return image


def _build_variants(image: Image.Image) -> list[Image.Image]:
    upscaled = image.resize((image.width * 2, image.height * 2)) if min(image.size) < 1600 else image.copy()
    autocontrast = ImageOps.autocontrast(upscaled)
    sharpened = autocontrast.filter(ImageFilter.SHARPEN)
    denoised = autocontrast.filter(ImageFilter.MedianFilter(size=3))

    threshold_145 = autocontrast.point(lambda px: 0 if px < 145 else 255, mode="1")
    threshold_170 = autocontrast.point(lambda px: 0 if px < 170 else 255, mode="1")

    return [autocontrast, sharpened, denoised, threshold_145, threshold_170]
