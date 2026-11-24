/* =====================================================================
   投研雷达 V4 · 短线复盘前端渲染与动效引擎（供 radar/site/app.js 集成挂载）
   特性：
   1. 对齐原站 IntersectionObserver 错峰渐显、数字滚动跳字、弹簧仪表、滑动滑块；
   2. 增加顶栏阅读进度细线、语义色双层聚光灯、Sparkline 渐变面积发光、
      时间轴滚动激光进度线 + ScrollSpy 自动高亮、光标跟随浮层提示；
   3. 严格遵循 V3 XSS 与文本安全：所有文本走 esc() 或 textContent；
   4. 严格不含 banned_words 与旧 UI 措辞；DATA.shortTerm 缺省时降级显示。
   ===================================================================== */
(() => {
  'use strict';

  const RM = () => !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, m => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]
    ));
  }

  const shown = value => esc(value == null || value === '' ? '—' : value);
  const empty = message => `<p class="sub" style="padding:8px 16px">${esc(message)}</p>`;
  const percentage = value => Number.isFinite(value) && value >= 0 && value <= 100;

  function fmtPct(v) {
    if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
    const sign = v > 0 ? '+' : v < 0 ? '−' : '';
    return sign + (Math.abs(v) * 100).toFixed(2) + '%';
  }

  function ensureGlobalChrome() {
    if (!document.getElementById('srSvgDefs')) {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.id = 'srSvgDefs';
      svg.setAttribute('width', '0');
      svg.setAttribute('height', '0');
      svg.setAttribute('aria-hidden', 'true');
      svg.style.position = 'absolute';
      svg.innerHTML = `
        <defs>
          <linearGradient id="sr-g-up" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--up)" stop-opacity=".34"/>
            <stop offset="100%" stop-color="var(--up)" stop-opacity="0"/>
          </linearGradient>
          <linearGradient id="sr-g-down" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--down)" stop-opacity=".34"/>
            <stop offset="100%" stop-color="var(--down)" stop-opacity="0"/>
          </linearGradient>
          <linearGradient id="srGaugeGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#1fc77e"/>
            <stop offset="45%" stop-color="#8b7bff"/>
            <stop offset="78%" stop-color="#ffb020"/>
            <stop offset="100%" stop-color="#ff4d5e"/>
          </linearGradient>
        </defs>
      `;
      document.body.appendChild(svg);
    }

    let prog = document.getElementById('srReadProgress');
    if (!prog) {
      prog = document.createElement('div');
      prog.id = 'srReadProgress';
      prog.className = 'sr-read-progress';
      document.body.appendChild(prog);
    }

    let tip = document.getElementById('srTip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'srTip';
      tip.className = 'sr-tip';
      tip.setAttribute('role', 'tooltip');
      document.body.appendChild(tip);
    }
    return { prog, tip };
  }

  function sparkSvg(vals, isUp) {
    if (!Array.isArray(vals) || vals.length < 2 || vals.length > 5 || !vals.every(Number.isFinite)) return '';
    const w = 68, h = 24, pad = 2.5;
    const min = Math.min(...vals), max = Math.max(...vals);
    const span = max - min || 1;
    const pts = vals.map((v, i) => {
      const x = pad + (i / (vals.length - 1)) * (w - pad * 2);
      const y = h - pad - ((v - min) / span) * (h - pad * 2);
      return [x.toFixed(1), y.toFixed(1)];
    });
    const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ',' + p[1]).join(' ');
    const area = `${d} L${pts[pts.length - 1][0]},${h} L${pts[0][0]},${h} Z`;
    const last = pts[pts.length - 1];
    const kind = isUp ? 'up' : 'down';
    return `<span class="sr-spark ${kind}"><svg viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${area}" fill="url(#sr-g-${kind})"/><path class="line" d="${d}"/><circle cx="${last[0]}" cy="${last[1]}" r="2.2"/></svg></span>`;
  }

  function renderGaugeSvg(score, stateLabel) {
    if (!percentage(score)) return empty(stateLabel || '散户情绪暂无数据');
    const safeScore = score;
    const deg = (-90 + (safeScore / 100) * 180).toFixed(1);
    const arcLen = 320.44; // PI * 102
    const targetOffset = (arcLen * (1 - safeScore / 100)).toFixed(2);
    const rad = ((safeScore / 100) * Math.PI);
    const endX = (130 - 102 * Math.cos(rad)).toFixed(1);
    const endY = (128 - 102 * Math.sin(rad)).toFixed(1);

    return `
      <div style="text-align:center">
        <svg viewBox="0 0 260 150" style="width:224px;margin:0 auto" aria-label="散户情绪温度计">
          <path d="M 28 128 A 102 102 0 0 1 232 128" fill="none" stroke="var(--surface-3)" stroke-width="14" stroke-linecap="round"/>
          <path class="sr-gauge-arc" d="M 28 128 A 102 102 0 0 1 232 128" fill="none" stroke="url(#srGaugeGrad)" stroke-width="14" stroke-linecap="round"
            stroke-dasharray="${arcLen}" stroke-dashoffset="${RM() ? targetOffset : arcLen}" data-to="${targetOffset}" opacity=".95"/>
          <circle class="sr-gauge-halo" cx="${endX}" cy="${endY}" r="7"/>
          <g class="sr-gauge-needle" data-deg="${deg}" style="${RM() ? `transform:rotate(${deg}deg)` : ''}">
            <line x1="130" y1="128" x2="130" y2="40" stroke="var(--text)" stroke-width="3" stroke-linecap="round"/>
          </g>
          <circle cx="130" cy="128" r="6.5" fill="var(--text)"/>
          <text x="22" y="146" fill="var(--text-3)" font-size="10" font-family="var(--font-mono)">0 冰点</text>
          <text x="115" y="18" fill="var(--text-3)" font-size="10" font-family="var(--font-mono)">50 分歧</text>
          <text x="206" y="146" fill="var(--text-3)" font-size="10" font-family="var(--font-mono)">100 亢奋</text>
        </svg>
        <div style="margin-top:-6px">
          <div class="num" style="font-size:30px;font-weight:780;line-height:1">
            <span data-count="${safeScore}">${safeScore}</span><span style="font-size:13px;color:var(--text-3)"> / 100</span>
          </div>
          <div style="margin-top:6px"><span class="st stale">${esc(stateLabel)}</span></div>
        </div>
      </div>
    `;
  }

  function renderRankRows(rows, isUp, maxAbs) {
    if (!rows?.length) return empty('该榜暂无数据');
    return rows.map((r, idx) => {
      const barW = Math.min(100, Math.max(16, (Math.abs(r.pct || 0) / maxAbs) * 100)).toFixed(0);
      const tipDetail = [
        `${r.name}（${r.code}）`,
        `涨跌幅 ${fmtPct(r.pct)}`,
        `成交 ${r.turnover ?? '—'}`,
        r.netFlow ? `资金 ${r.netFlow}` : '',
        r.radarLink ? `雷达关联：${r.radarLink}` : '',
        r.reason
      ].filter(Boolean).join(' ｜ ');

      return `
        <div class="sr-rank-row ${isUp ? 'is-up' : 'is-down'}" data-sr-tip="${esc(tipDetail)}" tabindex="0">
          <div class="sr-rank-idx ${r.rank === 1 ? 'top1 ' + (isUp ? 'is-up' : 'is-down') : ''}">${esc(r.rank)}</div>
          <div class="sr-rank-main">
            <div class="sr-rank-title">
              <b>${esc(r.name)}</b>
              <span class="sr-rank-code">${esc(r.code)}</span>
              ${r.radarLink ? `<span class="sr-radar-tag">★ ${esc(r.radarLink)}</span>` : ''}
            </div>
            <div class="sr-rank-reason">${esc(r.reason)}</div>
            <div class="sr-rank-meta num">
              <span>成交 ${shown(r.turnover)}</span>
              ${r.netFlow ? `<span>资金 ${esc(r.netFlow)}</span>` : ''}
            </div>
          </div>
          <div class="sr-rank-spark">${sparkSvg(r.spark, isUp)}</div>
          <div class="sr-rank-val">
            <div class="sr-rank-pct num ${isUp ? 'up' : 'down'}">${fmtPct(r.pct)}</div>
            ${r.px ? `<div class="sr-rank-px num">现价 ${esc(r.px)}</div>` : ''}
            <div class="sr-ebar ${isUp ? 'up-bar' : 'down-bar'}"><i style="width:${barW}%;animation-delay:${idx * 55}ms"></i></div>
          </div>
        </div>
      `;
    }).join('');
  }

  function countUp(el) {
    const to = parseFloat(el.dataset.count);
    const dp = +(el.dataset.dp || 0);
    if (!Number.isFinite(to)) return;
    if (RM()) { el.textContent = to.toFixed(dp); return; }
    const t0 = performance.now();
    const dur = 950;
    const step = now => {
      if (!el.isConnected || el.closest('[hidden]')) return;
      const p = Math.min(1, (now - t0) / dur);
      const ease = 1 - Math.pow(1 - p, 3);
      el.textContent = (to * ease).toFixed(dp);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function moveSegThumb(segEl) {
    if (!segEl) return;
    const btn = segEl.querySelector('button.on');
    const thumb = segEl.querySelector('.thumb');
    if (!btn || !thumb || !btn.offsetWidth) return;
    thumb.style.left = btn.offsetLeft + 'px';
    thumb.style.width = btn.offsetWidth + 'px';
  }

  function initSegThumbs(root, previousThumbs) {
    root.querySelectorAll('.sr-seg').forEach((segEl, index) => {
      if (!segEl.querySelector('.thumb')) {
        const span = document.createElement('span');
        span.className = 'thumb';
        if (previousThumbs[index]) {
          span.style.left = previousThumbs[index].left;
          span.style.width = previousThumbs[index].width;
        }
        segEl.insertBefore(span, segEl.firstChild);
      }
      segEl.querySelectorAll('button').forEach(btn => {
        btn.setAttribute('aria-pressed', String(btn.classList.contains('on')));
      });
      void segEl.offsetWidth;
      requestAnimationFrame(() => moveSegThumb(segEl));
    });
  }

  function initShortTermModule(options) {
    const shortData = options && options.shortData;
    const mount = options && options.mountEl;
    const longView = options && options.longViewEl;
    const todayMount = options && options.todayTeaserEl;
    const onViewChange = options && options.onViewChange;
    if (!mount) return { switchView() {} };

    const { prog, tip } = ensureGlobalChrome();

    const ui = {
      view: 'long',
      dayIdx: 0,
      boardTab: 'industry',
      stockScope: 'market',
      egoPlatform: 'all',
      catFilter: 'all',
      revealObs: null,
      spyObs: null
    };

    // 全局光标聚光灯 + 悬浮提示框 + 阅读进度条 + 时间轴激光进度线
    if (!window.__srGlobalFxBound) {
      window.__srGlobalFxBound = true;
      let tipTarget = null;
      const clearTip = () => { tip.classList.remove('on'); tipTarget = null; };
      ui.clearTip = clearTip;
      const placeTip = (x, y) => {
        const w = tip.offsetWidth || 260, h = tip.offsetHeight || 60;
        const L = x + 14 + w > innerWidth - 10 ? x - w - 14 : x + 14;
        const T = y + 16 + h > innerHeight - 10 ? y - h - 12 : y + 16;
        tip.style.transform = `translate(${Math.max(8, L)}px, ${Math.max(8, T)}px)`;
      };

      document.addEventListener('pointermove', e => {
        const glowEl = e.target.closest && e.target.closest('.card, .sr-glow');
        if (glowEl && (mount.contains(glowEl) || todayMount?.contains(glowEl))) {
          const r = glowEl.getBoundingClientRect();
          glowEl.style.setProperty('--mx', (e.clientX - r.left) + 'px');
          glowEl.style.setProperty('--my', (e.clientY - r.top) + 'px');
        }
        if (tipTarget && tipTarget.isConnected) {
          placeTip(e.clientX, e.clientY);
        }
      }, { passive: true });

      document.addEventListener('pointerover', e => {
        if (e.pointerType === 'touch') return;
        const t = e.target.closest && e.target.closest('[data-sr-tip]');
        if (!t || t === tipTarget || !mount.contains(t)) return;
        tipTarget = t;
        tip.textContent = t.dataset.srTip;
        tip.classList.add('on');
        placeTip(e.clientX, e.clientY);
      });

      document.addEventListener('pointerout', e => {
        if (!tipTarget) return;
        const rel = e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('[data-sr-tip]');
        if (rel !== tipTarget) {
          tip.classList.remove('on');
          tipTarget = null;
        }
      });

      document.addEventListener('focusin', e => {
        const t = e.target.closest && e.target.closest('[data-sr-tip]');
        if (!t || !mount.contains(t)) return;
        tipTarget = t;
        tip.textContent = t.dataset.srTip;
        tip.classList.add('on');
        const r = t.getBoundingClientRect();
        placeTip(r.left + 20, r.bottom);
      });

      document.addEventListener('focusout', e => {
        if (e.target.closest && e.target.closest('[data-sr-tip]')) {
          tip.classList.remove('on');
          tipTarget = null;
        }
      });

      let rafPending = false;
      const updateScrollFx = () => {
        rafPending = false;
        if (mount.hidden) { prog.classList.remove('on'); return; }
        const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
        const ratio = Math.max(0, Math.min(1, window.scrollY / maxScroll));
        prog.style.setProperty('--sr-scroll', ratio.toFixed(4));
        prog.classList.toggle('on', window.scrollY > 36);

        const stream = mount.querySelector('.sr-tl-stream');
        if (stream && stream.offsetParent !== null) {
          const r = stream.getBoundingClientRect();
          const vh = window.innerHeight;
          const progress = Math.max(0.08, Math.min(1, (vh * 0.62 - r.top) / Math.max(1, r.height)));
          stream.style.setProperty('--tl-fill', progress.toFixed(4));
          stream.querySelectorAll('.sr-tl-stage').forEach(st => {
            const sr = st.getBoundingClientRect();
            st.classList.toggle('is-lit', sr.top <= vh * 0.68);
          });
        }
      };

      ui.updateScrollFx = updateScrollFx;
      window.addEventListener('scroll', () => {
        if (tipTarget) { tip.classList.remove('on'); tipTarget = null; }
        if (!rafPending) { rafPending = true; requestAnimationFrame(updateScrollFx); }
      }, { passive: true });

      window.addEventListener('resize', () => {
        mount.querySelectorAll('.sr-seg').forEach(moveSegThumb);
      });
    }

    function activateScrollRevealAndGauge(previousThumbs) {
      if (ui.revealObs) ui.revealObs.disconnect();
      if (ui.spyObs) ui.spyObs.disconnect();

      const revealEls = Array.from(mount.querySelectorAll('.sr-reveal'));
      const fireCardFx = el => {
        el.querySelectorAll('[data-count]').forEach(countUp);
        el.querySelectorAll('.sr-gauge-arc').forEach(arc => {
          requestAnimationFrame(() => { arc.style.strokeDashoffset = arc.dataset.to; });
        });
        el.querySelectorAll('.sr-gauge-needle').forEach(n => {
          requestAnimationFrame(() => { n.style.transform = `rotate(${n.dataset.deg}deg)`; });
        });
      };

      if (!('IntersectionObserver' in window) || RM()) {
        revealEls.forEach(el => { el.classList.add('in'); fireCardFx(el); });
      } else {
        ui.revealObs = new IntersectionObserver((entries, observer) => {
          entries.forEach(entry => {
            if (!entry.isIntersecting || mount.hidden || !entry.target.isConnected) return;
            entry.target.classList.add('in');
            fireCardFx(entry.target);
            observer.unobserve(entry.target);
          });
        }, { threshold: 0.06, rootMargin: '0px 0px -4% 0px' });

        revealEls.forEach((el, idx) => {
          const siblingIdx = el.parentElement ? Array.from(el.parentElement.children).indexOf(el) : idx;
          el.style.transitionDelay = Math.min(280, siblingIdx * 65) + 'ms';
          ui.revealObs.observe(el);
        });
      }

      // 左侧时间轴 ScrollSpy 自动追踪 + 点击闪烁定位
      const railLinks = Array.from(mount.querySelectorAll('.sr-rail-nav a[href^="#"]'));
      const setRailActive = id => {
        railLinks.forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + id));
      };
      if ('IntersectionObserver' in window && railLinks.length) {
        ui.spyObs = new IntersectionObserver(entries => {
          if (mount.hidden) return;
          entries.forEach(entry => {
            if (entry.isIntersecting && entry.target.isConnected) setRailActive(entry.target.id);
          });
        }, { rootMargin: '-28% 0px -62% 0px' });
        railLinks.forEach(a => {
          const target = mount.querySelector(a.getAttribute('href'));
          if (target) ui.spyObs.observe(target);
        });
      }

      const jumpLinks = [...railLinks, ...mount.querySelectorAll('.sr-upcoming a[href="#srCatalysts"]')];
      jumpLinks.forEach(a => {
        a.addEventListener('click', e => {
          e.preventDefault();
          const id = a.getAttribute('href').slice(1);
          const target = mount.querySelector('#' + id);
          if (!target) return;
          setRailActive(id);
          target.scrollIntoView({ behavior: RM() ? 'auto' : 'smooth', block: 'start' });
          const flashBox = target.classList.contains('card') || target.classList.contains('sr-tl-card')
            ? target : target.querySelector('.sr-tl-card, .card');
          if (flashBox) {
            flashBox.classList.remove('sr-flash');
            void flashBox.offsetWidth;
            flashBox.classList.add('sr-flash');
          }
        });
      });

      initSegThumbs(mount, previousThumbs);
      ui.updateScrollFx?.();
    }

    function switchView(nextView) {
      ui.view = nextView === 'short' ? 'short' : 'long';
      if (longView) longView.hidden = ui.view === 'short';
      mount.hidden = ui.view !== 'short';
      ui.clearTip?.();
      if (mount.hidden) {
        ui.revealObs?.disconnect();
        ui.spyObs?.disconnect();
        prog.classList.remove('on');
      }
      if (typeof onViewChange === 'function') onViewChange(ui.view);
      if (ui.view === 'short') {
        mount.classList.remove('sr-fade-swap');
        void mount.offsetWidth;
        mount.classList.add('sr-fade-swap');
        renderShortView();
        window.scrollTo({ top: 0, behavior: RM() ? 'auto' : 'smooth' });
      }
    }

    function renderTodayTeaser() {
      if (!todayMount) return;
      const days = Array.isArray(shortData?.days) ? shortData.days : [];
      if (!days.length) return;
      const d = days[0];
      const topInd = d.industries && d.industries.up && d.industries.up[0];
      todayMount.innerHTML = `
        <div class="sr-today-link sr-glow sr-glow-cyan">
          <div>
            <span class="mono" style="color:var(--accent-2);font-weight:700">短线复盘 · ${esc(d.shortDate)}</span>
            <span class="muted"> · 情绪 ${shown(d.sentimentScore)}/100${shortData.meta?.isStale ? ' · 沿用快照' : ''}</span>
            ${topInd ? ` · 领涨 <b>${esc(topInd.name)}</b> <span class="up num">${fmtPct(topInd.pct)}</span>` : ''}
          </div>
          <button type="button" class="sr-link-btn" data-open-short>进入短线复盘 →</button>
        </div>
      `;
      const btn = todayMount.querySelector('[data-open-short]');
      if (btn) btn.addEventListener('click', () => switchView('short'));
    }

    function renderShortView() {
      const days = Array.isArray(shortData?.days) ? shortData.days : [];
      const previousThumbs = Array.from(mount.querySelectorAll('.sr-seg .thumb'), thumb => ({
        left: thumb.style.left, width: thumb.style.width
      }));
      ui.clearTip?.();
      const catalysts = ui.dayIdx === 0 && Array.isArray(shortData?.catalysts)
        ? shortData.catalysts.filter(e => e && [3, 4, 5].includes(e.stars) && typeof e.title === 'string') : [];
      const pulseInfo = (shortData && shortData.meta) || {};
      if (!days.length) {
        mount.innerHTML = `
          <div class="card card-b sr-glow" style="margin-top:20px">
            <h2 class="h2">短线复盘数据暂未生成</h2>
            <p class="sub">短线复盘在交易日 20:30 汇总。快照更新后可在这里查看。</p>
          </div>
        `;
        return;
      }
      if (ui.dayIdx >= days.length) ui.dayIdx = 0;
      const d = days[ui.dayIdx];
      const b = d.breadth || {};
      const counts = [b.up, b.flat, b.down];
      const total = counts.every(n => Number.isSafeInteger(n) && n >= 0)
        ? counts.reduce((sum, n) => sum + n, 0) : null;
      const share = n => total > 0 ? (n / total * 100).toFixed(1) : null;
      const [upW, flatW, downW] = counts.map(share);
      const platforms = (d.ego?.platforms || []).filter(p =>
        [p.bull, p.flat, p.bear].every(percentage));

      const rec = d.yesterdayReconcile || { summary: '暂无前日锚点记录', items: [] };
      const showInd = ui.boardTab === 'industry' || ui.boardTab === 'both';
      const showCon = ui.boardTab === 'concept' || ui.boardTab === 'both';
      const stkSet = (d.stocks && d.stocks[ui.stockScope]) || { up: [], down: [] };
      const maxStkAbs = ui.stockScope === 'market' ? 0.16 : 0.105;

      const egoPosts = ((d.ego && d.ego.posts) || []).filter(
        p => ui.egoPlatform === 'all' || p.platform === ui.egoPlatform
      );
      const filteredCatalysts = catalysts.filter(ev => {
        if (ui.catFilter === 'star5') return ev.stars === 5;
        if (ui.catFilter === 'industry') return ev.category === 'industry';
        if (ui.catFilter === 'macro') return ev.category === 'macro';
        return true;
      });

      mount.innerHTML = `
        <section class="section" style="padding-top:16px">
          <div class="sr-date-strip sr-glow sr-reveal">
            <div class="sr-date-top">
              <span><b>滚动近 ${days.length} 个交易日复盘档期</b> <span class="muted">（每日 20:30 晚间定稿 · 点击日期即可回看红黑榜、Ego舆情与锚点对比）</span></span>
              <span class="num mono">当前：${esc(d.date)}（第 ${ui.dayIdx + 1}/${days.length} 日）</span>
            </div>
            <div class="sr-date-pills">
              ${days.map((item, idx) => `
                <button type="button" class="sr-date-pill sr-glow ${idx === ui.dayIdx ? 'active' : ''}" data-day-idx="${idx}">
                  <div class="sr-dp-r1"><span>${esc(item.shortDate)}</span><span class="sr-dot ${esc(item.themeColor || 'warn')}"></span></div>
                  <div class="sr-dp-r2"><span>${esc(item.weekday)}</span><span class="num">情绪 ${shown(item.sentimentScore)}</span></div>
                </button>
              `).join('')}
            </div>
          </div>

          <div class="sr-hero-grid">
            <div class="sr-reveal">
              <div class="eyebrow"><span class="live"></span><span>SHORT-TERM RADAR · ${esc(d.date)} ${esc(d.weekday)}</span></div>
              <h1 class="h1 grad">${esc(d.headline)}</h1>
              <div class="prov">
                <span class="st ai">${esc((d.pulse && d.pulse.finalTime) || '定稿时间暂缺')}</span>
                ${pulseInfo.isStale ? `<span class="st stale">沿用快照 · ${esc(d.date)}</span>` : ''}
                <span>来源：<b>${esc(pulseInfo.sourceLabel || '本机短线快照')}</b></span>
              </div>
              <p class="lead">${esc(d.subHeadline)}</p>
              <div class="pulse">
                <span class="dot ${pulseInfo.isStale ? 'warn' : ''}"></span>
                <span><b>${esc(d.pulse?.quoteTime || '行情时间暂缺')}</b></span><span>·</span>
                <span>${esc(d.pulse?.egoTime || '舆情时间暂缺')}</span>
              </div>
              <div class="sr-kpis">
                <div class="sr-kpi sr-glow sr-glow-up"><div class="sr-kpi-ic" style="--c:var(--up)">▲</div><div class="sr-kpi-l"><div class="sr-kpi-v num"><span class="up" data-count="${shown(b.up)}">${shown(b.up)}</span>/<span class="down" data-count="${shown(b.down)}">${shown(b.down)}</span></div>涨跌家数<small>平盘 ${shown(b.flat)}</small></div></div>
                <div class="sr-kpi sr-glow sr-glow-cyan"><div class="sr-kpi-ic" style="--c:var(--accent-2)">¥</div><div class="sr-kpi-l"><div class="sr-kpi-v num">${shown(b.turnover)}</div>三市成交<small>较前日 ${shown(b.turnoverDelta)}</small></div></div>
                <div class="sr-kpi sr-glow sr-glow-warm"><div class="sr-kpi-ic" style="--c:var(--warm)">⚡</div><div class="sr-kpi-l"><div class="sr-kpi-v num"><span class="up" data-count="${shown(b.limitUp)}">${shown(b.limitUp)}</span>:<span class="down" data-count="${shown(b.limitDown)}">${shown(b.limitDown)}</span></div>涨跌停比<small>炸板 ${shown(b.brokenRate)} · 昨板 ${shown(b.yesterdayPremium)}</small></div></div>
                <div class="sr-kpi sr-glow"><div class="sr-kpi-ic" style="--c:var(--accent)">◎</div><div class="sr-kpi-l"><div class="sr-kpi-v num"><span data-count="${shown(d.sentimentScore)}">${shown(d.sentimentScore)}</span><span style="font-size:12px;color:var(--text-3)">/100</span></div>散户情绪<small>${esc(d.sentimentState)}</small></div></div>
              </div>
              <div class="sr-breadth sr-glow sr-glow-cyan">
                <div class="sr-breadth-top">
                  <span><b>全市场涨跌分布条</b> <span class="muted">（${shown(total)} 只）</span></span>
                  <span class="num"><span class="up">涨 ${shown(b.up)}${upW === null ? '' : ` (${upW}%)`}</span> · <span class="muted">平 ${shown(b.flat)}</span> · <span class="down">跌 ${shown(b.down)}${downW === null ? '' : ` (${downW}%)`}</span></span>
                </div>
                ${total > 0 ? `<div class="sr-breadth-bar"><div class="b-up" style="width:${upW}%"></div><div class="b-flat" style="width:${flatW}%"></div><div class="b-down" style="width:${downW}%"></div></div>` : ''}
              </div>
            </div>

            <aside class="card sr-glow sr-glow-cyan sr-reveal">
              <div class="card-h">
                <div class="card-t">昨日观察锚点 → 今日实盘对比</div>
                ${ui.dayIdx + 1 < days.length ? `<button type="button" class="sr-link-btn" data-prev-day>回看 ${esc(days[ui.dayIdx + 1].shortDate)} →</button>` : ''}
              </div>
              <div style="padding:10px 16px 0;font-size:12px;color:var(--text-2)">${esc(rec.summary)}</div>
              <div class="sr-rec-list">
                ${(rec.items || []).map(it => `
                  <div class="sr-rec-item ${esc(it.status)}">
                    <div class="sr-rec-head"><span class="sr-rec-code">${esc(it.code)}</span><span class="sr-rec-badge ${esc(it.status)}">${esc(it.statusLabel)}</span></div>
                    <div class="sr-rec-claim">${esc(it.claim)}</div>
                    <div class="sr-rec-actual">${esc(it.actual)}</div>
                  </div>
                `).join('')}
              </div>
            </aside>
          </div>

          <div class="sr-mid-row">
            <article class="card sr-glow sr-reveal">
              <div class="card-h"><div class="card-t">Ego 五平台散户温度 &amp; 圈层温差</div><span class="st ai">平台覆盖 ${platforms.length}/5</span></div>
              <div class="card-b sr-ego-quick">
                ${renderGaugeSvg(d.sentimentScore, d.sentimentState)}
                <div style="display:grid;gap:8px">
                  ${platforms.length ? platforms.map(p => `
                    <div style="display:grid;gap:4px" data-sr-tip="${esc(p.name + '｜热议：' + p.hotTopic + '｜' + p.note)}">
                      <div style="display:flex;justify-content:space-between;font-size:11.5px"><span><b>${esc(p.name)}</b> <span class="muted">(${esc(p.kind)})</span></span><span class="num up">多 ${esc(p.bull)}% · ${esc(p.volume)}</span></div>
                      <div class="sr-plat-bar"><div class="bull" style="width:${p.bull}%"></div><div class="mid" style="width:${p.flat}%"></div><div class="bear" style="width:${p.bear}%"></div></div>
                    </div>
                  `).join('') : empty('暂无平台样本')}
                </div>
              </div>
            </article>
            <article class="card sr-glow sr-glow-cyan sr-reveal">
              <div class="card-h"><div class="card-t">当日结构与口径说明</div><span class="st auto">混合存储 · V4 规范</span></div>
              <div class="card-b" style="display:grid;gap:10px">
                <div class="sr-rec-item"><div class="sr-rec-head"><span class="sr-rec-code">个股红黑榜选样口径</span></div><div class="sr-rec-actual">全市场榜剔除上市不足 30 日、新股标识、ST / *ST 与退市整理股，<b>日成交额 ≥ 10 亿元</b>。核心池按雷达收录的 A 股单列。</div></div>
                <div class="sr-rec-item"><div class="sr-rec-head"><span class="sr-rec-code">Ego 平台覆盖</span></div><div class="sr-rec-actual">${esc((d.ego && d.ego.summary) || '')}</div></div>
              </div>
            </article>
          </div>

          ${catalysts.length ? `
            <div class="sr-upcoming sr-glow sr-glow-gold sr-reveal">
              <div style="display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:660"><span>⏳ 近期重磅催化倒计时</span><span class="hint">（会前看预期 · 开会防兑现）</span></div>
              <div class="sr-upcoming-pills">
                ${catalysts.slice(0, 5).map(ev => `
                  <a href="#srCatalysts" class="sr-up-pill">
                    <span class="tleft">${esc(ev.dateLabel)} (${esc(ev.daysLeft)})</span>
                    <span>${esc(ev.title.split('（')[0])}</span>
                    <span class="sr-stars s${ev.stars}">${'★'.repeat(ev.stars)}</span>
                  </a>
                `).join('')}
                <a href="#srCatalysts" class="sr-link-btn">查看全部 ${catalysts.length} 项 ↓</a>
              </div>
            </div>
          ` : ''}
        </section>

        <section class="section sr-reveal">
          <div class="sec-head">
            <div><div class="eyebrow">01 · 板块红黑榜 TOP 5</div><h2 class="h2">行业板块 vs 概念题材 涨跌幅前 5 名</h2></div>
            <div class="sr-seg" role="group" aria-label="板块范围">
              <button type="button" data-board="industry" class="${ui.boardTab === 'industry' ? 'on' : ''}">行业板块 Top 5</button>
              <button type="button" data-board="concept" class="${ui.boardTab === 'concept' ? 'on' : ''}">概念题材 Top 5</button>
              <button type="button" data-board="both" class="${ui.boardTab === 'both' ? 'on' : ''}">同屏并列</button>
            </div>
          </div>
          <div class="sr-fade-swap">
            ${showInd ? `<div class="sr-duel-grid" style="${showCon ? 'margin-bottom:16px' : ''}"><article class="card sr-glow sr-glow-up sr-duel-up"><div class="card-h"><div class="card-t"><span class="up">▲</span> 行业板块 · 涨幅前 5</div><span class="st up-tag">主线聚焦</span></div>${renderRankRows(d.industries && d.industries.up, true, 0.055)}</article><article class="card sr-glow sr-glow-down sr-duel-down"><div class="card-h"><div class="card-t"><span class="down">▼</span> 行业板块 · 跌幅前 5</div><span class="st down-tag">跌幅居前</span></div>${renderRankRows(d.industries && d.industries.down, false, 0.055)}</article></div>` : ''}
            ${showCon ? `<div class="sr-duel-grid"><article class="card sr-glow sr-glow-up sr-duel-up"><div class="card-h"><div class="card-t"><span class="up">▲</span> 概念题材 · 涨幅前 5</div><span class="st ai">短线热点</span></div>${renderRankRows(d.concepts && d.concepts.up, true, 0.068)}</article><article class="card sr-glow sr-glow-down sr-duel-down"><div class="card-h"><div class="card-t"><span class="down">▼</span> 概念题材 · 跌幅前 5</div><span class="st conflict">弱势退潮</span></div>${renderRankRows(d.concepts && d.concepts.down, false, 0.068)}</article></div>` : ''}
          </div>
        </section>

        <section class="section sr-reveal">
          <div class="sec-head">
            <div><div class="eyebrow">02 · 个股红黑榜 TOP 5（双版面常驻）</div><h2 class="h2">领涨个股 Top 5 ⇄ 领跌个股 Top 5</h2></div>
            <div class="sr-seg" role="group" aria-label="个股范围">
              <button type="button" data-scope="market" class="${ui.stockScope === 'market' ? 'on' : ''}">活跃焦点股 Top 5（≥10亿）</button>
              <button type="button" data-scope="radar" class="${ui.stockScope === 'radar' ? 'on' : ''}">投研雷达追踪池 Top 5</button>
            </div>
          </div>
          <div class="sr-duel-grid sr-fade-swap">
            <article class="card sr-glow sr-glow-up sr-duel-up"><div class="card-h"><div class="card-t"><span class="up">▲</span> 个股涨幅前 5 名</div><span class="st up-tag">${ui.stockScope === 'market' ? '剔新ST·≥10亿' : '核心池领涨'}</span></div>${renderRankRows(stkSet.up, true, maxStkAbs)}</article>
            <article class="card sr-glow sr-glow-down sr-duel-down"><div class="card-h"><div class="card-t"><span class="down">▼</span> 个股跌幅前 5 名</div><span class="st down-tag">${ui.stockScope === 'market' ? '剔新ST·≥10亿' : '核心池回撤'}</span></div>${renderRankRows(stkSet.down, false, maxStkAbs)}</article>
          </div>
        </section>

        <section class="section sr-reveal">
          <div class="sec-head"><div><div class="eyebrow">03 · 纵向日内时间轴复盘流</div><h2 class="h2">交易日至晚间的盘面记录</h2></div></div>
          <div class="sr-story-shell">
            <aside class="sr-story-rail sr-glow">
              <h3>DAILY TIMELINE</h3>
              <nav class="sr-rail-nav">
                <a href="#srTlIntraday" class="active"><span class="tm">09:25 – 15:00</span><span>盘中节奏演变</span></a>
                <a href="#srTlCycle"><span class="tm">15:00 结算</span><span>连板梯队 × 共振矩阵</span></a>
                <a href="#srTlLhb"><span class="tm">17:30 龙虎榜</span><span>机构游资 vs 拉萨席位</span></a>
                <a href="#srTlEgo"><span class="tm">晚间 Ego</span><span>散户舆情</span></a>
                <a href="#srTlAnchors"><span class="tm">20:30 明日与应对</span><span>观察锚点与排雷</span></a>
                <a href="#srCatalysts"><span class="tm">前瞻日历 · 3~5★</span><span>宏观与产业催化</span></a>
              </nav>
            </aside>
            <div class="sr-tl-stream">
              <div id="srTlIntraday" style="display:grid;gap:14px">
                ${(d.timeline || []).map(t => `
                  <div class="sr-tl-stage sr-reveal"><article class="sr-tl-card sr-glow sr-glow-cyan"><div class="sr-tl-top"><span class="sr-tl-time">${esc(t.time)}</span><span class="sr-tl-badge">${esc(t.phase)}</span><span class="st auto" style="margin-left:auto">${esc(t.tag)}</span></div><div style="font-size:15.5px;font-weight:680">${esc(t.title)}</div><p style="font-size:12.5px;color:var(--text-2);margin-top:5px">${esc(t.detail)}</p></article></div>
                `).join('')}
              </div>

              <div class="sr-tl-stage sr-reveal" id="srTlCycle">
                <div class="sr-tl-card sr-glow" style="display:grid;gap:16px">
                  <div class="sr-tl-top"><span class="sr-tl-time">15:00 盘后结构结算</span><span class="sr-tl-badge">短线周期 × 基本面共振四象限</span></div>
                  <div>
                    <div class="sr-cycle-track">${((d.cycle && d.cycle.steps) || []).map((s, i) => `<div class="sr-cycle-step ${i === d.cycle.activeStep ? 'on' : ''}">${i + 1}. ${esc(s)}</div>`).join('')}</div>
                    <p class="sub" style="margin:0 0 10px">${esc(d.cycle?.note || '周期数据暂缺')} ${d.cycle?.maxHeight ? `· 最高连板 ${esc(d.cycle.maxHeight)}` : ''}</p>
                    <div style="display:grid;gap:8px">${((d.cycle && d.cycle.tiers) || []).map(tr => `<div class="sr-ladder-row"><div class="sr-ladder-tier">${esc(tr.tier)}</div><div style="display:flex;flex-wrap:wrap;gap:6px">${(tr.stocks || []).map(s => `<span class="chip"><b>${esc(s.n)}</b> <span class="num">${esc(s.c)}</span> <span class="muted">· ${esc(s.tag)}</span></span>`).join('')}</div><div class="num" style="text-align:right;font-size:11.5px;color:var(--text-2)">${esc(tr.rate)}</div></div>`).join('')}</div>
                  </div>
                  <div class="sr-matrix-grid">
                    ${(d.matrix || []).map(q => `<article class="sr-quad sr-glow ${esc(q.key)}"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h4 style="font-size:13.5px;font-weight:680">${esc(q.title)}</h4><span class="${esc(q.badge)}">${esc(q.badgeText)}</span></div>${!q.items?.length ? empty('今日暂无此类标的') : q.items.map(it => `<div class="sr-quad-item"><b>${esc(it.name)}</b><div class="mono" style="font-size:11px;color:var(--accent-2);margin-top:2px">${esc(it.meta)}</div><p style="font-size:11.5px;color:var(--text-2);margin-top:3px">${esc(it.note)}</p></div>`).join('')}</article>`).join('')}
                  </div>
                </div>
              </div>

              <div class="sr-tl-stage sr-reveal" id="srTlLhb">
                <div class="sr-tl-card sr-glow">
                  <div class="sr-tl-top"><span class="sr-tl-time">17:30 龙虎榜主力席位底牌</span><span class="sr-tl-badge">机构/北向/游资 ⇄ 拉萨营业部</span></div>
                  <p class="sub" style="margin:0 0 10px">${esc(d.dragonTiger && d.dragonTiger.summary)}</p>
                  <div class="sr-lhb-list">${((d.dragonTiger && d.dragonTiger.items) || []).map(it => `<div class="sr-lhb-row"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><b>${esc(it.stock)}</b><span class="st ${esc(it.tone)}">${esc(it.tag)}</span><span class="mono num" style="margin-left:auto;font-weight:700;font-size:12px">${esc(it.net)}</span></div><div style="font-size:12px;color:var(--text-2)">${esc(it.seats)}</div><div style="font-size:11.5px;color:var(--text-3)">${esc(it.note)}</div></div>`).join('')}</div>
                </div>
              </div>

              <div class="sr-tl-stage stage-ego sr-reveal" id="srTlEgo">
                <div class="sr-tl-card sr-glow">
                  <div class="sr-tl-top"><span class="sr-tl-time">晚间 Ego 五平台散户舆情</span><span class="sr-tl-badge">东财/雪球/同花顺 + 抖音/小红书大V评论区（已脱敏）</span></div>
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px">
                    <p class="sub" style="margin:0">${esc(d.ego && d.ego.summary)}</p>
                    <div class="sr-seg" role="group" aria-label="评论平台">
                      <button type="button" data-plat="all" class="${ui.egoPlatform === 'all' ? 'on' : ''}">全部</button>
                      <button type="button" data-plat="em" class="${ui.egoPlatform === 'em' ? 'on' : ''}">东方财富</button>
                      <button type="button" data-plat="xq" class="${ui.egoPlatform === 'xq' ? 'on' : ''}">雪球</button>
                      <button type="button" data-plat="ths" class="${ui.egoPlatform === 'ths' ? 'on' : ''}">同花顺</button>
                      <button type="button" data-plat="dy" class="${ui.egoPlatform === 'dy' ? 'on' : ''}">抖音·大V区</button>
                      <button type="button" data-plat="xhs" class="${ui.egoPlatform === 'xhs' ? 'on' : ''}">小红书·大V区</button>
                    </div>
                  </div>
                  <div class="sr-ego-feed sr-fade-swap">${!egoPosts.length ? empty('当前平台筛选没有评论样本') : egoPosts.map(p => `<article class="sr-ego-post sr-glow"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11.5px"><span class="sr-plat-pill ${esc(p.pillClass)}">${esc(p.platName)}</span><span class="st ${esc(p.sentimentTone)}">${esc(p.sentimentTag)}</span><span class="muted num" style="margin-left:auto">${esc(p.time)} · ${esc(p.likes)}</span></div><div class="sr-ego-ctx">${esc(p.kolContext)}</div><div style="font-size:13px;line-height:1.55;font-weight:500">${esc(p.quote)}</div><div style="font-size:11px;color:var(--text-3)">${esc(p.author)}</div><div class="sr-ego-diag"><b>情绪解读：</b>${esc(p.aiDiag)}</div></article>`).join('')}</div>
                </div>
              </div>

              <div class="sr-tl-stage stage-anchor sr-reveal" id="srTlAnchors">
                <div class="sr-tl-card sr-glow sr-glow-warm">
                  <div class="sr-tl-top"><span class="sr-tl-time">20:30 明日开盘锚点 · 应对预案 · 排雷提示</span></div>
                  <div class="sr-anchors-grid">${(d.anchors || []).map(a => `<article class="sr-anchor-card sr-glow sr-glow-cyan"><div class="mono" style="font-size:11px;color:var(--accent-2);font-weight:700">${esc(a.code)}</div><div style="font-size:14px;font-weight:660">${esc(a.title)}</div><div style="font-size:12px;color:var(--text-2);line-height:1.55">${esc(a.desc)}</div></article>`).join('')}</div>
                  ${d.strategyPlan ? `<div class="sr-strat-grid"><div class="sr-strat-box offense sr-glow sr-glow-up"><div class="up" style="font-size:12px;font-weight:700">进攻观察主线</div><div style="font-size:12.5px;color:var(--text-2);line-height:1.6">${esc(d.strategyPlan.offense)}</div></div><div class="sr-strat-box defense sr-glow sr-glow-cyan"><div style="font-size:12px;font-weight:700;color:var(--ease)">防守与风控底线</div><div style="font-size:12.5px;color:var(--text-2);line-height:1.6">${esc(d.strategyPlan.defense)}</div></div></div>${(d.strategyPlan.mines || []).map(m => `<div class="sr-mine-item"><b style="color:var(--tight)">⚠️ ${esc(m.title)}：</b><span style="color:var(--text-2)">${esc(m.detail)}</span></div>`).join('')}` : ''}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="section sr-reveal" id="srCatalysts">
          <div class="sec-head">
            <div><div class="eyebrow">04 · 前瞻预期：星级宏观与产业大事催化 &amp; 兑现日历</div><h2 class="h2">未来重要大会 / 宏观政策 / 流动性节点（3~5★ 跟踪）</h2></div>
            <div class="sr-seg" role="group" aria-label="催化事件类型">
              <button type="button" data-cat="all" class="${ui.catFilter === 'all' ? 'on' : ''}">全部大事 (${catalysts.length})</button>
              <button type="button" data-cat="star5" class="${ui.catFilter === 'star5' ? 'on' : ''}">★★★★★ 五星</button>
              <button type="button" data-cat="industry" class="${ui.catFilter === 'industry' ? 'on' : ''}">产业大会</button>
              <button type="button" data-cat="macro" class="${ui.catFilter === 'macro' ? 'on' : ''}">宏观与流动性</button>
            </div>
          </div>
          <div class="sr-cat-list sr-fade-swap">
            ${!filteredCatalysts.length ? empty(ui.dayIdx ? '该交易日未单独归档催化日历' : '当前筛选暂无催化事件') : filteredCatalysts.map(ev => `<article class="sr-cat-card sr-glow ${ev.stars === 5 ? 'sr-glow-gold is-s5' : ev.stars === 4 ? 'is-s4' : 'sr-glow-cyan'}"><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11.5px"><span class="mono" style="font-weight:700;padding:2px 7px;border-radius:6px;background:var(--surface-2);border:1px solid var(--border)">${esc(ev.dateLabel)}</span><span class="mono" style="font-size:11px;color:var(--accent-2);font-weight:700">${esc(ev.daysLeft)}</span><span class="sr-stars s${ev.stars}">${'★'.repeat(ev.stars)}${'☆'.repeat(5 - ev.stars)}</span><span class="st ${esc(ev.phaseTone)}" style="margin-left:auto">${esc(ev.phaseTag)}</span></div><div style="font-size:15.5px;font-weight:700">${esc(ev.title)}</div><div style="font-size:12.5px;color:var(--text-2)"><b>核心看点：</b>${esc(ev.focus)}</div><div style="font-size:11.5px;color:var(--accent-2)">📌 映射方向：${esc(ev.mapping)}</div><div class="sr-cat-game"><b>预期与兑现推演：</b>${esc(ev.expectationNote)}</div></article>`).join('')}
          </div>
        </section>
      `;

      activateScrollRevealAndGauge(previousThumbs);
    }

    // Filtering replaces the rendered cards. Keep focus and scroll at the
    // clicked control, and animate the new thumb from its prior position.
    mount.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || !mount.contains(button)) return;
      const fields = button.dataset;
      let selector;
      if ('dayIdx' in fields || 'prevDay' in fields) {
        ui.dayIdx = 'dayIdx' in fields ? Number(fields.dayIdx) : ui.dayIdx + 1;
        selector = `[data-day-idx="${ui.dayIdx}"]`;
      } else {
        const filters = { board: 'boardTab', scope: 'stockScope', plat: 'egoPlatform', cat: 'catFilter' };
        const key = Object.keys(filters).find(name => name in fields);
        if (!key) return;
        ui[filters[key]] = fields[key];
        selector = `[data-${key}="${CSS.escape(fields[key])}"]`;
      }
      const before = button.getBoundingClientRect().top;
      renderShortView();
      const next = mount.querySelector(selector);
      if (next) {
        next.focus({ preventScroll: true });
        const delta = next.getBoundingClientRect().top - before;
        if (Math.abs(delta) > 1) window.scrollBy({ top: delta, behavior: 'instant' });
      }
    });

    renderTodayTeaser();
    return { switchView, renderShortView, renderTodayTeaser };
  }

  window.AlphaRadarShortTerm = { initShortTermModule };
})();
