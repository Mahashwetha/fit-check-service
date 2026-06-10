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
from collections import defaultdict
from datetime import date
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List

from resume_parser import parse_resume
from scorer import score_fit, score_fit_batch_urls

app = FastAPI(title='Fit-Check Service', version='1.3')

# ── Per-IP daily quota ────────────────────────────────────────────────────────
# Structure: { ip: {"count": int, "date": date} }
_quota: dict = defaultdict(lambda: {"count": 0, "date": date.today()})
DAILY_FREE_LIMIT = 20

# ── Global server-wide daily counter ─────────────────────────────────────────
_global = {"count": 0, "date": date.today(), "alert_sent": False}
ALERT_THRESHOLD = 1400  # warn at this many total server requests/day


def _get_ip(request: Request) -> str:
    """Best-effort client IP (works behind Render's proxy)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_quota(ip: str) -> bool:
    """Returns True if the IP is within the free daily limit."""
    entry = _quota[ip]
    if entry["date"] != date.today():
        entry["count"] = 0
        entry["date"] = date.today()
    return entry["count"] < DAILY_FREE_LIMIT


def _increment_quota(ip: str):
    """Increment per-IP counter and global counter; fire alert if threshold crossed."""
    # Per-IP
    entry = _quota[ip]
    if entry["date"] != date.today():
        entry["count"] = 0
        entry["date"] = date.today()
    entry["count"] += 1

    # Global
    if _global["date"] != date.today():
        _global["count"] = 0
        _global["date"] = date.today()
        _global["alert_sent"] = False
    _global["count"] += 1

    if _global["count"] >= ALERT_THRESHOLD and not _global["alert_sent"]:
        _global["alert_sent"] = True
        print(f"[quota-alert] ⚠️ {_global['count']} server requests today — approaching Gemini free limit (1500).")


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
  .gaps-text { font-size: 11px; color: #2b4c8c; font-weight: 500; }
  .rec-text { font-size: 11px; color: #2d3748; font-style: italic; }
  .desc-chip {
    display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 10px;
    background: #e2e8f0; color: #718096; margin-top: 3px;
  }
  .desc-chip.ok { background: #c6f6d5; color: #276749; }

  .error-box { background: #fff5f5; border: 1px solid #fed7d7; border-radius: 8px; padding: 12px 16px; color: #c53030; font-size: 13px; margin-top: 20px; }
  .quota-box { background: #fffbeb; border: 1px solid #f6e05e; border-radius: 8px; padding: 16px; margin-top: 20px; font-size: 13px; color: #744210; }
  .quota-box strong { display: block; margin-bottom: 6px; font-size: 14px; }
  .quota-box a { color: #667eea; font-weight: 600; }
  .quota-key-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; }
  .quota-key-row input { flex: 1; padding: 8px 10px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 13px; font-family: inherit; }
  .quota-key-row button { padding: 8px 14px; background: linear-gradient(135deg,#667eea,#764ba2); color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
  .spinner { display: inline-block; width: 18px; height: 18px; border: 2px solid rgba(255,255,255,.4); border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
  hr.divider { border: none; border-top: 1px solid #edf2f7; margin: 24px 0; }

  /* Footer */
  .footer {
    margin-top: 32px; padding-top: 20px;
    border-top: 1px solid #edf2f7;
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 12px;
  }
  .footer-stats {
    font-size: 11px; color: #a0aec0;
    display: flex; align-items: center; gap: 6px;
  }
  .footer-stats .count {
    background: #edf2f7; color: #4a5568;
    padding: 2px 8px; border-radius: 10px;
    font-weight: 700; font-size: 11px;
  }
  .footer-links { display: flex; gap: 8px; }
  .footer-btn {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 6px 12px; border-radius: 6px;
    font-size: 12px; font-weight: 600; text-decoration: none;
    transition: opacity .15s;
  }
  .footer-btn:hover { opacity: .8; }
  .footer-btn.linkedin { background: #0a66c2; color: white; }
  .footer-btn.github   { background: #24292f; color: white; }
</style>
</head>
<body>
<div class="card">
  <h1>🎯 Fit-Check</h1>
  <p class="subtitle">Score job postings against your resume using Gemini AI.</p>

  <!-- ── API Key (only shown when server has no key configured) ── -->
  <div id="key-section" style="display:none;background:#f7f8ff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;margin-bottom:20px;">
    <label style="margin-bottom:4px;">🔑 Your Gemini API Key</label>
    <div style="display:flex;gap:8px;align-items:center;">
      <input type="password" id="api-key" placeholder="AIzaSy..." style="flex:1;margin:0;"
        oninput="saveKey(this.value)">
      <button type="button" onclick="toggleKey()" style="padding:8px 12px;background:#edf2f7;border:1px solid #e2e8f0;border-radius:6px;font-size:12px;cursor:pointer;white-space:nowrap;">Show</button>
    </div>
    <div style="font-size:11px;color:#a0aec0;margin-top:5px;">
      Free key at <a href="https://aistudio.google.com/apikey" target="_blank" style="color:#667eea;">aistudio.google.com/apikey</a> — never stored on server, sent only for your request.
    </div>
  </div>

  <!-- ── Shared Resume Upload ── -->
  <div class="field" id="resume-section">
    <label>📄 Your Resume <span style="font-weight:400;color:#a0aec0">(PDF or DOCX — shared across both tabs)</span></label>
    <div class="file-drop" id="shared-drop" onclick="document.getElementById('shared-resume').click()">
      <input type="file" id="shared-resume" accept=".pdf,.docx">
      <div>Click to upload or drag & drop</div>
      <div class="file-name" id="shared-fname"></div>
    </div>
  </div>

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
      <button type="submit" id="m-btn">Compare All Jobs</button>
    </form>
    <div id="m-result"></div>
  </div>

  <!-- ── Footer ── -->
  <div class="footer">
    <div class="footer-stats">
      <span>🔢 Today's checks:</span>
      <span class="count" id="stats-count">…</span>
    </div>
    <div style="text-align:right;">
      <div style="font-size:12px;color:#718096;margin-bottom:6px;">
        Built by <strong style="color:#2d3748;">Mahashwetha</strong>
      </div>
      <div class="footer-links">
        <a class="footer-btn linkedin" href="https://linkedin.com/in/mahashwetha-rao" target="_blank">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-10h3v10zm-1.5-11.268c-.966 0-1.75-.784-1.75-1.75s.784-1.75 1.75-1.75 1.75.784 1.75 1.75-.784 1.75-1.75 1.75zm13.5 11.268h-3v-5.604c0-1.337-.027-3.063-1.867-3.063-1.869 0-2.155 1.46-2.155 2.967v5.7h-3v-10h2.881v1.367h.041c.401-.761 1.381-1.563 2.845-1.563 3.042 0 3.604 2.002 3.604 4.604v5.592z"/></svg>
          LinkedIn
        </a>
        <a class="footer-btn github" href="https://github.com/Mahashwetha/fit-check-service" target="_blank">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
          GitHub
        </a>
      </div>
    </div>
  </div>
</div>

<script>
// ── API key persistence ──
function saveKey(v) { try { localStorage.setItem('fitcheck_key', v); } catch(e) {} }
function loadKey() { try { return localStorage.getItem('fitcheck_key') || ''; } catch(e) { return ''; } }
function toggleKey() {
  const inp = document.getElementById('api-key');
  const btn = event.target;
  if (inp.type === 'password') { inp.type = 'text'; btn.textContent = 'Hide'; }
  else { inp.type = 'password'; btn.textContent = 'Show'; }
}
// Returns the api_key to send — empty string when server has its own key
function getApiKey() {
  const section = document.getElementById('key-section');
  if (section.style.display === 'none') return '';
  return document.getElementById('api-key').value.trim();
}
window.addEventListener('load', async () => {
  loadStats();
  try {
    const res = await fetch('/config');
    const cfg = await res.json();
    if (cfg.key_configured) {
      // Server has a key — hide the field entirely and clear any stale stored key
      document.getElementById('key-section').style.display = 'none';
      try { localStorage.removeItem('fitcheck_key'); } catch(e) {}
    } else {
      // Server has no key — show the field and restore from localStorage
      document.getElementById('key-section').style.display = 'block';
      document.getElementById('api-key').value = loadKey();
    }
  } catch(e) {
    // If /config fails, fall back to showing the field
    document.getElementById('key-section').style.display = 'block';
    document.getElementById('api-key').value = loadKey();
  }
});

// ── Footer stats ──
async function loadStats() {
  try {
    const res = await fetch('/stats');
    const d = await res.json();
    document.getElementById('stats-count').textContent = d.requests_today;
  } catch(e) {
    document.getElementById('stats-count').textContent = '—';
  }
}

// ── Quota limit UI ──
// kind: 'personal' = this IP used its daily free checks
//       'server'   = the server's shared Gemini key is rate-limited by Google
function showQuotaPrompt(outEl, retryFn, kind) {
  const heading = kind === 'server'
    ? "🚦 The server's Gemini key is rate-limited"
    : "🚦 You've used your 20 free checks today";
  const body = kind === 'server'
    ? 'Too many requests right now — wait a minute and retry, or continue immediately with your own free Gemini API key.<br>'
    : 'You can continue with your own free Gemini API key — resets tomorrow otherwise.<br>';
  outEl.innerHTML = `
    <div class="quota-box">
      <strong>${heading}</strong>
      ${body}
      Get one in 30 seconds at <a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a>
      <div class="quota-key-row">
        <input type="password" id="quota-key-input" placeholder="Paste your key here (AIzaSy...)">
        <button onclick="applyQuotaKey(this, arguments[0])">Continue →</button>
      </div>
      <div style="font-size:11px;color:#a0aec0;margin-top:5px;">Key is only used for your requests — never stored on the server.</div>
    </div>`;
  // store retry callback so applyQuotaKey can call it
  outEl._retryFn = retryFn;
}

function applyQuotaKey(btn, ev) {
  const box = btn.closest('.quota-box');
  const keyVal = document.getElementById('quota-key-input').value.trim();
  if (!keyVal) { alert('Please paste a key first.'); return; }
  // Save to localStorage and show the key section for future visits
  saveKey(keyVal);
  document.getElementById('api-key').value = keyVal;
  document.getElementById('key-section').style.display = 'block';
  // Clear the quota box and retry the submission
  const outEl = box.closest('[id$="-result"]');
  outEl.innerHTML = '';
  if (outEl._retryFn) outEl._retryFn(keyVal);
}

// ── Tab switching ──
function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}

// ── Shared file drop wiring ──
(function() {
  const drop = document.getElementById('shared-drop');
  const inp  = document.getElementById('shared-resume');
  const fn   = document.getElementById('shared-fname');
  inp.addEventListener('change', () => { fn.textContent = inp.files[0]?.name || ''; });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) { inp.files = e.dataTransfer.files; fn.textContent = e.dataTransfer.files[0].name; }
  });
})();

function getResumeFile() { return document.getElementById('shared-resume').files[0]; }

// ── Colour helpers ──
const C = {
  Strong:   { bg: '#276749', bar: '#48bb78', chip: 'background:#c6f6d5;color:#276749' },
  Good:     { bg: '#2f855a', bar: '#68d391', chip: 'background:#c6f6d5;color:#2f855a' },
  Moderate: { bg: '#975a16', bar: '#f6ad55', chip: 'background:#fefcbf;color:#975a16' },
  Weak:     { bg: '#9b2c2c', bar: '#fc8181', chip: 'background:#fed7d7;color:#9b2c2c' },
};
function c(v) { return C[v] || C.Moderate; }

// ── Single result renderer ──
function renderSkillRow(icon, bgColor, textColor, skill, detail) {
  return `<div style="display:flex;align-items:flex-start;gap:10px;padding:7px 10px;border-radius:6px;background:${bgColor};margin-bottom:5px;">
    <span style="font-size:13px;flex-shrink:0;margin-top:1px;">${icon}</span>
    <div>
      <span style="font-weight:700;font-size:13px;color:${textColor};">${skill}</span>
      <span style="font-size:12px;color:#718096;margin-left:6px;">${detail}</span>
    </div>
  </div>`;
}

function renderSingle(data) {
  const col = c(data.verdict);

  const matchedRows = (data.matched || []).map(m =>
    renderSkillRow('✅', '#f0fff4', '#276749', m.skill, m.evidence)
  ).join('');

  const partialRows = (data.partial || []).map(p =>
    renderSkillRow('⚠️', '#fffff0', '#975a16', p.skill, p.note)
  ).join('');

  const missingRows = (data.missing || []).map(m =>
    renderSkillRow('❌', '#fff5f5', '#9b2c2c', m.skill, m.required)
  ).join('');

  const extraRows = (data.extra || []).map(m =>
    renderSkillRow('➕', '#f7fafc', '#4a5568', m.skill, m.evidence || m.note || '')
  ).join('');

  const extraSection = extraRows ? `
    <div style="margin-top:10px;font-size:11px;font-weight:600;color:#a0aec0;text-transform:uppercase;letter-spacing:0.5px;">On your resume — not requested in this job</div>
    ${extraRows}` : '';

  const skillSection = (matchedRows || partialRows || missingRows || extraRows) ? `
    <div class="section">
      <div class="section-title">Skill Breakdown</div>
      ${matchedRows}${partialRows}${missingRows}
      ${extraSection}
      <div style="font-size:11px;color:#a0aec0;margin-top:8px;">Score weighs overall fit — seniority, domain, location — not just the count of exact skill matches.</div>
    </div>` : '';

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
    ${skillSection}
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
async function submitSingle(overrideKey) {
  const btn = document.getElementById('s-btn');
  const out = document.getElementById('s-result');
  if (!getResumeFile()) { out.innerHTML = '<div class="error-box">❌ Please upload your resume first.</div>'; return; }
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Analysing…';
  if (!overrideKey) out.innerHTML = '';

  const fd = new FormData();
  fd.append('url',     document.getElementById('s-url').value.trim());
  fd.append('title',   document.getElementById('s-title').value.trim());
  fd.append('company', document.getElementById('s-company').value.trim());
  fd.append('api_key', overrideKey || getApiKey());
  fd.append('resume',  getResumeFile());

  try {
    const resp = await fetch('/fit-check', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) {
      if (data.detail === 'daily_limit_reached' || (data.detail||'').toLowerCase().includes('rate limit')) {
        showQuotaPrompt(out, k => submitSingle(k), data.detail === 'daily_limit_reached' ? 'personal' : 'server');
        return;
      }
      throw new Error(data.detail || JSON.stringify(data));
    }
    out.innerHTML = renderSingle(data);
    loadStats();
  } catch(err) {
    out.innerHTML = `<div class="error-box">❌ ${err.message}</div>`;
  } finally {
    btn.disabled = false; btn.innerHTML = 'Analyse Fit';
  }
}
document.getElementById('form-single').addEventListener('submit', e => { e.preventDefault(); submitSingle(); });

// ── Multi form submit ──
async function submitMulti(overrideKey) {
  const btn = document.getElementById('m-btn');
  const out = document.getElementById('m-result');
  if (!getResumeFile()) { out.innerHTML = '<div class="error-box">❌ Please upload your resume first.</div>'; btn.disabled = false; return; }
  btn.disabled = true;

  const urls = document.getElementById('m-urls').value
    .split('\\n').map(u => u.trim()).filter(u => u.startsWith('http'));
  if (!urls.length) { out.innerHTML = '<div class="error-box">❌ No valid URLs found.</div>'; btn.disabled = false; return; }

  btn.innerHTML = `<span class="spinner"></span>Fetching & scoring ${urls.length} jobs…`;
  if (!overrideKey) out.innerHTML = '';

  const fd = new FormData();
  urls.forEach(u => fd.append('urls', u));
  fd.append('api_key', overrideKey || getApiKey());
  fd.append('resume', getResumeFile());

  try {
    const resp = await fetch('/fit-check/batch', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) {
      if (data.detail === 'daily_limit_reached' || (data.detail||'').toLowerCase().includes('rate limit')) {
        showQuotaPrompt(out, k => submitMulti(k), data.detail === 'daily_limit_reached' ? 'personal' : 'server');
        return;
      }
      throw new Error(data.detail || JSON.stringify(data));
    }
    out.innerHTML = renderBatch(data.results);
    loadStats();
  } catch(err) {
    out.innerHTML = `<div class="error-box">❌ ${err.message}</div>`;
  } finally {
    btn.disabled = false; btn.innerHTML = 'Compare All Jobs';
  }
}
document.getElementById('form-multi').addEventListener('submit', e => { e.preventDefault(); submitMulti(); });
</script>
</body>
</html>"""


@app.get('/', response_class=HTMLResponse)
def index():
    return HTML


# ── Single job endpoint ───────────────────────────────────────────────────────

@app.post('/fit-check')
async def fit_check_upload(
    request: Request,
    url: str = Form(...),
    title: str = Form(''),
    company: str = Form(''),
    api_key: str = Form(''),
    resume: UploadFile = File(...),
):
    ip = _get_ip(request)
    if not api_key and not _check_quota(ip):
        raise HTTPException(status_code=429, detail='daily_limit_reached')

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
        result = score_fit(url, resume_text, title=title, company=company, api_key=api_key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Scoring failed: {e}')
    if not api_key:
        _increment_quota(ip)
    return JSONResponse(content=result)


# ── Batch endpoint ────────────────────────────────────────────────────────────

@app.post('/fit-check/batch')
async def fit_check_batch(
    request: Request,
    urls: List[str] = Form(...),
    api_key: str = Form(''),
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

    ip = _get_ip(request)
    # Batch counts as one request against quota
    if not api_key and not _check_quota(ip):
        raise HTTPException(status_code=429, detail='daily_limit_reached')

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
        results = score_fit_batch_urls(valid_urls, resume_text, api_key=api_key)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Batch scoring failed: {e}')

    if not api_key:
        _increment_quota(ip)
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


@app.get('/stats')
def stats():
    """Today's server-wide request count."""
    today = date.today()
    count = _global["count"] if _global["date"] == today else 0
    return {
        'date': str(today),
        'requests_today': count,
        'alert_threshold': ALERT_THRESHOLD,
        'alert_sent': _global["alert_sent"] if _global["date"] == today else False,
    }


@app.get('/config')
def config():
    """Tells the UI whether the server has a Gemini key pre-configured.
    If yes → hide the key field. If no → show it so users bring their own.
    """
    return {'key_configured': bool(os.environ.get('GEMINI_API_KEY', ''))}
