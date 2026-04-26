"""Extract plain text from PDFs and images for the text-model fallback path."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_path: str | Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise RuntimeError("PyMuPDF (pymupdf) is required for PDF text extraction") from e

    path = Path(file_path)
    doc = fitz.open(path)
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text("text") or "")
    doc.close()
    return "\n".join(parts).strip()


def pdf_first_page_as_png_bytes(file_path: str | Path, dpi: int = 120) -> bytes:
    """Rasterize first PDF page for vision models."""
    import fitz

    path = Path(file_path)
    doc = fitz.open(path)
    try:
        page = doc.load_page(0)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def shrink_png_max_side(png_bytes: bytes, max_side: int) -> bytes | None:
    """
    If the longest edge exceeds max_side, return a downscaled PNG (RGB); else None.
    Used to retry vision calls when Ollama returns 5xx (VRAM / model load limits).
    """
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return None

    try:
        img = Image.open(BytesIO(png_bytes))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        w, h = img.size
        m = max(w, h)
        if m <= max_side:
            return None
        scale = max_side / m
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        out = BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as exc:
        logger.warning("shrink_png_max_side failed: %s", exc)
        return None


def vision_png_size_candidates(original: bytes) -> list[bytes]:
    """Largest first, then smaller variants (from the same source) for Ollama vision retries."""
    variants: list[bytes] = [original]
    for max_side in (1536, 1152, 896, 640, 512):
        s = shrink_png_max_side(original, max_side)
        if not s:
            continue
        if len(s) < len(variants[-1]) * 0.88:
            variants.append(s)
    return variants


def ocr_image_bytes(
    image_bytes: bytes,
    *,
    ollama_model: str,
    ollama_base_url: str,
    vision_capable: bool = True,
    skip_capability_gate: bool = False,
) -> str:
    """
    Plain-text OCR via Ollama /api/generate with the image.

    When ``skip_capability_gate`` is True (dedicated ``ollama_ocr_model`` set, e.g.
    ``glm-ocr:latest``), OCR runs even if the main vision model is not marked vision-capable.
    """
    if not skip_capability_gate and not vision_capable:
        logger.warning(
            "Ollama OCR skipped: vision model is not marked vision-capable in Settings "
            "(set a dedicated OCR model under System settings to bypass)."
        )
        return ""
    if not (ollama_model or "").strip() or not (ollama_base_url or "").strip():
        logger.warning("Ollama OCR skipped: missing model or base URL.")
        return ""

    from documents.services.ollama_client import ocr_image_with_ollama

    try:
        return ocr_image_with_ollama(
            image_bytes,
            model=ollama_model.strip(),
            base_url=ollama_base_url.rstrip("/"),
        )
    except Exception as exc:
        logger.warning("Ollama OCR failed: %s", exc)
        return ""
