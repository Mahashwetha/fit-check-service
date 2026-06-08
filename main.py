"""
Fit-Check Service — FastAPI app.

Endpoints:
  GET  /                → HTML UI (single + multi-URL tabs)
  POST /fit-check       → single job (multipart: url + resume file)
  POST /fit-check/batch → multiple jobs (multipart: urls + resume file)
  POST /fit-check/json  → single job (JSON body)
  GET  /health
"""

import os
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List

from resume_parser import parse_resume
from scorer import score_fit, score_fit_batch_urls

app = FastAPI(title='Fit-Check Service', version='1.1')


# ── HTML UI ───────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fit-Check — Job Fit Analyser</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #f0f4f8;
    min-height: 100vh;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 40px 16px;
  }
  .card {
    background: white;
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    padding: 36px;
    width: 100%;
    max-width: 680px;
  }
  h1 { font-size: 22px; color: #1a202c; margin-bottom: 4px; }
  .subtitle { color: #718096; font-size: 13px; margin-bottom: 24px; }

  /* Tabs */
  .tabs { display: flex; gap: 0; border-bottom: 2px solid #e2e8f0; margin-bottom: 24px; }
  .tab {
    padding: 8px 20px; font-size: 13px; font-weight: 600; color: #718096;
    cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px;
    transition: color .15s, border-color .15s;
  }
  .tab.active { color: #667eea; border-bottom-color: #667eea; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  label { display: block; font-size: 13px; font-weight: 600; color: #2d3748; margin-bottom: 6px; }
  input[type="url"], input[type="text"], textarea {
    width: 100%; padding: 10px 12px; border: 1px solid #e2e8f0;
    border-radius: 8px; font-size: 13px; outline: none; transition: border-color .15s;
    font-family: inherit;
  }
  input[type="url"]:focus, input[type="text"]:focus, textarea:focus { border-color: #667eea; }
  textarea { resize: vertical; min-height: 100px; }
  .file-drop {
    border: 2px dashed #e2e8f0; border-radius: 8px; padding: 20px;
    text-align: center; cursor: pointer; transition: border-color .15s, background .15s;
    font-size: 13px; color: #718096;
  }
  .file-drop:hover, .file-drop.over { border-color: #667eea; background: #f7f8ff; }
  .file-drop input { display: none; }
  .file-name { margin-top: 6px; font-size: 12px; color: #667eea; font-weight: 600; }
  .field { margin-bottom: 18px; }
  .row { display: flex; gap: 12px; }
  .row .field { flex: 1; }
  .hint { font-size: 11px; color: #a0aec0; margin-top: 4px; }
  button[type="submit"] {
    width: 100%; padding: 12px; background: linear-gradient(135deg, #667eea, #764ba2);
    color: white; border: none; border-radius: 8px; font-size: 15px; font-weight: 600;
    cursor: pointer; transition: opacity .15s; margin-top: 4px;
  }
  button[type="submit"]:hover { opacity: .9; }
  button[type="submit"]:disabled { opacity: .6; cursor: not-allowed; }

  /* Single result */
  .result-block { margin-top: 28px; }
  .score-row { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; }
  .score-circle {
    width: 72px; height: 72px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 22px; font-weight: 700; color: white; flex-shrink: 0;
  }
  .verdict-badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; }
  .score-bar-wrap { background: #edf2f7; border-radius: 4px; height: 8px; width: 100%; margin-top: 6px; }
  .score-bar { height: 8px; border-radius: 4px; transition: width .6s ease; }
  .section { margin-bottom: 14px; }
  .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; color: #718096; margin-bottom: 6px; }
  .section-body { font-size: 13px; color: #2d3748; line-height: 1.6; }
  .rec { background: #f7f8ff; border-left: 3px solid #667eea; padding: 10px 14px; border-radius: 0 6px 6px 0; font-size: 13px; color: #2d3748; }
  .desc-note { font-size: 11px; color: #a0aec0; margin-top: 12px; }

  /* Batch results table */
  .batch-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 20px; }
  .batch-table th {
    background: linear-gradient(135deg, #667eea, #764ba2); color: white;
    padding: 8px 10px; text-align: left; font-size: 11px;
  }
  .batch-table td { padding: 8px 10px; border-bottom: 1px solid #edf2f7; vertical-align: top; }
  .batch-table tr:hover td { background: #f7f8ff; }
  .batch-table tr.strong td { border-left: 3px solid #48bb78; }
  .batch-table tr.good td { border-left: 3px solid #68d391; }
  .batch-table tr.moderate td { border-left: 3px solid #f6ad55; }
  .batch-table tr.weak td { border-left: 3px solid #fc8181; }
  .job-title a { color: #2d3748; font-weight: 600; text-decoration: none; }
  .job-title a:hover { color: #667eea; text-decoration: underline; }
  .job-company { color: #718096; font-size: 11px; }
  .score-chip {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 11px; font-weight: 700; white-space: nowrap;
  }
  .gaps-text { font-size: 11px; color: #718096; }
  .rec-text { font-size: 11px; color: #2d3748; font-style: italic; }
  .desc-chip {
    display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 10px;
    background: #e2e8f0; color: #718096; margin-top: 3px;
  }
  .desc-chip.ok { background: #c6f6d5; color: #276749; }

  .error-box { background: #fff5f5; border: 1px solid #fed7d7; border-radius: 8px; padding: 12px 16px; color: #c53030; font-size: 13px; margin-top: 20px; }
  .spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid rgba(255,255,255,.4); border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
  hr.divider { border: none; border-top: 1px solid #edf2f7; margin: 24px 0; }
</style>
</head>
<body>
<div class="card">
  <h1>🎯 Fit-Check</h1>
  <p class="subtitle">Score job postings against your resume using Gemini AI.</p>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('single', this)">Single Job</div>
    <div class="tab" onclick="switchTab('multi', this)">Compare Multiple Jobs</div>
  </div>

  <!-- ── Single Job Tab ── -->
  <div class="tab-panel active" id="tab-single">
    <form id="form-single">
      <div class="field">
        <label>Job URL</label>
        <input type="url" id="s-url" placeholder="https://www.welcometothejungle.com/..." required>
      </div>
      <div class="row">
        <div class="field">
          <label>Job Title <span style="font-weight:400;color:#a0aec0">(optional)</span></label>
          <input type="text" id="s-title" placeholder="Senior Backend Engineer">
        </div>
        <div class="field">
          <label>Company <span style="font-weight:400;color:#a0aec0">(optional)</span></label>
          <input type="text" id="s-company" placeholder="Acme Corp">
        </div>
      </div>
      <div class="field">
        <label>Resume (PDF or DOCX)</label>
        <div class="file-drop" id="s-drop" onclick="document.getElementById('s-resume').click()">
          <input type="file" id="s-resume" accept=".pdf,.docx" required>
          <div>📄 Click to upload or drag & drop</div>
          <div class="file-name" id="s-fname"></div>
        </div>
      </div>
      <button type="submit" id="s-btn">Analyse Fit</button>
    </form>
    <div id="s-result"></div>
  </div>

  <!-- ── Multi Job Tab ── -->
  <div class="tab-panel" id="tab-multi">
    <form id="form-multi">
      <div class="field">
        <label>Job URLs — one per line</label>
        <textarea id="m-urls" placeholder="https://www.welcometothejungle.com/...&#10;https://www.linkedin.com/jobs/view/...&#10;https://builtin.com/job/..." required></textarea>
        <div class="hint">Paste up to 10 URLs. Descriptions are fetched automatically.</div>
      </div>
      <div class="field">
        <label>Resume (PDF or DOCX)</label>
        <div class="file-drop" id="m-drop" onclick="document.getElementById('m-resume').click()">
          <input type="file" id="m-resume" accept=".pdf,.docx" required>
          <div>📄 Click to upload or drag & drop</div>
          <div class="file-name" id="m-fname"></div>
        </div>
      </div>
      <button type="submit" id="m-btn">Compare All Jobs</button>
    </form>
    <div id="m-result"></div>
  </div>
</div>

<script>
// ── Tab switching ──
function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

// ── File drop wiring ──
function wireFileDrop(dropId, inputId, fnameId) {
  const drop = document.getElementById(dropId);
  const inp  = document.getElementById(inputId);
  const fn   = document.getElementById(fnameId);
  inp.addEventListener('change', () => { fn.textContent = inp.files[0]?.name || ''; });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) { inp.files = e.dataTransfer.files; fn.textContent = e.dataTransfer.files[0].name; }
  });
}
wireFileDrop('s-drop', 's-resume', 's-fname');
wireFileDrop('m-drop', 'm-resume', 'm-fname');

// ── Colour helpers ──
const C = {
  Strong:   { bg: '#276749', bar: '#48bb78', chip: 'background:#c6f6d5;color:#276749' },
  Good:     { bg: '#2f855a', bar: '#68d391', chip: 'background:#c6f6d5;color:#2f855a' },
  Moderate: { bg: '#975a16', bar: '#f6ad55', chip: 'background:#fefcbf;color:#975a16' },
  Weak:     { bg: '#9b2c2c', bar: '#fc8181', chip: 'background:#fed7d7;color:#9b2c2c' },
};
function c(v) { return C[v] || C.Moderate; }

// ── Single result renderer ──
function renderSingle(data) {
  const col = c(data.verdict);
  return `
    <hr class="divider">
    <div class="score-row">
      <div class="score-circle" style="background:${col.bg}">${data.score}</div>
      <div style="flex:1">
        <div style="font-size:15px;font-weight:700;color:#1a202c;margin-bottom:4px;">
          ${data.title}${data.company ? ' @ ' + data.company : ''}
        </div>
        <span class="verdict-badge" style="${col.chip}">${data.verdict}</span>
        <div class="score-bar-wrap" style="margin-top:8px">
          <div class="score-bar" style="width:${data.score}%;background:${col.bar}"></div>
        </div>
      </div>
    </div>
    <div class="section"><div class="section-title">✅ Strengths</div><div class="section-body">${data.strengths}</div></div>
    <div class="section"><div class="section-title">⚠️ Gaps</div><div class="section-body">${data.gaps}</div></div>
    <div class="rec">${data.recommendation}</div>
    <p class="desc-note">${data.description_used
      ? '✓ Full description fetched.'
      : '⚠ Description unavailable — title-based estimate.'}</p>`;
}

// ── Batch result renderer ──
function renderBatch(results) {
  const rows = results.map(d => {
    const col = c(d.verdict);
    const descChip = d.description_used
      ? '<span class="desc-chip ok">desc ✓</span>'
      : '<span class="desc-chip">title only</span>';
    return `<tr class="${d.verdict.toLowerCase()}">
      <td>
        <div class="job-title"><a href="${d.url}" target="_blank">${d.title}</a></div>
        <div class="job-company">${d.company || ''}</div>
        ${descChip}
      </td>
      <td><span class="score-chip" style="${col.chip}">${d.score}% ${d.verdict}</span></td>
      <td><div class="gaps-text">${d.gaps}</div></td>
      <td><div class="rec-text">${d.recommendation}</div></td>
    </tr>`;
  }).join('');

  return `
    <hr class="divider">
    <div style="font-size:13px;font-weight:600;color:#2d3748;margin-bottom:8px;">
      📊 ${results.length} jobs scored — sorted by fit
    </div>
    <table class="batch-table">
      <thead>
        <tr>
          <th width="30%">Job</th>
          <th width="14%">Score</th>
          <th width="28%">Gaps</th>
          <th width="28%">Verdict</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ── Single form submit ──
document.getElementById('form-single').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('s-btn');
  const out = document.getElementById('s-result');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Analysing…';
  out.innerHTML = '';

  const fd = new FormData();
  fd.append('url',     document.getElementById('s-url').value.trim());
  fd.append('title',   document.getElementById('s-title').value.trim());
  fd.append('company', document.getElementById('s-company').value.trim());
  fd.append('resume',  document.getElementById('s-resume').files[0]);

  try {
    const resp = await fetch('/fit-check', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
    out.innerHTML = renderSingle(data);
  } catch(err) {
    out.innerHTML = `<div class="error-box">❌ ${err.message}</div>`;
  } finally {
    btn.disabled = false; btn.innerHTML = 'Analyse Fit';
  }
});

// ── Multi form submit ──
document.getElementById('form-multi').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('m-btn');
  const out = document.getElementById('m-result');
  btn.disabled = true;

  const urls = document.getElementById('m-urls').value
    .split('\\n').map(u => u.trim()).filter(u => u.startsWith('http'));
  if (!urls.length) { out.innerHTML = '<div class="error-box">❌ No valid URLs found.</div>'; btn.disabled = false; return; }

  btn.innerHTML = `<span class="spinner"></span>Fetching & scoring ${urls.length} jobs…`;
  out.innerHTML = '';

  const fd = new FormData();
  urls.forEach(u => fd.append('urls', u));
  fd.append('resume', document.getElementById('m-resume').files[0]);

  try {
    const resp = await fetch('/fit-check/batch', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || JSON.stringify(data));
    out.innerHTML = renderBatch(data.results);
  } catch(err) {
    out.innerHTML = `<div class="error-box">❌ ${err.message}</div>`;
  } finally {
    btn.disabled = false; btn.innerHTML = 'Compare All Jobs';
  }
});
</script>
</body>
</html>"""


@app.get('/', response_class=HTMLResponse)
def index():
    return HTML


# ── Single job endpoint ───────────────────────────────────────────────────────

@app.post('/fit-check')
async def fit_check_upload(
    url: str = Form(...),
    title: str = Form(''),
    company: str = Form(''),
    resume: UploadFile = File(...),
):
    file_bytes = await resume.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail='Resume file is empty.')
    try:
        resume_text = parse_resume(file_bytes, resume.filename or 'resume.pdf')
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if len(resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail='Could not extract text from resume. Try a different file.')
    try:
        result = score_fit(url, resume_text, title=title, company=company)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Scoring failed: {e}')
    return JSONResponse(content=result)


# ── Batch endpoint ────────────────────────────────────────────────────────────

@app.post('/fit-check/batch')
async def fit_check_batch(
    urls: List[str] = Form(...),
    resume: UploadFile = File(...),
):
    if not urls:
        raise HTTPException(status_code=400, detail='At least one URL is required.')
    if len(urls) > 10:
        raise HTTPException(status_code=400, detail='Maximum 10 URLs per batch.')

    # Filter valid URLs
    valid_urls = [u.strip() for u in urls if u.strip().startswith('http')]
    if not valid_urls:
        raise HTTPException(status_code=400, detail='No valid URLs provided.')

    file_bytes = await resume.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail='Resume file is empty.')
    try:
        resume_text = parse_resume(file_bytes, resume.filename or 'resume.pdf')
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if len(resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail='Could not extract text from resume.')

    try:
        results = score_fit_batch_urls(valid_urls, resume_text)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Batch scoring failed: {e}')

    return JSONResponse(content={'results': results, 'count': len(results)})


# ── JSON endpoint (no file upload — resume as text) ───────────────────────────

class FitCheckJSON(BaseModel):
    url: str
    resume_text: str
    title: str = ''
    company: str = ''


@app.post('/fit-check/json')
def fit_check_json(body: FitCheckJSON):
    if len(body.resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail='resume_text is too short.')
    try:
        result = score_fit(body.url, body.resume_text, title=body.title, company=body.company)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Scoring failed: {e}')
    return result


@app.get('/health')
def health():
    return {'status': 'ok'}
