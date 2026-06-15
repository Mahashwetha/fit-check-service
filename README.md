# Fit-Check Service

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

## How Scoring Works

The score (0–100) is a holistic judgment by the LLM — it weighs seniority match, domain overlap, location, and skill alignment together, not just a count of exact keyword matches. Two green ticks on a 75% score means the other 25 points came from overall profile fit (experience level, industry, etc.).

Skill rows are only shown when the full job description was successfully fetched. If the description is unavailable, the skill breakdown is hidden — title-only scores are unreliable and treated as such.

The `extra` section ("On your resume — not requested in this job") shows skills the model initially matched but that don't appear in the actual job description — useful context, not a real match.

## Free Tier & API Key

Each IP gets **20 free checks per day** using the server's shared Gemini key. Once the limit is hit, the UI prompts you to paste your own free Gemini API key — no account needed beyond that. You can get one in ~30 seconds at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The key is saved to localStorage and sent with each request; it never touches the server's storage.

If the server already has a key configured, the key input field is hidden entirely.

## Error Handling

| Error | Cause | What happens |
|---|---|---|
| `429 Too Many Requests` | Gemini quota exhausted (server key or your own key) | UI shows a clear message with a link to get a new key |
| `503 Service Unavailable` | Render cold start or Gemini API down | UI shows a retry prompt; usually resolves in a few seconds |

### ⚠️ Job Description Warnings

| Warning | Cause | What happens |
|---|---|---|
| "Job description unavailable" (amber banner) | Site blocks scrapers, requires login, or is JS-rendered with no meta fallback | Score and skill breakdown are hidden — based on job title only and unreliable. Open the job directly to verify. |
| "Description not used" chip | Fetched page had less than 100 chars of useful text | Same as above — title-only estimate |

**Known affected sites:**
- **LinkedIn** — guest API works for older job IDs but is increasingly blocked for recent postings. Inconsistent — try the URL, if the banner appears the description wasn't fetched.
- **JS-rendered sites** (e.g. workatastartup.com) — scraper falls back to the page's meta description, which usually contains the full JD. Works in most cases.

## Privacy

Resume text is parsed in memory and sent to Google's Gemini API for scoring. It is not stored on this server. However, it does transit Google's infrastructure — do not upload resumes containing sensitive personal data beyond what you'd normally share with a job application.

## Performance & Availability

Hosted on Render's free tier — the instance sleeps after ~15 minutes of inactivity. The first request after a sleep triggers a cold start (~30–60 seconds). Subsequent requests are fast. The `/health` endpoint can be used to wake the instance before a batch run.

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
