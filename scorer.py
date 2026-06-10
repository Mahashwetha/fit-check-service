"""
Scorer — fetches job description from a URL and scores it against a resume
using Gemini 2.5 Flash.

Standalone module — no dependency on the job agent.
Requires GEMINI_API_KEY environment variable.
"""

import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load .env for local dev (no-op in production where env vars are set directly)
load_dotenv()

GEMINI_MODEL = 'gemini-2.5-flash-lite'
GEMINI_URL = (
    f'https://generativelanguage.googleapis.com/v1beta/models/'
    f'{GEMINI_MODEL}:generateContent'
)


def _extract_json(raw: str, kind: str = 'object') -> str:
    """Strip markdown fences and extract the first JSON object or array."""
    # Remove markdown code fences (```json ... ``` or ``` ... ```)
    text = re.sub(r'```(?:json)?\s*', '', raw).replace('```', '').strip()

    if kind == 'array':
        m = re.search(r'\[', text)
        if not m:
            raise ValueError(f'No JSON array found in response: {raw[:300]}')
        start = m.start()
        depth, in_str, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    else:
        m = re.search(r'\{', text)
        if not m:
            raise ValueError(f'No JSON object found in response: {raw[:300]}')
        start = m.start()
        depth, in_str, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

    raise ValueError(f'Unbalanced JSON in response: {raw[:300]}')


# ── Gemini call ───────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, api_key: str = '') -> str:
    api_key = api_key or os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        raise RuntimeError('No Gemini API key provided. Enter your key in the form or set GEMINI_API_KEY on the server.')

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.2,
            'maxOutputTokens': 8192,
        },
    }
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.post(
                GEMINI_URL,
                headers={'Content-Type': 'application/json'},
                params={'key': api_key},
                json=payload,
                timeout=30,
            )
            if resp.status_code in (429, 500, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))  # 5s, 10s
                continue
            if resp.status_code == 503:
                raise RuntimeError('Gemini is temporarily overloaded — please try again in a few seconds.')
            if resp.status_code == 429:
                raise RuntimeError('Gemini rate limit reached. Add your own Gemini API key to continue.')
            if resp.status_code == 401:
                raise RuntimeError('Invalid Gemini API key. Please check your key and try again.')
            resp.raise_for_status()
            return resp.json()['candidates'][0]['content']['parts'][0]['text']
        except RuntimeError:
            raise
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('Gemini is temporarily overloaded — please try again in a few seconds.')


# ── Job description fetching ──────────────────────────────────────────────────

def fetch_job_description(url: str) -> str:
    """Fetch and clean job description text from a URL.
    Supports LinkedIn, WTTJ (Algolia), and generic HTML pages.
    Returns plain text (up to 4000 chars), or '' on failure.
    """
    url_lower = url.lower()
    if 'linkedin.com/jobs/view/' in url_lower:
        return _fetch_linkedin(url)
    if 'welcometothejungle.com' in url_lower:
        return _fetch_wttj(url)
    return _fetch_generic(url)


def _fetch_linkedin(url: str) -> str:
    m = re.search(r'-(\d+)(?:\?|$)', url)
    if not m:
        return ''
    job_id = m.group(1)
    api_url = f'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}'
    try:
        resp = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if resp.status_code != 200:
            return ''
        match = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div', resp.text, re.DOTALL)
        if not match:
            return ''
        text = re.sub(r'<[^>]+>', ' ', match.group(1))
        return ' '.join(text.split())[:4000]
    except Exception:
        return ''


def _fetch_wttj(url: str) -> str:
    m = re.search(r'/companies/([^/]+)/jobs/([^?&#]+)', url)
    if not m:
        return _fetch_generic(url)
    job_slug = m.group(2)
    try:
        algolia_url = 'https://CSEKHVMS53-dsn.algolia.net/1/indexes/wttj_jobs_production_fr/query'
        headers = {
            'X-Algolia-Application-Id': 'CSEKHVMS53',
            'X-Algolia-API-Key': '4bd8f6215d0cc52b26430765769e65a0',
            'Content-Type': 'application/json',
            'Origin': 'https://www.welcometothejungle.com',
            'Referer': 'https://www.welcometothejungle.com/',
        }
        query = job_slug.replace('-', ' ')
        payload = {'params': f'query={query}&hitsPerPage=5'}
        resp = requests.post(algolia_url, headers=headers, json=payload, timeout=15)
        if resp.ok:
            for hit in resp.json().get('hits', []):
                if hit.get('slug') == job_slug:
                    desc = hit.get('description') or hit.get('profile') or ''
                    if isinstance(desc, dict):
                        desc = ' '.join(str(v) for v in desc.values())
                    if desc:
                        return str(desc)[:4000]
    except Exception:
        pass
    return _fetch_generic(url)


def _fetch_generic(url: str) -> str:
    try:
        # Some sites (e.g. workatastartup.com) return 406 without Accept headers
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return ''
        soup = BeautifulSoup(resp.text, 'html.parser')
        ld = soup.find('script', type='application/ld+json')
        if ld and ld.string:
            try:
                data = json.loads(ld.string)
                desc = data.get('description', '')
                if desc and len(desc) > 100:
                    return BeautifulSoup(desc, 'html.parser').get_text(' ', strip=True)[:4000]
            except Exception:
                pass
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        text = soup.get_text(' ', strip=True)
        # JS-rendered shells (e.g. workatastartup.com) leave almost no visible
        # text but often ship the full JD in the meta description
        if len(text) < 500:
            meta = (soup.find('meta', attrs={'name': 'description'})
                    or soup.find('meta', attrs={'property': 'og:description'}))
            content = meta.get('content', '') if meta else ''
            if len(content) > len(text):
                text = content
        return text[:4000]
    except Exception:
        return ''


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_fit(url: str, resume_text: str, title: str = '', company: str = '', api_key: str = '') -> dict:
    """Fetch job description from URL and score fit against resume_text.

    Returns:
      {
        "score": int,
        "verdict": str,         Weak | Moderate | Good | Strong
        "matched": [...],       list of {skill, evidence}
        "missing": [...],       list of {skill, required}
        "partial": [...],       list of {skill, note}
        "recommendation": str,
        "description_used": bool,
        "title": str,
        "company": str,
        "url": str,
      }
    """
    if not title:
        slug = re.sub(r'[-_]', ' ', url.rstrip('/').split('/')[-1].split('?')[0])
        slug = re.sub(r'[^a-zA-Z\s]', ' ', slug)
        title = ' '.join(slug.split()).title() or 'Unknown Role'

    description = fetch_job_description(url)
    has_desc = bool(description and len(description) > 100)
    desc_section = f'\n\nJOB DESCRIPTION:\n{description[:3000]}' if has_desc else ''

    prompt = f"""You are a senior tech recruiter. Do a skill-by-skill fit analysis for this candidate.

CANDIDATE RESUME:
{resume_text[:2500]}

JOB:
Title: {title}
Company: {company or "unknown"}{desc_section}

Reply ONLY in this exact JSON format (no markdown, no extra text):
{{
  "score": <0-100>,
  "verdict": "<Weak|Moderate|Good|Strong>",
  "title": "<actual job title from the description; keep the given title if no description>",
  "company": "<company name from the description, or the given company>",
  "matched": [
    {{"skill": "<skill name>", "evidence": "<where it appears on resume, max 8 words>"}},
    ...
  ],
  "missing": [
    {{"skill": "<skill name>", "required": "<mandatory or nice-to-have, max 8 words>"}},
    ...
  ],
  "partial": [
    {{"skill": "<skill name>", "note": "<what they have vs what's needed, max 10 words>"}},
    ...
  ],
  "recommendation": "<one sentence: apply / apply with cover note / skip>"
}}

Rules:
- matched: skills the JOB explicitly requires or prefers AND that are clearly present on the resume (0-6 items). Do NOT list resume skills the job never asks for.
- missing: skills explicitly required or preferred in JD but absent from resume (2-5 items)
- partial: skills where the JD asks for X and the candidate has something related but not X (0-3 items). e.g. JD wants Ruby, candidate has Java → partial or missing, never matched.
- Scoring: Strong 80+, Good 65-79, Moderate 40-64, Weak <40
- Be specific — use actual skill names, not vague terms like "experience" """

    raw = _call_gemini(prompt, api_key=api_key)
    result = json.loads(_extract_json(raw, kind='object'))
    result['description_used'] = has_desc
    if not result.get('title'):
        result['title'] = title
    if not result.get('company'):
        result['company'] = company
    result.setdefault('matched', [])
    result.setdefault('missing', [])
    result.setdefault('partial', [])
    result['url'] = url
    return result


def score_fit_batch_urls(urls: list[str], resume_text: str, api_key: str = '') -> list[dict]:
    """Fetch descriptions for multiple URLs and score all in ONE Gemini call.

    Returns list of result dicts sorted by score descending.
    Each dict has same shape as score_fit() plus 'url' and 'description_used'.
    """
    # Step 1 — fetch descriptions for all URLs
    jobs = []
    for url in urls:
        slug = re.sub(r'[-_]', ' ', url.rstrip('/').split('/')[-1].split('?')[0])
        slug = re.sub(r'[^a-zA-Z\s]', ' ', slug)
        title = ' '.join(slug.split()).title() or 'Unknown Role'
        description = fetch_job_description(url)
        has_desc = bool(description and len(description) > 100)
        jobs.append({
            'url': url,
            'title': title,
            'description': description[:2000] if has_desc else '',
            'description_used': has_desc,
        })

    # Step 2 — build one batched prompt
    job_lines = []
    for i, j in enumerate(jobs):
        desc_part = f"\n   Description: {j['description'][:500]}" if j['description'] else ''
        job_lines.append(f"{i + 1}. {j['title']} — {j['url']}{desc_part}")

    prompt = f"""You are a senior tech recruiter. Score each job's fit for this candidate.

CANDIDATE RESUME:
{resume_text[:2500]}

JOBS TO SCORE:
{chr(10).join(job_lines)}

Reply ONLY with a JSON array — one object per job, same order, no extra text:
[
  {{
    "score": <0-100>,
    "verdict": "<Weak|Moderate|Good|Strong>",
    "title": "<job title, clean>",
    "company": "<company name, infer from URL/description if possible>",
    "strengths": "<2-3 concrete matching points>",
    "gaps": "<2-3 concrete missing requirements>",
    "recommendation": "<one sentence: apply / apply with cover note / skip>"
  }},
  ...
]

Scoring: Strong 80+, Good 65-79, Moderate 40-64, Weak <40. Be honest and specific."""

    raw = _call_gemini(prompt, api_key=api_key)
    results = json.loads(_extract_json(raw, kind='array'))

    # Merge url + description_used back in and sort by score desc
    for i, r in enumerate(results):
        if i < len(jobs):
            r['url'] = jobs[i]['url']
            r['description_used'] = jobs[i]['description_used']

    results.sort(key=lambda x: x.get('score', 0), reverse=True)
    return results
