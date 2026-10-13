(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const fa = new Intl.NumberFormat('fa-IR');
  const toast = $('#toast');
  let toastTimer;
  function notify(message) { toast.textContent = message; toast.classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('visible'), 2400); }
  function setTheme(theme) { document.documentElement.dataset.theme = theme; $('#theme-toggle').setAttribute('aria-label', theme === 'dark' ? 'تغییر به تم روشن' : 'تغییر به تم تیره'); try { localStorage.setItem('fnc-docs-theme', theme); } catch {} }
  try { setTheme(localStorage.getItem('fnc-docs-theme') === 'dark' ? 'dark' : 'light'); } catch {}
  $('#theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

  function highlight(code) {
    const source = code.textContent;
    const tokens = /(#[^\n]*|"[^"\n]*"|'[^'\n]*'|\b(?:async|await|from|import|as|with|def|print|return|if|else|try|except|for|in|True|False|None)\b|\b\d+\b)/g;
    const fragment = document.createDocumentFragment(); let start = 0;
    for (const match of source.matchAll(tokens)) {
      fragment.append(document.createTextNode(source.slice(start, match.index)));
      const span = document.createElement('span'); span.textContent = match[0];
      span.className = match[0][0] === '#' ? 'syntax-comment' : /^['"]/.test(match[0]) ? 'syntax-string' : /^\d/.test(match[0]) ? 'syntax-number' : 'syntax-keyword';
      fragment.append(span); start = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(source.slice(start))); code.replaceChildren(fragment);
  }
  $$('.language-python').forEach(highlight);
  $$('.copy-button').forEach(button => button.addEventListener('click', async () => {
    const code = $('pre code', button.closest('.code-card'));
    try {
      let copied = false;
      if (navigator.clipboard && window.isSecureContext) {
        try { await Promise.race([navigator.clipboard.writeText(code.textContent), new Promise((_, reject) => setTimeout(() => reject(new Error('Clipboard unavailable')), 1200))]); copied = true; } catch {}
      }
      if (!copied) {
        const input = document.createElement('textarea'); input.value = code.textContent;
        input.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0';
        document.body.append(input); input.select(); copied = document.execCommand('copy'); input.remove(); button.focus();
        if (!copied) throw new Error('Copy failed');
      }
      button.textContent = 'کپی شد ✓'; notify('کد در کلیپ‌بورد کپی شد'); setTimeout(() => button.textContent = 'کپی کد', 2200);
    } catch { const range = document.createRange(); range.selectNodeContents(code); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); notify('کد انتخاب شد؛ با Ctrl+C آن را کپی کنید'); }
  }));

  $$('.tab-group').forEach(group => {
    const tabs = $$('[role=tab]', group);
    function activate(tab) { tabs.forEach(item => { const active = item === tab; item.setAttribute('aria-selected', String(active)); item.tabIndex = active ? 0 : -1; document.getElementById(item.getAttribute('aria-controls')).hidden = !active; }); }
    tabs.forEach((tab, index) => { tab.addEventListener('click', () => activate(tab)); tab.addEventListener('keydown', event => { let next; if (event.key === 'ArrowLeft') next = (index + 1) % tabs.length; if (event.key === 'ArrowRight') next = (index - 1 + tabs.length) % tabs.length; if (event.key === 'Home') next = 0; if (event.key === 'End') next = tabs.length - 1; if (next !== undefined) { event.preventDefault(); activate(tabs[next]); tabs[next].focus(); } }); });
  });

  const sidebar = $('#sidebar'), menuButton = $('#menu-toggle'), backdrop = $('#menu-backdrop');
  function closeMenu() { sidebar.classList.remove('is-open'); menuButton.setAttribute('aria-expanded', 'false'); backdrop.hidden = true; sidebar.inert = matchMedia('(max-width:780px)').matches; }
  menuButton.addEventListener('click', () => { const open = !sidebar.classList.contains('is-open'); sidebar.classList.toggle('is-open', open); menuButton.setAttribute('aria-expanded', String(open)); backdrop.hidden = !open; sidebar.inert = !open && matchMedia('(max-width:780px)').matches; });
  backdrop.addEventListener('click', closeMenu); $$('.nav-link').forEach(link => link.addEventListener('click', closeMenu));
  addEventListener('resize', () => { if (!matchMedia('(max-width:780px)').matches) closeMenu(); else sidebar.inert = !sidebar.classList.contains('is-open'); });
  closeMenu();
  const sections = $$('main > section');
  function updateActive() { let active = sections[0]; for (const section of sections) { if (section.getBoundingClientRect().top <= 145) active = section; } $$('.nav-link').forEach(link => { const selected = link.getAttribute('href') === '#' + active.id; link.classList.toggle('active', selected); if (selected) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current'); }); }
  let scrollTick = false;
  addEventListener('scroll', () => { if (!scrollTick) requestAnimationFrame(() => { updateActive(); scrollTick = false; }); scrollTick = true; }, {passive:true}); updateActive();

  const methodRows = $$('#method-list tr');
  function filterMethods() { const query = $('#method-search').value.trim().toLowerCase(), kind = $('#method-kind').value; let count = 0; for (const row of methodRows) { const matches = row.dataset.method.includes(query) && (kind === 'all' || row.dataset.kind === kind); row.hidden = !matches; if (matches) count++; } $('#method-count').textContent = fa.format(count) + ' عملیات'; $('#method-empty').hidden = count !== 0; }
  $('#method-search').addEventListener('input', filterMethods); $('#method-kind').addEventListener('change', filterMethods); filterMethods();

  const dialog = $('#search-dialog'), input = $('#doc-search'), results = $('#search-results');
  const searchIndex = sections.map(section => ({id:section.id, title:section.dataset.search || $('h2', section)?.textContent || 'معرفی', text:section.textContent.toLowerCase()}));
  function normalize(value) { return value.toLowerCase().replace(/ي/g,'ی').replace(/ك/g,'ک').replace(/\u200c/g,' '); }
  function renderSearch() {
    const query = normalize(input.value.trim()); results.replaceChildren();
    const found = query ? searchIndex.filter(item => normalize(item.text).includes(query)) : searchIndex.slice(0,6);
    if (!found.length) { const empty = document.createElement('p'); empty.className = 'empty-state'; empty.textContent = 'نتیجه‌ای پیدا نشد. نام متد یا موضوع دیگری را امتحان کنید.'; results.append(empty); return; }
    for (const item of found) { const link = document.createElement('a'); link.href = '#' + item.id; link.className = 'search-result'; const title = document.createElement('strong'); title.textContent = item.title; const hint = document.createElement('span'); hint.textContent = item.id === 'catalog' ? 'فهرست قابل جست‌وجوی عملیات RPC' : 'رفتن به بخش مستندات'; link.append(title, hint); link.addEventListener('click', () => { dialog.close(); closeMenu(); }); results.append(link); }
  }
  function openSearch() { renderSearch(); dialog.showModal(); input.focus(); }
  $('#search-trigger').addEventListener('click', openSearch); $('#search-close').addEventListener('click', () => dialog.close()); input.addEventListener('input', renderSearch);
  dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } });
  addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); if (event.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !document.activeElement.isContentEditable) { event.preventDefault(); openSearch(); } });
})();
