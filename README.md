# RoleScore

A lightweight web service that scores how well a job posting matches your resume — instantly, with a skill-by-skill breakdown.

Live at: https://fit-check-service.onrender.com/

## What it does

Paste a job URL and upload your resume (PDF or DOCX). The service fetches the job description, extracts your skills, and uses an LLM to produce:

- An overall fit score (0–100)
- A per-skill breakdown: ✅ matched / ⚠️ partial / ❌ missing
- A short summary of strengths and gaps

You can also run a **batch compare** — score up to 10 job URLs at once and rank them side by side.

## Features

- Single job fit score with skill breakdown
- Batch scoring (up to 10 URLs) with ranking
- PDF and DOCX resume support
- Bring-your-own Gemini API key (optional, for power users)
- Daily free checks per IP with graceful quota prompt
- `/stats` endpoint showing server-wide daily usage

## Free Tier & API Key

Each IP gets **20 free checks per day** using the server's shared Gemini key. Once the limit is hit, the UI prompts you to paste your own free Gemini API key — no account needed beyond that. You can get one in ~30 seconds at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The key is saved to localStorage and sent with each request; it never touches the server's storage.

If the server already has a key configured, the key input field is hidden entirely.

## Error Handling

| Error | Cause | What happens |
|---|---|---|
| `429 Too Many Requests` | Gemini quota exhausted (server key or your own key) | UI shows a clear message with a link to get a new key |
| `503 Service Unavailable` | Render cold start or Gemini API down | UI shows a retry prompt; usually resolves in a few seconds |

## Stack

- **Backend:** FastAPI + Python
- **LLM:** Google Gemini (`gemini-2.5-flash-lite`) — model set in `scorer.py`
- **Resume parsing:** PyMuPDF (PDF), python-docx (DOCX)
- **Hosting:** Render (auto-deploy from `master`)

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `POST` | `/fit-check` | Score a single job URL |
| `POST` | `/fit-check/batch` | Score up to 10 job URLs |
| `GET` | `/config` | Returns `{key_configured: bool}` |
| `GET` | `/stats` | Server-wide daily request count |
| `GET` | `/health` | Health check |

## Local Dev

```bash
pip install -r requirements.txt
# add GEMINI_API_KEY to .env
uvicorn main:app --reload
```
