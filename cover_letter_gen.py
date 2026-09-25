"""
Cover letter generator — tailors a cover letter to a job posting using the
candidate's uploaded resume text and Gemini.

Reuses job-description fetching and the Gemini call from scorer.py.
"""

import hashlib
import json
import re

from scorer import _call_gemini, _extract_json, fetch_job_info

BANNED_OPENINGS = ("i am writing", "i'm writing", "express my interest", "i am excited",
                   "i'm excited", "with over", "i am thrilled", "i would like to apply",
                   "aligns perfectly")

# ── Candidate profile (per resume, cached in the user's browser) ─────────────
# The projects paragraph, closing and links come from the uploaded resume, never from
# hard-coded text, so each user's letter describes THEM. The profile is generated once
# per resume (temperature 0), returned to the browser, and sent back on later requests;
# the server reuses it only if its fingerprint matches the uploaded resume.

PROFILE_VERSION = 1
MAX_PARA = 900

PROFILE_PROMPT = """Extract facts from this resume. Reply ONLY with a JSON object (no markdown):
{{
  "location": "<the candidate's current city/country exactly as written in the resume, '' if not stated>",
  "languages": ["<each spoken language with its level exactly as written in the resume, e.g. 'English (Fluent)'>"],
  "project_names": ["<names of the candidate's personal/side projects exactly as written in the resume; [] if none>"],
  "projects_para": "<2-3 sentences in first person (I, my) describing ONLY those personal projects, their tech and what they do, using only facts in the resume; '' if there are no personal projects>"
}}
Rules: never invent anything; copy names and levels exactly as they appear; no work-experience roles in project_names.

RESUME:
{resume}"""


def resume_fingerprint(resume_text: str) -> str:
    norm = re.sub(r"\s+", " ", resume_text).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]


def _in_resume(fragment: str, resume_low: str) -> bool:
    f = re.sub(r"\s+", " ", fragment).strip().lower()
    return bool(f) and f in resume_low


def _links(resume_text: str) -> dict:
    gh = re.search(r"github\.com/([A-Za-z0-9-]+)", resume_text, re.I)
    li = re.search(r"linkedin\.com/in/([A-Za-z0-9%_-]+)", resume_text, re.I)
    return {"github": f"https://github.com/{gh.group(1)}" if gh else "",
            "linkedin": f"https://linkedin.com/in/{li.group(1).rstrip('-')}" if li else ""}


def build_profile(resume_text: str, api_key: str = '') -> dict:
    """Generate the per-resume profile once. Every fact is checked against the resume."""
    resume_low = re.sub(r"\s+", " ", resume_text).lower()
    raw = _call_gemini(PROFILE_PROMPT.format(resume=resume_text[:4000]), api_key=api_key, temperature=0)
    data = json.loads(_extract_json(raw, kind='object'))

    location = str(data.get('location') or '').strip()
    if not _in_resume(location, resume_low):
        location = ''
    languages = [str(x).strip() for x in (data.get('languages') or []) if str(x).strip()]
    languages = [x for x in languages if _in_resume(re.sub(r"\s*\(.*\)$", "", x), resume_low)]

    names = [str(x).strip() for x in (data.get('project_names') or []) if str(x).strip()]
    projects_para = str(data.get('projects_para') or '').strip()
    # keep the paragraph only if it is grounded: every named project is literally in the resume
    if not names or not all(_in_resume(n, resume_low) for n in names) or len(projects_para) > MAX_PARA:
        projects_para = ''

    return {"version": PROFILE_VERSION, "fingerprint": resume_fingerprint(resume_text),
            "location": location, "languages": languages[:5],
            "projects_para": projects_para, **_links(resume_text)}


def valid_profile(profile, resume_text: str) -> bool:
    """A profile sent back by the browser is reused only if it belongs to this exact resume."""
    return (isinstance(profile, dict) and profile.get("version") == PROFILE_VERSION
            and profile.get("fingerprint") == resume_fingerprint(resume_text)
            and all(isinstance(profile.get(k, ''), str) and len(profile.get(k, '')) <= MAX_PARA
                    for k in ("location", "projects_para", "github", "linkedin"))
            and isinstance(profile.get("languages", []), list))


def _close_para(company: str, profile: dict) -> str:
    where = f"Currently based in {profile['location']}, I am" if profile.get('location') else "I am"
    text = (f"{where} open to remote, hybrid, or on-site roles and am particularly motivated by "
            f"opportunities where I can own services end-to-end and collaborate closely with "
            f"cross-functional teams.")
    langs = [str(x) for x in profile.get('languages', [])][:5]
    if langs:
        text += f" Languages: {', '.join(langs)}."
    return text + f" I would welcome the chance to discuss how my background aligns with {company}'s engineering goals."

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


def _assemble(candidate_name: str, role: str, company: str, parts: dict, profile: dict) -> str:
    paragraphs = ["Respected Hiring Manager,", "", _opening(role, company, parts), "",
                  parts.get('matched_para', ''), "", parts.get('gap_para', ''), ""]
    if profile.get('projects_para'):
        paragraphs += [profile['projects_para'], ""]
    paragraphs += [_close_para(company, profile), "",
                   "Thank you for considering my application. I look forward to the possibility of speaking with you.",
                   ""]
    links = [f"My GitHub profile: {profile['github']}" if profile.get('github') else "",
             f"My LinkedIn profile: {profile['linkedin']}" if profile.get('linkedin') else ""]
    links = [l for l in links if l]
    if links:
        paragraphs += links + [""]
    paragraphs += ["Sincerely,", candidate_name if candidate_name == 'the candidate' else candidate_name.split()[0]]
    return "\n".join(paragraphs)


def generate_cover_letter(url: str, title: str, company: str, resume_text: str, api_key: str = '',
                          profile: dict | None = None) -> tuple[str, dict]:
    """Fetch the job description and return (cover letter text, profile to cache in the browser)."""
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
    if not valid_profile(profile, resume_text):
        profile = build_profile(resume_text, api_key=api_key)
    return _assemble(candidate_name, role, company_name, parts, profile), profile
