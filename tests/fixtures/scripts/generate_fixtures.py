"""Generates real, small sample files for each supported ingestion format.

Run with: uv run --group fixtures python tests/fixtures/scripts/generate_fixtures.py

Every fixture is real content produced by these libraries at generation
time — not a hand-fabricated stand-in for a real file.
"""

from email.message import EmailMessage
from pathlib import Path

from docx import Document as DocxDocument
from fpdf import FPDF
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "documents"

PDF_TEXT = "Quarterly Compliance Report"
DOCX_HEADING = "Lending Policy Overview"
DOCX_BODY = "All loan applications must be reviewed within five business days."
PPTX_TITLE = "Q3 Retail Sales Summary"
PPTX_BODY = "Revenue grew twelve percent quarter over quarter."
XLSX_HEADERS = ["product", "units_sold", "revenue"]
XLSX_ROW = ["widget-a", 42, 1050]
HTML_HEADING = "Onboarding Runbook"
HTML_BODY = "Follow these steps to onboard a new enterprise tenant."
OCR_TEXT = "INVOICE NUMBER 48213"
STT_TEXT = "the quarterly earnings call starts at nine a m eastern time"
EML_SUBJECT = "Contract renewal reminder"
EML_BODY = "Please review the attached renewal terms before Friday."


def generate_pdf() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=16)
    pdf.cell(text=PDF_TEXT)
    pdf.output(str(OUTPUT_DIR / "sample.pdf"))


def generate_docx() -> None:
    doc = DocxDocument()
    doc.add_heading(DOCX_HEADING, level=1)
    doc.add_paragraph(DOCX_BODY)
    doc.save(str(OUTPUT_DIR / "sample.docx"))


def generate_pptx() -> None:
    prs = Presentation()
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = PPTX_TITLE
    body = slide.placeholders[1]
    body.text_frame.text = PPTX_BODY
    prs.save(str(OUTPUT_DIR / "sample.pptx"))


def generate_xlsx() -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(XLSX_HEADERS)
    ws.append(XLSX_ROW)
    wb.save(str(OUTPUT_DIR / "sample.xlsx"))


def generate_html() -> None:
    html = f"<html><body><h1>{HTML_HEADING}</h1><p>{HTML_BODY}</p></body></html>"
    (OUTPUT_DIR / "sample.html").write_text(html)


def generate_ocr_image() -> None:
    img = Image.new("RGB", (400, 100), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size=28
    )
    draw.text((10, 30), OCR_TEXT, fill="black", font=font)
    img.save(str(OUTPUT_DIR / "sample_ocr.png"))


def generate_audio() -> None:
    import pyttsx3

    engine = pyttsx3.init()
    # Default espeak-ng rate (200wpm) transcribes poorly with faster-whisper on
    # this synthetic voice; slowing it down measurably improves accuracy
    # (verified: "quarterly earnings call" transcribes correctly at rate=130
    # but not at the default rate).
    engine.setProperty("rate", 130)
    engine.save_to_file(STT_TEXT, str(OUTPUT_DIR / "sample_audio.wav"))
    engine.runAndWait()


def generate_eml() -> None:
    msg = EmailMessage()
    msg["Subject"] = EML_SUBJECT
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg.set_content(EML_BODY)
    (OUTPUT_DIR / "sample.eml").write_bytes(msg.as_bytes())


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_pdf()
    generate_docx()
    generate_pptx()
    generate_xlsx()
    generate_html()
    generate_ocr_image()
    generate_audio()
    generate_eml()
    print(f"Generated fixtures in {OUTPUT_DIR}")
