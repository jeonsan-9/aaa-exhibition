/* AAA 천체사진전 — 전시실 걷기, 작품 크게 보기, 작품 목록, 음악 */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const works = JSON.parse($('#works-data').textContent);
  const pad = (n) => String(n).padStart(2, '0');
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const paras = (t) => String(t || '').trim().split(/\n\s*\n/).filter(Boolean).map((b) => `<p>${esc(b.trim()).replace(/\n/g, '<br>')}</p>`).join('');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── 전시실: 세로 스크롤을 벽을 따라 걷는 움직임으로 ── */
  const hall = $('.hall'), sticky = $('.hall-sticky'), track = $('.track');
  const pieces = $$('.piece', track);
  const wide = matchMedia('(min-width: 821px) and (min-height: 521px)');
  const hudCount = $('.hud-count'), hudTitle = $('.hud-title'), rail = $('.hud-rail i');
  let extra = 0, centers = [], cur = 0;

  function layout() {
    if (!wide.matches) { hall.style.height = ''; track.style.transform = ''; return; }
    extra = Math.max(0, track.scrollWidth - window.innerWidth);
    hall.style.height = sticky.offsetHeight + extra + 'px';
    centers = pieces.map((p) => p.offsetLeft + $('.frame', p).offsetWidth / 2);
    walk();
  }
  function walk() {
    if (!wide.matches) return;
    const x = Math.min(extra, Math.max(0, -hall.getBoundingClientRect().top));
    track.style.transform = `translate3d(${-x}px,0,0)`;
    const mid = x + window.innerWidth * 0.42;
    let best = 0;
    centers.forEach((c, i) => { if (Math.abs(c - mid) < Math.abs(centers[best] - mid)) best = i; });
    cur = best;
    hudCount.textContent = pad(works[best].n);
    hudTitle.textContent = `${works[best].title}${works[best].author ? ' — ' + works[best].author : ''}`;
    rail.style.width = (extra ? (x / extra) * 100 : 0) + '%';
  }
  function goTo(i, instant) {
    i = Math.min(pieces.length - 1, Math.max(0, i));
    const behavior = instant || reduced ? 'auto' : 'smooth';
    if (!wide.matches) { pieces[i].scrollIntoView({ behavior, block: 'center' }); return; }
    const top = hall.getBoundingClientRect().top + window.scrollY;
    window.scrollTo({ top: top + Math.min(extra, Math.max(0, centers[i] - window.innerWidth * 0.42)), behavior });
  }
  addEventListener('scroll', walk, { passive: true });
  addEventListener('resize', layout);
  addEventListener('load', layout);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
  layout();
  sticky.addEventListener('wheel', (e) => { // 트랙패드 좌우 쓸기
    if (wide.matches && Math.abs(e.deltaX) > Math.abs(e.deltaY)) { e.preventDefault(); window.scrollBy(0, e.deltaX); }
  }, { passive: false });
  $$('[data-step]').forEach((b) => b.addEventListener('click', () => goTo(cur + Number(b.dataset.step))));

  /* ── 작품 크게 보기 ── */
  const viewer = $('.viewer'), vImg = $('.viewer-stage img'), vText = $('.viewer-text'), vCount = $('.viewer-count');
  let vi = 0;
  function setHash(h) { try { history.replaceState(null, '', h || location.pathname + location.search); } catch (_) { /* 미리보기에서는 무시 */ } }
  function show(i) {
    vi = (i + works.length) % works.length;
    const w = works[vi];
    vImg.src = w.thumb; vImg.alt = w.title;
    vImg.width = w.w; vImg.height = w.h;
    const full = new Image();
    full.onload = () => { if (works[vi] === w) vImg.src = w.full; };
    full.src = w.full;
    const rows = [['전시실', w.section], ['촬영지', w.place], ['촬영일', w.date], ['장비', w.gear], ['촬영 정보', w.settings]]
      .filter((r) => r[1]).map((r) => `<dt>${r[0]}</dt><dd>${esc(r[1])}</dd>`).join('');
    vText.innerHTML = `<span class="no">No. ${pad(w.n)}</span><h2>${esc(w.title || '무제')}</h2>`
      + (w.author ? `<p class="by">${esc(w.author)}${w.aff ? `<span>${esc(w.aff)}</span>` : ''}</p>` : '')
      + (rows ? `<dl>${rows}</dl>` : '')
      + (w.comment ? `<div class="comment">${paras(w.comment)}</div>` : '');
    vText.scrollTop = 0;
    vCount.textContent = `${pad(w.n)} / ${pad(works.length)}`;
    setHash('#w-' + pad(w.n));
  }
  function open(i) { show(i); if (!viewer.open) viewer.showModal(); }
  viewer.addEventListener('close', () => { setHash(''); goTo(vi, true); });
  viewer.addEventListener('click', (e) => { if (e.target === viewer || e.target.classList.contains('viewer-stage')) viewer.close(); });
  $('.viewer-close').addEventListener('click', () => viewer.close());
  $$('[data-v]').forEach((b) => b.addEventListener('click', () => show(vi + Number(b.dataset.v))));
  pieces.forEach((p) => {
    const i = Number(p.dataset.i);
    $('.frame', p).addEventListener('click', () => open(i));
    $('.label', p).addEventListener('click', () => open(i));
  });
  $$('[data-open]').forEach((b) => b.addEventListener('click', () => open(Number(b.dataset.open))));

  addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const d = e.key === 'ArrowRight' ? 1 : -1;
    if (viewer.open) { show(vi + d); e.preventDefault(); return; }
    if (index.open || !wide.matches) return;
    const r = hall.getBoundingClientRect();
    if (r.top <= 1 && r.bottom >= window.innerHeight - 1) { goTo(cur + d); e.preventDefault(); }
  });

  /* ── 작품 목록 ── */
  const index = $('.index'), grid = $('.index-grid');
  let filled = false;
  $$('[data-open-index]').forEach((b) => b.addEventListener('click', () => {
    if (!filled) {
      grid.innerHTML = works.map((w, i) => `<button type="button" data-i="${i}"><img src="${w.thumb}" loading="lazy" alt=""><span class="no">No. ${pad(w.n)}</span><b>${esc(w.title || '무제')}</b><span>${esc(w.author)}</span></button>`).join('');
      filled = true;
    }
    index.showModal();
  }));
  grid.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-i]');
    if (!b) return;
    index.close();
    open(Number(b.dataset.i));
  });
  $('.index-close').addEventListener('click', () => index.close());

  /* ── 인사말 탭 ── */
  const tabs = $$('.g-tabs [role="tab"]');
  tabs.forEach((t) => t.addEventListener('click', () => {
    tabs.forEach((o) => { o.setAttribute('aria-selected', String(o === t)); $('#' + o.getAttribute('aria-controls')).hidden = o !== t; });
  }));

  /* ── 음악: 사이트에서는 작은 플레이어, 임베드가 막힌 곳에서는 유튜브 새 창 ── */
  const bgm = $('.bgm'), dock = $('.bgm-dock');
  if (bgm && $('.app').dataset.embed === 'on') {
    const label = $('span', bgm);
    const stop = () => { dock.hidden = true; dock.innerHTML = ''; bgm.classList.remove('on'); label.textContent = '음악 켜기'; };
    bgm.addEventListener('click', (e) => {
      e.preventDefault();
      if (!dock.hidden) return stop();
      const id = bgm.dataset.yt;
      dock.innerHTML = `<iframe src="https://www.youtube-nocookie.com/embed/${id}?autoplay=1&loop=1&playlist=${id}" title="전시 음악" allow="autoplay; encrypted-media"></iframe><button type="button">음악 끄기</button>`;
      $('button', dock).addEventListener('click', stop);
      dock.hidden = false; bgm.classList.add('on'); label.textContent = '음악 끄기';
    });
  }

  /* ── 주소에 #w-07 이 있으면 그 작품부터 ── */
  const m = /^#w-(\d+)$/.exec(location.hash);
  if (m && works[Number(m[1]) - 1]) { goTo(Number(m[1]) - 1, true); open(Number(m[1]) - 1); }
})();
