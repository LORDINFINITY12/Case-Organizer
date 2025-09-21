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

function populateOptions(select, arr, placeholder="Select"){
  select.innerHTML = "";
  const opt = el("option"); opt.value = ""; opt.textContent = placeholder; select.append(opt);
  arr.forEach(v => { const o = el("option"); o.textContent = v; select.append(o); });
  select.disabled = false;
}

// --- Search helpers -----------------------------------------------------
async function runBasicSearch(){
  const q = ($('#search-q').value || '').trim();
  const r = await fetch(`/search?q=${encodeURIComponent(q)}`);
  const data = await r.json();
  renderResults(data.results);
}

async function runAdvancedSearch(){
  const params = new URLSearchParams();

  const party = (document.getElementById('party')?.value || '').trim();
  const year  = (document.getElementById('year')?.value || '').trim();   // works with hidden #year from year-dd
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
  const data = await r.json();
  renderResults(data.results);
}

// Infinite, scrollable year dropdown (virtualized-ish)
function initYearDropdown(wrapperId, hiddenInputId, startYear = 2015) {
  const wrap = document.getElementById(wrapperId);
  if (!wrap) return;
  const trigger = wrap.querySelector('.yd-trigger');
  const panel = wrap.querySelector('.yd-panel');
  const hidden = document.getElementById(hiddenInputId);

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
    const el = panel.querySelector(`.yd-item[data-year="${y}"]`);
    if (el) el.classList.add('selected');
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
    if (['ArrowUp','ArrowDown','PageUp','PageDown','Home','End','Enter','Escape'].includes(e.key)) {
      e.preventDefault();
      let next = cur;
      if (e.key === 'ArrowUp') next = cur + 1;
      if (e.key === 'ArrowDown') next = cur - 1;
      if (e.key === 'PageUp') next = cur + 10;
      if (e.key === 'PageDown') next = cur - 10;
      if (e.key === 'Home') next = 9999;
      if (e.key === 'End') next = 1;
      if (e.key === 'Enter') { close(); return; }
      if (e.key === 'Escape') { close(); return; }
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
      const el = panel.querySelector(`.yd-item[data-year="${next}"]`);
      if (el) {
        const r = el.getBoundingClientRect();
        const pr = panel.getBoundingClientRect();
        if (r.top < pr.top + 4) panel.scrollTop -= (pr.top + 4 - r.top);
        if (r.bottom > pr.bottom - 4) panel.scrollTop += (r.bottom - (pr.bottom - 4));
      }
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

  // Initial render will happen on first open; set a sane initial label now
  setYear(selected);
}

window.addEventListener('DOMContentLoaded', () => {
  // ...your existing wiring...
  initYearDropdown('year-dd', 'year', 2015);
});

function renderResults(items){
  const results = $('#results');
  results.innerHTML = '';
  if (!items || !items.length){ results.textContent = 'No results'; return; }
  items.forEach(it => {
    const row = el('div','result-item');
    const left = el('div'); left.textContent = it.rel;
    const dl = el('a'); dl.textContent = 'Download'; dl.href = `/static-serve?path=${encodeURIComponent(it.path)}&download=1`; dl.target = '_blank';
    row.append(left, dl);
    results.append(row);
  });
}

// --- Forms --------------------------------------------------------------
function setActive(card, others){
  card.classList.add('active'); card.setAttribute('aria-pressed','true');
  others.forEach(c => { c.classList.remove('active'); c.setAttribute('aria-pressed','false'); });
}

function createCaseForm(){
  const host = $('#form-host');
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
  $('#cc-date').valueAsDate = new Date();

  // Auto case name from PN/RN
  function updateCaseName(){
    const pn = ($('#pn').value || '').trim();
    const rn = ($('#rn').value || '').trim();
    const name = (pn && rn) ? `${pn} v. ${rn}` : '';
    $('#cc-name').value = name;
    $('#cc-name-preview').value = name;
  }
  ['pn','rn'].forEach(id => $('#'+id).addEventListener('input', updateCaseName));
  updateCaseName();

  // Domain -> Subcategory -> CaseType
  $('#cat').addEventListener('change', () => {
    const dom = $('#cat').value || '';
    if (dom && SUBCATS[dom]) {
      populateOptions($('#subcat'), SUBCATS[dom], "Subcategory");
      populateOptions($('#ctype'), CASE_TYPES[dom], "Case Type");
      $('#ctype').disabled = false;
    } else {
      $('#subcat').innerHTML = '<option value="">Subcategory</option>'; $('#subcat').disabled = true;
      $('#ctype').innerHTML = '<option value="">Case Type</option>'; $('#ctype').disabled = true;
      $('#ctype-other').style.display = 'none';
    }
  });

  // Show text input only if Case Type == Others
  $('#ctype').addEventListener('change', () => {
    const val = $('#ctype').value || '';
    $('#ctype-other').style.display = (val === 'Others') ? 'block' : 'none';
  });

  // Submit
  $('#cc-go').addEventListener('click', async ()=>{
    const fd = new FormData();
    fd.set('Date', $('#cc-date').value);
    fd.set('Case Name', $('#cc-name').value);  // auto-built
    fd.set('Petitioner Name', ($('#pn').value || '').trim());
    fd.set('Petitioner Address', ($('#pa').value || '').trim());
    fd.set('Petitioner Contact', ($('#pc').value || '').trim());
    fd.set('Respondent Name', ($('#rn').value || '').trim());
    fd.set('Respondent Address', ($('#ra').value || '').trim());
    fd.set('Respondent Contact', ($('#rc').value || '').trim());
    fd.set('Our Party', $('#op').value);
    const cat = $('#cat').value || '';
    const subcat = $('#subcat').value || '';
    fd.set('Case Category', cat);
    fd.set('Case Subcategory', subcat);
    const ctypeSel = $('#ctype').value || '';
    const ctype = (ctypeSel === 'Others') ? ($('#ctype-other').value || '').trim() : ctypeSel;
    fd.set('Case Type', ctype);
    fd.set('Origin State', ($('#os').value || '').trim());
    fd.set('Origin District', ($('#od').value || '').trim());
    fd.set('Origin Court/Forum', ($('#of').value || '').trim());
    fd.set('Current State', ($('#cs').value || '').trim());
    fd.set('Current District', ($('#cd').value || '').trim());
    fd.set('Current Court/Forum', ($('#cf').value || '').trim());
    fd.set('Additional Notes', ($('#an').value || '').trim());

    if (!$('#cc-name').value) { alert('Enter Petitioner and Respondent to form the Case Name.'); return; }

    const r = await fetch('/create-case', { method: 'POST', body: fd });
    const data = await r.json();
    alert(data.ok ? 'Case created at: ' + data.path : ('Error: ' + data.msg));
  });
}


function manageCaseForm(){
  const host = $('#form-host');
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
        <option>Criminal</option><option>Civil</option><option>Commercial</option>
      </select>
      <select id="subcategory" disabled><option value="">Subcategory</option></select>
      <input type="text" id="main-type" placeholder="Main Type (e.g., Transfer Petition, Criminal Revision, Orders)" />

      <!-- Date used in filename (only if Main Type is provided) -->
      <input type="date" id="mc-date" />
    </div>

    <div class="dropzone" id="drop" tabindex="0">Drag & drop files here or click to select</div>
    <input type="file" id="file" hidden accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.json" multiple />
    <div id="file-list" class="results"></div>

    <div class="form-actions">
      <button id="mc-go" class="btn-primary" type="button">Upload & Categorize File(s)</button>
    </div>
  `;
  host.append(wrap);
  $('#mc-date').valueAsDate = new Date();

  // --- Populate Year / Month / Case from backend -----------------------
  const yearSel  = $('#mc-year');
  const monthSel = $('#mc-month');
  const caseSel  = $('#mc-case');

  async function loadYears(){
    const r = await fetch('/api/years'); const data = await r.json();
    yearSel.innerHTML = '<option value="">Year</option>';
    (data.years || []).forEach(y => {
      const o = el('option'); o.value = y; o.textContent = y; yearSel.append(o);
    });
    yearSel.disabled = false;
    monthSel.innerHTML = '<option value="">Month</option>'; monthSel.disabled = true;
    caseSel.innerHTML  = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true;
  }

  async function loadMonths(year){
    const r = await fetch(`/api/months?${new URLSearchParams({year})}`); const data = await r.json();
    monthSel.innerHTML = '<option value="">Month</option>';
    (data.months || []).forEach(m => {
      const o = el('option'); o.value = m; o.textContent = m; monthSel.append(o);
    });
    monthSel.disabled = false;
    caseSel.innerHTML  = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true;
  }

  async function loadCases(year, month){
    const r = await fetch(`/api/cases?${new URLSearchParams({year, month})}`); const data = await r.json();
    caseSel.innerHTML = '<option value="">Case (Petitioner v. Respondent)</option>';
    (data.cases || []).forEach(cn => {
      const o = el('option'); o.value = cn; o.textContent = cn; caseSel.append(o);
    });
    caseSel.disabled = false;
  }

  yearSel.addEventListener('change', () => {
    const y = yearSel.value || '';
    if (!y){
      monthSel.innerHTML = '<option value="">Month</option>'; monthSel.disabled = true;
      caseSel.innerHTML  = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true;
      return;
    }
    loadMonths(y);
  });

  monthSel.addEventListener('change', () => {
    const y = yearSel.value || ''; const m = monthSel.value || '';
    if (y && m) loadCases(y, m);
    else { caseSel.innerHTML = '<option value="">Case (Petitioner v. Respondent)</option>'; caseSel.disabled = true; }
  });

  // Kickoff
  loadYears();

  // --- Domain -> Subcategory ------------------------------------------
  $('#domain').addEventListener('change', () => {
    const dom = $('#domain').value || '';
    if (dom && SUBCATS[dom]) {
      populateOptions($('#subcategory'), SUBCATS[dom], "Subcategory");
    } else {
      $('#subcategory').innerHTML = '<option value="">Subcategory</option>'; $('#subcategory').disabled = true;
    }
  });

// When subcategory is "Primary Documents", disable Main Type and mark optional
$('#subcategory').addEventListener('change', () => {
  const val = ($('#subcategory').value || '').toLowerCase();
  const mt  = $('#main-type');
  if (val === 'primary documents') {
    mt.value = '';
    mt.disabled = true;
    mt.placeholder = 'Main Type (not used for Primary Documents)';
  } else {
    mt.disabled = false;
    mt.placeholder = 'Main Type (e.g., Transfer Petition, Criminal Revision, Orders)';
  }
});

  // --- File selection (multi) with remove buttons ----------------------
  const dz = $('#drop');
  const fileInput = $('#file');
  const fileList  = $('#file-list');
  /** @type {File[]} */
  let selectedFiles = [];

  function renderSelected(){
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

  function chooseFiles(){ fileInput.click(); }
  dz.addEventListener('click', chooseFiles);
  dz.addEventListener('keydown', (e)=>{ if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chooseFiles(); }});

  fileInput.addEventListener('change', ()=>{
    selectedFiles = Array.from(fileInput.files || []);
    renderSelected();
  });

  dz.addEventListener('dragover', e=>{ e.preventDefault(); dz.classList.add('dragover'); });
  dz.addEventListener('dragleave', ()=> dz.classList.remove('dragover'));
  dz.addEventListener('drop', e=>{
    e.preventDefault(); dz.classList.remove('dragover');
    const files = Array.from(e.dataTransfer.files || []);
    if (!files.length) return;
    const key = f => `${f.name}-${f.size}`;
    const have = new Set(selectedFiles.map(key));
    files.forEach(f => { if (!have.has(key(f))) selectedFiles.push(f); });
    renderSelected();
  });

  // --- Submit -----------------------------------------------------------
  $('#mc-go').addEventListener('click', async ()=>{
    const year  = yearSel.value || '';
    const month = monthSel.value || '';
    const cname = caseSel.value || '';
    if (!year || !month || !cname){ alert('Select Year, Month, and Case.'); return; }
    if (!selectedFiles.length){ alert('Select at least one file'); return; }

    const fd = new FormData();
    fd.set('Year', year);
    fd.set('Month', month);
    fd.set('Case Name', cname);
    fd.set('Domain', $('#domain').value || '');
    fd.set('Subcategory', $('#subcategory').value || '');
    fd.set('Main Type', ($('#main-type').value || '').trim());   // OPTIONAL
    fd.set('Date', $('#mc-date').value);                         // used only if Main Type provided
    selectedFiles.forEach(f => fd.append('file', f));

    const r = await fetch('/manage-case/upload', { method: 'POST', body: fd });
    const data = await r.json();
    if (data.ok) {
      const saved = Array.isArray(data.saved_as) ? data.saved_as.join('\n') : data.saved_as;
      alert('Saved:\n' + saved);
      selectedFiles = []; fileInput.value = ''; renderSelected();
    } else {
      alert('Error: ' + (data.msg || 'Upload failed'));
    }
  });

  renderSelected();
}


// --- Startup wiring -----------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
  // Advanced search toggle
  const advToggle = $('#adv-toggle');
  const advForm = $('#adv-form');
  if (advToggle) {
    advToggle.addEventListener('click', ()=>{
      const isHidden = advForm.hidden;
      advForm.hidden = !isHidden;
      advToggle.setAttribute('aria-expanded', String(!isHidden));
    });
  }

  // Populate subcat in adv search when domain changes
  const advDom = $('#adv-domain');
  const advSub = $('#adv-subcat');
  if (advDom) {
    advDom.addEventListener('change', ()=>{
      const dom = advDom.value || '';
      if (dom && SUBCATS[dom]) {
        populateOptions(advSub, SUBCATS[dom], "Subcategory");
      } else {
        advSub.innerHTML = '<option value="">Subcategory</option>'; advSub.disabled = true;
      }
    });
  }

  // Basic search + enter key
  const searchBtn = $('#search-btn');
  const searchQ = $('#search-q');
  if (searchBtn) {
    searchBtn.addEventListener('click', runBasicSearch);
    searchQ.addEventListener('keydown', (e)=>{ if (e.key === 'Enter') { e.preventDefault(); runBasicSearch(); }});
  }

  // Advanced search
  const advSearch = $('#adv-search');
  if (advSearch) advSearch.addEventListener('click', runAdvancedSearch);

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
});

// --- Auto Dismiss Annotations ------------------------------------------
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

window.addEventListener('DOMContentLoaded', () => {
  // ...your existing wiring...
  autoDismissFlashes(3000);
  populateYearSelect('year', 2015, 5);
});

// --- Dark/Light Mode ------------------------------------------

// Theme state keys
const THEME_KEY = 'caseOrg.theme';

function applyTheme(theme){
  // theme: 'light' | 'dark'
  document.documentElement.setAttribute('data-theme', theme);
  // swap icon
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.innerHTML = theme === 'dark'
      ? '<i class="fa-solid fa-sun"></i>'
      : '<i class="fa-solid fa-moon"></i>';
  }
}

function initTheme(){
  // 1) saved preference
  const saved = localStorage.getItem(THEME_KEY);
  if (saved === 'light' || saved === 'dark') {
    applyTheme(saved);
    return;
  }
  // 2) system preference
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

  // keep in sync if user changes OS theme (only when no explicit choice saved)
  const saved = localStorage.getItem(THEME_KEY);
  if (!saved && window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', e => applyTheme(e.matches ? 'dark' : 'light'));
  }
}

// Ensure it initializes with the rest of your bootstrapping code
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  setupThemeToggle();
});

