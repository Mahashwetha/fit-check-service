"""
Cover letter generator — tailors a cover letter to a job posting using the
candidate's uploaded resume text and Gemini.

Reuses job-description fetching and the Gemini call from scorer.py.
"""

import json
import re

from scorer import _call_gemini, _extract_json, fetch_job_info

PERSONAL_PROJECTS_PARA = (
    "In parallel to my job search, I built several personal projects end-to-end: "
    "an automated job-tracking pipeline (Python, Excel, SMTP, Gemini API, Claude API), "
    "and Fit-Check — a live AI-powered job fit scorer deployed on Render "
    "(FastAPI, Gemini 2.5 Flash, Docker) that parses any job URL against a resume and "
    "returns a skill-by-skill breakdown."
)

CLOSE_PARA_TEMPLATE = (
    "Currently based in Paris, I am open to remote, hybrid, or on-site roles and am "
    "particularly motivated by opportunities where I can own services end-to-end and "
    "collaborate closely with cross-functional teams. I communicate professionally in "
    "English and am actively progressing in French. I would welcome the chance to "
    "discuss how my background aligns with {company}'s engineering goals."
)

COVER_PROMPT = """You are a cover letter writer. Write a tailored cover letter opening and body for this candidate.

CANDIDATE RESUME:
{resume}

JOB:
Title: {title}
Company: {company}
Job Description:
{jd}

Reply ONLY with a JSON object with these keys (no markdown, no extra text):
{{
  "candidate_name": "<candidate's full name, extracted from the resume; 'the candidate' if not found>",
  "company_value_prop": "<what the company/platform does — plain noun phrase, max 12 words>",
  "role_hook": "<what this role builds/delivers — starts with an -ing verb, max 15 words>",
  "matched_para": "<full paragraph (3-5 sentences) highlighting the candidate's existing skills/experience that directly match this JD — name specific tech/tools/experience from the resume that also appear in the JD; be concrete not vague>",
  "gap_para": "<full paragraph (2-4 sentences) briefly bridging the most important gaps between the resume and the JD — be honest but positive; mention any genuine adjacent skills; don't list all gaps, pick the 1-2 most important>"
}}

Rules:
- matched_para: only mention skills/experience explicitly present in the resume AND relevant to the JD
- gap_para: don't fabricate experience; use phrases like 'exposure to', 'actively expanding', 'hands-on with adjacent X and motivated to deepen Y'
- Keep paragraphs at roughly the same length as natural cover letter prose
- Tone: confident, specific, not generic"""


def _assemble(candidate_name: str, role: str, company: str, parts: dict) -> str:
    value_prop = parts.get('company_value_prop') or f"work at {company}"
    role_hook = parts.get('role_hook') or f"contributing to {role}"

    intro = (
        f"I am writing to express my interest in the {role} position at {company}. "
        f"I am excited by the opportunity to contribute to {company}'s {value_prop} "
        f"by {role_hook}."
    )

    paragraphs = [
        "Respected Hiring Manager,",
        "",
        intro,
        "",
        parts.get('matched_para', ''),
        "",
        parts.get('gap_para', ''),
        "",
        PERSONAL_PROJECTS_PARA,
        "",
        CLOSE_PARA_TEMPLATE.format(company=company),
        "",
        "Thank you for considering my application. I look forward to the possibility of speaking with you.",
        "",
        "Sincerely,",
        candidate_name,
    ]
    return "\n".join(paragraphs)


def generate_cover_letter(url: str, title: str, company: str, resume_text: str, api_key: str = '') -> str:
    """Fetch the job description and return a full tailored cover letter as text."""
    description, ld_title, ld_company = fetch_job_info(url)
    role = title or ld_title or 'this role'
    company_name = company or ld_company or 'your company'

    prompt = COVER_PROMPT.format(
        resume=resume_text[:2500],
        title=role,
        company=company_name,
        jd=description[:5000] if description else '(no description available)',
    )
    raw = _call_gemini(prompt, api_key=api_key)
    parts = json.loads(_extract_json(raw, kind='object'))
    candidate_name = parts.get('candidate_name') or 'the candidate'
    if candidate_name.strip().lower() in ('the candidate', 'unknown', ''):
        candidate_name = 'the candidate'
    return _assemble(candidate_name, role, company_name, parts)
