// ═══════════════════════════════════════════════════════════════════════════
//  Card Wash — Frontend Logic
// ═══════════════════════════════════════════════════════════════════════════

const API = '';  // same origin

// Load server-side default config (env vars)
(async function loadDefaults() {
  try {
    const res = await fetch(`${API}/api/config`);
    if (!res.ok) return;
    const cfg = await res.json();
    if (cfg.provider) {
      const sel = document.getElementById('llmProvider');
      if (sel) { sel.value = cfg.provider; sel.dispatchEvent(new Event('change')); }
      const bsel = document.getElementById('batchProvider');
      if (bsel) { bsel.value = cfg.provider; bsel.dispatchEvent(new Event('change')); }
    }
    if (cfg.model) {
      const m = document.getElementById('llmModel');
      if (m) m.value = cfg.model;
      const bm = document.getElementById('batchModel');
      if (bm) bm.value = cfg.model;
    }
    if (cfg.base_url) {
      const bu = document.getElementById('llmBaseUrl');
      if (bu) bu.value = cfg.base_url;
      const bbu = document.getElementById('batchBaseUrl');
      if (bbu) bbu.value = cfg.base_url;
    }
    if (cfg.has_key) {
      // Server has a default key — show placeholder
      const k = document.getElementById('llmApiKey');
      if (k) k.placeholder = '已配置服务端默认 Key';
      const bk = document.getElementById('batchApiKey');
      if (bk) bk.placeholder = '已配置服务端默认 Key';
    }
  } catch (_) {}
})();

// ── State ────────────────────────────────────────────────────────────────
let state = {
  sessionId: null,
  card: null,
  avatar: '',
  analysis: null,
  rewritableFields: [],
  rewriteResult: null,     // {original, rewritten}
  acceptedFields: {},      // field -> 'accept' | 'reject'
  currentStrength: 'medium',
};

// ── DOM refs ─────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const pages = {
  upload:  $('#page-upload'),
  analyze: $('#page-analyze'),
  rewrite: $('#page-rewrite'),
  export:  $('#page-export'),
};

// ═══════════════════════════════════════════════════════════════════════════
//  Navigation
// ═══════════════════════════════════════════════════════════════════════════

function goToPage(name) {
  Object.values(pages).forEach(p => p.classList.remove('active'));
  pages[name].classList.add('active');

  $$('.steps-nav .step').forEach(btn => {
    const s = btn.dataset.step;
    btn.classList.remove('active');
    btn.disabled = true;
    if (s === name) {
      btn.classList.add('active');
      btn.disabled = false;
    }
  });

  // Enable previous steps
  const order = ['upload', 'analyze', 'rewrite', 'export'];
  const idx = order.indexOf(name);
  for (let i = 0; i <= idx; i++) {
    const btn = $(`.step[data-step="${order[i]}"]`);
    btn.disabled = false;
    if (i < idx) btn.classList.add('done');
  }
}

$$('.steps-nav .step').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!btn.disabled) goToPage(btn.dataset.step);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
//  Toast
// ═══════════════════════════════════════════════════════════════════════════

function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  $('#toastContainer').appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

// ═══════════════════════════════════════════════════════════════════════════
//  Upload
// ═══════════════════════════════════════════════════════════════════════════

const uploadZone = $('#uploadZone');
const fileInput = $('#fileInput');

uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('dragover');
});
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files.length) handleFile(fileInput.files[0]);
});

async function handleFile(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['png', 'webp', 'charx', 'json'].includes(ext)) {
    toast('仅支持 .png / .webp / .charx / .json 文件', 'error');
    return;
  }

  const form = new FormData();
  form.append('file', file);

  toast('上传中...');

  try {
    const res = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    state.sessionId = data.session_id;
    state.card = data.card;
    state.avatar = data.avatar;
    state.analysis = data.analysis;
    state.rewritableFields = data.rewritable_fields;
    state.rewriteResult = null;
    state.acceptedFields = {};

    toast('解析成功！', 'success');
    renderAnalyze();
    goToPage('analyze');
  } catch (e) {
    toast(`上传失败: ${e.message}`, 'error');
  }
}

// ═══════════════════════════════════════════════════════════════════════════
//  Analyze page rendering
// ═══════════════════════════════════════════════════════════════════════════

function riskClass(score) {
  return `risk-${Math.min(score, 5)}`;
}

function riskLabel(score) {
  const labels = ['安全', '低风险', '中低', '中等', '高风险', '极高'];
  return labels[Math.min(score, 5)];
}

function riskColor(score) {
  if (score <= 1) return 'var(--success)';
  if (score <= 3) return 'var(--warning)';
  return 'var(--danger)';
}

function riskBg(score) {
  if (score <= 1) return 'var(--success-dim)';
  if (score <= 3) return 'var(--warning-dim)';
  return 'var(--danger-dim)';
}

const LANG_FLAGS = {
  en: '🇬🇧 English',
  zh: '🇨🇳 中文',
  ja: '🇯🇵 日本語',
  ko: '🇰🇷 한국어',
  mixed: '🌐 Mixed',
};

function renderAnalyze() {
  const { card, avatar, analysis } = state;
  const d = card.data;

  // Avatar
  const img = $('#cardAvatar');
  const placeholder = $('#avatarPlaceholder');
  if (avatar) {
    img.src = avatar;
    img.classList.add('visible');
    placeholder.style.display = 'none';
  } else {
    img.classList.remove('visible');
    placeholder.style.display = 'flex';
  }

  // Name and meta
  $('#cardName').textContent = d.name || d.char_name || 'Unknown';
  const meta = [];
  if (analysis.detected_language) {
    meta.push(LANG_FLAGS[analysis.detected_language] || analysis.detected_language);
  }
  if (d.creator) meta.push(`by ${d.creator}`);
  if (d.tags && d.tags.length) meta.push(d.tags.slice(0, 3).join(', '));
  $('#cardMeta').textContent = meta.join(' · ');

  // Overall risk
  const badge = $('#overallRisk');
  badge.textContent = `${riskLabel(analysis.overall_risk)} (${analysis.overall_risk}/5)`;
  badge.className = `risk-badge ${riskClass(analysis.overall_risk)}`;

  $('#riskSummary').textContent = analysis.summary;

  // Separate main fields, lorebook entries, and alternate greetings
  const mainFields = [];
  const lorebookFields = [];
  const greetingFields = [];
  for (const f of analysis.fields) {
    if (f.field_name.startsWith('lorebook:')) lorebookFields.push(f);
    else if (f.field_name.startsWith('alternate_greetings[')) greetingFields.push(f);
    else mainFields.push(f);
  }

  const list = $('#fieldsList');
  list.innerHTML = '';

  // Main fields
  for (const f of mainFields) {
    list.appendChild(buildFieldCard(f));
  }

  // Lorebook section (collapsible)
  if (lorebookFields.length) {
    const lorebookRisks = lorebookFields.filter(f => f.risk_score > 0);
    const section = document.createElement('div');
    section.className = 'field-group';
    section.innerHTML = `
      <div class="field-group-header" data-toggle="lorebook">
        <span class="field-group-toggle">▶</span>
        <span class="field-group-title">Lorebook</span>
        <span class="field-group-count">${lorebookFields.length} 条</span>
        ${lorebookRisks.length
          ? `<span class="field-group-risk" style="background:${riskBg(Math.max(...lorebookRisks.map(f=>f.risk_score)))};color:${riskColor(Math.max(...lorebookRisks.map(f=>f.risk_score)))}">${lorebookRisks.length} 条有风险</span>`
          : `<span class="field-group-risk" style="background:var(--success-dim);color:var(--success)">安全</span>`
        }
      </div>
      <div class="field-group-body" id="lorebookGroup" style="display:none"></div>
    `;
    list.appendChild(section);

    const body = section.querySelector('.field-group-body');
    for (const f of lorebookFields) {
      body.appendChild(buildFieldCard(f));
    }

    section.querySelector('.field-group-header').addEventListener('click', () => {
      const expanded = body.style.display !== 'none';
      body.style.display = expanded ? 'none' : 'flex';
      section.querySelector('.field-group-toggle').textContent = expanded ? '▶' : '▼';
    });
  }

  // Alternate greetings section (collapsible)
  if (greetingFields.length) {
    const section = document.createElement('div');
    section.className = 'field-group';
    section.innerHTML = `
      <div class="field-group-header" data-toggle="greetings">
        <span class="field-group-toggle">▶</span>
        <span class="field-group-title">Alternate Greetings</span>
        <span class="field-group-count">${greetingFields.length} 条</span>
      </div>
      <div class="field-group-body" id="greetingsGroup" style="display:none"></div>
    `;
    list.appendChild(section);

    const body = section.querySelector('.field-group-body');
    for (const f of greetingFields) {
      body.appendChild(buildFieldCard(f));
    }

    section.querySelector('.field-group-header').addEventListener('click', () => {
      const expanded = body.style.display !== 'none';
      body.style.display = expanded ? 'none' : 'flex';
      section.querySelector('.field-group-toggle').textContent = expanded ? '▶' : '▼';
    });
  }
}

function buildFieldCard(f) {
  const el = document.createElement('div');
  el.className = 'field-card';
  const preview = getFieldValue(f.field_name);
  el.innerHTML = `
    <div class="field-card-header">
      <span class="field-card-name">${f.field_name}</span>
      <span class="field-card-risk" style="background:${riskBg(f.risk_score)};color:${riskColor(f.risk_score)}">
        ${riskLabel(f.risk_score)}
      </span>
    </div>
    ${preview ? `<div class="field-card-preview">${escapeHtml(preview).slice(0, 150)}${preview.length > 150 ? '...' : ''}</div>` : ''}
    ${f.matches.length ? `<div class="field-card-matches">${f.matches.map(m => `<span class="match-tag">${escapeHtml(m.text)}</span>`).join('')}</div>` : ''}
  `;
  return el;
}

function getFieldValue(fieldName) {
  const d = state.card.data;
  // Handle lorebook entries — show actual content
  if (fieldName.startsWith('lorebook:')) {
    const book = d.character_book;
    if (!book || !book.entries) return '';
    // Parse the entry identifier (name or id)
    const key = fieldName.replace('lorebook:', '');
    const entry = book.entries.find(e =>
      (e.name && e.name === key) || String(e.id) === key
    ) || book.entries[parseInt(key)] || null;
    if (!entry) return '';
    const parts = [];
    if (entry.keys && entry.keys.length) parts.push(`[${entry.keys.join(', ')}]`);
    if (entry.content) parts.push(entry.content);
    return parts.join(' ') || '';
  }
  if (fieldName.startsWith('alternate_greetings[')) {
    const idx = parseInt(fieldName.match(/\[(\d+)\]/)?.[1] || '0');
    return (d.alternate_greetings || [])[idx] || '';
  }
  return d[fieldName] || '';
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

// ── Go to rewrite ────────────────────────────────────────────────────────

$('#goToRewrite').addEventListener('click', () => {
  renderRewriteConfig();
  goToPage('rewrite');
});

// ═══════════════════════════════════════════════════════════════════════════
//  Rewrite page
// ═══════════════════════════════════════════════════════════════════════════

function renderRewriteConfig() {
  // Field checkboxes
  const container = $('#fieldCheckboxes');
  container.innerHTML = '';
  const fieldAnalysisMap = {};
  for (const f of state.analysis.fields) {
    fieldAnalysisMap[f.field_name] = f;
  }

  const forceMode = $('#forceRewrite').checked;

  for (const fname of state.rewritableFields) {
    const fa = fieldAnalysisMap[fname];
    const score = fa ? fa.risk_score : 0;
    // In force mode, auto-select all; otherwise only risky fields
    const checked = forceMode || score >= 2 ? 'checked' : '';
    const label = document.createElement('label');
    label.className = 'field-checkbox';
    label.innerHTML = `
      <input type="checkbox" value="${fname}" ${checked} />
      <span class="field-checkbox-label">${fname}</span>
      <span class="field-checkbox-risk" style="background:${riskBg(score)};color:${riskColor(score)}">${score}</span>
    `;
    container.appendChild(label);
  }
}

// Force rewrite toggle: re-render field checkboxes when toggled
document.addEventListener('DOMContentLoaded', () => {
  const forceEl = $('#forceRewrite');
  if (forceEl) {
    forceEl.addEventListener('change', () => {
      if (state.rewritableFields.length) renderRewriteConfig();
    });
  }
});

// Provider change → show/hide base URL
$('#llmProvider').addEventListener('change', (e) => {
  $('#baseUrlGroup').style.display = e.target.value === 'openai_compatible' ? 'block' : 'none';
  // Update default model
  if (e.target.value === 'anthropic') {
    $('#llmModel').value = 'claude-sonnet-4-20250514';
  } else if (e.target.value === 'openai') {
    $('#llmModel').value = 'gpt-4o-mini';
  }
});

// Strength buttons
const strengthDescs = {
  light: '仅替换显式的角色名和直接引用。最小改动。',
  medium: '替换名称、地点和世界观引用，保留性格和风格。',
  heavy: '完全转化为原创角色，仅保留核心性格原型。',
};

$$('.strength-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.strength-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.currentStrength = btn.dataset.strength;
    $('#strengthDesc').textContent = strengthDescs[btn.dataset.strength];
  });
});

// Temperature slider
$('#llmTemp').addEventListener('input', (e) => {
  $('#tempValue').textContent = parseFloat(e.target.value).toFixed(1);
});

// ── Start rewrite ────────────────────────────────────────────────────────

$('#startRewrite').addEventListener('click', startRewrite);

async function startRewrite() {
  const apiKey = $('#llmApiKey').value.trim();
  // Allow empty key if server has a default configured
  // (server will reject if neither is set)

  const selectedFields = [...$$('#fieldCheckboxes input:checked')].map(cb => cb.value);
  if (!selectedFields.length) {
    toast('请至少选择一个字段', 'error');
    return;
  }

  const form = new FormData();
  form.append('session_id', state.sessionId);
  form.append('provider', $('#llmProvider').value);
  form.append('api_key', apiKey);
  form.append('model', $('#llmModel').value);
  form.append('base_url', $('#llmBaseUrl').value || '');
  form.append('strength', state.currentStrength);
  form.append('selected_fields', selectedFields.join(','));
  form.append('temperature', $('#llmTemp').value);

  $('#startRewrite').disabled = true;
  $('#rewriteLoading').style.display = 'flex';

  try {
    const res = await fetch(`${API}/api/rewrite`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    state.rewriteResult = data;
    state.acceptedFields = {};
    // Default: accept all
    for (const key of Object.keys(data.rewritten)) {
      state.acceptedFields[key] = 'accept';
    }
    renderDiff();
    toast('改写完成！', 'success');
  } catch (e) {
    toast(`改写失败: ${e.message}`, 'error');
  } finally {
    $('#startRewrite').disabled = false;
    $('#rewriteLoading').style.display = 'none';
  }
}

// ── Render diff ──────────────────────────────────────────────────────────

function renderDiff() {
  const container = $('#diffContainer');
  container.innerHTML = '';

  if (!state.rewriteResult) return;
  const { original, rewritten } = state.rewriteResult;

  for (const [fname, origVal] of Object.entries(original)) {
    const newVal = rewritten[fname] || origVal;

    const block = document.createElement('div');
    block.className = 'diff-block';
    block.innerHTML = `
      <div class="diff-block-header">
        <span class="diff-block-name">${fname}</span>
        <div class="diff-block-actions">
          <button class="diff-action-btn accepted" data-field="${fname}" data-action="accept">采纳</button>
          <button class="diff-action-btn" data-field="${fname}" data-action="reject">保留原文</button>
        </div>
      </div>
      <div class="diff-columns">
        <div class="diff-col diff-col-original">
          <div class="diff-col-label">原文</div>
          ${escapeHtml(origVal)}
        </div>
        <div class="diff-col diff-col-rewritten">
          <div class="diff-col-label">改写后（可编辑）</div>
          <textarea data-field="${fname}">${escapeHtml(newVal)}</textarea>
        </div>
      </div>
    `;
    container.appendChild(block);
  }

  // Add "Apply & Export" button at end
  const applyRow = document.createElement('div');
  applyRow.style.cssText = 'display:flex;justify-content:flex-end;gap:0.8rem;margin-top:1rem';
  applyRow.innerHTML = `
    <button class="btn btn-primary btn-lg" id="applyAndExport">
      应用改写并导出
    </button>
  `;
  container.appendChild(applyRow);

  // Event: accept/reject buttons
  container.querySelectorAll('.diff-action-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const field = btn.dataset.field;
      const action = btn.dataset.action;
      state.acceptedFields[field] = action;
      // Update visuals
      const header = btn.closest('.diff-block-header');
      header.querySelectorAll('.diff-action-btn').forEach(b => {
        b.classList.remove('accepted', 'rejected');
      });
      btn.classList.add(action === 'accept' ? 'accepted' : 'rejected');
    });
  });

  // Event: apply
  $('#applyAndExport').addEventListener('click', applyAndExport);
}

// ═══════════════════════════════════════════════════════════════════════════
//  Apply & Export
// ═══════════════════════════════════════════════════════════════════════════

async function applyAndExport() {
  // Collect final field values
  const finalFields = {};
  const { original, rewritten } = state.rewriteResult;

  for (const fname of Object.keys(original)) {
    if (state.acceptedFields[fname] === 'reject') {
      // Keep original — don't include in apply
      continue;
    }
    // Get value from textarea (user may have edited)
    const textarea = $(`#diffContainer textarea[data-field="${fname}"]`);
    finalFields[fname] = textarea ? textarea.value : rewritten[fname];
  }

  if (Object.keys(finalFields).length === 0) {
    toast('没有需要应用的改写', 'error');
    return;
  }

  const form = new FormData();
  form.append('session_id', state.sessionId);
  form.append('rewritten_fields', JSON.stringify(finalFields));

  try {
    const res = await fetch(`${API}/api/apply`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    state.card = data.card;
    state.analysis = data.analysis;

    renderExport();
    goToPage('export');
    toast('改写已应用！', 'success');
  } catch (e) {
    toast(`应用失败: ${e.message}`, 'error');
  }
}

function renderExport() {
  const d = state.card.data;

  // Avatar
  const img = $('#exportAvatar');
  const placeholder = $('#exportAvatarPlaceholder');
  if (state.avatar) {
    img.src = state.avatar;
    img.classList.add('visible');
    placeholder.style.display = 'none';
  } else {
    img.classList.remove('visible');
    placeholder.style.display = 'flex';
  }

  $('#exportName').textContent = d.name || 'Unknown';

  const badge = $('#exportRisk');
  badge.textContent = `${riskLabel(state.analysis.overall_risk)} (${state.analysis.overall_risk}/5)`;
  badge.className = `risk-badge ${riskClass(state.analysis.overall_risk)}`;

  $('#exportSummary').textContent = state.analysis.summary;
}

// ── Export buttons ────────────────────────────────────────────────────────

$('#exportJson').addEventListener('click', async () => {
  await doExport('json');
});

$('#exportPng').addEventListener('click', async () => {
  await doExport('png');
});

async function doExport(format) {
  const form = new FormData();
  form.append('session_id', state.sessionId);

  try {
    const res = await fetch(`${API}/api/export/${format}`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;

    // Get filename from Content-Disposition
    const cd = res.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/);
    a.download = match ? match[1] : `card_washed.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(`${format.toUpperCase()} 导出成功！`, 'success');
  } catch (e) {
    toast(`导出失败: ${e.message}`, 'error');
  }
}

// ── Start over ───────────────────────────────────────────────────────────

$('#startOver').addEventListener('click', () => {
  state = {
    sessionId: null,
    card: null,
    avatar: '',
    analysis: null,
    rewritableFields: [],
    rewriteResult: null,
    acceptedFields: {},
    currentStrength: 'medium',
  };
  fileInput.value = '';
  goToPage('upload');
});


// ═══════════════════════════════════════════════════════════════════════════
//  BATCH MODE
// ═══════════════════════════════════════════════════════════════════════════

let batchState = {
  batchId: null,
  items: [],
  strength: 'medium',
  results: null,
};

// ── Mode toggle ──────────────────────────────────────────────────────────

$$('.mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const mode = btn.dataset.mode;
    if (mode === 'single') {
      $('#uploadZone').style.display = '';
      $('#batchUploadZone').style.display = 'none';
      $('#batchQueue').style.display = 'none';
    } else {
      $('#uploadZone').style.display = 'none';
      $('#batchUploadZone').style.display = '';
    }
  });
});

// ── Batch upload ─────────────────────────────────────────────────────────

const batchZone = $('#batchUploadZone');
const batchFileInput = $('#batchFileInput');

batchZone.addEventListener('dragover', (e) => { e.preventDefault(); batchZone.classList.add('dragover'); });
batchZone.addEventListener('dragleave', () => batchZone.classList.remove('dragover'));
batchZone.addEventListener('drop', (e) => {
  e.preventDefault();
  batchZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) handleBatchFiles(e.dataTransfer.files);
});
batchFileInput.addEventListener('change', () => {
  if (batchFileInput.files.length) handleBatchFiles(batchFileInput.files);
});

async function handleBatchFiles(fileList) {
  const files = [...fileList].filter(f => {
    const ext = f.name.split('.').pop().toLowerCase();
    return ['png', 'webp', 'charx', 'json'].includes(ext);
  });
  if (!files.length) {
    toast('没有有效的 .png / .webp / .charx / .json 文件', 'error');
    return;
  }

  toast(`上传 ${files.length} 个文件...`);

  const form = new FormData();
  for (const f of files) form.append('files', f);

  try {
    const res = await fetch(`${API}/api/batch/upload`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    batchState.batchId = data.batch_id;
    batchState.items = data.items;
    batchState.results = null;

    toast(`成功解析 ${data.total} 个文件`, 'success');
    renderBatchQueue();
  } catch (e) {
    toast(`批量上传失败: ${e.message}`, 'error');
  }
}

function renderBatchQueue() {
  $('#batchUploadZone').style.display = 'none';
  $('#batchQueue').style.display = 'block';
  $('#batchResults').style.display = 'none';

  const items = batchState.items;
  $('#batchCount').textContent = `${items.length} 个文件`;

  const list = $('#batchList');
  list.innerHTML = '';

  for (const it of items) {
    const el = document.createElement('div');
    el.className = 'batch-item';
    el.dataset.id = it.id;

    const risk = it.analysis ? it.analysis.overall_risk : 0;
    const thumbHtml = it.avatar
      ? `<img src="${it.avatar}" />`
      : `<svg viewBox="0 0 48 48" fill="currentColor"><circle cx="24" cy="18" r="10"/><path d="M4 44c0-11 8.95-20 20-20s20 9 20 20"/></svg>`;

    el.innerHTML = `
      <div class="batch-item-thumb">${thumbHtml}</div>
      <div class="batch-item-info">
        <div class="batch-item-name">${it.card_name || 'Unknown'}</div>
        <div class="batch-item-file">${it.filename}</div>
      </div>
      <span class="batch-item-risk" style="background:${riskBg(risk)};color:${riskColor(risk)}">${riskLabel(risk)}</span>
      <span class="batch-item-status pending" data-item-id="${it.id}">${it.status === 'parse_error' ? '解析错误' : '等待中'}</span>
    `;
    list.appendChild(el);
  }
}

// ── Batch config events ──────────────────────────────────────────────────

$('#batchProvider').addEventListener('change', (e) => {
  $('#batchBaseUrlGroup').style.display = e.target.value === 'openai_compatible' ? 'block' : 'none';
  if (e.target.value === 'anthropic') $('#batchModel').value = 'claude-sonnet-4-20250514';
  else if (e.target.value === 'openai') $('#batchModel').value = 'gpt-4o-mini';
});

$$('.batch-str-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.batch-str-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    batchState.strength = btn.dataset.strength;
  });
});

$('#batchTemp').addEventListener('input', (e) => {
  $('#batchTempValue').textContent = parseFloat(e.target.value).toFixed(1);
});

// ── Start batch rewrite ──────────────────────────────────────────────────

$('#startBatchRewrite').addEventListener('click', startBatchRewrite);

async function startBatchRewrite() {
  const apiKey = $('#batchApiKey').value.trim();

  const form = new FormData();
  form.append('batch_id', batchState.batchId);
  form.append('provider', $('#batchProvider').value);
  form.append('api_key', apiKey);
  form.append('model', $('#batchModel').value);
  form.append('base_url', $('#batchBaseUrl')?.value || '');
  form.append('strength', batchState.strength);
  form.append('selected_fields', '');  // all fields
  form.append('temperature', $('#batchTemp').value);
  form.append('force', $('#batchForceRewrite').checked ? 'true' : 'false');

  $('#startBatchRewrite').disabled = true;
  $('#batchLoading').style.display = 'flex';
  const total = batchState.items.filter(it => it.status !== 'parse_error').length;
  $('#batchProgress').textContent = `处理中 0/${total} ...`;

  // Mark all as processing
  $$('.batch-item-status').forEach(el => {
    if (el.textContent === '等待中') {
      el.textContent = '排队中';
      el.className = 'batch-item-status processing';
    }
  });

  try {
    const res = await fetch(`${API}/api/batch/rewrite`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    batchState.results = data.results;

    // Update status indicators
    for (const r of data.results) {
      const el = $(`.batch-item-status[data-item-id="${r.id}"]`);
      if (!el) continue;
      if (r.status === 'ok') {
        el.textContent = '完成';
        el.className = 'batch-item-status done';
      } else if (r.status === 'no_risk') {
        el.textContent = '无风险';
        el.className = 'batch-item-status no-risk';
      } else if (r.status === 'error') {
        el.textContent = '错误';
        el.className = 'batch-item-status error';
      } else {
        el.textContent = '跳过';
        el.className = 'batch-item-status no-risk';
      }
    }

    renderBatchResults(data.results);
    toast('批量改写完成！', 'success');
  } catch (e) {
    toast(`批量改写失败: ${e.message}`, 'error');
  } finally {
    $('#startBatchRewrite').disabled = false;
    $('#batchLoading').style.display = 'none';
  }
}

function renderBatchResults(results) {
  $('#batchResults').style.display = 'block';
  const list = $('#batchResultsList');
  list.innerHTML = '';

  let okCount = 0, errCount = 0, skipCount = 0;

  for (const r of results) {
    const el = document.createElement('div');
    el.className = 'batch-result-item';

    let statusClass = 'ok', statusText = '已改写';
    if (r.status === 'ok') { okCount++; }
    else if (r.status === 'error') { errCount++; statusClass = 'error'; statusText = '错误'; }
    else if (r.status === 'no_risk') { skipCount++; statusClass = 'no-risk'; statusText = '无风险'; }
    else { skipCount++; statusClass = 'skipped'; statusText = '跳过'; }

    const riskHtml = r.risk_before != null && r.risk_after != null
      ? `<span class="batch-result-risk" style="color:${riskColor(r.risk_before)}">${r.risk_before}</span>
         <span class="batch-result-arrow">&rarr;</span>
         <span class="batch-result-risk" style="color:${riskColor(r.risk_after)}">${r.risk_after}</span>`
      : '<span class="batch-result-risk" style="color:var(--text-muted)">—</span>';

    el.innerHTML = `
      <span class="batch-result-name">${r.filename}</span>
      <div style="display:flex;align-items:center;gap:0.3rem">${riskHtml}</div>
      <span class="batch-result-status ${statusClass}">${statusText}</span>
    `;
    list.appendChild(el);
  }

  // Summary line
  const summary = document.createElement('div');
  summary.style.cssText = 'text-align:center;color:var(--text-secondary);font-size:0.82rem;margin:0.8rem 0';
  summary.textContent = `改写 ${okCount} / 跳过 ${skipCount} / 错误 ${errCount}`;
  list.appendChild(summary);
}

// ── Batch export ─────────────────────────────────────────────────────────

$('#batchExportJson').addEventListener('click', () => doBatchExport('json'));
$('#batchExportPng').addEventListener('click', () => doBatchExport('png'));

async function doBatchExport(format) {
  const form = new FormData();
  form.append('batch_id', batchState.batchId);
  form.append('format', format);

  try {
    const res = await fetch(`${API}/api/batch/export`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'card_wash_batch.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast('ZIP 导出成功！', 'success');
  } catch (e) {
    toast(`导出失败: ${e.message}`, 'error');
  }
}

$('#batchStartOver').addEventListener('click', () => {
  batchState = { batchId: null, items: [], strength: 'medium', results: null };
  batchFileInput.value = '';
  $('#batchQueue').style.display = 'none';
  $('#batchUploadZone').style.display = '';
});


// ═══════════════════════════════════════════════════════════════════════════
//  TRANSLATE MODE
// ═══════════════════════════════════════════════════════════════════════════

const LANG_DISPLAY = { zh: '中文', en: 'English', ja: '日本語' };

$('#goToTranslate').addEventListener('click', () => {
  const modal = $('#translateModal');
  const detected = state.analysis?.detected_language || 'zh';

  // Set source language display
  $('#translateFromLang').textContent = LANG_DISPLAY[detected] || detected;

  // Set target options — remove source lang from choices
  const sel = $('#translateTargetLang');
  sel.innerHTML = '';
  for (const [code, name] of Object.entries(LANG_DISPLAY)) {
    if (code !== detected) {
      const opt = document.createElement('option');
      opt.value = code;
      opt.textContent = name;
      sel.appendChild(opt);
    }
  }

  // Auto-fill from server config
  const tprov = $('#translateProvider');
  const tmodel = $('#translateModel');
  const tbase = $('#translateBaseUrl');
  const tkey = $('#translateApiKey');
  // Inherit from single-mode fields if filled
  if ($('#llmProvider').value) tprov.value = $('#llmProvider').value;
  if ($('#llmModel').value) tmodel.value = tmodel.value || $('#llmModel').value;
  if ($('#llmBaseUrl').value) tbase.value = tbase.value || $('#llmBaseUrl').value;
  if ($('#llmApiKey').value) tkey.value = tkey.value || $('#llmApiKey').value;

  modal.style.display = 'flex';
});

$('#translateCancel').addEventListener('click', () => {
  $('#translateModal').style.display = 'none';
});

$('#translateModal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) $('#translateModal').style.display = 'none';
});

$('#translateProvider').addEventListener('change', (e) => {
  $('#translateBaseUrlGroup').style.display = e.target.value === 'openai_compatible' ? 'block' : 'none';
});

$('#translateStart').addEventListener('click', startTranslate);

async function startTranslate() {
  const targetLang = $('#translateTargetLang').value;

  const form = new FormData();
  form.append('session_id', state.sessionId);
  form.append('provider', $('#translateProvider').value);
  form.append('api_key', $('#translateApiKey').value.trim());
  form.append('model', $('#translateModel').value.trim());
  form.append('base_url', $('#translateBaseUrl')?.value || '');
  form.append('target_lang', targetLang);
  form.append('selected_fields', '');  // all fields
  form.append('temperature', '0.3');

  $('#translateStart').disabled = true;
  $('#translateLoading').style.display = 'flex';

  try {
    const res = await fetch(`${API}/api/translate`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();

    // Apply translated fields as if they were rewritten
    state.rewriteResult = {
      original: data.original,
      rewritten: data.translated,
    };
    state.acceptedFields = {};
    for (const key of Object.keys(data.translated)) {
      state.acceptedFields[key] = 'accept';
    }

    // Close modal, go to rewrite page to show diff
    $('#translateModal').style.display = 'none';
    renderDiff();
    goToPage('rewrite');
    toast(`翻译完成！${LANG_DISPLAY[data.source_lang]} → ${LANG_DISPLAY[data.target_lang]}`, 'success');
  } catch (e) {
    toast(`翻译失败: ${e.message}`, 'error');
  } finally {
    $('#translateStart').disabled = false;
    $('#translateLoading').style.display = 'none';
  }
}
