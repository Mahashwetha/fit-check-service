"""
Cover letter generator — tailors a cover letter to a job posting using the
candidate's uploaded resume text and Gemini.

Reuses job-description fetching and the Gemini call from scorer.py.
"""

import json
import re

from scorer import _call_gemini, _extract_json, fetch_job_info

PERSONAL_PROJECTS_PARA = (
    "Outside work, I build and ship my own tools. I built an automated job-search pipeline "
    "(Python, Gemini and Claude APIs) and Fit-Check, a live AI app on Render (FastAPI, Gemini, "
    "Docker) that scores any job posting against a resume, skill by skill. Both are open source "
    "and I use them every day, which is how I learned to design, deploy and maintain "
    "AI-powered systems end to end."
)

BANNED_OPENINGS = ("i am writing", "i'm writing", "express my interest", "i am excited",
                   "i'm excited", "with over", "i am thrilled", "i would like to apply",
                   "aligns perfectly")

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
  "opening_type": "<one of: achievement, company, capability>",
  "opening_para": "<exactly 2 sentences that open the letter. Choose the ONE strongest opening for this job: achievement (one concrete, ideally quantified achievement that is literally in the resume, tied to an outcome this JD cares about); company (a concrete detail from the JD about what the company builds or has just announced, connected to the candidate's real experience); capability (the JD's single most critical requirement, stated with specific evidence from the resume). Sentence 2 connects it to the role at the company.>",
  "company_value_prop": "<what the company/platform does — plain noun phrase, max 12 words>",
  "role_hook": "<what this role builds/delivers — starts with an -ing verb, max 15 words>",
  "matched_para": "<full paragraph (3-5 sentences) written in first person (I, my, me) highlighting the candidate's existing skills/experience that directly match this JD — name specific tech/tools/experience from the resume that also appear in the JD; be concrete not vague>",
  "gap_para": "<full paragraph (2-4 sentences) written in first person (I, my, me) briefly bridging the most important gaps between the resume and the JD — be honest but positive; mention any genuine adjacent skills; don't list all gaps, pick the 1-2 most important>"
}}

Rules:
- matched_para and gap_para MUST be written in first person (I, my, me) — never refer to the candidate by name or use 'she/her/he/his/they'
- matched_para: only mention skills/experience explicitly present in the resume AND relevant to the JD
- gap_para: don't fabricate experience. State plainly what the candidate has not used, then mention only real adjacent experience found in the resume. Never claim the candidate is currently learning, deepening, expanding or upskilling in a gap technology unless the resume explicitly says so
- opening_para must NOT contain "I am writing", "express my interest", "I am excited", "With over", "aligns perfectly", must not summarise the CV and must not explain why the candidate wants the job; it must name {company}; every fact and number must appear in the resume
- NEVER re-label the candidate's domain to match the company's (e.g. do not call trade surveillance "payments" or video software "fintech"); describe past work exactly as the resume does, then connect it as "similar" or "transferable" if relevant
- matched_para must NOT start with "With over" or restate the achievement already used in opening_para; use different evidence
- Keep paragraphs at roughly the same length as natural cover letter prose
- Tone: confident, specific, not generic"""


def _opening(role: str, company: str, parts: dict) -> str:
    """Gemini's opening_para if it follows the rules, else a neutral company-led opening."""
    opening = (parts.get('opening_para') or '').strip()
    low = opening.lower()
    if opening and company.lower() in low and not any(b in low for b in BANNED_OPENINGS):
        return opening
    value_prop = (parts.get('company_value_prop') or '').strip().rstrip('.')
    what = f"{company}'s {value_prop}" if value_prop else f"the {role} role at {company}"
    return (f"{what[0].upper()}{what[1:]} is closely connected to the systems I have built so far. "
            f"Here is the experience I would bring to the {role} role.")


def _assemble(candidate_name: str, role: str, company: str, parts: dict) -> str:
    intro = _opening(role, company, parts)

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
        "My GitHub profile: https://github.com/Mahashwetha",
        "My LinkedIn profile: https://linkedin.com/in/mahashwetha-rao",
        "",
        "Sincerely,",
        candidate_name if candidate_name == 'the candidate' else candidate_name.split()[0],
    ]
    return "\n".join(paragraphs)


def generate_cover_letter(url: str, title: str, company: str, resume_text: str, api_key: str = '') -> str:
    """Fetch the job description and return a full tailored cover letter as text."""
    description, ld_title, ld_company = fetch_job_info(url)
    if not description or len(description) <= 100:
        raise ValueError("Couldn't fetch the job description, so a tailored cover letter isn't possible. Open the job directly and copy the description.")
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
