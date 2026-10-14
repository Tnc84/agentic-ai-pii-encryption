from pathlib import Path

from docx import Document

from api.app import app
from mcp_server.server import mcp

root = Path("examples/test_docs")
root.mkdir(parents=True, exist_ok=True)

text = (
    "Synthetic vendor note. Contact Ana Demo, ana.demo@example.test, "
    "phone +40 721 000 111. IBAN DE89370400440532013000. Address 1 Test Street."
)

doc = Document()
doc.add_paragraph(text)
doc.save(root / "11_sample.docx")
print("wrote docx")

# Minimal text PDF via reportlab alternative: write plain using pypdf is hard;
# create a simple .txt sibling and a docx is enough; also write pdf with basic content
try:
    from pypdf.generic import create_string_object
except Exception:
    create_string_object = None

# Fallback: store as text file named for pdf pipeline test using a tiny valid PDF
# Using a handcrafted one-page PDF with the text embedded.
pdf_path = root / "11_sample.pdf"
content = f"""%PDF-1.1
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 68 >>stream
BT /F1 12 Tf 50 700 Td ({text[:60]}) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000266 00000 n 
0000000384 00000 n 
trailer<< /Size 6 /Root 1 0 R >>
startxref
461
%%EOF
"""
pdf_path.write_text(content, encoding="latin-1", errors="ignore")
print("wrote pdf")


print("mcp", type(mcp))
print("api", app.title)
