from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

# fpdf2's core fonts are latin-1 only; map common typographic characters first.
_PDF_REPLACEMENTS = {
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "‚": ",", "“": '"', "”": '"', "„": '"',
    "•": "-", "…": "...", " ": " ", " ": " ",
}


def extract_text(filename: str, content: bytes) -> str:
    """Extract plain text from an uploaded CV / letter (.pdf, .txt, .md)."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if suffix in {".txt", ".md", ""}:
        return content.decode("utf-8", errors="replace").strip()
    raise ValueError(f"Unsupported file type {suffix!r}; use PDF, TXT or MD")


def combine_letters(text: str, files: list[tuple[str, str]]) -> str:
    """
    Merge pasted text and any number of uploaded letters into one proto cover letter.
    Each file gets a header so the profile extraction can tell the documents apart.
    """
    parts = [text.strip()] if text.strip() else []
    parts += [f"--- {name} ---\n{content.strip()}" for name, content in files if content.strip()]
    return "\n\n".join(parts)


def _pdf_safe(text: str) -> str:
    for src, dst in _PDF_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def render_letter_pdf(
    path: Path,
    *,
    sender_lines: list[str],
    recipient_lines: list[str],
    date_line: str,
    subject: str,
    body: str,
) -> Path:
    """Render a plain DIN-5008-ish cover letter to PDF."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_margins(left=25, top=20, right=20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", size=9)
    pdf.multi_cell(0, 4.5, _pdf_safe("\n".join(line for line in sender_lines if line)))
    pdf.ln(8)

    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 5.5, _pdf_safe("\n".join(line for line in recipient_lines if line)))
    pdf.ln(6)
    pdf.cell(0, 5.5, _pdf_safe(date_line), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.set_font("Helvetica", style="B", size=11)
    pdf.multi_cell(0, 5.5, _pdf_safe(subject))
    pdf.ln(4)

    pdf.set_font("Helvetica", size=11)
    for paragraph in body.split("\n\n"):
        pdf.multi_cell(0, 5.5, _pdf_safe(paragraph.strip()))
        pdf.ln(3)

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path
