# Fit-Check Service

FastAPI web service for scoring how well a job posting matches a resume. Deployed on Render at https://fit-check-service.onrender.com/

## Stack

- **Backend:** FastAPI + Python
- **LLM:** Google Gemini (see section below)
- **Resume parsing:** PyMuPDF (PDF) + python-docx (DOCX)
- **Hosting:** Render (auto-deploy from `master`)

## Gemini Model

> **Current model:** `gemini-2.5-flash-lite` — set in `scorer.py` (`GEMINI_MODEL`)

### Why this matters

Gemini free-tier quotas are **per-model, per-project, per-day** — not per API key.
Swapping models without checking the quota first causes silent failures or 429s.

| Model | Free quota (as of Jun 2026) | Notes |
|---|---|---|
| `gemini-2.5-flash-lite` | ~1000 req/day | Current default |
| `gemini-2.5-flash` | 20 req/day | Too low for free tier use |
| `gemini-2.0-flash` | 0 req/day | Removed from free tier |

### To upgrade the model

1. Check current quotas at https://aistudio.google.com/apikey (click the key → "View quotas")
2. Update `GEMINI_MODEL` in `scorer.py`
3. Update `DAILY_FREE_LIMIT` in `main.py` to match the new model's daily quota
4. Update the quota message string in `main.py` (search for "free checks today")
5. Update the table above in this README

### Billing

Once billing is enabled on the Gemini project, bump back to `gemini-2.5-flash` and raise `DAILY_FREE_LIMIT` accordingly.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `POST` | `/fit-check` | Score a single job URL |
| `POST` | `/fit-check/batch` | Score up to 10 job URLs |
| `GET` | `/config` | Returns `{key_configured: bool}` |
| `GET` | `/stats` | Server-wide daily request count |
| `GET` | `/health` | Health check |

## Per-IP Quota

Free users get `DAILY_FREE_LIMIT` checks/day (defined in `main.py`). On limit, the UI prompts them to bring their own Gemini API key. If the server has `GEMINI_API_KEY` set, the key field is hidden in the UI.

## Local Dev

```bash
pip install -r requirements.txt
# add GEMINI_API_KEY to .env
uvicorn main:app --reload
```
