# Agentic AI PII Encryption

Modular Python CLI (+ optional FastAPI/MCP) that runs a LangGraph pipeline:
detect PII → verify → anonymize → rewrite → report → seal encrypted alias map.

## Stack

- Typer CLI; optional FastAPI (`pii-pipeline-api`) and read-only MCP (`pii-pipeline-mcp`)
- LangGraph + LangChain (`langchain-ollama`) + Sqlite checkpointer (resume after escalate)
- Hybrid detect: **regex ∥ Microsoft Presidio** (parallel), optional LLM soft entities
- Local LLM: **Ollama + Mistral** (verify/rewrite)
- SQLAlchemy + Alembic (SQLite default; PostgreSQL via `DATABASE_URL`)
- AES-GCM vault (PBKDF2 passphrase); ciphertext only in DB
- Ingest: `.txt`, `.md`, `.pdf`, `.docx`

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate.bat
pip install -e .
python -m spacy download en_core_web_sm

copy .env.example .env
# set VAULT_PASSPHRASE

pii-pipeline db upgrade

ollama serve
ollama pull mistral
```

Postgres (optional): set `DATABASE_URL=postgresql+psycopg://...` then `pii-pipeline db upgrade`.

## Commands

```bash
pii-pipeline detect examples/sample.txt
pii-pipeline run examples/sample.txt --force
pii-pipeline resume --run-id <run_id>
pii-pipeline deanonymize artifacts/<run_id>/rewritten.txt --vault-id <vault_id>
pii-pipeline-api
pii-pipeline-mcp
```

- Residual PII after rewrite triggers **re-map/anonymize** (`build_map`), not re-detect on raw text.
- Escalate pauses the graph (checkpointer); approve with `resume`.
- Reports/audit never store plaintext PII or clear alias maps.
- MCP tools are **read-only** (runs/audit/report); no vault decrypt.

## API (thin)

- `POST /v1/runs` `{ "path": "...", "force": true }`
- `GET /v1/runs/{id}`, `GET /v1/runs/{id}/audit`
- `POST /v1/runs/{id}/resume`, `POST /v1/deanonymize`
