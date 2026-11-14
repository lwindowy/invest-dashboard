/* 화면은 data/dashboard.json 만 읽어 그린다.
   탭과 섹션 배치는 config/dashboard.json 의 tabs 를 그대로 따른다.
   공통 부품: 숫자 카드(numCard), 추이 그래프(sparkline), 표(watchlist), 신호등(pill) */
(function () {
  'use strict';

  var DATA = null;
  var store = {
    get: function (k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  var state = { tab: (location.hash || '').slice(1) || 'home', market: store.get('market', 'us') };
  var root = document.documentElement;
  var $ = function (id) { return document.getElementById(id); };

  // ───────── 표시 형식 ─────────
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(x, digits) {
    if (x == null) return '–';
    return Number(x).toLocaleString('ko-KR', { minimumFractionDigits: digits || 0, maximumFractionDigits: digits || 0 }).replace('-', '−');
  }
  function signed(x, digits, unit) {
    if (x == null) return '';
    var zero = Number(Math.abs(x).toFixed(digits)) === 0;
    return (zero ? '' : x > 0 ? '+' : '−') + fmt(Math.abs(x), digits) + (unit || '');
  }
  function dir(x) { return x > 0 ? 'up' : x < 0 ? 'down' : 'flat'; }
  function md(iso) { return iso ? Number(iso.slice(5, 7)) + '/' + Number(iso.slice(8, 10)) : ''; }
  function weekday(iso) { return '일월화수목금토'[new Date(iso + 'T00:00:00').getDay()]; }
  var LEVEL = { '양호': 'good', '주의': 'warn', '위험': 'bad', '확인 불가': 'none' };

  // ───────── 공통 부품 ─────────
  function pill(text, level, small) {
    return '<span class="pill ' + level + (small ? ' small' : '') + '">' + esc(text) + '</span>';
  }
  function sparkline(values, cls, w, h) {
    var v = (values || []).filter(function (x) { return x != null; });
    if (v.length < 2) return '<span></span>';
    var min = Math.min.apply(null, v), max = Math.max.apply(null, v), span = (max - min) || 1;
    var pts = v.map(function (y, i) {
      return (i * (w / (v.length - 1))).toFixed(1) + ',' + (h - 2 - ((y - min) / span) * (h - 4)).toFixed(1);
    }).join(' ');
    return '<svg class="spark ' + cls + '" aria-hidden="true" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '"><polyline points="' + pts + '"></polyline></svg>';
  }
  function change(s) {
    // 등락률(%) 또는 직전값 대비 차이
    if (s.change === 'diff') return { text: signed(s.diff, s.diff_decimals || 0, s.diff_unit), d: dir(s.diff) };
    return { text: signed(s.change_pct, 2, '%'), d: dir(s.change_pct) };
  }
  function stamp(item) {
    // 데이터마다 출처와 기준일을 붙인다
    if (!item || item.error) return '';
    var when = item.period ? esc(item.period) : md(item.asof) + (item.source === '직접 입력' ? ' 입력' : ' 기준');
    return esc(item.source || '') + ' · ' + when + (item.stale ? ' · 수집 실패로 이전 값' : '');
  }
  function value(s) {
    // 숫자와 단위. '%'처럼 짧은 단위는 붙여 쓰고, '천 명' 같은 단위는 작게 띄어 쓴다
    var n = (s.signed && s.value > 0 ? '+' : '') + fmt(s.value, s.decimals);
    var u = s.unit || '';
    return esc(s.prefix || '') + n + (u.length > 2 ? '<small>' + esc(u) + '</small>' : esc(u));
  }
  function numCard(s) {
    if (!s) return '';
    if (s.error || s.value == null) {
      return '<div class="num-card"><span class="name">' + esc(s.name) + '</span><span class="value flat">–</span><span class="note">' + esc(s.error_note || '데이터를 받지 못했습니다') + '</span></div>';
    }
    var c = change(s);
    var note = s.note ? (s.note_level ? pill(s.note, s.note_level, true) : esc(s.note)) : '';
    return '<div class="num-card">' +
      '<span class="name">' + esc(s.name) + '</span>' +
      '<span class="value">' + value(s) + '</span>' +
      '<div class="row"><span class="chg ' + c.d + '">' + c.text + '</span>' + sparkline(s.spark, c.d, 84, 26) + '</div>' +
      (note ? '<span class="note">' + note + '</span>' : '') +
      (s.next_release ? '<span class="note">다음 발표 ' + md(s.next_release) + ' (' + weekday(s.next_release) + ')</span>' : '') +
      '<span class="src">' + stamp(s) + '</span></div>';
  }

  // ───────── 섹션 ─────────
  var SECTIONS = {
    regime: function (sec) {
      var r = DATA.regime;
      var sum = '<strong>' + r.total + '개 중 ' + r.good + '개 양호</strong> · 주의 ' + r.warn + '개 · 위험 ' + r.bad + '개' +
        (r.unknown ? ' · 확인 불가 ' + r.unknown + '개' : '');
      var items = r.items.map(function (i) {
        return '<div class="regime-item"><div class="head"><span class="name">' + esc(i.name) + '</span>' +
          pill(i.state, LEVEL[i.state] || 'none') + '</div><span class="why">' + esc(i.why) + '</span></div>';
      }).join('');
      var rules = r.items.map(function (i) { return '<li><b>' + esc(i.name) + '</b> — ' + esc(i.rule) + '</li>'; }).join('');
      return '<section class="card" aria-label="' + esc(sec.label) + '">' +
        '<div class="card-head"><h2>' + esc(sec.label) + '</h2><p class="regime-sum">' + sum + '</p></div>' +
        '<div class="regime-grid">' + items + '</div>' +
        '<details class="rules"><summary>판단 기준 보기</summary><ul>' + rules + '</ul>' +
        '<p class="src">출처: Yahoo Finance, FRED. 기준값은 config/dashboard.json 의 regime 에서 바꿉니다.</p></details></section>';
    },
    cards: function (sec) {
      var cards = '<div class="cards">' + sec.items.map(function (id) { return numCard(DATA.series[id]); }).join('') + '</div>';
      if (!sec.heading) return '<section aria-label="' + esc(sec.label) + '">' + cards + '</section>';
      return '<section class="group" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2>' + cards +
        (sec.note ? '<p class="src">' + esc(sec.note) + '</p>' : '') + '</section>';
    },
    curve: function (sec) {
      var c = DATA.curve;
      if (!c) return '<section class="card"><h2>' + esc(sec.label) + '</h2><p class="empty">데이터를 받지 못했습니다.</p></section>';
      var W = 720, H = 260, L = 44, R = 16, T = 14, B = 30, n = c.labels.length;
      var lines = [['now', '현재'], ['month', '1개월 전'], ['year', '1년 전']];
      var all = [].concat(c.now.values, c.month.values, c.year.values).filter(function (v) { return v != null; });
      var lo = Math.floor(Math.min.apply(null, all) * 2) / 2, hi = Math.ceil(Math.max.apply(null, all) * 2) / 2;
      if (hi === lo) hi = lo + 0.5;
      function x(i) { return L + i * (W - L - R) / (n - 1); }
      function y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
      var grid = '', step = (hi - lo) > 3 ? 1 : 0.5;
      for (var v = lo; v <= hi + 1e-9; v += step) {
        grid += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '"></line>' +
          '<text class="axis" x="' + (L - 8) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end">' + v.toFixed(1) + '%</text>';
      }
      var xs = c.labels.map(function (l, i) {
        return '<text class="axis" x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="middle">' + esc(l) + '</text>';
      }).join('');
      var paths = lines.slice().reverse().map(function (ln) {
        var pts = c[ln[0]].values.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); }).join(' ');
        var dots = ln[0] === 'now' ? c.now.values.map(function (v, i) { return '<circle class="dot" cx="' + x(i).toFixed(1) + '" cy="' + y(v).toFixed(1) + '" r="3"></circle>'; }).join('') : '';
        return '<polyline class="curve-' + ln[0] + '" points="' + pts + '"></polyline>' + dots;
      }).join('');
      var legend = lines.map(function (ln) {
        return '<span class="legend-item"><svg aria-hidden="true" width="28" height="10"><line class="curve-' + ln[0] + '" x1="1" x2="27" y1="5" y2="5"></line></svg>' +
          ln[1] + ' (' + md(c[ln[0]].date) + (ln[0] === 'year' ? ', ' + c.year.date.slice(0, 4) + '년' : '') + ')</span>';
      }).join('');
      var head = '<div class="ctr th"><span>만기</span>' + lines.map(function (ln) { return '<span>' + ln[1] + '</span>'; }).join('') + '</div>';
      var body = c.labels.map(function (l, i) {
        return '<div class="ctr"><span>' + esc(l) + '</span>' + lines.map(function (ln) { return '<span>' + fmt(c[ln[0]].values[i], 2) + '%</span>'; }).join('') + '</div>';
      }).join('');
      return '<section class="card" aria-label="' + esc(sec.label) + '"><div class="card-head"><h2>' + esc(sec.label) + '</h2><div class="legend">' + legend + '</div></div>' +
        '<svg class="curve" role="img" aria-label="미국 국채 수익률 곡선. 아래 표에 같은 값이 있습니다." viewBox="0 0 ' + W + ' ' + H + '">' + grid + xs + paths + '</svg>' +
        '<details class="rules"><summary>만기별 금리 표 보기</summary><div class="ctable">' + head + body + '</div></details>' +
        '<p class="src">미국 국채 만기별 금리. 단기 금리가 장기 금리보다 높으면(역전) 경기 둔화 신호로 봅니다. 출처: ' + esc(c.source) + ' · ' + md(c.now.date) + ' 기준</p></section>';
    },
    watchlist: function (sec) {
      var seg = [['us', '미국'], ['kr', '한국']].map(function (m) {
        return '<button type="button" class="btn" data-market="' + m[0] + '" aria-pressed="' + (state.market === m[0]) + '">' + m[1] + '</button>';
      }).join('');
      var list = (DATA.watchlist[state.market] || []);
      var rows = list.map(function (s) {
        var name = '<div class="stock-name"><b>' + esc(s.name) + '</b><span>' + esc(s.ticker.replace('.KS', '')) + (s.stale ? ' · 이전 값' : '') + '</span></div>';
        if (s.error || s.price == null) {
          return '<div class="tr">' + name + '<span class="flat">–</span><span></span><span></span><span></span><span class="src">수집 실패</span></div>';
        }
        var price = s.currency === 'KRW' ? fmt(s.price, 0) + '원' : '$' + fmt(s.price, 2);
        var d = dir(s.change_pct);
        var flag = s.rsi >= 70 ? pill('과매수', 'warn', true) : s.rsi != null && s.rsi <= 30 ? pill('과매도', 'good', true) : '';
        return '<div class="tr">' + name +
          '<span class="price">' + price + '</span>' +
          '<span class="chg-cell ' + d + '">' + signed(s.change_pct, 2, '%') + '</span>' +
          '<div class="rsi-cell">' + flag + '<span>' + (s.rsi == null ? '–' : fmt(s.rsi, 0)) + '</span></div>' +
          '<span class="flat">' + signed(s.from_high_pct, 1, '%') + '</span>' +
          sparkline(s.spark, d, 96, 28) + '</div>';
      }).join('');
      var asof = list.filter(function (s) { return s.asof; }).map(function (s) { return s.asof; }).sort().pop();
      return '<section class="card" aria-label="' + esc(sec.label) + '">' +
        '<div class="card-head"><h2>' + esc(sec.label) + '</h2><div class="seg">' + seg + '</div></div>' +
        '<div class="scroll-x"><div class="table">' +
        '<div class="tr th"><span>종목</span><span>현재가</span><span>등락률</span><span>RSI(14)</span><span>52주 고점 대비</span><span>3개월 추이</span></div>' +
        rows + '</div></div>' +
        '<p class="src">RSI 70 이상은 과매수, 30 이하는 과매도로 표시합니다. 출처: Yahoo Finance · ' + md(asof) + ' 기준 · 주가는 15분가량 지연됩니다.</p></section>';
    },
    events: function (sec) {
      var ev = DATA.events || [];
      var body = ev.length ? ev.map(function (e) {
        return '<div class="event"><div class="date"><b>' + md(e.date) + '</b><span>' + weekday(e.date) + '</span></div>' +
          '<div class="what"><b>' + esc(e.title) + '</b><span>' + esc(e.kind) + ' · ' + esc(e.source || '') + '</span></div></div>';
      }).join('') : '<p class="empty">앞으로 30일 안에 잡힌 일정이 없습니다.</p>';
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2>' + body +
        '<p class="src">경제지표 발표일은 캘린더 탭을 만들 때 추가합니다. 실적일은 회사 확정 전에는 바뀔 수 있습니다.</p></section>';
    },
    rows: function (sec) {
      var rows = sec.items.map(function (id) {
        var s = DATA.series[id];
        if (!s) return '';
        if (s.error || s.value == null) return '<div class="kv"><span class="k">' + esc(s.name) + '</span><span class="src">수집 실패</span></div>';
        var c = change(s);
        return '<div class="kv" title="' + stamp(s) + '"><span class="k">' + esc(s.name) + (s.stale ? ' (이전 값)' : '') + '</span>' +
          '<div class="v"><b>' + fmt(s.value, s.decimals) + esc(s.unit || '') + '</b><span class="' + c.d + '">' + c.text + '</span></div></div>';
      }).join('');
      var used = sec.items.map(function (id) { return DATA.series[id]; }).filter(function (s) { return s && s.asof; });
      var by = {};
      used.forEach(function (s) { if (!by[s.source] || by[s.source] < s.asof) by[s.source] = s.asof; });
      var src = Object.keys(by).map(function (k) { return esc(k) + ' ' + md(by[k]) + ' 기준'; }).join(' · ');
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2><div class="rows">' + rows + '</div>' +
        '<p class="src">변화는 직전 발표값 대비입니다. 출처: ' + src + '</p></section>';
    }
  };

  // ───────── 화면 조립 ─────────
  function renderTabs() {
    $('tabs').innerHTML = DATA.tabs.map(function (t) {
      return '<button type="button" class="tab" role="tab" data-tab="' + esc(t.id) + '" aria-selected="' + (t.id === state.tab) + '">' + esc(t.label) + '</button>';
    }).join('');
  }
  function renderView() {
    var tab = DATA.tabs.filter(function (t) { return t.id === state.tab; })[0] || DATA.tabs[0];
    state.tab = tab.id;
    if (!tab.sections) {
      $('view').innerHTML = '<section class="card"><h2>' + esc(tab.label) + ' 탭은 준비 중입니다</h2>' +
        '<p class="empty">' + esc(tab.stage || '') + ' 버전에서 만듭니다. 들어갈 내용: ' + esc(tab.planned || '') + '</p></section>';
      return;
    }
    var html = '', cols = null;
    function flush() {
      if (!cols) return;
      html += '<div class="cols"><div class="col-main">' + cols.main + '</div><div class="col-side">' + cols.side + '</div></div>';
      cols = null;
    }
    tab.sections.forEach(function (sec) {
      var out = SECTIONS[sec.type] ? SECTIONS[sec.type](sec) : '';
      if (sec.column === 'main' || sec.column === 'side') {
        cols = cols || { main: '', side: '' };
        cols[sec.column] += out;
      } else { flush(); html += out; }
    });
    flush();
    $('view').innerHTML = html;
  }
  function renderChrome() {
    document.title = DATA.site.title;
    $('site-title').textContent = DATA.site.title;
    var t = new Date(DATA.generated_at);
    var when = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'short' }).format(t);
    $('updated').textContent = '마지막 갱신 ' + when + ' (한국 시간) · 약 30분마다 자동 갱신 · 주가 15분가량 지연';
    var notes = [];
    var hours = (Date.now() - t.getTime()) / 36e5;
    if (hours > 3) notes.push('자동 갱신이 ' + Math.floor(hours) + '시간째 멈춰 있습니다. 아래 숫자는 마지막 갱신 시점의 값입니다.');
    if (DATA.errors && DATA.errors.length) {
      notes.push('일부 항목을 받지 못했습니다: ' + DATA.errors.map(function (e) { return e.where; }).join(', ') + '. 해당 항목은 이전 값이거나 비어 있습니다.');
    }
    $('notice').innerHTML = notes.map(function (n) { return '<p class="notice" role="status">' + esc(n) + '</p>'; }).join('');
    $('foot').innerHTML = esc(DATA.site.disclaimer) + '<br>출처: Yahoo Finance(주가·환율·지수·원자재), FRED(금리·스프레드·경제지표). 무료 데이터는 개인 용도로만 씁니다.';
  }
  function renderButtons() {
    var dark = root.dataset.theme === 'dark', us = root.dataset.color === 'us';
    $('btn-theme').textContent = dark ? '밝은 화면' : '어두운 화면';
    $('btn-color').textContent = us ? '색: 미국식 (상승 초록)' : '색: 한국식 (상승 빨강)';
  }
  function render() { renderChrome(); renderTabs(); renderView(); }

  // ───────── 동작 ─────────
  $('btn-theme').addEventListener('click', function () {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    store.set('theme', root.dataset.theme); renderButtons();
  });
  $('btn-color').addEventListener('click', function () {
    root.dataset.color = root.dataset.color === 'us' ? 'kr' : 'us';
    store.set('colorStyle', root.dataset.color); renderButtons();
  });
  $('tabs').addEventListener('click', function (e) {
    var b = e.target.closest('[data-tab]');
    if (!b || !DATA) return;
    state.tab = b.dataset.tab; history.replaceState(null, '', '#' + state.tab);
    renderTabs(); renderView();
  });
  $('view').addEventListener('click', function (e) {
    var b = e.target.closest('[data-market]');
    if (!b || !DATA) return;
    state.market = b.dataset.market; store.set('market', state.market); renderView();
  });

  function load() {
    return fetch('data/dashboard.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) { DATA = d; render(); })
      .catch(function (err) {
        if (DATA) return; // 이미 그린 화면은 그대로 둔다
        $('updated').textContent = '데이터를 불러오지 못했습니다.';
        $('view').innerHTML = '<section class="card"><h2>데이터를 불러오지 못했습니다</h2><p class="empty">data/dashboard.json 을 읽을 수 없습니다 (' + esc(err.message) + '). 자동 갱신이 한 번 이상 성공했는지 GitHub Actions 기록을 확인하세요.</p></section>';
      });
  }
  renderButtons();
  load();
  setInterval(load, 10 * 60 * 1000); // 화면을 켜 두면 10분마다 새 데이터를 다시 읽는다
})();
