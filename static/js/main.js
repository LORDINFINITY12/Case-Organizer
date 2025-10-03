/* ============================================================================
   Case Organizer — main.js (full rewrite, v2)
   ============================================================================
   Covers:
   - Global helpers ($, el)
   - Taxonomies (SUBCATS, CASE_TYPES)
   - Search (basic + advanced) with single authoritative renderResults
   - Infinite year dropdown
   - Create Case form
   - Manage Case form (year/month/case, domain→subcategory, file upload)
   - Note.json button (either Add OR View/Edit) + modal wiring
   - Flash auto-dismiss
   - Theme toggle
   ============================================================================ */

// Small helpers
function $(sel){ return document.querySelector(sel); }
function el(tag, cls){ const e=document.createElement(tag); if(cls) e.className=cls; return e; }

// --- Data: subcategories & case types ----------------------------------
const SUBCATS = {
  Criminal: [
    "Anticipatory Bail","Appeals","Bail","Charges","Criminal Miscellaneous",
    "Orders/Judgments","Primary Documents","Revisions","Trial","Writs",
    "Reference","Transfer Petitions"
  ],
  Civil: [
    "Civil Main","Civil Miscellaneous Main","Civil Appeal","Civil Revision",
    "Civil Writ Petition","Orders/Judgments","Primary Documents",
    "Reference","Transfer Petitions"
  ],
  Commercial: [
    "Civil Main","Civil Miscellaneous Main","Civil Appeal","Civil Revision",
    "Civil Writ Petition","Orders/Judgments","Primary Documents",
    "Reference","Transfer Petitions"
  ],
  // NOTE: Intentionally no "Case Law" key so subcategory is disabled when selected.
};

const CASE_TYPES = {
  Criminal: [
    "498A (Cruelty/Dowry)","Murder","Rape","Sexual Harassment","Hurt",
    "138 NI Act","Fraud","Human Trafficking","NDPS","PMLA","POCSO","Others"
  ],
  Civil: [
    "Property","Rent Control","Inheritance/Succession","Contract",
    "Marital Divorce","Marital Maintenance","Marital Guardianship","Others"
  ],
  Commercial: [
    "Trademark","Copyright","Patent","Banking","Others"
  ],
};

const NOTE_TEMPLATE_DEFAULT = `{
  "Petitioner Name": "",
  "Petitioner Address": "",
  "Petitioner Contact": "",

  "Respondent Name": "",
  "Respondent Address": "",
  "Respondent Contact": "",

  "Our Party": "",

  "Case Category": "",
  "Case Subcategory": "",
  "Case Type": "",

  "Court of Origin": {
    "State": "",
    "District": "",
    "Court/Forum": ""
  },

  "Current Court/Forum": {
    "State": "",
    "District": "",
    "Court/Forum": ""
  },

  "Additional Notes": ""
}`;

function defaultNoteTemplate(){
  return NOTE_TEMPLATE_DEFAULT;
}

// ------------------ Common UI utilities ------------------
function populateOptions(select, arr, placeholder="Select"){
  if (!select) return;
  select.innerHTML = "";
  const opt = el("option");
  opt.value = "";
  opt.textContent = placeholder;
  select.append(opt);
  arr.forEach(v => {
    const o = el("option");
    o.textContent = v;
    select.append(o);
  });
  select.disabled = false;
}

// --- Search helpers -----------------------------------------------------
async function runBasicSearch(){
  const q = ($('#search-q')?.value || '').trim();
  const url = new URL('/search', location.origin);
  if (q) url.searchParams.set('q', q);
  const r = await fetch(url);
  const data = await r.json().catch(()=>({results:[]}));
  renderResults(data.results || []);
}

async function runAdvancedSearch(){
  const params = new URLSearchParams();
  const party = (document.getElementById('party')?.value || '').trim();
  const year  = (document.getElementById('year')?.value || '').trim();   // hidden #year (from year-dd)
  const month = document.getElementById('month')?.value || '';
  const domain = document.getElementById('adv-domain')?.value || '';
  const subcat = document.getElementById('adv-subcat')?.value || '';

  if (party) params.set('party', party);
  if (year)  params.set('year', year);
  if (month) params.set('month', month);
  if (domain) params.set('domain', domain);
  if (subcat) params.set('subcategory', subcat);

  // Only include 'type' if the element still exists (back-compat)
  const typeEl = document.getElementById('type');
  if (typeEl && typeEl.value) params.set('type', typeEl.value);

  const r = await fetch(`/search?${params.toString()}`);
  const data = await r.json().catch(()=>({results:[]}));
  renderResults(data.results || []);
}

// ------------ Infinite, scrollable year dropdown (virtualized-ish) ------------
function initYearDropdown(wrapperId, hiddenInputId, startYear = 2025) {
  const wrap = document.getElementById(wrapperId);
  if (!wrap) return;
  const trigger = wrap.querySelector('.yd-trigger');
  const panel = wrap.querySelector('.yd-panel');
  const hidden = document.getElementById(hiddenInputId);
  if (!trigger || !panel || !hidden) return;

  // Config
  const CHUNK = 80;          // how many years to render per side at once
  const THRESHOLD = 40;      // when to grow (px from top/bottom)
  const itemHeight = 32;     // keep in sync with CSS

  // State
  let anchor = startYear;    // visual center
  let from = anchor - CHUNK; // inclusive
  let to   = anchor + CHUNK; // inclusive
  let selected = startYear;

  // Ensure initial value
  hidden.value = String(selected);
  trigger.textContent = `Year: ${selected}`;

  // Utilities
  function render(initial = false) {
    const frag = document.createDocumentFragment();
    for (let y = from; y <= to; y++) {
      const opt = document.createElement('div');
      opt.className = 'yd-item';
      opt.setAttribute('role','option');
      opt.dataset.year = String(y);
      opt.textContent = String(y);
      if (y === selected) opt.classList.add('selected');
      frag.appendChild(opt);
    }
    if (initial) {
      panel.innerHTML = '';
    }
    panel.appendChild(frag);

    if (initial) {
      // scroll so that "anchor" sits roughly in the middle
      const midIndex = anchor - from;
      panel.scrollTop = Math.max(0, midIndex * itemHeight - panel.clientHeight/2 + itemHeight/2);
    }
  }

  function open() {
    if (!panel.hasAttribute('hidden')) return;
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');

    // First open: initial render
    if (!panel.dataset.ready) {
      render(true);
      panel.dataset.ready = '1';
    }
    // focus panel for keyboard nav
    panel.focus({ preventScroll: true });
  }

  function close() {
    if (panel.hasAttribute('hidden')) return;
    panel.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }

  function setYear(y) {
    selected = y;
    hidden.value = String(y);
    trigger.textContent = `Year: ${y}`;
    // update selection highlight
    panel.querySelectorAll('.yd-item.selected').forEach(n => n.classList.remove('selected'));
    const elx = panel.querySelector(`.yd-item[data-year="${y}"]`);
    if (elx) elx.classList.add('selected');
  }

  // Expand list when scrolling near top/bottom
  panel.addEventListener('scroll', () => {
    const nearTop = panel.scrollTop <= THRESHOLD;
    const nearBottom = (panel.scrollHeight - panel.clientHeight - panel.scrollTop) <= THRESHOLD;

    if (nearTop) {
      // prepend older years
      const oldFrom = from;
      from = from - CHUNK;
      const frag = document.createDocumentFragment();
      for (let y = from; y < oldFrom; y++) {
        const opt = document.createElement('div');
        opt.className = 'yd-item';
        opt.setAttribute('role','option');
        opt.dataset.year = String(y);
        opt.textContent = String(y);
        if (y === selected) opt.classList.add('selected');
        frag.appendChild(opt);
      }
      panel.prepend(frag);
      // maintain visual position
      panel.scrollTop += CHUNK * itemHeight;
    }

    if (nearBottom) {
      const oldTo = to;
      to = to + CHUNK;
      const frag = document.createDocumentFragment();
      for (let y = oldTo + 1; y <= to; y++) {
        const opt = document.createElement('div');
        opt.className = 'yd-item';
        opt.setAttribute('role','option');
        opt.dataset.year = String(y);
        opt.textContent = String(y);
        if (y === selected) opt.classList.add('selected');
        frag.appendChild(opt);
      }
      panel.append(frag);
    }
  });

  // Click select
  panel.addEventListener('click', (e) => {
    const d = e.target.closest('.yd-item');
    if (!d) return;
    const y = parseInt(d.dataset.year, 10);
    if (!isNaN(y)) {
      setYear(y);
      close();
    }
  });

  // Keyboard on panel (Up/Down/Page/Home/End/Enter/Esc)
  panel.tabIndex = 0;
  panel.addEventListener('keydown', (e) => {
    const cur = parseInt(hidden.value || String(selected), 10);
    if (!['ArrowUp','ArrowDown','PageUp','PageDown','Home','End','Enter','Escape'].includes(e.key)) return;
    e.preventDefault();
    let next = cur;
    if (e.key === 'ArrowUp') next = cur + 1;
    if (e.key === 'ArrowDown') next = cur - 1;
    if (e.key === 'PageUp') next = cur + 10;
    if (e.key === 'PageDown') next = cur - 10;
    if (e.key === 'Home') next = 9999;
    if (e.key === 'End') next = 1;
    if (e.key === 'Enter' || e.key === 'Escape') { close(); return; }

    setYear(next);

    // Ensure year element exists; extend if necessary
    if (next < from + 5) {
      const oldFrom = from;
      from = next - CHUNK;
      const frag = document.createDocumentFragment();
      for (let y = from; y < oldFrom; y++) {
        const opt = document.createElement('div');
        opt.className = 'yd-item';
        opt.setAttribute('role','option');
        opt.dataset.year = String(y);
        opt.textContent = String(y);
        if (y === selected) opt.classList.add('selected');
        frag.appendChild(opt);
      }
      panel.prepend(frag);
      panel.scrollTop += (oldFrom - from) * itemHeight;
    } else if (next > to - 5) {
      const oldTo = to;
      to = next + CHUNK;
      const frag = document.createDocumentFragment();
      for (let y = oldTo + 1; y <= to; y++) {
        const opt = document.createElement('div');
        opt.className = 'yd-item';
        opt.setAttribute('role','option');
        opt.dataset.year = String(y);
        opt.textContent = String(y);
        if (y === selected) opt.classList.add('selected');
        frag.appendChild(opt);
      }
      panel.append(frag);
    }

    // Scroll selected into view
    const elx = panel.querySelector(`.yd-item[data-year="${next}"]`);
    if (elx) {
      const r = elx.getBoundingClientRect();
      const pr = panel.getBoundingClientRect();
      if (r.top < pr.top + 4) panel.scrollTop -= (pr.top + 4 - r.top);
      if (r.bottom > pr.bottom - 4) panel.scrollTop += (r.bottom - (pr.bottom - 4));
    }
  });

  // Open/close trigger + wheel fine-tune
  trigger.addEventListener('click', () => (panel.hidden ? open() : close()));
  trigger.addEventListener('wheel', (e) => {
    if (!panel.hidden) return;
    if (!e.ctrlKey) {
      e.preventDefault();
      const delta = e.deltaY < 0 ? +1 : -1;
      setYear(selected + delta);
    }
  }, { passive: false });

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target)) close();
  });

  // Initial text label already set
}

// ------------- Results renderer (authoritative) ----------------
function openConfirm(message) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirmModal');
    const text  = document.getElementById('confirmText');
    const yes   = document.getElementById('confirmYes');
    const no    = document.getElementById('confirmNo');
    const x     = document.getElementById('confirmClose');

    if (!modal || !yes || !no || !x) {
      const ok = window.confirm(message || 'Do you want to delete this file?');
      resolve(ok);
      return;
    }

    if (text) text.textContent = message || 'Do you want to delete this file?';
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden', 'false');

    const cleanup = () => {
      modal.setAttribute('hidden', '');
      modal.setAttribute('aria-hidden', 'true');
      yes.removeEventListener('click', onYes);
      no.removeEventListener('click', onNo);
      x.removeEventListener('click', onNo);
    };
    const onYes = () => { cleanup(); resolve(true); };
    const onNo  = () => { cleanup(); resolve(false); };

    yes.addEventListener('click', onYes);
    no.addEventListener('click', onNo);
    x.addEventListener('click', onNo);
  });
}

function smartTruncate(filename, maxLen = 100) {
  if (!filename || filename.length <= maxLen) return filename || '';
  const extIndex = filename.lastIndexOf('.');
  const ext = extIndex !== -1 ? filename.slice(extIndex) : '';
  const base = extIndex !== -1 ? filename.slice(0, extIndex) : filename;
  const keep = maxLen - ext.length - 3;
  const startLen = Math.ceil(keep / 2);
  const endLen = Math.floor(keep / 2);
  return base.slice(0, startLen) + '...' + base.slice(-endLen) + ext;
}

function buildResultItem(rec) {
  const row = document.createElement('div');
  row.className = 'result-item';
  row.dataset.path = rec.path;

  // filename (truncated for display only)
  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = smartTruncate(rec.file, 100);

  // actions area
  const actions = document.createElement('div');
  actions.className = 'icon-row';

  // Download button
  const dl = document.createElement('a');
  dl.className = 'icon-btn';
  dl.href = `/static-serve?path=${encodeURIComponent(rec.path)}&download=1`;
  dl.setAttribute('title', 'Download');
  dl.innerHTML = `<i class="fa-solid fa-download" aria-hidden="true"></i><span class="sr-only">Download</span>`;

  // Delete button
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'icon-btn';
  del.setAttribute('title', 'Delete');
  del.innerHTML = `<i class="fa-solid fa-trash" aria-hidden="true"></i><span class="sr-only">Delete</span>`;
  del.addEventListener('click', async () => {
    const displayName = smartTruncate(rec.file, 100);
    const ok = await openConfirm(`Delete “${displayName}”?`);
    if (!ok) return;

    try {
      const resp = await fetch('/api/delete-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: rec.path })
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.ok) {
        const msg = data && data.msg ? data.msg : `HTTP ${resp.status}`;
        alert(`Delete failed: ${msg}`);
        return;
      }
      row.remove();
    } catch (e) {
      alert(`Delete failed: ${e}`);
    }
  });

  // double-click downloads
  row.addEventListener('dblclick', () => dl.click());

  // assemble row
  actions.appendChild(dl);
  actions.appendChild(del);
  row.appendChild(name);
  row.appendChild(actions);
  return row;
}

function renderResults(list) {
  const host = document.getElementById('results');
  if (!host) return;
  host.innerHTML = '';
  if (!list || !list.length) {
    const empty = document.createElement('div');
    empty.className = 'result-item';
    empty.textContent = 'No results.';
    host.appendChild(empty);
    return;
  }
  list.forEach(rec => host.appendChild(buildResultItem(rec)));
}

// ------------- Directory tree (optional button #dir-search) -------------
async function showDirLevel(relPath) {
  const results = document.getElementById('results');
  if (!results) return;

  const url = new URL('/api/dir-tree', location.origin);
  if (relPath) url.searchParams.set('path', relPath);

  try {
    const resp = await fetch(url.toString());
    const data = await resp.json().catch(() => ({}));
    results.innerHTML = '';

    // Up directory
    if (relPath) {
      const up = document.createElement('div');
      up.className = 'result-item folder';
      up.innerHTML = `<i class="fa-solid fa-arrow-up" style="margin-right:6px;"></i> ..`;
      up.addEventListener('click', () => {
        const parts = relPath.split('/');
        parts.pop();
        showDirLevel(parts.join('/'));
      });
      results.appendChild(up);
    }

    // Directories
    (data.dirs || []).forEach(dir => {
      const row = document.createElement('div');
      row.className = 'result-item folder';
      row.innerHTML = `<i class="fa-solid fa-folder-open" style="color: var(--accent); margin-right:6px;"></i> ${dir}`;
      row.addEventListener('click', () => {
        const newPath = relPath ? `${relPath}/${dir}` : dir;
        showDirLevel(newPath);
      });
      results.appendChild(row);
    });

    // Files
    (data.files || []).forEach(f => {
      results.appendChild(buildResultItem({
        file: f.name,
        path: f.path,
        rel: f.name
      }));
    });

    if ((!data.dirs || !data.dirs.length) && (!data.files || !data.files.length)) {
      const empty = document.createElement('div');
      empty.className = 'result-item';
      empty.textContent = '(empty)';
      results.appendChild(empty);
    }
  } catch (e) {
    results.innerHTML = `<div class="result-item">Error: ${e}</div>`;
  }
}

// -------------------- Create Case form --------------------
function setActive(card, others){
  card.classList.add('active'); card.setAttribute('aria-pressed','true');
  others.forEach(c => { c.classList.remove('active'); c.setAttribute('aria-pressed','false'); });
}

function createCaseForm(){
  const host = $('#form-host');
  if (!host) return;
  host.innerHTML = '';
  const wrap = el('div','form-card');
  wrap.innerHTML = `
    <h3>Create Case</h3>
    <div class="form-grid">
      <input type="date" id="cc-date" />

      <!-- Parties -->
      <input type="text" id="pn" placeholder="Petitioner Name" />
      <input type="text" id="rn" placeholder="Respondent Name" />
      <input type="text" id="pa" placeholder="Petitioner Address" />
      <input type="text" id="ra" placeholder="Respondent Address" />
      <input type="text" id="pc" placeholder="Petitioner Contact" />
      <input type="text" id="rc" placeholder="Respondent Contact" />

      <!-- Auto Case Name (preview) -->
      <input type="text" id="cc-name-preview" placeholder="Case Name (auto)" disabled />
      <input type="hidden" id="cc-name" />

      <!-- Representing -->
      <div style="grid-column: span 2;">
        <label style="display:block;margin:6px 0 4px;">We’re Representing:</label>
        <select id="op"><option>Petitioner</option><option>Respondent</option></select>
      </div>

      <!-- Domain -> Subcategory -->
      <select id="cat"><option value="">Case Category</option><option>Criminal</option><option>Civil</option><option>Commercial</option></select>
      <select id="subcat" disabled><option value="">Subcategory</option></select>

      <!-- Case Type (domain-specific) -->
      <select id="ctype" disabled><option value="">Case Type</option></select>
      <input type="text" id="ctype-other" placeholder="Case Type (Other)" style="display:none;" />
      
      <!-- Courts -->
      <input type="text" id="os" placeholder="Origin State" />
      <input type="text" id="od" placeholder="Origin District" />
      <input type="text" id="of" placeholder="Origin Court/Forum" />
      <input type="text" id="cs" placeholder="Current State" />
      <input type="text" id="cd" placeholder="Current District" />
      <input type="text" id="cf" placeholder="Current Court/Forum" />

      <textarea id="an" rows="3" placeholder="Additional Notes" style="grid-column: span 2;"></textarea>
    </div>
    <div class="form-actions">
      <button id="cc-go" class="btn-primary" type="button">Create Case & Save Note</button>
    </div>
  `;
  host.append(wrap);

  // defaults
  const dateEl = $('#cc-date');
  if (dateEl) dateEl.valueAsDate = new Date();

  // Auto case name from PN/RN
  function updateCaseName(){
    const pn = ($('#pn')?.value || '').trim();
    const rn = ($('#rn')?.value || '').trim();
    const name = (pn && rn) ? `${pn} v. ${rn}` : '';
    const hidden = $('#cc-name');
    const preview = $('#cc-name-preview');
    if (hidden) hidden.value = name;
    if (preview) preview.value = name;
  }
  ['pn','rn'].forEach(id => $('#'+id)?.addEventListener('input', updateCaseName));
  updateCaseName();

  // Domain -> Subcategory -> CaseType
  $('#cat')?.addEventListener('change', () => {
    const dom = $('#cat').value || '';
    if (dom && SUBCATS[dom]) {
      populateOptions($('#subcat'), SUBCATS[dom], "Subcategory");
      populateOptions($('#ctype'), CASE_TYPES[dom], "Case Type");
      $('#ctype').disabled = false;
    } else {
      if ($('#subcat')) { $('#subcat').innerHTML = '<option value="">Subcategory</option>'; $('#subcat').disabled = true; }
      if ($('#ctype')) { $('#ctype').innerHTML = '<option value="">Case Type</option>'; $('#ctype').disabled = true; }
      if ($('#ctype-other')) $('#ctype-other').style.display = 'none';
    }
  });

  // Show text input only if Case Type == Others
  $('#ctype')?.addEventListener('change', () => {
    const val = $('#ctype').value || '';
    if ($('#ctype-other')) $('#ctype-other').style.display = (val === 'Others') ? 'block' : 'none';
  });

  // Submit
  $('#cc-go')?.addEventListener('click', async ()=>{
    const fd = new FormData();
    fd.set('Date', $('#cc-date')?.value || '');
    fd.set('Case Name', $('#cc-name')?.value || '');  // auto-built
    fd.set('Petitioner Name', ($('#pn')?.value || '').trim());
    fd.set('Petitioner Address', ($('#pa')?.value || '').trim());
    fd.set('Petitioner Contact', ($('#pc')?.value || '').trim());
    fd.set('Respondent Name', ($('#rn')?.value || '').trim());
    fd.set('Respondent Address', ($('#ra')?.value || '').trim());
    fd.set('Respondent Contact', ($('#rc')?.value || '').trim());
    fd.set('Our Party', $('#op')?.value || '');
    const cat = $('#cat')?.value || '';
    const subcat = $('#subcat')?.value || '';
    fd.set('Case Category', cat);
    fd.set('Case Subcategory', subcat);
    const ctypeSel = $('#ctype')?.value || '';
    const ctype = (ctypeSel === 'Others') ? (($('#ctype-other')?.value || '').trim()) : ctypeSel;
    fd.set('Case Type', ctype);
    fd.set('Origin State', ($('#os')?.value || '').trim());
    fd.set('Origin District', ($('#od')?.value || '').trim());
    fd.set('Origin Court/Forum', ($('#of')?.value || '').trim());
    fd.set('Current State', ($('#cs')?.value || '').trim());
    fd.set('Current District', ($('#cd')?.value || '').trim());
    fd.set('Current Court/Forum', ($('#cf')?.value || '').trim());
    fd.set('Additional Notes', ($('#an')?.value || '').trim());

    if (!($('#cc-name')?.value)) { alert('Enter Petitioner and Respondent to form the Case Name.'); return; }

    const r = await fetch('/create-case', { method: 'POST', body: fd });
    const data = await r.json().catch(()=>({ok:false,msg:'Bad JSON'}));
    alert(data.ok ? 'Case created at: ' + data.path : ('Error: ' + (data.msg || 'Failed')));
  });
}

// -------------------- Manage Case form --------------------
function manageCaseForm(){
  const host = $('#form-host');
  if (!host) return;
  host.innerHTML = '';
  const wrap = el('div','form-card');
  wrap.innerHTML = `
    <h3>Manage Case</h3>
    <div class="form-grid">
      <!-- Locate existing case -->
      <select id="mc-year"><option value="">Year</option></select>
      <select id="mc-month" disabled><option value="">Month</option></select>
      <select id="mc-case" disabled><option value="">Case (Petitioner v. Respondent)</option></select>

      <!-- Classification for this upload -->
      <select id="domain">
        <option value="">Case Category</option>
        <option>Criminal</option><option>Civil</option><option>Commercial</option><option>Case Law</option>
      </select>
      <select id="subcategory" disabled><option value="">Subcategory</option></select>
      <input type="text" id="main-type" placeholder="Main Type (e.g., Transfer Petition, Criminal Revision, Orders)" />

      <!-- Date + Notes -->
      <input type="date" id="mc-date" />
      <button id="create-note-btn" class="btn-secondary" type="button" hidden>
        View / Edit Notes
      </button>
    </div>

    <div class="dropzone" id="drop" tabindex="0">Drag & drop files here or click to select</div>
    <input type="file" id="file" hidden accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.json" multiple />
    <div id="file-list" class="results"></div>

    <div class="form-actions">
      <button id="mc-go" class="btn-primary" type="button">Upload & Categorize File(s)</button>
    </div>
  `;
  host.append(wrap);

  // defaults
  const mcDate = $('#mc-date'); if (mcDate) mcDate.valueAsDate = new Date();

  // --- Populate Year / Month / Case from backend -----------------------
  const yearSel  = $('#mc-year');
  const monthSel = $('#mc-month');
  const caseSel  = $('#mc-case');
  const noteBtn  = $('#create-note-btn');

  async function loadYears(){
    const r = await fetch('/api/years');
    const data = await r.json().catch(()=>({years:[]}));
    yearSel.innerHTML = '<option value="">Year</option>';
    (data.years || []).forEach(y => {
      const o = el('option'); o.value = y; o.textContent = y; yearSel.append(o);
    });
    yearSel.disabled = false;
    monthSel.innerHTML = '<option value="">Month</option>'; monthSel.disabled = true;
    caseSel.innerHTML  = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true;
    updateNoteButtonVisibility();
  }

  async function loadMonths(year){
    const r = await fetch(`/api/months?${new URLSearchParams({year})}`);
    const data = await r.json().catch(()=>({months:[]}));
    monthSel.innerHTML = '<option value="">Month</option>';
    (data.months || []).forEach(m => {
      const o = el('option'); o.value = m; o.textContent = m; monthSel.append(o);
    });
    monthSel.disabled = false;
    caseSel.innerHTML  = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true;
    updateNoteButtonVisibility();
  }

  async function loadCases(year, month){
    const r = await fetch(`/api/cases?${new URLSearchParams({year, month})}`);
    const data = await r.json().catch(()=>({cases:[]}));
    caseSel.innerHTML = '<option value="">Case (Petitioner v. Respondent)</option>';
    (data.cases || []).forEach(cn => {
      const o = el('option'); o.value = cn; o.textContent = cn; caseSel.append(o);
    });
    caseSel.disabled = false;
    updateNoteButtonVisibility();
  }

  yearSel.addEventListener('change', () => {
    const y = yearSel.value || '';
    if (!y){
      monthSel.innerHTML = '<option value="">Month</option>'; monthSel.disabled = true;
      caseSel.innerHTML  = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true;
      updateNoteButtonVisibility();
      return;
    }
    loadMonths(y);
  });

  monthSel.addEventListener('change', () => {
    const y = yearSel.value || ''; const m = monthSel.value || '';
    if (y && m) loadCases(y, m);
    else { caseSel.innerHTML = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true; updateNoteButtonVisibility(); }
  });

  caseSel.addEventListener('change', updateNoteButtonVisibility);

  // --- Notes presence check + button wiring -----------------
  async function getNoteState(year, month, cname) {
      try {
          const resp = await fetch(`/api/note/${year}/${month}/${encodeURIComponent(cname)}`);
          const data = await resp.json().catch(()=>null);
          if (resp.ok && data?.ok) {
              return {
                  exists: true,
                  content: data.content || '',
                  template: data.template || defaultNoteTemplate()
              };
          }
          return {
              exists: false,
              content: '',
              template: (data && data.template) || defaultNoteTemplate()
          };
      } catch (err) {
          console.warn('Note check failed', err);
          return { exists: false, content: '', template: defaultNoteTemplate() };
      }
  }

  function openNotesModalEditable(content, intent){
      if (typeof window._openNotesWith === 'function') {
          window._openNotesWith(content || '', intent || 'update');
          return;
      }
      // Fallback if global handlers have not bound yet.
      const modal  = document.getElementById('notesModal');
      const editor = document.getElementById('notesEditor');
      if (!modal || !editor) return;
      editor.value = content || '';
      editor.style.display = 'block';
      modal.removeAttribute('hidden');
      modal.setAttribute('aria-hidden','false');
      editor.focus();
  }

  async function updateNoteButtonVisibility() {
      if (!noteBtn) return;
      const year  = yearSel.value || '';
      const month = monthSel.value || '';
      const cname = caseSel.value || '';

      if (!year || !month || !cname) {
          noteBtn.setAttribute('hidden','');
          noteBtn.removeAttribute('data-has-note');
          noteBtn.removeAttribute('data-intent');
          return;
      }

      const noteState = await getNoteState(year, month, cname);
      const exists = noteState.exists;
      noteBtn.removeAttribute('hidden');
      if (exists) noteBtn.dataset.hasNote = '1'; else delete noteBtn.dataset.hasNote;
      noteBtn.dataset.intent = exists ? 'update' : 'create';

      if (exists) {
          noteBtn.textContent = 'View / Edit Note.json';
          noteBtn.onclick = async () => {
              const currentState = await getNoteState(yearSel.value || '', monthSel.value || '', caseSel.value || '');
              if (!currentState.exists) {
                  alert('Note.json not found for this case.');
                  updateNoteButtonVisibility();
                  return;
              }
              openNotesModalEditable(currentState.content || '', 'update');
          };
      } else {
          noteBtn.textContent = 'Create Note.json';
          noteBtn.onclick = async () => {
              const currentState = await getNoteState(yearSel.value || '', monthSel.value || '', caseSel.value || '');
              const template = currentState.template || defaultNoteTemplate();
              openNotesModalEditable(template, currentState.exists ? 'update' : 'create');
          };
      }
  }

  // expose so the modal save handler can refresh after writes
  window.__refreshNoteButton = updateNoteButtonVisibility;


  // Load initial years
  loadYears();

  // --- Domain -> Subcategory ------------------------------------------
  $('#domain')?.addEventListener('change', () => {
    const dom = $('#domain').value || '';
    const subSel = $('#subcategory');
    const mt = $('#main-type');

    if (dom === 'Case Law') {
      if (subSel) { subSel.innerHTML = '<option value="">Subcategory (not used for Case Law)</option>'; subSel.disabled = true; }
      if (mt) mt.placeholder = 'Case Law title / citation (used as filename)';
      return;
    }

    if (mt) mt.placeholder = 'Main Type (e.g., Transfer Petition, Criminal Revision, Orders)';
    if (dom && SUBCATS[dom]) {
      populateOptions(subSel, SUBCATS[dom], "Subcategory");
    } else if (subSel) {
      subSel.innerHTML = '<option value="">Subcategory</option>'; subSel.disabled = true;
    }
  });

  $('#subcategory')?.addEventListener('change', () => {
    const val = ($('#subcategory')?.value || '').toLowerCase();
    const mt  = $('#main-type');
    if (!mt) return;
    if (val === 'primary documents') {
      mt.value = '';
      mt.disabled = true;
      mt.placeholder = 'Main Type (not used for Primary Documents)';
    } else {
      mt.disabled = false;
      if (($('#domain')?.value || '') !== 'Case Law') {
        mt.placeholder = 'Main Type (e.g., Transfer Petition, Criminal Revision, Orders)';
      }
    }
  });

  // --- File selection / upload -----------------------------------------
  const dz = $('#drop');
  const fileInput = $('#file');
  const fileList  = $('#file-list');
  let selectedFiles = [];

  function renderSelected(){
    if (!fileList) return;
    fileList.innerHTML = '';
    if (!selectedFiles.length){ fileList.textContent = 'No files selected.'; return; }
    selectedFiles.forEach((f, idx) => {
      const row = el('div','result-item');
      const name = el('div'); name.textContent = f.name;
      const meta = el('span','badge'); meta.textContent = `${(f.size/1024).toFixed(1)} KB`;
      const rm = el('button'); rm.type = 'button'; rm.textContent = '✕'; rm.className = 'btn-ghost';
      rm.style.padding = '4px 8px'; rm.style.marginLeft = 'auto';
      rm.addEventListener('click', ()=>{ selectedFiles.splice(idx,1); renderSelected(); });
      row.append(name, meta, rm);
      fileList.append(row);
    });
  }

  function chooseFiles(){ fileInput?.click(); }
  dz?.addEventListener('click', chooseFiles);
  dz?.addEventListener('keydown', (e)=>{ if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chooseFiles(); }});
  fileInput?.addEventListener('change', ()=>{ selectedFiles = Array.from(fileInput.files || []); renderSelected(); });
  dz?.addEventListener('dragover', e=>{ e.preventDefault(); dz.classList.add('dragover'); });
  dz?.addEventListener('dragleave', ()=> dz.classList.remove('dragover'));
  dz?.addEventListener('drop', e=>{
    e.preventDefault(); dz.classList.remove('dragover');
    const files = Array.from(e.dataTransfer.files || []);
    if (!files.length) return;
    const key = f => `${f.name}-${f.size}`;
    const have = new Set(selectedFiles.map(key));
    files.forEach(f => { if (!have.has(key(f))) selectedFiles.push(f); });
    renderSelected();
  });

  $('#mc-go')?.addEventListener('click', async ()=>{
    const year  = yearSel.value || '';
    const month = monthSel.value || '';
    const cname = caseSel.value || '';
    if (!year || !month || !cname){ alert('Select Year, Month, and Case.'); return; }
    if (!selectedFiles.length){ alert('Select at least one file'); return; }

    const fd = new FormData();
    fd.set('Year', year);
    fd.set('Month', month);
    fd.set('Case Name', cname);
    fd.set('Domain', $('#domain')?.value || '');
    fd.set('Subcategory', $('#subcategory')?.value || '');
    fd.set('Main Type', ($('#main-type')?.value || '').trim());
    fd.set('Date', $('#mc-date')?.value || '');
    selectedFiles.forEach(f => fd.append('file', f));

    const r = await fetch('/manage-case/upload', { method: 'POST', body: fd });
    const data = await r.json().catch(()=>({ok:false,msg:'Bad JSON'}));
    if (data.ok) {
      const saved = Array.isArray(data.saved_as) ? data.saved_as.join('\n') : data.saved_as;
      alert('Saved:\n' + saved);
      selectedFiles = []; if (fileInput) fileInput.value = ''; renderSelected();
    } else {
      alert('Error: ' + (data.msg || 'Upload failed'));
    }
  });

  renderSelected();
}

// -------------------- Notes modal global handlers --------------------
function bindGlobalNotesModalHandlers(){
  const modal   = document.getElementById('notesModal');
  const editor  = document.getElementById('notesEditor');
  const saveBtn = document.getElementById('saveNotesBtn');
  const cancel  = document.getElementById('cancelNotesBtn');
  const close   = document.getElementById('notesClose');
  const editBtn = document.getElementById('editNotesBtn');
  const title   = document.getElementById('notesTitle');

  if (!modal || !editor || !saveBtn || !cancel || !close || !editBtn) return;

  let originalContent = '';

  function setState(state){
    modal.dataset.state = state;
    const editing = state === 'edit';
    editor.readOnly = !editing;
    editor.classList.toggle('notes-readonly', !editing);
    saveBtn.hidden = !editing;
    editBtn.hidden = editing || modal.dataset.intent === 'create';
    cancel.textContent = editing && modal.dataset.intent !== 'create' ? 'Cancel' : 'Close';
    if (!editing) {
      // ensure caret doesn't stay focused when in view mode
      editor.blur();
    }
  }

  function openModal(content, intent){
    modal.dataset.intent = intent === 'create' ? 'create' : 'update';
    originalContent = content || '';
    editor.value = originalContent;
    setState(intent === 'create' ? 'edit' : 'view');
    editor.style.display = 'block';
    modal.removeAttribute('hidden');
    modal.setAttribute('aria-hidden','false');
    if (title) {
      title.textContent = intent === 'create' ? 'Create Note.json' : 'Case Notes (Note.json)';
    }
    if (modal.dataset.state === 'edit') {
      editor.focus();
      editor.setSelectionRange(editor.value.length, editor.value.length);
    }
  }

  function closeModal(){
    modal.setAttribute('hidden','');
    modal.setAttribute('aria-hidden','true');
    editor.readOnly = true;
    editor.blur();
    editor.style.display = 'none';
  }

  // Public helper used by manageCaseForm
  window._openNotesWith = function(content, intent){
    openModal(content || '', intent || 'update');
  };

  editBtn.addEventListener('click', () => {
    originalContent = editor.value;
    setState('edit');
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
  });

  async function saveCurrent(){
    const yEl = document.getElementById('mc-year');
    const mEl = document.getElementById('mc-month');
    const cEl = document.getElementById('mc-case');
    const year  = yEl?.value || '';
    const month = mEl?.value || '';
    const cname = cEl?.value || '';

    if (!year || !month || !cname) {
      alert('Select Year, Month, and Case first.');
      return;
    }

    const body = { content: editor.value };
    const intent = modal.dataset.intent === 'create' ? 'create' : 'update';
    let resp;
    try {
      if (intent === 'create') {
        resp = await fetch('/api/create-note', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ year, month, case: cname, content: editor.value })
        });
      } else {
        resp = await fetch(`/api/note/${year}/${month}/${encodeURIComponent(cname)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
      }
      const data = await resp.json().catch(()=>({}));
      if (!resp.ok || !data.ok) {
        throw new Error(data.msg || `HTTP ${resp.status}`);
      }
      originalContent = editor.value;
      alert(intent === 'create' ? 'Note.json created!' : 'Notes saved!');
      closeModal();
      modal.dataset.intent = 'update';
      setState('view');
      if (typeof window.__refreshNoteButton === 'function') {
        window.__refreshNoteButton();
      }
    } catch (err) {
      alert(`Save failed: ${err.message || err}`);
    }
  }

  function handleCancel(){
    const editing = modal.dataset.state === 'edit';
    if (editing && modal.dataset.intent !== 'create') {
      editor.value = originalContent;
      setState('view');
      return;
    }
    editor.value = originalContent;
    closeModal();
    setState('view');
  }

  saveBtn.addEventListener('click', saveCurrent);
  cancel.addEventListener('click', handleCancel);
  close.addEventListener('click', () => {
    editor.value = originalContent;
    closeModal();
    setState('view');
  });
}

// -------------------- Theme + flashes --------------------
function autoDismissFlashes(ms = 3000){
  const flashes = document.querySelectorAll('.flash-stack .flash');
  flashes.forEach(el => {
    // click to dismiss immediately
    const removeNow = () => { el.classList.add('flash-fade'); setTimeout(()=> el.remove(), 350); };
    el.addEventListener('click', removeNow, { once: true });

    // timed auto-dismiss
    setTimeout(() => {
      if (!document.body.contains(el)) return;
      el.classList.add('flash-fade');
      setTimeout(() => el.remove(), 350);
    }, ms);
  });
}

const THEME_KEY = 'caseOrg.theme';
function applyTheme(theme){
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.innerHTML = theme === 'dark'
      ? '<i class="fa-solid fa-sun"></i>'
      : '<i class="fa-solid fa-moon"></i>';
  }
}

function initTheme(){
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'light' || saved === 'dark') {
    applyTheme(saved);
    return;
  }
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(prefersDark ? 'dark' : 'light');
}

function setupThemeToggle(){
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  });

  const saved = localStorage.getItem(THEME_KEY);
  if (!saved && window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', e => applyTheme(e.matches ? 'dark' : 'light'));
  }
}

// -------------------- Startup wiring (single DOMContentLoaded) --------------------
document.addEventListener('DOMContentLoaded', () => {
  // Flashes auto-dismiss
  autoDismissFlashes(3000);

  // Theme
  initTheme();
  setupThemeToggle();

  // Year dropdown in Advanced Search
  initYearDropdown('year-dd', 'year', 2025);

  // Simple search
  const searchBtn = $('#search-btn');
  const searchQ = $('#search-q');
  searchBtn?.addEventListener('click', runBasicSearch);
  searchQ?.addEventListener('keydown', (e)=>{ if (e.key === 'Enter') { e.preventDefault(); runBasicSearch(); }});

  // Advanced toggle
  const advToggle = $('#adv-toggle');
  const advForm = $('#adv-form');
  advToggle?.addEventListener('click', ()=>{
    const isHidden = advForm.hidden;
    advForm.hidden = !isHidden;
    advToggle.setAttribute('aria-expanded', String(!isHidden));
  });

  // Advanced domain -> subcat
  const advDom = $('#adv-domain');
  const advSub = $('#adv-subcat');
  advDom?.addEventListener('change', ()=>{
    const dom = advDom.value || '';
    if (dom && SUBCATS[dom]) {
      populateOptions(advSub, SUBCATS[dom], "Subcategory");
    } else if (advSub) {
      advSub.innerHTML = '<option value="">Subcategory</option>';
      advSub.disabled = true;
    }
  });

  // Advanced search run
  const advSearch = $('#adv-search');
  advSearch?.addEventListener('click', runAdvancedSearch);

  // Directory search (if button exists)
  const dirBtn = document.getElementById('dir-search');
  dirBtn?.addEventListener('click', async () => {
    const results = document.getElementById('results');
    if (results) results.innerHTML = '<div class="result-item">Loading directory tree...</div>';
    await showDirLevel('');
  });

  // Cards + forms
  const cardCreate = $('#card-create');
  const cardManage = $('#card-manage');
  if (cardCreate && cardManage) {
    const activateCreate = ()=>{ setActive(cardCreate, [cardManage]); createCaseForm(); };
    const activateManage = ()=>{ setActive(cardManage, [cardCreate]); manageCaseForm(); };
    cardCreate.addEventListener('click', activateCreate);
    cardManage.addEventListener('click', activateManage);
    [cardCreate, cardManage].forEach(c=>{
      c.addEventListener('keydown', (e)=>{
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          (c === cardCreate ? activateCreate : activateManage)();
        }
      });
    });
  }

  // Notes modal global handlers (Save/Cancel/Close)
  bindGlobalNotesModalHandlers();
});
