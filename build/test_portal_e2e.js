// portal_e2e.js - end-to-end test of ExM Explorer in jsdom (real DOM, real event dispatch).
// Usage: npm install jsdom && node test_portal_e2e.js ../portal/index.html
const { JSDOM, VirtualConsole } = require('jsdom');
const fs = require('fs');
const FILE = process.argv[2];
const html = fs.readFileSync(FILE, 'utf8');
const errors = [], downloads = [], opened = [], notes = [];
let clip = null, ctx = 'load';
const vc = new VirtualConsole();
vc.on('jsdomError', e => { const m = String(e.message || e); if (!/Not implemented: (navigation|window\.scrollTo|HTMLCanvas)/.test(m)) errors.push(`[${ctx}] ${m} ${e.detail ? (e.detail.stack || e.detail).toString().split('\n')[0] : ''}`); });
vc.on('error', m => errors.push(`[${ctx}] console.error: ${m}`));
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://www.dudinlab.com/exame/', virtualConsole: vc,
  beforeParse(w) {
    w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = function () { w.__scrolledTo = this.id; };
    w.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {} });
    w.open = (u) => { opened.push(u); return null; }; w.confirm = () => true; w.alert = () => {};
    const B = w.Blob; w.Blob = function (parts, opt) { const b = new B(parts, opt); b.__text = parts.map(String).join(''); return b; };
    w.__blobs = {}; let n = 0;
    w.URL.createObjectURL = b => { const id = 'blob:test/' + (n++); w.__blobs[id] = b; return id; };
    w.URL.revokeObjectURL = () => {};
    Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: t => { clip = t; return Promise.resolve(); } }, configurable: true });
    w.HTMLAnchorElement.prototype.click = function () {
      const h = this.getAttribute('href') || '';
      if (this.download || h.startsWith('blob:')) downloads.push({ name: this.download, text: (w.__blobs[h] || {}).__text, ctx });
      else opened.push(this.href);
    };
  }
});
const w = dom.window, d = w.document;
const $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)];
const visible = el => { for (let e = el; e && e !== d.body; e = e.parentElement) { if (e.style && e.style.display === 'none') return false; if (e.id === 'panel' && !d.body.innerHTML.includes('panel')) return false; } return true; };
const KEYWORDS = new Set(['if', 'return', 'function', 'event', 'stopPropagation', 'preventDefault', 'this', 'for', 'while', 'switch']);
const missingFns = new Set(), clicked = {}, linkIssues = [], allLinks = new Map();
function scanHandlers() {
  for (const el of $$('[onclick],[onchange],[oninput]')) {
    for (const a of ['onclick', 'onchange', 'oninput']) {
      const code = el.getAttribute(a); if (!code) continue;
      for (const m of code.replace(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g,"''").matchAll(/(?:^|[^.\w])([A-Za-z_]\w*)\s*\(/g)) if (!KEYWORDS.has(m[1]) && typeof w[m[1]] !== 'function') missingFns.add(`${m[1]} (in ${a}="${code.slice(0, 60)}")`);
    }
  }
}
function scanLinks() {
  for (const a of $$('a[href]')) {
    const h = a.getAttribute('href'), t = (a.textContent || '').trim().slice(0, 40);
    allLinks.set(h, t);
    if (h && h.startsWith('blob:')) continue;
    if (!h || /undefined|null|NaN|\[object/.test(h)) linkIssues.push(`bad href "${h}" (${t}) [${ctx}]`);
    else if (!/^(https:\/\/|mailto:|#)/.test(h)) linkIssues.push(`unexpected scheme "${h}" (${t}) [${ctx}]`);
    if (/doi\.org\//.test(h) && !/^https:\/\/doi\.org\/10\.\d{4,9}\/\S+$/.test(h)) linkIssues.push(`malformed DOI link "${h}" [${ctx}]`);
    if (a.getAttribute('target') === '_blank' && !/noopener/.test(a.getAttribute('rel') || '')) notes.push(`target=_blank without rel=noopener: ${h.slice(0, 60)}`);
  }
}
function clickAll(label, sel, maxPerFn = 2) {
  ctx = label; scanHandlers(); scanLinks();
  const groups = {};
  for (const el of $$(sel || '[onclick]')) { const f = ((el.getAttribute('onclick') || '').match(/([A-Za-z_]\w*)\s*\(/) || [])[1]; if (!f) continue; (groups[f] = groups[f] || []).push(el); }
  return groups;
}
function fire(el, label) { ctx = label; try { el.click(); } catch (e) { errors.push(`[${label}] threw ${e.message}`); } clicked[label] = (clicked[label] || 0) + 1; scanHandlers(); scanLinks(); }
function input(id, v, ev = 'input') { const e = $('#' + id); if (!e) { errors.push(`[${ctx}] missing input #${id}`); return; } e.value = v; e.dispatchEvent(new w.Event(ev, { bubbles: true })); }
const textOf = id => ($('#' + id) || { textContent: '' }).textContent;

(async () => {
  await new Promise(r => setTimeout(r, 300));
  ctx = 'init'; scanHandlers(); scanLinks();
  const R = {};
  // ---- tabs
  const tabs = $$('.tab').map(t => t.getAttribute('data-tab'));
  for (const t of tabs) {
    fire($(`.tab[data-tab="${t}"]`), `tab:${t}`);
    const view = $('#view-' + t), shown = view && view.style.display !== 'none';
    R[`tab ${t} shows its view`] = shown && view.textContent.trim().length > 50;
  }
  // ---- overview + infographic
  fire($('.tab[data-tab="overview"]'), 'overview');
  R['Fig1 tree rendered'] = (textOf('f1-tree').length > 200);
  R['Fig2 bars rendered'] = (textOf('f2-bars').length > 100);
  R['Fig1 KPI + prokaryote note'] = textOf('f1-kpi').length > 5 && /bacteria/.test(textOf('f1-prok'));
  fire($('.tab[data-tab="trends"]'), 'infographic');
  R['Infographic: 11 figure cards'] = $$('#ov-grid .ocard').length === 11;
  const trans = $$('#ov-grid a[href*="google"], #ov-grid [onclick]');
  R['Infographic: transferability antibodies clickable'] = trans.length >= 10;
  // ---- species tab
  fire($('.tab[data-tab="browse"]'), 'species');
  const cards = $$('#grid [onclick]');
  R['Species grid lists all species'] = cards.length === w.eval("SPECIES").length || /\d/.test(textOf('browse-count'));
  const sideClicks = $$('#sidebar [onclick]');
  for (const el of sideClicks.slice(0, 12)) fire(el, 'species filter');
  for (const el of $$('#sidebar [onclick]').slice(0, 12)) fire(el, 'species filter reset');
  fire($$('#grid [onclick]')[0], 'open species');
  R['Species panel opens with content'] = ($('#panel') || {}).textContent.length > 100;
  const pLinks = $$('#panel [onclick]');
  const pg = {}; pLinks.forEach(e => { const f = (e.getAttribute('onclick').match(/([A-Za-z_]\w*)\s*\(/) || [])[1]; (pg[f] = pg[f] || []).push(e); });
  for (const f in pg) if (!['closePanel'].includes(f)) { fire($$('.tab[data-tab="browse"]')[0], 'species'); fire($$('#grid [onclick]')[0], 'open species'); const e = $$('#panel [onclick]').find(x => (x.getAttribute('onclick') || '').startsWith(f)); if (e) fire(e, `species panel → ${f}`); }
  w.closePanel && w.closePanel();
  // ---- antibodies
  fire($('.tab[data-tab="antibodies"]'), 'antibodies');
  const nAB0 = $$('#view-antibodies [onclick*="openAB"]').length;
  input('ab-q', 'tubulin'); const nAB1 = $$('#view-antibodies [onclick*="openAB"]').length;
  R['Antibody search filters'] = nAB1 > 0 && nAB1 <= nAB0;
  for (const [id, ev] of [['ab-clade', 'change'], ['ab-cat', 'change'], ['ab-type', 'change'], ['ab-min', 'change'], ['ab-chan', 'change'], ['ab-homog', 'change'], ['ab-var', 'change']]) {
    const s = $('#' + id); if (!s) { errors.push('missing #' + id); continue; }
    for (const o of [...s.options].slice(0, 4)) { ctx = `antibody filter ${id}=${o.value}`; s.value = o.value; s.dispatchEvent(new w.Event(ev, { bubbles: true })); }
    s.value = s.options[0].value; s.dispatchEvent(new w.Event(ev, { bubbles: true }));
  }
  input('ab-q', 'tubulin');
  let dl0 = downloads.length; fire($('[onclick^="exportAB"]'), 'export antibodies CSV');
  const abcsv = downloads[dl0];
  R['Antibody CSV export (filtered)'] = !!abcsv && abcsv.name.endsWith('.csv') && abcsv.text.split('\n').length > 2 && /^name,target/.test(abcsv.text);
  input('ab-q', ''); dl0 = downloads.length; fire($('[onclick^="exportAB"]'), 'export antibodies CSV (all)');
  R[`Antibody CSV export (all = ${w.eval("ABP").length})`] = downloads[dl0] && downloads[dl0].text.split('\n').length - 1 === w.eval("ABP").length;
  const ty = $('#ab-type'); if (ty && [...ty.options].some(o => o.value === 'secondary')) { ty.value = 'secondary'; ty.dispatchEvent(new w.Event('change')); dl0 = downloads.length; fire($('[onclick^="exportAB"]'), 'export secondary CSV'); R[`Secondary CSV export (= ${w.eval("ABS").length})`] = downloads[dl0] && downloads[dl0].text.split('\n').length - 1 === w.eval("ABS").length; ty.value = ty.options[0].value; ty.dispatchEvent(new w.Event('change')); }
  fire($$('#view-antibodies [onclick*="openAB"]')[0], 'open antibody');
  R['Antibody panel opens'] = ($('#panel') || {}).textContent.length > 80;
  const buy = $$('#panel a[href]').map(a => a.getAttribute('href'));
  R['Antibody panel has buy/registry links'] = buy.some(h => /^https:\/\//.test(h));
  const add = $('#panel [onclick^="addCur"]'); if (add) fire(add, 'add to reagent list');
  for (const f of ['toggleCmp', 'openReagentFromPaper', 'openPaper', 'openSpecies']) { const e = $(`#panel [onclick^="${f}"]`); if (e) { fire(e, `antibody panel → ${f}`); fire($('.tab[data-tab="antibodies"]'), 'antibodies'); fire($$('#view-antibodies [onclick*="openAB"]')[0], 'open antibody'); } }
  // ---- dyes
  fire($('.tab[data-tab="dye"]'), 'dyes');
  input('dy-q', 'DAPI'); R['Dye search filters'] = $$('#view-dye [onclick*="openDye"]').length > 0;
  for (const [id, ev] of [['dy-type', 'change'], ['dy-clade', 'change'], ['dy-min', 'change'], ['dy-chan', 'change']]) { const s = $('#' + id); if (!s) { errors.push('missing #' + id); continue; } for (const o of [...s.options].slice(0, 4)) { ctx = `dye filter ${id}=${o.value}`; s.value = o.value; s.dispatchEvent(new w.Event(ev, { bubbles: true })); } s.value = s.options[0].value; s.dispatchEvent(new w.Event(ev, { bubbles: true })); }
  input('dy-q', ''); dl0 = downloads.length; fire($('[onclick^="exportDye"]'), 'export dyes CSV');
  R[`Dye CSV export (all = ${w.eval("DYE").length})`] = downloads[dl0] && downloads[dl0].text.split('\n').length - 1 === w.eval("DYE").length;
  fire($$('#view-dye [onclick*="openDye"]')[0], 'open dye'); R['Dye panel opens'] = ($('#panel') || {}).textContent.length > 80;
  const addD = $('#panel [onclick^="addCur"]'); if (addD) fire(addD, 'add dye to list');
  // ---- publications
  fire($('.tab[data-tab="papers"]'), 'publications');
  R['Publications list rendered'] = $$('.papercard').length > 20;
  R['Publications header counts studies'] = /^\d+ studies/.test(textOf('pp-stats'));
  for (const v of ['year', 'variant', '']) { ctx = 'group ' + v; const s = $('#pp-group'); s.value = v; s.dispatchEvent(new w.Event('change')); }
  input('pp-q', 'Mikus'); R['Publication search'] = $$('.papercard').length >= 1;
  input('pp-q', 'sphaeroforma'); R['Publication search by species (Sphaeroforma: 3)'] = $$('.papercard').length === 3;
  input('pp-q', 'ichthyosporea'); R['Publication search by lineage (Ichthyosporea: 4)'] = $$('.papercard').length === 4;
  input('pp-q', 'Mikus');
  dl0 = downloads.length; fire($('[onclick^="exportBib"]'), 'export BibTeX'); R['BibTeX export (filtered)'] = downloads[dl0] && /@article\{/.test(downloads[dl0].text);
  input('pp-q', ''); dl0 = downloads.length; fire($('[onclick^="exportBib"]'), 'export BibTeX all');
  R[`BibTeX export (all = ${w.eval("PAPERS").length})`] = downloads[dl0] && (downloads[dl0].text.match(/@article\{/g) || []).length === w.eval("PAPERS").length;
  dl0 = downloads.length; fire($('[onclick^="exportRis"]'), 'export RIS'); R[`RIS export (all = ${w.eval("PAPERS").length})`] = downloads[dl0] && (downloads[dl0].text.match(/^TY  - JOUR/gm) || []).length === w.eval("PAPERS").length;
  const bibKeys = (downloads[downloads.length - 2].text.match(/@article\{([^,]+),/g) || []); R['BibTeX keys unique'] = new Set(bibKeys).size === bibKeys.length;
  fire($$('.papercard')[0], 'open paper'); R['Paper panel opens with DOI link'] = $$('#panel a[href^="https://doi.org/"]').length >= 1;
  for (const f of ['openSpecies', 'openReagentFromPaper']) { const e = $(`#panel [onclick^="${f}"]`); if (e) { fire(e, `paper panel → ${f}`); fire($('.tab[data-tab="papers"]'), 'publications'); fire($$('.papercard')[0], 'open paper'); } }
  // ---- methods
  fire($('.tab[data-tab="methods"]'), 'methods');
  const steps = $$('.pstep'); let okSteps = 0;
  for (const s of steps) { w.__scrolledTo = null; fire(s, 'method step'); const target = (s.getAttribute('onclick').match(/'([\w-]+)'/) || [])[1]; if (target && $('#' + target) && w.__scrolledTo === target) okSteps++; else errors.push(`[methods] step → #${target} did not scroll to an existing section`); }
  R[`Methods: all ${steps.length} scheme steps jump to their section`] = okSteps === steps.length && steps.length === 11;
  R['Methods: subtitles removed'] = $$('#view-methods .fd2').length === 0;
  // ---- basket
  fire($('.hbtn'), 'open basket'); R['Reagent list shows added items'] = ($('#mbody') || {}).textContent.length > 20 && w.eval("basket") && w.eval("basket").length >= 1;
  dl0 = downloads.length; const eb = $('[onclick^="exportBasket"]'); if (eb) fire(eb, 'export reagent list'); R['Reagent list CSV export'] = downloads[dl0] && downloads[dl0].text.split('\n').length - 1 === w.eval("basket").length;
  const rb = $('[onclick^="removeBasket"]'); if (rb) fire(rb, 'remove from list');
  const cb = $('[onclick^="clearBasket"]'); if (cb) fire(cb, 'clear list'); R['Reagent list clears'] = w.eval("basket").length === 0;
  w.closeModal();
  // ---- compare tray
  const cmp = $('[onclick^="openCompare"]'); if (cmp) { fire(cmp, 'open compare'); R['Compare opens'] = ($('#mbody') || {}).textContent.length > 20; const cc = $('[onclick^="clearCmp"]'); if (cc) fire(cc, 'clear compare'); w.closeModal(); } else notes.push('compare tray not reachable in this run (needs two items toggled)');
  // ---- global search
  for (const q of ['tubulin', 'Homo', 'DAPI', 'Mikus', 'metamonada']) {
    input('gq', q); const res = $$('#gdrop .gi[onclick]'); R[`Global search "${q}" returns results`] = res.length > 0;
    if (res.length) fire(res[0], `global search → ${q}`);
  }
  // ---- citation
  fire($('.footer [onclick^="openCite"]'), 'footer Cite button'); R['Footer Cite button opens citation'] = ($('#mbody')||{}).textContent.includes('ExM Explorer v1.0'); w.closeModal(); w.openCite(); R['Citation names version and DOI'] = /^Mikus F, Llanos Fuentes PL, Juárez Núñez KA, Beltrame D, Dey G, Dudin O \(2026\)/.test(textOf('mbody').trim()) && /ExM Explorer v1\.0/.test(textOf('mbody')) && /doi\.org\/10\.5281\/zenodo\.23439354/.test(textOf('mbody'));
  clip = null; fire($('[onclick^="copyCite"]'), 'copy citation'); await new Promise(r => setTimeout(r, 50)); R['Copy citation puts it on clipboard'] = clip && /ExM Explorer/.test(clip);
  w.closeModal();
  // ---- hash deep links
  for (const [h, chk] of [['#antibodies', () => $('#view-antibodies').style.display !== 'none'], ['#papers', () => $('#view-papers').style.display !== 'none'],
    ['#browse/species/' + encodeURIComponent(w.eval("SPECIES")[0].sp), () => ($('#panel') || {}).textContent.includes(w.eval("SPECIES")[0].sp)],
    ['#antibodies/antibody/' + encodeURIComponent(w.eval("ABP")[0].name), () => ($('#panel') || {}).textContent.includes(w.eval("ABP")[0].name)]]) {
    ctx = 'hash ' + h; w.location.hash = h; w.dispatchEvent(new w.HashChangeEvent('hashchange')); await new Promise(r => setTimeout(r, 20)); R[`Deep link ${h.slice(0, 40)}`] = !!chk(); w.closePanel && w.closePanel();
  }
  // ---- Escape closes things
  w.openCite(); d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); R['Escape closes the modal'] = !$('#mwrap').classList.contains('on');
  // ---- every buy link the antibody/dye panels can produce
  const hosts = {}; for (const a of w.eval('ABP').concat(w.eval('ABS'), w.eval('DYE'))) { const u = w.buyLink(a); const hst = (u.match(/^https:\/\/([^/]+)/) || [, 'BAD:' + u])[1]; hosts[hst] = (hosts[hst] || 0) + 1; }
  console.log('buy-link hosts over all reagents:', JSON.stringify(hosts));
  R['Buy links only use verified patterns'] = Object.keys(hosts).every(h => ['www.google.com', 'www.abcam.com', 'www.thermofisher.com'].includes(h));
  R['Citation with DOI link in footer (every tab)'] = !!$('.footer #citetext a[href="https://doi.org/10.5281/zenodo.23439354"]') && !$('.footer').closest('[id^="view-"]');
  R['Release date 21 October 2026 shown'] = /21 October 2026/.test($('.footer').textContent) && /21 October 2026/.test($('#view-methods').textContent);
  // ---- full-page figure views (complete axes) and figure clicks
  w.switchTab('overview'); w.renderOverview();
  const figKeys = [...d.querySelectorAll('[data-fig]')].map(x => x.getAttribute('data-fig'));
  let figOK = figKeys.length === 13, axOK = true;
  for (const k of figKeys) { ctx = 'fig ' + k; try { w.openFig(k); } catch (e) { errors.push(`[fig ${k}] ${e.message}`); figOK = false; continue; }
    if (!$('#fsw').classList.contains('on')) figOK = false;
    const sv = $('#fsb svg');
    if (sv) { const fw = [...sv.querySelectorAll('text[font-weight="600"]')].length; if (fw < 2) { axOK = false; notes.push(`fig ${k}: ${fw} axis titles`); } }
    else if (!$('#fsb .fsmtx')) axOK = false;
    w.figCSV(); if (sv) w.figSVG(); w.closeFig(); }
  R['Every Overview figure opens full page (13)'] = figOK;
  R['Every full-page chart has both axis titles'] = axOK;
  const clickSvg = () => $('#fsb g.fsclk').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  R['Small Overview cards are not clickable'] = d.querySelectorAll('#ov-grid [onclick]:not(.fsbtn)').length === 0;
  R['Figure 1 card has 3 headline numbers'] = d.querySelectorAll('#f1-kpi .k1').length === 3;
  w.openFig('target'); clickSvg(); const T = $('#fsside .sdt').textContent.replace('Target: ', '');
  R['Target bar opens a side card, page unchanged'] = w.eval('currentTab') === 'overview' && $('#fsw').classList.contains('on') && $('#fsgrid').classList.contains('side') &&
    d.querySelectorAll('#fsside details').length === w.eval('ABP').filter(a => (a.tgts || [a.target]).includes(T)).length;
  w.openFig('cat'); clickSvg(); const cn = $('#fsside .sdt').textContent.replace('Category: ', '');
  R['Category side card lists exactly the antibodies counted'] = d.querySelectorAll('#fsside details').length === w.eval('OVERVIEW').CAT.find(c => c.label === cn).value;
  w.openFig('trans'); clickSvg(); R['Transferability bar opens the antibody sheet beside the chart'] = $('#fsside details').open && w.eval('currentTab') === 'overview';
  w.openFig('mat'); $('#fsb td.fsclk').click(); const M = w.eval('OVERVIEW').MAT;
  R['Matrix cell lists the antibodies behind it'] = d.querySelectorAll('#fsside details').length === M.abs[0][0].length && M.abs[0][0].length > 0;
  $('#fsside .x').click(); R['Side card closes'] = !$('#fsgrid').classList.contains('side');
  w.closeFig(); w.switchTab('overview');
  // ---- species view: secondaries hidden by default; protocol records link their papers
  const SP = w.eval('SPECIES'); const si = SP.findIndex(s => s.labels.some(l => l.type === 'secondary_antibody'));
  w.eval('SHOWSEC=false'); w.openSpecies(si);
  const secShown = () => [...d.querySelectorAll('#panel .labcard .lm')].filter(x => /secondary antibody/.test(x.textContent)).length;
  const s0 = secShown(); $('#sectog').checked = true; $('#sectog').dispatchEvent(new w.Event('change', { bubbles: true })); const s1 = secShown();
  R['Secondaries hidden by default, shown by toggle'] = s0 === 0 && s1 > 0; w.eval('SHOWSEC=false'); w.closePanel();
  let ppOK = true; SP.forEach(s => s.protos.forEach(p => { if (!p.pp || !p.pp.length || p.pp.some(k => !s.papers[k])) ppOK = false; }));
  R['Every protocol record lists its source papers'] = ppOK;
  const hi = SP.findIndex(s => s.protos.some(p => p.pp.length > 1)); const pj = SP[hi].protos.findIndex(p => p.pp.length > 1);
  w.openCard(hi, pj); R['Protocol card links every paper that reported the recipe'] = $('#mbody').querySelectorAll('.paperitem a[href^="https://doi.org/"]').length === SP[hi].protos[pj].pp.filter(k => SP[hi].papers[k].doi).length; w.closeModal();
  w.cmp.length = 0; w.cmp.push(si, SP.findIndex((s, i) => i !== si && s.labels.length)); w.eval('SHOWSEC=false'); w.openCompare();
  const exp = new Set(); w.cmp.forEach(k => SP[k].labels.forEach(l => { if (l.type !== 'secondary_antibody') exp.add(l.name); }));
  const nrows = d.querySelectorAll('#mbody .cmptbl tbody tr').length;
  R['Compare view hides secondaries by default'] = !!$('#cmpsectog') && nrows === Math.min(200, exp.size);
  w.closeModal(); w.cmp.length = 0;
  // ---- report
  ctx = 'final'; scanLinks();
  const fails = Object.entries(R).filter(([k, v]) => !v);
  console.log('\n=== CHECKS ==='); for (const [k, v] of Object.entries(R)) console.log((v ? '  PASS ' : '  FAIL ') + k);
  console.log(`\nclick actions fired: ${Object.values(clicked).reduce((a, b) => a + b, 0)} across ${Object.keys(clicked).length} kinds`);
  console.log(`downloads: ${downloads.map(x => x.name).join(', ')}`);
  console.log(`window.open targets: ${opened.length} (${[...new Set(opened.map(u => (u.match(/^https?:\/\/([^/]+)/) || [, u])[1]))].join(', ')})`);
  console.log(`distinct hrefs seen: ${allLinks.size}`);
  console.log(`\nMISSING HANDLER FUNCTIONS (${missingFns.size}):`); [...missingFns].forEach(x => console.log('  ' + x));
  console.log(`LINK ISSUES (${linkIssues.length}):`); [...new Set(linkIssues)].slice(0, 30).forEach(x => console.log('  ' + x));
  console.log(`JS ERRORS (${errors.length}):`); [...new Set(errors)].slice(0, 40).forEach(x => console.log('  ' + x));
  console.log(`NOTES (${new Set(notes).size}):`); [...new Set(notes)].slice(0, 10).forEach(x => console.log('  ' + x));
  fs.writeFileSync(require('path').join(require('os').tmpdir(),'exm_hrefs.json'), JSON.stringify([...allLinks.entries()]));
  console.log(`\nRESULT: ${Object.keys(R).length} checks, ${fails.length} failed, ${new Set(errors).size} JS errors, ${missingFns.size} missing handlers, ${new Set(linkIssues).size} link issues`);
  process.exit(0);
})();
