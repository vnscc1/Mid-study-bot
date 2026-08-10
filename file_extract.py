"""استخراج النص من الملفات المرفوعة (PDF أو صور)"""

import io


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    lower = filename.lower()

    if lower.endswith(".pdf"):
        return _extract_from_pdf(file_bytes)
    elif lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return _extract_from_image(file_bytes)
    elif lower.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="ignore")
    else:
        return ""


def _extract_from_pdf(file_bytes: bytes) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def _extract_from_image(file_bytes: bytes) -> str:
    """
    ملاحظة: الصور تحتاج مسار مختلف (إرسالها مباشرة لـ Claude Vision كصورة،
    مو كنص مستخرج). هذا غير مفعّل بعد في هذا الملف — راجع قسم
    "الخطوة القادمة: دعم الصور" في README.md.
    """
    return ""
