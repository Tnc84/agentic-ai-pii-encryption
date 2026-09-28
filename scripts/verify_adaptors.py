from mcp_server.server import mcp
from api.app import app
from services.ingest import ingest_text

print("mcp", mcp.name)
print("api", app.title)
print("docx", ingest_text("examples/test_docs/11_sample.docx", 50000)[1][:60])
try:
    print("pdf", ingest_text("examples/test_docs/11_sample.pdf", 50000)[1][:60])
except Exception as exc:
    print("pdf_err", exc)
