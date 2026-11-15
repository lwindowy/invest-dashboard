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
  var state = { tab: 'home', stock: null, market: store.get('market', 'us'), edit: false, compare: '', month: null, kinds: {} };
  function route() {
    var h = (location.hash || '#home').slice(1).split('/');
    state.tab = h[0] || 'home';
    state.stock = h[1] ? decodeURIComponent(h[1]) : null;
  }
  route();
  // 종목 숨기기·순서·즐겨찾기는 브라우저에만 저장한다
  var prefs = { order: [], hidden: [], fav: [] };
  try { prefs = Object.assign(prefs, JSON.parse(store.get('stockPrefs', '{}'))); } catch (e) {}
  function savePrefs() { store.set('stockPrefs', JSON.stringify(prefs)); }
  function has(list, t) { return list.indexOf(t) >= 0; }
  function toggle(list, t) { var i = list.indexOf(t); if (i >= 0) list.splice(i, 1); else list.push(t); }
  function ordered(market, withHidden) {
    var list = (DATA.watchlist[market] || []).slice();
    var pos = function (s) { var i = prefs.order.indexOf(s.ticker); return i < 0 ? 1e6 + list.indexOf(s) : i; };
    list.sort(function (a, b) { return (has(prefs.fav, b.ticker) - has(prefs.fav, a.ticker)) || (pos(a) - pos(b)); });
    return withHidden ? list : list.filter(function (s) { return !has(prefs.hidden, s.ticker); });
  }
  function move(market, ticker, step) {
    var list = ordered(market, true).map(function (s) { return s.ticker; });
    var i = list.indexOf(ticker), j = i + step;
    if (j < 0 || j >= list.length) return;
    list[i] = list[j]; list[j] = ticker;
    prefs.order = list.concat(prefs.order.filter(function (t) { return !has(list, t); }));
    savePrefs();
  }
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

  // ───────── 용어 설명 (이름 옆 물음표) ─────────
  function q(key) {
    var g = key && DATA.glossary && DATA.glossary[key];
    return g ? '<button type="button" class="help" data-help="' + esc(key) + '" aria-label="' + esc(g.title) + ' 설명 보기">?</button>' : '';
  }
  var HELP_BY_LABEL = {
    '시가총액': 'market_cap', '순현금': 'net_cash', '순부채': 'net_cash', 'PER': 'per', '포워드 PER': 'forward_per', 'PSR': 'psr', 'PEG': 'peg',
    '매출 성장률 (전년 동기 대비)': 'revenue_growth', 'EPS (최근 12개월)': 'eps', 'ROE': 'roe', '예상 대비': 'earnings_surprise',
    'Short Float': 'short_float', 'Short Ratio': 'short_ratio', 'Short Interest': 'short_interest', 'RSI (14)': 'rsi', 'CCI (20)': 'cci',
    '이자보상배율': 'interest_coverage', '순부채 ÷ EBITDA': 'net_debt_ebitda', '부채비율': 'debt_to_equity', '유동비율': 'current_ratio',
    '52주 고점 대비': 'from_high', '신용등급': 'credit_rating', '최근 공시': 'filings', '내부자 매매': 'insider', '차트 체크리스트': 'chart_checklist', '애널리스트 목표주가': 'target_price',
    '나스닥 대비 상대 강도와 종목 비교': 'relative_strength', '실적 추이': 'fcf'
  };

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
  function numCard(s, id) {
    if (!s) return '';
    // 차트 이력이 있는 카드는 누르면 큰 차트가 열린다
    var open = '<div class="num-wrap">' + (s.chart ? '<button type="button" class="num-card" data-chart="' + esc(id) + '" aria-label="' + esc(s.name) + ' 차트 보기">' : '<div class="num-card">');
    var close = (s.chart ? '</button>' : '</div>') + q(s.help) + '</div>';
    if (s.error || s.value == null) {
      return '<div class="num-wrap"><div class="num-card"><span class="name">' + esc(s.name) + '</span><span class="value flat">–</span><span class="note">' + esc(s.error_note || '데이터를 받지 못했습니다') + '</span></div>' + q(s.help) + '</div>';
    }
    var c = change(s);
    var note = s.note ? (s.note_level ? pill(s.note, s.note_level, true) : esc(s.note)) : '';
    return open +
      '<span class="name">' + esc(s.name) + '</span>' +
      '<span class="value">' + value(s) + '</span>' +
      '<span class="row"><span class="chg ' + c.d + '">' + c.text + '</span>' + sparkline(s.spark, c.d, 84, 26) + '</span>' +
      (note ? '<span class="note">' + note + '</span>' : '') +
      (s.next_release ? '<span class="note">다음 발표 ' + md(s.next_release) + ' (' + weekday(s.next_release) + ')</span>' : '') +
      '<span class="src">' + stamp(s) + '</span>' + close;
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
        '<div class="card-head"><h2>' + esc(sec.label) + q('regime') + '</h2><p class="regime-sum">' + sum + '</p></div>' +
        '<div class="regime-grid">' + items + '</div>' +
        '<details class="rules"><summary>판단 기준 보기</summary><ul>' + rules + '</ul>' +
        '<p class="src">출처: Yahoo Finance, FRED. 기준값은 config/dashboard.json 의 regime 에서 바꿉니다.</p></details></section>';
    },
    cards: function (sec) {
      var cards = '<div class="cards">' + sec.items.map(function (id) { return numCard(DATA.series[id], id); }).join('') + '</div>';
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
      return '<section class="card" aria-label="' + esc(sec.label) + '"><div class="card-head"><h2>' + esc(sec.label) + q('yield_curve') + '</h2><div class="legend">' + legend + '</div></div>' +
        '<svg class="curve" role="img" aria-label="미국 국채 수익률 곡선. 아래 표에 같은 값이 있습니다." viewBox="0 0 ' + W + ' ' + H + '">' + grid + xs + paths + '</svg>' +
        '<details class="rules"><summary>만기별 금리 표 보기</summary><div class="ctable">' + head + body + '</div></details>' +
        '<p class="src">미국 국채 만기별 금리. 단기 금리가 장기 금리보다 높으면(역전) 경기 둔화 신호로 봅니다. 출처: ' + esc(c.source) + ' · ' + md(c.now.date) + ' 기준</p></section>';
    },
    watchlist: function (sec) {
      var seg = [['us', '미국'], ['kr', '한국']].map(function (m) {
        return '<button type="button" class="btn" data-market="' + m[0] + '" aria-pressed="' + (state.market === m[0]) + '">' + m[1] + '</button>';
      }).join('');
      var list = ordered(state.market);
      var rows = list.map(function (s) {
        var name = '<div class="stock-name"><a href="#stocks/' + encodeURIComponent(s.ticker) + '"><b>' + (has(prefs.fav, s.ticker) ? '★ ' : '') + esc(s.name) + '</b></a><span>' + esc(s.ticker.replace(/\.K[SQ]$/, '')) + (s.stale ? ' · 이전 값' : '') + '</span></div>';
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
        '<div class="tr th"><span>종목</span><span>현재가</span><span>등락률</span><span>RSI(14)' + q('rsi') + '</span><span>52주 고점 대비' + q('from_high') + '</span><span>3개월 추이</span></div>' +
        rows + '</div></div>' +
        '<p class="src">종목 이름을 누르면 종목 한 장 요약으로 이동합니다. RSI 70 이상은 과매수, 30 이하는 과매도로 표시합니다. 출처: Yahoo Finance · ' + md(asof) + ' 기준 · 주가는 15분가량 지연됩니다.</p></section>';
    },
    heatmap: function (sec) {
      var hm = DATA.heatmap, key = state.heat || 'd1';
      if (!hm) return '';
      var PERIODS = [['d1', '1일'], ['w1', '1주'], ['m1', '1개월'], ['m3', '3개월'], ['ytd', '연초 이후']];
      var all = [].concat.apply([], hm.groups.map(function (g) { return g.cells; })).map(function (c) { return Math.abs(c[key] || 0); });
      var scale = Math.max.apply(null, all) || 1;
      var buttons = PERIODS.map(function (p) {
        return '<button type="button" class="btn small" data-heat="' + p[0] + '" aria-pressed="' + (p[0] === key) + '">' + p[1] + '</button>';
      }).join('');
      var body = hm.groups.map(function (g) {
        var cells = g.cells.slice().sort(function (a, b) { return (b[key] || 0) - (a[key] || 0); }).map(function (c) {
          var v = c[key], strength = v == null ? 0 : Math.round(8 + Math.abs(v) / scale * 37);   // 색은 진해도 글자가 읽히게 45%까지만
          var color = v > 0 ? 'var(--up)' : v < 0 ? 'var(--down)' : 'var(--sub)';
          return '<div class="heat" style="background: color-mix(in srgb, ' + color + ' ' + strength + '%, var(--card))">' +
            '<span class="n">' + esc(c.name) + '</span><b>' + (v == null ? '–' : signed(v, 1, '%')) + '</b><span class="t">' + esc(c.symbol) + '</span></div>';
        }).join('');
        return '<div class="heat-group"><h3>' + esc(g.name) + '</h3><div class="heat-grid">' + cells + '</div></div>';
      }).join('');
      var asof = hm.groups[0] && hm.groups[0].cells[0] ? hm.groups[0].cells[0].asof : '';
      return '<section class="card" aria-label="' + esc(sec.label) + '"><div class="card-head"><h2>' + esc(sec.label) + q('heatmap') + '</h2><div class="seg wrap">' + buttons + '</div></div>' + body +
        '<p class="src">업종·테마 ETF의 수익률입니다. 수익률이 높은 순으로 놓고, 많이 움직일수록 색이 진합니다. 출처: ' + esc(hm.source) + ' · ' + md(asof) + ' 기준</p></section>';
    },
    capex: function (sec) {
      var cx = DATA.capex;
      if (!cx || !cx.companies || !cx.companies.length) return '<section class="card"><h2>' + esc(sec.label) + '</h2><p class="empty">데이터를 받지 못했습니다.</p></section>';
      var last = cx.totals[cx.totals.length - 1];
      var lead = last ? '<p class="lead">' + esc(last.period) + ' 분기 합계 <b>' + money(last.total, 'USD') + '</b>' +
        (last.yoy_pct != null ? ' · 1년 전 같은 분기 대비 <b class="' + dir(last.yoy_pct) + '">' + signed(last.yoy_pct, 1, '%') + '</b>' : '') + '</p>' : '';
      var chart = cx.totals.length >= 2 ? '<div class="minis one">' + barChart(cx.totals, 'total', 'USD', '5개 회사 합계 (모두 값이 있는 분기만)', true) + '</div>' : '';
      var periods = cx.periods.slice(-6);
      var head = '<div class="ctr cx th" style="--cols:' + periods.length + '"><span>회사</span>' + periods.map(function (p) { return '<span>' + esc(p) + '</span>'; }).join('') + '</div>';
      var rows = cx.companies.map(function (c) {
        return '<div class="ctr cx" style="--cols:' + periods.length + '"><span>' + esc(c.name) + '</span>' + periods.map(function (p) {
          return '<span>' + (c.quarters[p] == null ? '–' : money(c.quarters[p], 'USD', true)) + '</span>'; }).join('') + '</div>';
      }).join('');
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + q('bigtech_capex') + '</h2>' + lead + chart +
        '<div class="scroll-x"><div class="ctable wide cx-table">' + head + rows + '</div></div>' +
        '<p class="src">단위: 달러. 분기는 끝난 달 기준이고, 회계 분기가 다른 오라클은 가까운 달로 맞췄습니다(8월 말 → 9월). 값이 없는 분기(–)는 무료 데이터에 빠져 있는 것입니다. 출처: ' + esc(cx.source) + ' · ' + md(cx.fetched) + ' 수집</p></section>';
    },
    insider: function (sec) {
      var cs = (DATA.sec || {}).companies || {};
      var rows = Object.keys(cs).map(function (t) {
        var c = cs[t], m = c.summary, name = (DATA.stocks[t] || {}).name || t;
        var last = c.insider[0];
        return '<div class="ctr ins"><span><a href="#stocks/' + encodeURIComponent(t) + '">' + esc(name) + '</a></span>' +
          '<span>' + (m.buy_count ? pill(m.buy_count + '건', 'good', true) + ' ' + money(m.buy_value, 'USD') : '없음') + '</span>' +
          '<span>' + (m.sell_count ? m.sell_count + '건 · ' + money(m.sell_value, 'USD') + (m.sell_planned ? ' <small>(계획 매도 ' + m.sell_planned + '건)</small>' : '') : '없음') + '</span>' +
          '<span>' + (last ? md(last.date) + ' ' + esc(last.owner) + ' ' + (last.code === 'P' ? '매수' : '매도') : '–') + '</span></div>';
      }).join('');
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + q('insider') + '</h2>' +
        '<div class="scroll-x"><div class="ctable wide ins-table"><div class="ctr ins th"><span>종목</span><span>공개시장 매수</span><span>공개시장 매도</span><span>가장 최근 거래</span></div>' + rows + '</div></div>' +
        '<p class="src">임원·이사·10% 이상 주주가 공개시장에서 사고판 것만 셉니다(주식 보상, 옵션 행사, 증여 제외). 계획 매도는 미리 정해 둔 일정(10b5-1)에 따른 매도입니다. 종목을 누르면 거래 내역이 나옵니다. 미국 상장 종목만 해당합니다. 출처: SEC · ' + md((DATA.sec || {}).fetched) + ' 수집</p></section>';
    },
    managers: function (sec) {
      var ms = (DATA.sec || {}).managers || [];
      if (!ms.length) return '<section class="card"><h2>' + esc(sec.label) + '</h2><p class="empty">데이터를 받지 못했습니다.</p></section>';
      var cards = ms.map(function (m) {
        var top = m.top.slice(0, 6).map(function (h) {
          return '<div class="hold"><span>' + esc(h.issuer) + '</span><span>' + fmt(h.weight_pct, 1) + '%' + (h.change && h.change !== '그대로' ? ' <small>' + esc(h.change) + '</small>' : '') + '</span></div>';
        }).join('');
        var watch = m.watch.length ? m.watch.map(function (w) {
          var tone = /매수|늘림/.test(w.change || '') ? 'good' : /매도|줄임/.test(w.change || '') ? 'warn' : 'none';
          return '<div class="hold"><span><a href="#stocks/' + encodeURIComponent(w.ticker) + '">' + esc(w.name) + '</a></span><span>' + (w.value ? fmt(w.weight_pct, 1) + '% ' : '') + (w.change ? pill(w.change, tone, true) : '') + '</span></div>';
        }).join('') : '<p class="empty">내 관심 종목은 보유하고 있지 않습니다.</p>';
        return '<div class="mgr"><div class="head"><div><h3>' + esc(m.name) + '</h3><span class="sub">' + esc(m.who || '') + '</span></div>' +
          '<span class="sub">' + esc(m.period.slice(0, 7).replace('-', '.')) + ' 말 기준<br>' + money(m.total, 'USD') + ' · ' + m.count + '개</span></div>' +
          '<h4>내 관심 종목</h4>' + watch + '<h4>비중 상위</h4>' + top +
          (m.sold && m.sold.length ? '<p class="src">전부 판 종목: ' + esc(m.sold.join(', ')) + '</p>' : '') +
          '<a class="src" href="' + esc(m.url) + '" target="_blank" rel="noopener">SEC 원문 보기</a></div>';
      }).join('');
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + q('13f') + '</h2><div class="mgrs">' + cards + '</div>' +
        '<p class="src">분기 말 기준 미국 주식 보유 목록이고 최대 석 달 반 늦습니다. 옵션은 빼고 주식만 셉니다. 변화는 직전 분기 신고와 주식 수를 비교한 것입니다. 볼 운용사는 config/dashboard.json 의 sec.managers 에서 바꿉니다. 출처: SEC</p></section>';
    },
    todo: function (sec) {
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2><ul class="todo">' +
        sec.items.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ul></section>';
    },
    alerts: function (sec) {
      var list = (DATA.alerts || []).slice(0, 8), tone = { good: 'good', warn: 'warn', info: 'none' };
      var body = list.length ? list.map(function (a) {
        var when = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(a.at));
        var title = a.ticker && DATA.stocks[a.ticker] ? '<a href="#stocks/' + encodeURIComponent(a.ticker) + '">' + esc(a.title) + '</a>' : esc(a.title);
        return '<div class="alert">' + pill(a.kind, tone[a.level] || 'none', true) + '<div class="what"><b>' + title + '</b><span>' + esc(a.detail) + ' · ' + when + '</span></div></div>';
      }).join('') : '<p class="empty">최근 며칠 동안 알릴 만한 변화가 없었습니다.</p>';
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2>' + body +
        '<p class="src">급등락, 실적, 이동평균선 돌파, RSI, 국면 변화, 주요 일정을 30분마다 점검합니다. 참고용 점검 알림입니다.</p></section>';
    },
    events: function (sec) {
      var ev = DATA.events || [];
      var body = ev.length ? ev.map(function (e) {
        return '<div class="event"><div class="date"><b>' + md(e.date) + '</b><span>' + weekday(e.date) + '</span></div>' +
          '<div class="what"><b>' + esc(e.title) + '</b><span>' + esc(e.kind) + ' · ' + esc(e.source || '') + '</span></div></div>';
      }).join('') : '<p class="empty">앞으로 30일 안에 잡힌 일정이 없습니다.</p>';
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2>' + body +
        '<p class="src">전체 일정은 <a href="#calendar">캘린더 탭</a>에서 봅니다. 실적일은 회사 확정 전에는 바뀔 수 있습니다.</p></section>';
    },
    rows: function (sec) {
      var rows = sec.items.map(function (id) {
        var s = DATA.series[id];
        if (!s) return '';
        if (s.error || s.value == null) return '<div class="kv"><span class="k">' + esc(s.name) + '</span><span class="src">수집 실패</span></div>';
        var c = change(s);
        var tag = s.chart ? 'button type="button" data-chart="' + esc(id) + '" aria-label="' + esc(s.name) + ' 차트 보기"' : 'div';
        return '<' + tag + ' class="kv" title="' + stamp(s) + '"><span class="k">' + esc(s.name) + (s.stale ? ' (이전 값)' : '') + '</span>' +
          '<span class="v"><b>' + fmt(s.value, s.decimals) + esc(s.unit || '') + '</b><span class="' + c.d + '">' + c.text + '</span></span></' + tag.split(' ')[0] + '>';
      }).join('');
      var used = sec.items.map(function (id) { return DATA.series[id]; }).filter(function (s) { return s && s.asof; });
      var by = {};
      used.forEach(function (s) { if (!by[s.source] || by[s.source] < s.asof) by[s.source] = s.asof; });
      var src = Object.keys(by).map(function (k) { return esc(k) + ' ' + md(by[k]) + ' 기준'; }).join(' · ');
      return '<section class="card" aria-label="' + esc(sec.label) + '"><h2>' + esc(sec.label) + '</h2><div class="rows">' + rows + '</div>' +
        '<p class="src">변화는 직전 발표값 대비입니다. 출처: ' + src + '</p></section>';
    }
  };


  // ───────── 종목 탭 ─────────
  function price(v, cur) { return v == null ? '–' : cur === 'KRW' ? fmt(v, 0) + '원' : '$' + fmt(v, 2); }
  function money(v, cur, bare) {
    // 큰 금액을 조·억 단위로 줄여 쓴다
    if (v == null) return '–';
    var a = Math.abs(v), sign = v < 0 ? '−' : '', unit = bare ? '' : cur === 'KRW' ? '원' : ' 달러';
    if (a >= 1e12) return sign + fmt(a / 1e12, a >= 1e14 ? 0 : 2) + '조' + unit;
    if (a >= 1e8) return sign + fmt(a / 1e8, a >= 1e10 ? 0 : 1) + '억' + unit;
    return sign + fmt(a / 1e4, 0) + '만' + unit;
  }
  function ratio(v, digits, unit) { return v == null ? '–' : fmt(v, digits == null ? 2 : digits) + (unit || ''); }
  function fact(label, val, sub) {
    return '<div class="fact"><span class="k">' + esc(label) + q(HELP_BY_LABEL[label]) + '</span><b>' + val + '</b>' + (sub ? '<span class="s">' + sub + '</span>' : '') + '</div>';
  }
  function box(title, body, src) {
    return '<section class="card" aria-label="' + esc(title) + '"><h2>' + esc(title) + q(HELP_BY_LABEL[title]) + '</h2>' + body + (src ? '<p class="src">' + src + '</p>' : '') + '</section>';
  }
  function rangeBar(lo, hi, at, cur, label) {
    if (lo == null || hi == null || at == null || hi <= lo) return '';
    var pct = Math.max(0, Math.min(100, (at - lo) / (hi - lo) * 100));
    return '<div class="range"><div class="track"><span class="mark" style="left:' + pct.toFixed(1) + '%"></span></div>' +
      '<div class="ends"><span>' + price(lo, cur) + '</span><span>' + esc(label) + ' ' + price(at, cur) + '</span><span>' + price(hi, cur) + '</span></div></div>';
  }
  function barChart(quarters, key, cur, title, isMoney, unit) {
    var q = quarters.filter(function (x) { return x[key] != null; });
    var many = q.length > 8;   // 막대가 많으면 숫자는 마지막 막대에만, 기간 이름은 건너뛰며 적는다
    if (!q.length) return '<div class="mini"><h3>' + esc(title) + '</h3><p class="empty">데이터 없음</p></div>';
    var W = 300, H = 150, T = 20, B = 38, bw = Math.min(44, (W - 20) / q.length - 10);
    var vals = q.map(function (x) { return x[key]; });
    var hi = Math.max(0, Math.max.apply(null, vals)), lo = Math.min(0, Math.min.apply(null, vals)), span = (hi - lo) || 1;
    function y(v) { return T + (hi - v) / span * (H - T - B); }
    var bars = q.map(function (x, i) {
      var cx = (i + 0.5) * W / q.length, v = x[key], top = Math.min(y(v), y(0)), h = Math.max(1, Math.abs(y(v) - y(0)));
      var text = isMoney ? money(v, cur, true) : (v < 0 ? '−' : '') + fmt(Math.abs(v), unit ? 1 : cur === 'KRW' ? 0 : 2) + (unit || '');
      var showVal = !many, showAxis = !many || (q.length - 1 - i) % 2 === 0;
      return '<rect class="' + (v < 0 ? 'neg' : 'pos') + '" x="' + (cx - bw / 2).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="2"></rect>' +
        (showVal ? '<text class="val" x="' + cx.toFixed(1) + '" y="' + (v < 0 ? top + h + 12 : top - 5).toFixed(1) + '" text-anchor="middle">' + text + '</text>' : '') +
        (showAxis ? '<text class="axis" x="' + cx.toFixed(1) + '" y="' + (H - 2) + '" text-anchor="middle">' + esc(x.period) + '</text>' : '') +
        '<title>' + esc(x.period + ' ' + text) + '</title>';
    }).join('');
    var lastV = q[q.length - 1][key], lastText = isMoney ? money(lastV, cur, true) : (lastV < 0 ? '−' : '') + fmt(Math.abs(lastV), unit ? 1 : 2) + (unit || '');
    return '<div class="mini"><h3>' + esc(title) + (many ? ' <span class="h-sub">최근 ' + lastText + '</span>' : '') + '</h3><svg class="bars" role="img" aria-label="' + esc(title) + ' 막대 그래프" viewBox="0 0 ' + W + ' ' + H + '">' +
      '<line class="grid" x1="0" x2="' + W + '" y1="' + y(0).toFixed(1) + '" y2="' + y(0).toFixed(1) + '"></line>' + bars + '</svg></div>';
  }
  function strengthChart(s) {
    var b = DATA.benchmark, dates = s.chart.dates;
    if (!b || dates.length < 2) return '<p class="empty">차트 데이터를 받지 못했습니다.</p>';
    function aligned(src) {      // 날짜가 다른 시장끼리는 직전 값으로 맞춘다
      var out = [], j = 0, last = null;
      dates.forEach(function (d) {
        while (j < src.dates.length && src.dates[j] <= d) { last = src.close[j]; j++; }
        out.push(last);
      });
      return out;
    }
    function norm(v) { var base = v.filter(function (x) { return x != null; })[0]; return v.map(function (x) { return x == null ? null : x / base * 100; }); }
    var other = state.compare && DATA.stocks[state.compare] && state.compare !== s.ticker ? DATA.stocks[state.compare] : null;
    var lines = [{ cls: 'now', name: s.name, v: norm(s.chart.close) }, { cls: 'month', name: b.name, v: norm(aligned(b)) }];
    if (other) lines.push({ cls: 'year', name: other.name, v: norm(aligned(other.chart)) });
    var W = 720, H = 260, L = 44, R = 16, T = 14, B = 30, n = dates.length;
    var all = [].concat.apply([], lines.map(function (l) { return l.v; })).filter(function (x) { return x != null; });
    var lo = Math.floor(Math.min.apply(null, all) / 10) * 10, hi = Math.ceil(Math.max.apply(null, all) / 10) * 10;
    function x(i) { return L + i * (W - L - R) / (n - 1); }
    function y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
    var grid = '', step = Math.max(10, Math.ceil((hi - lo) / 5 / 10) * 10);
    for (var g = lo; g <= hi; g += step) {
      grid += '<line class="grid" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(g).toFixed(1) + '" y2="' + y(g).toFixed(1) + '"></line>' +
        '<text class="axis" x="' + (L - 8) + '" y="' + (y(g) + 4).toFixed(1) + '" text-anchor="end">' + g + '</text>';
    }
    var ticks = [0, Math.floor(n / 2), n - 1].map(function (i) {
      return '<text class="axis" x="' + x(i).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="' + (i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle') + '">' + md(dates[i]) + '</text>';
    }).join('');
    var paths = lines.slice().reverse().map(function (l) {
      var pts = l.v.map(function (v, i) { return v == null ? null : x(i).toFixed(1) + ',' + y(v).toFixed(1); }).filter(Boolean).join(' ');
      return '<polyline class="curve-' + l.cls + '" points="' + pts + '"></polyline>';
    }).join('');
    var legend = lines.map(function (l) {
      var end = l.v[l.v.length - 1];
      return '<span class="legend-item"><svg aria-hidden="true" width="28" height="10"><line class="curve-' + l.cls + '" x1="1" x2="27" y1="5" y2="5"></line></svg>' + esc(l.name) + ' ' + signed(end - 100, 1, '%') + '</span>';
    }).join('');
    var gap = lines[0].v[n - 1] - lines[1].v[n - 1];
    var options = '<option value="">비교 종목 없음</option>' + Object.keys(DATA.stocks).filter(function (t) { return t !== s.ticker; }).map(function (t) {
      return '<option value="' + esc(t) + '"' + (t === state.compare ? ' selected' : '') + '>' + esc(DATA.stocks[t].name) + '</option>';
    }).join('');
    return '<div class="card-head"><p class="lead">' + md(dates[0]) + ' 이후 ' + esc(b.name) + ' 대비 <b class="' + dir(gap) + '">' + signed(gap, 1, '%p') + '</b></p>' +
      '<label class="pick">비교 <select data-compare>' + options + '</select></label></div>' +
      '<div class="legend">' + legend + '</div>' +
      '<svg class="curve" role="img" aria-label="' + esc(s.name) + '과 ' + esc(b.name) + '의 기간 수익률 비교. 시작일을 100으로 맞춘 값." viewBox="0 0 ' + W + ' ' + H + '">' + grid + ticks + paths + '</svg>';
  }
  function stockLinks(s) {
    var t = s.ticker, code = t.replace(/\.K[SQ]$/, ''), f = s.fund || {}, L = [];
    L.push(['야후 파이낸스', 'https://finance.yahoo.com/quote/' + encodeURIComponent(t)]);
    if (s.market === 'kr') {
      L.push(['네이버 금융', 'https://finance.naver.com/item/main.naver?code=' + code]);
      L.push(['트레이딩뷰', 'https://www.tradingview.com/chart/?symbol=KRX%3A' + code]);
      L.push(['DART 공시 (회사명으로 검색)', 'https://dart.fss.or.kr/']);
    } else {
      L.push(['핀비즈', 'https://finviz.com/quote.ashx?t=' + encodeURIComponent(t)]);
      L.push(['트레이딩뷰', 'https://www.tradingview.com/chart/?symbol=' + encodeURIComponent(t)]);
      L.push(['SEC 공시', 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=' + encodeURIComponent(t) + '&owner=include&count=40']);
    }
    if (s.links && s.links.ir) L.push(['IR 페이지', s.links.ir]);
    else if (f.website && /^https?:\/\//.test(f.website)) L.push(['회사 홈페이지', f.website]);
    var note = (s.links && s.links.notion) || DATA.site.notion_company_notes;
    if (note) L.push(['노션 기업분석 노트', note]);
    return '<div class="links">' + L.map(function (l) { return '<a class="btn link" href="' + esc(l[1]) + '" target="_blank" rel="noopener">' + esc(l[0]) + '</a>'; }).join('') + '</div>';
  }
  function stockDetail(s) {
    var f = s.fund || {}, cur = s.currency, fc = f.currency || cur, d = dir(s.change_pct), e = f.earnings || {}, tg = f.target || {}, sh = f.short || {};
    var none = '<p class="empty">재무 데이터를 받지 못했습니다.</p>';
    var fsrc = s.fund ? esc(f.source) + ' · ' + md(f.fetched) + ' 수집' + (f.stale ? ' · 수집 실패로 이전 값' : '') : '';
    var head = '<section class="card stock-head"><a class="back" href="#stocks">← 종목 목록</a>' +
      '<div class="card-head"><div><h2 class="big">' + esc(s.name) + '</h2><p class="sub">' + esc(s.ticker.replace(/\.K[SQ]$/, '')) + (f.long_name ? ' · ' + esc(f.long_name) : '') + (f.industry ? ' · ' + esc(f.industry) : '') + '</p></div>' +
      '<div class="quote"><b>' + price(s.price, cur) + '</b><span class="' + d + '">' + signed(s.change_pct, 2, '%') + '</span></div></div>' +
      stockLinks(s) + '<p class="src">' + stamp(s) + ' · 주가는 15분가량 지연됩니다.</p></section>';

    var ret = '<div class="ctable wide"><div class="ctr c3 th"><span>기간</span><span>' + (cur === 'KRW' ? '수익률' : '달러 기준') + '</span><span>' + (cur === 'KRW' ? '' : '원화 환산') + '</span></div>' +
      s.returns.map(function (r) {
        return '<div class="ctr c3"><span>' + esc(r.label) + '</span><span class="' + dir(r.local) + '">' + (r.local == null ? '–' : signed(r.local, 1, '%')) + '</span>' +
          '<span class="' + dir(r.krw) + '">' + (cur === 'KRW' ? '' : r.krw == null ? '–' : signed(r.krw, 1, '%')) + '</span></div>';
      }).join('') + '</div>';
    var priceBox = box('가격', rangeBar(s.low52, s.high52, s.price, cur, '현재') +
      '<div class="facts">' + fact('52주 고점 대비', signed(s.from_high_pct, 1, '%')) + fact('52주 최고', price(s.high52, cur)) + fact('52주 최저', price(s.low52, cur)) + '</div>' + ret,
      cur === 'KRW' ? '' : '원화 환산 수익률은 같은 기간의 원/달러 환율 변화를 반영한 값입니다.');

    var base = box('기본 체력', s.fund ? '<div class="facts">' + fact('시가총액', money(f.market_cap, cur)) + fact('보유 현금', money(f.cash, fc)) + fact('부채', money(f.debt, fc)) +
      fact(f.net_cash < 0 ? '순부채' : '순현금', money(Math.abs(f.net_cash), fc), f.net_cash < 0 ? '부채가 현금보다 많음' : '현금이 부채보다 많음') + '</div>' : none, fsrc);

    var dm = f.debt_metrics || {}, R = DATA.debt_rules || {};
    function grade(v, bad, warn, lowIsBad) {
      // 기준선과 비교해 신호등을 붙인다
      if (v == null) return '';
      var isBad = lowIsBad ? v < bad : v >= bad, isWarn = lowIsBad ? v < warn : v >= warn;
      return ' ' + (isBad ? pill('위험', 'bad', true) : isWarn ? pill('주의', 'warn', true) : pill('양호', 'good', true));
    }
    var iq = dm.interest_quarters || [];
    var rt = s.rating, rtFact;
    if (rt) {
      var junk = rt.sp ? /^(BB|B|CCC|CC|C|D)[+-]?$/.test(rt.sp) : /^(Ba|B|Caa|Ca|C)\d?$/.test(rt.moodys || '');
      var parts = [rt.sp && 'S&P ' + rt.sp.replace('-', '−'), rt.moodys && '무디스 ' + rt.moodys, rt.fitch && '피치 ' + rt.fitch.replace('-', '−')].filter(Boolean);
      rtFact = fact('신용등급', esc(parts[0]) + ' ' + pill(junk ? '투기등급' : '투자적격', junk ? 'warn' : 'good', true),
        esc(parts.slice(1).concat([rt.note, md(rt.entered) + ' 입력']).filter(Boolean).join(' · ')));
    } else {
      rtFact = fact('신용등급', '확인된 등급 없음', 'S&P·무디스·피치의 회사 등급을 찾지 못했습니다. 등급을 받지 않은 회사일 수 있습니다');
    }
    var debtBox = box('부채와 신용 위험', s.fund && f.debt_metrics && Object.keys(dm).length ? '<div class="facts wide">' + rtFact + '</div><div class="facts">' +
      fact('이자보상배율', dm.ebit_ttm != null && dm.ebit_ttm <= 0 ? pill('영업적자', 'bad', true) : dm.interest_coverage == null ? (dm.interest_ttm ? '–' : '이자비용 없음') : fmt(dm.interest_coverage, dm.interest_coverage < 1 ? 2 : 1) + '배' + grade(dm.interest_coverage, R.coverage_bad, R.coverage_warn, true),
        '최근 4분기 EBIT ' + money(dm.ebit_ttm, fc) + ' ÷ 이자비용 ' + money(dm.interest_ttm, fc)) +
      fact('순부채 ÷ EBITDA', f.net_cash >= 0 ? '순현금 ' + pill('양호', 'good', true) : dm.net_debt_to_ebitda == null ? (dm.ebitda != null && dm.ebitda <= 0 ? pill('EBITDA 적자', 'bad', true) : '–') : fmt(dm.net_debt_to_ebitda, 1) + '배' + grade(dm.net_debt_to_ebitda, R.leverage_bad, R.leverage_warn, false),
        '번 돈으로 빚을 갚는 데 걸리는 햇수. EBITDA ' + money(dm.ebitda, fc)) +
      fact('부채비율', ratio(dm.debt_to_equity_pct, 0, '%'), '총부채 ÷ 자기자본') +
      fact('유동비율', dm.current_ratio == null ? '–' : fmt(dm.current_ratio, 2) + '배' + (dm.current_ratio < R.current_ratio_warn ? ' ' + pill('주의', 'warn', true) : ''), '1년 안에 현금화할 자산 ÷ 1년 안에 갚을 부채') +
      fact('1년 내 만기 부채', money(dm.short_debt, fc), dm.cash_to_short_debt == null ? '' : '보유 현금이 ' + fmt(dm.cash_to_short_debt, 1) + '배') +
      fact('분기 이자비용', iq.length ? money(iq[iq.length - 1].interest, fc) : '–', iq.length > 1 ? iq[0].period + ' 분기 ' + money(iq[0].interest, fc) + '에서 변화' : '') + '</div>' : none,
      '개별 기업의 CDS와 회사채 가격은 무료 데이터가 없어 재무제표로 계산한 지표로 대신합니다. 기준: 이자보상배율 ' + R.coverage_bad + '배 미만 위험·' + R.coverage_warn + '배 미만 주의, 순부채÷EBITDA ' + R.leverage_bad + '배 이상 위험·' + R.leverage_warn + '배 이상 주의. 등급별 회사채 스프레드는 <a href="#macro">거시경제 탭</a>의 신용 묶음에서 봅니다. ' + fsrc);

    var val = box('밸류에이션', s.fund ? '<div class="facts">' +
      fact('PER', ratio(f.per, 1, '배'), f.per == null ? '적자이거나 값 없음' : '') + fact('포워드 PER', ratio(f.forward_per, 1, '배')) + fact('PSR', ratio(f.psr, 1, '배')) + fact('PEG', ratio(f.peg, 2)) +
      fact('매출 성장률 (전년 동기 대비)', f.revenue_growth_pct == null ? '–' : '<span class="' + dir(f.revenue_growth_pct) + '">' + signed(f.revenue_growth_pct, 1, '%') + '</span>', '배수와 나란히 봅니다') +
      fact('EPS (최근 12개월)', f.eps == null ? '–' : price(f.eps, fc)) + fact('EPS (예상)', f.forward_eps == null ? '–' : price(f.forward_eps, fc)) + fact('ROE', ratio(f.roe_pct, 1, '%')) + '</div>' : none, fsrc);

    var q = f.quarters || [];
    var trend = box('실적 추이', q.length ? '<div class="minis">' + barChart(q, 'revenue', fc, '매출', true) + barChart(q, 'op_income', fc, '영업이익', true) + barChart(q, 'eps', fc, 'EPS', false) + '</div>' +
      '<div class="ctable wide"><div class="ctr c3 th"><span>분기 (끝난 달)</span><span>FCF</span><span>CAPEX</span></div>' + q.map(function (x) {
        return '<div class="ctr c3"><span>' + esc(x.period) + '</span><span>' + money(x.fcf, fc) + '</span><span>' + money(x.capex == null ? null : Math.abs(x.capex), fc) + '</span></div>';
      }).join('') + '</div>' : '<p class="empty">분기 실적을 받지 못했습니다.</p>',
      '단위: ' + (fc === 'KRW' ? '원' : '달러') + '. 무료 데이터는 최근 4~5개 분기만 제공합니다. ' + fsrc);

    var last = e.last;
    var earn = box('실적 발표', '<div class="facts">' + fact('다음 발표일', e.next ? md(e.next) + ' (' + weekday(e.next) + ')' : '–', e.next ? e.next.slice(0, 4) + '년 · 한국 시간' : '') +
      (last ? fact('지난 발표 EPS', price(last.eps_actual, fc), '예상 ' + price(last.eps_estimate, fc) + ' · ' + md(last.date) + ' 발표') +
        fact('예상 대비', last.surprise_pct == null ? '–' : '<span class="' + dir(last.surprise_pct) + '">' + signed(last.surprise_pct, 1, '%') + '</span>') : '') + '</div>',
      '매출 예상치 대비 실제는 무료 데이터가 없어 표시하지 않습니다. ' + fsrc);

    var up = tg.mean && s.price ? (tg.mean / s.price - 1) * 100 : null;
    var analyst = box('애널리스트 목표주가', tg.mean ? rangeBar(Math.min(tg.low, s.price), Math.max(tg.high, s.price), s.price, cur, '현재') +
      '<div class="facts">' + fact('평균', price(tg.mean, cur), up == null ? '' : '현재가 대비 ' + signed(up, 1, '%')) + fact('최고', price(tg.high, cur)) + fact('최저', price(tg.low, cur)) + fact('애널리스트 수', ratio(tg.analysts, 0, '명')) + '</div>' : '<p class="empty">목표주가 데이터가 없습니다.</p>', fsrc);

    var sf = sh.float_pct;
    var shortBox = box('공매도', sf != null ? '<div class="facts">' +
      fact('Short Float', fmt(sf, 1) + '% ' + (sf >= 20 ? pill('20% 이상', 'bad', true) : sf >= 10 ? pill('10% 이상', 'warn', true) : pill('10% 미만', 'good', true)), '유통 주식 중 공매도 비율') +
      fact('Short Ratio', ratio(sh.ratio, 1, '일'), '공매도 잔량 ÷ 하루 평균 거래량') + fact('Short Interest', sh.shares == null ? '–' : money(sh.shares, '', true) + '주') + '</div>'
      : '<p class="empty">' + (s.market === 'kr' ? '한국 종목의 공매도 데이터는 Yahoo에서 제공하지 않습니다.' : '공매도 데이터가 없습니다.') + '</p>',
      sf != null ? '기준일 ' + md(sh.date) + '. 월 2회 발표라 1~2주 늦습니다. ' + fsrc : '');

    var rsiPill = s.rsi == null ? '' : s.rsi >= 70 ? pill('과매수 (70 이상)', 'warn', true) : s.rsi <= 30 ? pill('과매도 (30 이하)', 'good', true) : pill('중립 (30~70)', 'none', true);
    var cciPill = s.cci == null ? '' : s.cci >= 100 ? pill('+100 이상', 'warn', true) : s.cci <= -100 ? pill('−100 이하', 'good', true) : pill('−100~+100', 'none', true);
    var tech = box('기술적 지표', '<div class="facts">' + fact('RSI (14)', (s.rsi == null ? '–' : fmt(s.rsi, 1)) + ' ' + rsiPill, '상승·하락 강도') + fact('CCI (20)', (s.cci == null ? '–' : fmt(s.cci, 0)) + ' ' + cciPill, '평균 가격 대비 이격도') + '</div>' +
      '<div class="ctable wide"><div class="ctr c3 th"><span>이동평균선</span><span>값</span><span>주가와의 간격</span></div>' + s.mas.map(function (m) {
        return '<div class="ctr c3"><span>' + m.days + '일</span><span>' + price(m.value, cur) + '</span><span class="' + dir(m.gap_pct) + '">' + (m.gap_pct == null ? '이력 부족' : signed(m.gap_pct, 1, '%')) + '</span></div>';
      }).join('') + '</div>', '일봉 종가로 직접 계산합니다. 간격이 +이면 주가가 이평선 위에 있습니다.');

    var check = box('차트 체크리스트', s.checklist.map(function (g) {
      var hits = g.items.filter(function (i) { return i.hit; }).length;
      return '<div class="check-group"><div class="head"><h3>' + esc(g.title) + '</h3>' + pill(hits + '개 해당', hits ? g.tone : 'none', true) + '</div>' + g.items.map(function (i) {
        var mark = i.hit == null ? pill('확인 불가', 'none', true) : i.hit ? pill('해당', g.tone, true) : pill('해당 없음', 'none', true);
        return '<div class="check"><div><b>' + esc(i.text) + '</b><span>' + esc(i.detail) + '</span></div>' + mark + '</div>';
      }).join('') + '</div>';
    }).join(''), '노션 「차트 분석」의 기준을 자동 점검한 참고용 알림입니다. 기준 숫자는 config/dashboard.json 의 chart_rules 에서 바꿉니다.');

    var charts = box('나스닥 대비 상대 강도와 종목 비교', '<div id="strength" class="stack">' + strengthChart(s) + '</div>', '시작일을 100으로 맞춘 값입니다. 비교 종목을 고르면 선이 하나 더 그려집니다.') +
      box('트레이딩뷰 차트', '<div id="tv" data-symbol="' + esc(s.market === 'kr' ? 'KRX:' + s.ticker.replace(/\.K[SQ]$/, '') : s.ticker) + '"></div>',
        '트레이딩뷰 무료 위젯입니다. 한국 종목은 무료 위젯에서 표시되지 않을 수 있습니다. 차트가 비어 있으면 위의 트레이딩뷰 바로가기를 누르세요.');

    var sc = ((DATA.sec || {}).companies || {})[s.ticker];
    var filingsBox = '', insiderBox = '';
    if (sc) {
      filingsBox = box('최근 공시', sc.filings.length ? sc.filings.map(function (f) {
        return '<div class="event"><div class="date"><b>' + md(f.date) + '</b><span>' + esc(f.form) + '</span></div><div class="what"><b><a href="' + esc(f.url) + '" target="_blank" rel="noopener">' +
          esc(f.items.length ? f.items.join(' · ') : f.label) + '</a></b><span>' + esc(f.label) + '</span></div></div>';
      }).join('') : '<p class="empty">최근 90일 동안 주요 공시가 없습니다.</p>', '최근 90일의 주요 공시입니다. 제목을 누르면 SEC 원문이 열립니다. 출처: SEC · ' + md(DATA.sec.fetched) + ' 수집');
      var trades = sc.insider.slice(0, 10);
      insiderBox = box('내부자 매매', '<div class="facts">' +
        fact('공개시장 매수 (90일)', sc.summary.buy_count ? sc.summary.buy_count + '건 ' + pill('매수 있음', 'good', true) : '없음', sc.summary.buy_count ? money(sc.summary.buy_value, 'USD') : '') +
        fact('공개시장 매도 (90일)', sc.summary.sell_count ? sc.summary.sell_count + '건' : '없음', sc.summary.sell_count ? money(sc.summary.sell_value, 'USD') + ' · 계획 매도 ' + sc.summary.sell_planned + '건' : '') + '</div>' +
        (trades.length ? '<div class="scroll-x"><div class="ctable wide"><div class="ctr tr5 th"><span>날짜</span><span>누가</span><span>거래</span><span>주식 수</span><span>금액</span></div>' + trades.map(function (r) {
          return '<div class="ctr tr5"><span>' + md(r.date) + '</span><span>' + esc(r.owner) + '<br><small>' + esc(r.role) + '</small></span>' +
            '<span>' + pill(r.code === 'P' ? '매수' : r.planned ? '계획 매도' : '매도', r.code === 'P' ? 'good' : 'none', true) + '</span>' +
            '<span>' + fmt(r.shares, 0) + '</span><span>' + (r.value ? money(r.value, 'USD') : '–') + '</span></div>';
        }).join('') + '</div></div>' : '<p class="empty">최근 180일 동안 공개시장 매수·매도 신고가 없습니다.</p>'),
        '주식 보상, 옵션 행사, 증여는 빼고 공개시장 거래만 보여 줍니다. 계획 매도는 미리 정해 둔 일정(10b5-1)에 따른 것입니다. 출처: SEC Form 4');
    }
    var finBox = box('장기 재무', '<div id="fin" data-t="' + esc(s.ticker) + '"><p class="empty">불러오는 중입니다…</p></div>');
    var nw = s.news, newsBox = '';
    if (nw) {
      newsBox = box('최근 뉴스', nw.items.length ? nw.items.map(function (n) {
        return '<div class="event"><div class="date"><b>' + md(n.at) + '</b><span>' + esc((n.at || '').slice(11, 16)) + '</span></div><div class="what"><b><a href="' + esc(n.url) +
          '" target="_blank" rel="noopener">' + esc(n.title) + '</a></b><span>' + esc(n.publisher || '') + '</span></div></div>';
      }).join('') : '<p class="empty">최근 뉴스가 없습니다.</p>',
        '제목을 누르면 원문이 열립니다. 기사는 영어이고, 시간은 한국 시간입니다. 출처: ' + esc(nw.source) + ' · ' + md(nw.fetched) + ' ' + esc((nw.fetched || '').slice(11, 16)) + ' 수집' + (nw.stale ? ' (이전 값)' : ''));
    }
    return head + '<div class="grid2">' + priceBox + tech + '</div>' + check + charts +
      '<div class="grid2">' + base + val + '</div>' + finBox + debtBox + trend + '<div class="grid2">' + earn + analyst + '</div>' + shortBox + newsBox + (sc ? '<div class="grid2">' + filingsBox + insiderBox + '</div>' : '');
  }
  // ───────── 장기 재무 (SEC) — 종목별 AI용 파일(data/ai/티커.json)을 읽어 그린다 ─────────
  var AIF = {};
  var FIN_ROWS = [
    ['매출', 'revenue', 'money'], ['매출 성장률', 'revenue_growth_pct', 'growth'], ['매출총이익률', 'gross_margin_pct', 'pct'],
    ['영업이익', 'op_income', 'money'], ['영업이익률', 'op_margin_pct', 'pct'], ['순이익률', 'net_margin_pct', 'pct'],
    ['EPS (희석)', 'eps_diluted', 'eps'], ['EPS 성장률', 'eps_growth_pct', 'growth'],
    ['FCF', 'fcf', 'money'], ['FCF 마진', 'fcf_margin_pct', 'pct'], ['설비투자 ÷ 매출', 'capex_pct', 'pct'], ['주식보상 ÷ 매출', 'sbc_pct', 'pct'],
    ['ROIC', 'roic_pct', 'pct'], ['ROE', 'roe_pct', 'pct'], ['희석 주식 수 증감', 'share_change_pct', 'growth'], ['순현금 (음수면 순부채)', 'net_cash', 'money']
  ];
  function aiUrl(t) { return 'data/ai/' + t.replace(/[^A-Za-z0-9.-]/g, '_') + '.json'; }
  function aiAbsUrl(t) { return 'https://' + DATA.site.repo.split('/')[0] + '.github.io/' + DATA.site.repo.split('/')[1] + '/' + aiUrl(t); }
  function loadFin() {
    var holder = $('fin');
    if (!holder) return;
    var t = holder.dataset.t, key = t + DATA.generated_at;
    if (AIF[key]) { holder.innerHTML = finBody(AIF[key]); finScroll(); return; }
    fetch(aiUrl(t) + '?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (j) { AIF[key] = j; if ($('fin') && $('fin').dataset.t === t) { $('fin').innerHTML = finBody(j); finScroll(); } })
      .catch(function (err) { if ($('fin')) $('fin').innerHTML = '<p class="empty">장기 재무를 불러오지 못했습니다 (' + esc(err.message) + ').</p>'; });
  }
  function finScroll() { var sx = document.querySelector('#fin .scroll-x'); if (sx) sx.scrollLeft = sx.scrollWidth; }   // 표는 최근 기간이 보이게 오른쪽 끝으로
  function finCell(v, kind, cur) {
    if (v == null) return '–';
    if (kind === 'money') return money(v, cur, true);
    if (kind === 'eps') return (v < 0 ? '−' : '') + fmt(Math.abs(v), 2);
    if (kind === 'growth') return '<span class="' + dir(v) + '">' + (Math.abs(v) >= 1000 ? (v > 0 ? '+' : '−') + '999%↑' : signed(v, 1, '%')) + '</span>';
    return Math.abs(v) >= 1000 ? '<span title="' + fmt(v, 1) + '%">' + (v < 0 ? '−' : '') + '1000%+</span>' : fmt(v, 1) + '%';
  }
  function finBody(j) {
    var F = j.financials, view = state.finView || 'annual';
    var link = '<div class="ai-link"><p><b>AI 분석용 파일</b> 이 종목의 장기 재무, 밸류에이션, 실적 보도자료 본문, 공시, 알림을 한 파일에 모았습니다. 주소를 Claude 앱에 붙여 넣고 분석을 요청하면 됩니다.</p>' +
      '<div class="links"><a class="btn link" href="' + esc(aiUrl(j.ticker)) + '" target="_blank" rel="noopener">파일 열기</a>' +
      '<button type="button" class="btn small" data-copy="' + esc(aiAbsUrl(j.ticker)) + '">주소 복사</button></div></div>';
    if (!F) return '<p class="empty">' + (j.market === 'kr' ? '한국 종목은 SEC 자료가 없어 장기 재무가 없습니다. 금융감독원 DART의 API 키(무료)를 받으면 붙일 수 있습니다. AI용 파일에는 Yahoo의 최근 분기 실적만 들어 있습니다.'
      : 'SEC 장기 재무를 받지 못했습니다.') + '</p>' + link;
    var cur = F.currency === 'USD' ? 'USD' : F.currency, unitName = F.currency === 'USD' ? '달러' : F.currency;
    var rows = (view === 'annual' ? F.annual.slice(-10) : F.quarterly.slice(-12)).map(function (r) {
      var y = r.end.slice(2, 4);
      return Object.assign({ period: view === 'annual' ? 'FY' + y : y + '.' + r.end.slice(5, 7) }, r);
    });
    var tt = F.ttm, vc = j.valuation_calc || {}, tl = '최근 4분기';
    if (!tt && F.annual.length) { tt = F.annual[F.annual.length - 1]; tl = 'FY' + tt.end.slice(2, 4); }
    tt = tt || {};
    var seg = '<div class="seg">' + [['annual', '연간'], ['quarterly', '분기']].map(function (v) {
      return '<button type="button" class="btn small" data-fin="' + v[0] + '" aria-pressed="' + (v[0] === view) + '">' + v[1] + '</button>';
    }).join('') + '</div>';
    var facts = '<div class="facts">' +
      fact('매출 (' + tl + ')', money(tt.revenue, cur), tt.end ? md(tt.end) + (F.ttm ? ' 분기까지' : ' 끝난 회계연도') : '') +
      fact('영업이익률 (' + tl + ')', tt.op_margin_pct == null ? '–' : finCell(tt.op_margin_pct, 'pct')) +
      fact('FCF 마진 (' + tl + ')', tt.fcf_margin_pct == null ? '–' : finCell(tt.fcf_margin_pct, 'pct'), tt.fcf == null ? '' : 'FCF ' + money(tt.fcf, cur)) +
      fact('ROIC (' + tl + ')', tt.roic_pct == null ? '–' : finCell(tt.roic_pct, 'pct'), '세후 영업이익 ÷ 투하자본') +
      fact('P/FCF', vc.p_fcf == null ? (tt.fcf != null && tt.fcf <= 0 ? 'FCF 적자' : '–') : fmt(vc.p_fcf, 1) + '배', vc.fcf_yield_pct == null ? '' : 'FCF 수익률 ' + fmt(vc.fcf_yield_pct, 2) + '%') +
      fact('EV ÷ 매출', vc.ev_sales == null ? '–' : fmt(vc.ev_sales, 1) + '배', vc.ev == null ? '' : 'EV ' + money(vc.ev, cur)) + '</div>';
    var charts = rows.length ? '<div class="minis">' + barChart(rows, 'revenue', cur, '매출', true) + barChart(rows, 'fcf', cur, 'FCF', true) +
      barChart(rows, 'op_margin_pct', cur, '영업이익률', false, '%') + '</div>' : '';
    var n = rows.length, style = ' style="--cols:' + n + ';min-width:' + (130 + n * 74) + 'px"';
    var table = n ? '<div class="scroll-x"><div class="ctable wide"><div class="ctr fin th"' + style + '><span>항목</span>' + rows.map(function (r) { return '<span>' + esc(r.period) + '</span>'; }).join('') + '</div>' +
      FIN_ROWS.map(function (m) {
        return '<div class="ctr fin"' + style + '><span>' + esc(m[0]) + '</span>' + rows.map(function (r) { return '<span>' + finCell(r[m[1]], m[2], cur) + '</span>'; }).join('') + '</div>';
      }).join('') + '</div></div>' : '<p class="empty">' + (view === 'quarterly' ? '분기 자료가 없습니다. 외국 기업(20-F)은 연간 자료만 SEC에 냅니다.' : '연간 자료가 없습니다. 상장한 지 1년이 안 됐을 수 있습니다.') + '</p>';
    var rel = j.earnings_release;
    var relHtml = rel ? '<div class="event"><div class="date"><b>' + md(rel.date) + '</b><span>' + esc(rel.date.slice(0, 4)) + '</span></div><div class="what"><b><a href="' + esc(rel.url) + '" target="_blank" rel="noopener">최근 실적 보도자료 (SEC 원문)</a></b>' +
      '<span>본문 ' + fmt(rel.chars, 0) + '자를 AI용 파일에 넣었습니다' + (rel.truncated ? ' (긴 부분은 앞쪽만)' : '') + '</span></div></div>' : '';
    var note = [F.since_note, F.stale ? '오늘 수집에 실패해 이전 값입니다.' : ''].filter(Boolean).join(' ');
    return '<div class="card-head sub-head">' + seg + '</div>' + (note ? '<p class="notice">' + esc(note) + '</p>' : '') + facts + charts + table + relHtml + link +
      '<p class="src">단위: ' + esc(unitName) + '. 회사가 SEC에 낸 10-K·10-Q 숫자로 계산합니다. 연도는 회계연도(FY, 끝난 해)이고 분기는 끝난 달입니다. ' +
      '현금흐름 분기 값은 누적값의 차이로, 4분기는 연간에서 9개월 누적을 빼서 만듭니다. 4분기 EPS는 계산하지 않습니다. ' +
      'ROIC는 세후 영업이익 ÷ (자기자본 + 차입금 − 현금·단기 투자)의 기초·기말 평균으로, 대시보드가 정한 방식입니다. 현금이 많아 투하자본이 총자산의 10%도 안 되면 값이 수백 %로 튀어 비워 둡니다. ' +
      'P/FCF·EV는 Yahoo 시가총액과 SEC 값을 함께 씁니다. 출처: SEC XBRL · ' + md(F.fetched) + ' 수집</p>';
  }
  function issueUrl(action, ticker, name) {
    // 종목 추가·삭제는 GitHub 요청(이슈)으로 보낸다. 저장소의 자동 작업이 받아서 처리한다
    return 'https://github.com/' + DATA.site.repo + '/issues/new?title=' + encodeURIComponent('종목 ' + action + ': ' + ticker) +
      '&body=' + encodeURIComponent((name ? '이름: ' + name + '\n\n' : '') + '아래 초록색 Create 버튼을 누르면 1~3분 뒤 사이트에 반영됩니다.');
  }
  function stockList() {
    var html = '<section class="card" aria-label="종목 추가"><h2>종목 추가</h2>' +
      '<form class="add" data-add><label>티커<input name="ticker" required maxlength="12" pattern="[A-Za-z0-9.\\-]+" placeholder="TSLA 또는 005930" autocomplete="off" autocapitalize="characters"></label>' +
      '<label>화면에 보일 이름 (선택)<input name="name" maxlength="30" placeholder="테슬라" autocomplete="off"></label>' +
      '<button type="submit" class="btn" aria-pressed="true">추가 요청 열기</button></form>' +
      '<p class="src">버튼을 누르면 GitHub 요청 화면이 새 탭으로 열립니다. 거기서 초록색 Create 버튼을 누르면 1~3분 뒤 모든 지표가 반영됩니다. ' +
      '미국 종목은 티커, 한국 종목은 숫자 6자리를 적습니다. 삭제는 아래 목록 편집에서 합니다. GitHub에 로그인돼 있어야 합니다.</p></section>';
    [['us', '미국'], ['kr', '한국']].forEach(function (m) {
      var list = ordered(m[0], state.edit);
      var rows = list.map(function (s, i) {
        var hid = has(prefs.hidden, s.ticker), fav = has(prefs.fav, s.ticker), t = esc(s.ticker);
        var name = '<div class="stock-name"><a href="#stocks/' + encodeURIComponent(s.ticker) + '"><b>' + (fav ? '★ ' : '') + esc(s.name) + '</b></a><span>' + esc(s.ticker.replace(/\.K[SQ]$/, '')) + (hid ? ' · 숨김' : '') + '</span></div>';
        if (state.edit) {
          return '<div class="tr edit' + (hid ? ' dim' : '') + '">' + name + '<div class="tools">' +
            '<button type="button" class="btn" data-act="fav" data-t="' + t + '" aria-pressed="' + fav + '">★ 즐겨찾기</button>' +
            '<button type="button" class="btn" data-act="up" data-m="' + m[0] + '" data-t="' + t + '" aria-label="' + esc(s.name) + ' 위로"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
            '<button type="button" class="btn" data-act="down" data-m="' + m[0] + '" data-t="' + t + '" aria-label="' + esc(s.name) + ' 아래로"' + (i === list.length - 1 ? ' disabled' : '') + '>↓</button>' +
            '<button type="button" class="btn" data-act="hide" data-t="' + t + '" aria-pressed="' + hid + '">' + (hid ? '다시 보이기' : '숨기기') + '</button>' +
            '<a class="btn link del" href="' + esc(issueUrl('삭제', s.ticker)) + '" target="_blank" rel="noopener">삭제 요청</a></div></div>';
        }
        if (s.error || s.price == null) return '<div class="tr">' + name + '<span class="flat">–</span><span></span><span></span><span></span><span class="src">수집 실패</span></div>';
        var d = dir(s.change_pct), det = DATA.stocks[s.ticker] || {}, f = det.fund || {};
        return '<div class="tr">' + name + '<span class="price">' + price(s.price, s.currency) + '</span>' +
          '<span class="chg-cell ' + d + '">' + signed(s.change_pct, 2, '%') + '</span>' +
          '<span>' + (s.rsi == null ? '–' : fmt(s.rsi, 0)) + '</span><span class="flat">' + signed(s.from_high_pct, 1, '%') + '</span>' +
          '<span>' + money(f.market_cap, s.currency) + '</span></div>';
      }).join('');
      html += '<section class="card" aria-label="' + m[1] + ' 종목"><div class="card-head"><h2>' + m[1] + '</h2>' +
        (m[0] === 'us' ? '<button type="button" class="btn" data-act="edit" aria-pressed="' + state.edit + '">' + (state.edit ? '편집 끝내기' : '목록 편집') + '</button>' : '') + '</div>' +
        '<div class="scroll-x"><div class="table">' + (state.edit ? '' : '<div class="tr th"><span>종목</span><span>현재가</span><span>등락률</span><span>RSI(14)' + q('rsi') + '</span><span>52주 고점 대비' + q('from_high') + '</span><span>시가총액</span></div>') +
        (rows || '<p class="empty">표시할 종목이 없습니다. 목록 편집에서 숨긴 종목을 다시 보이게 할 수 있습니다.</p>') + '</div></div></section>';
    });
    return html + '<p class="src">종목 이름을 누르면 종목 한 장 요약이 열립니다. 숨기기·순서·즐겨찾기는 이 브라우저에만 저장됩니다. 숨기기는 화면에서만 가리고, 삭제 요청은 수집 대상에서 완전히 뺍니다.</p>';
  }
  SECTIONS.stocks = function () {
    if (state.stock) {
      var s = DATA.stocks && DATA.stocks[state.stock];
      return s ? stockDetail(s) : '<section class="card"><a class="back" href="#stocks">← 종목 목록</a><h2>' + esc(state.stock) + ' 데이터가 없습니다</h2><p class="empty">관심 종목에 없거나 수집에 실패했습니다.</p></section>';
    }
    return stockList();
  };
  function loadTradingView(holder) {
    var w = document.createElement('div'), inner = document.createElement('div'), sc = document.createElement('script');
    w.className = 'tradingview-widget-container'; inner.className = 'tradingview-widget-container__widget';
    sc.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'; sc.async = true;
    sc.text = JSON.stringify({ autosize: true, symbol: holder.dataset.symbol, interval: 'D', timezone: 'Asia/Seoul', theme: root.dataset.theme === 'dark' ? 'dark' : 'light',
      style: '1', locale: 'kr', allow_symbol_change: false, hide_side_toolbar: true, support_host: 'https://www.tradingview.com' });
    holder.innerHTML = ''; holder.className = 'tv-on'; w.appendChild(inner); w.appendChild(sc); holder.appendChild(w);
  }

  // ───────── 캘린더 탭 ─────────
  var KINDS = ['실적', '경제지표', 'FOMC', '만기', '내 이벤트'];
  function kstToday() { return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date()); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  SECTIONS.calendar = function () {
    var today = kstToday();
    var ym = state.month || today.slice(0, 7), y = Number(ym.slice(0, 4)), m = Number(ym.slice(5, 7));
    var events = (DATA.events_all || []).filter(function (e) { return !state.kinds[KINDS.indexOf(e.kind) < 0 ? '내 이벤트' : e.kind]; });
    var inMonth = events.filter(function (e) { return e.date.slice(0, 7) === ym; });
    var byDay = {};
    inMonth.forEach(function (e) { (byDay[e.date] = byDay[e.date] || []).push(e); });
    function shift(step) { var d = new Date(y, m - 1 + step, 1); return d.getFullYear() + '-' + pad(d.getMonth() + 1); }
    var nav = '<div class="seg"><button type="button" class="btn" data-month="' + shift(-1) + '" aria-label="이전 달">←</button>' +
      '<button type="button" class="btn" data-month="' + today.slice(0, 7) + '">이번 달</button>' +
      '<button type="button" class="btn" data-month="' + shift(1) + '" aria-label="다음 달">→</button></div>';
    var filters = '<div class="seg wrap">' + KINDS.map(function (k) {
      return '<button type="button" class="btn small" data-kind="' + k + '" aria-pressed="' + !state.kinds[k] + '">' + k + '</button>';
    }).join('') + '</div>';
    var first = new Date(y, m - 1, 1).getDay(), days = new Date(y, m, 0).getDate(), cells = '';
    for (var i = 0; i < first; i++) cells += '<div class="day off"></div>';
    for (var d = 1; d <= days; d++) {
      var iso = ym + '-' + pad(d), list = byDay[iso] || [];
      cells += '<div class="day' + (iso === today ? ' today' : '') + (iso < today ? ' past' : '') + '"><span class="n">' + d + '</span>' +
        list.map(function (e) { return '<span class="chip k' + KINDS.indexOf(e.kind) + '" title="' + esc(e.title) + '">' + esc(e.title.replace(' 발표', '')) + '</span>'; }).join('') + '</div>';
    }
    var grid = '<div class="cal" aria-hidden="true"><div class="dow">' + '일월화수목금토'.split('').map(function (w) { return '<span>' + w + '</span>'; }).join('') + '</div><div class="days">' + cells + '</div></div>';
    var list = inMonth.length ? inMonth.map(function (e) {
      return '<div class="event' + (e.date < today ? ' past' : '') + '"><div class="date' + (e.date === today ? ' today' : '') + '"><b>' + md(e.date) + '</b><span>' + weekday(e.date) + '</span></div>' +
        '<div class="what"><b>' + esc(e.title) + '</b><span>' + esc(e.kind) + ' · ' + esc(e.source || '') + '</span></div></div>';
    }).join('') : '<p class="empty">이 달에 잡힌 일정이 없습니다. 실적일과 경제지표 발표일은 다음 한 건씩만 미리 알 수 있어, 먼 달은 FOMC와 만기일만 보입니다.</p>';
    return '<section class="card" aria-label="캘린더"><div class="card-head"><h2>' + y + '년 ' + m + '월</h2>' + nav + '</div>' + filters + grid + '</section>' +
      '<section class="card" aria-label="' + m + '월 일정 목록"><h2>' + m + '월 일정 ' + inMonth.length + '건</h2>' + list +
      '<p class="src">실적일은 한국 시간, 경제지표와 FOMC는 미국 날짜 기준입니다(FOMC 결과는 한국 시간으로 다음 날 새벽). 실적일은 회사 확정 전에는 바뀔 수 있습니다. ' +
      '직접 적는 일정은 config/manual.json 의 events 에 넣습니다. 출처: Yahoo Finance, FRED, 연준' + (DATA.fomc && DATA.fomc.fetched ? ' (FOMC ' + md(DATA.fomc.fetched) + ' 확인)' : '') + '</p></section>';
  };


  // ───────── 지표 차트 (카드를 누르면 열린다) ─────────
  var HIST = null, histAt = null, chart = { id: null, range: null };
  var RANGES = [['3m', '3개월', 92], ['1y', '1년', 366], ['3y', '3년', 1096], ['all', '전체', 1e9]];
  function loadHistory() {
    if (HIST && histAt === DATA.generated_at) return Promise.resolve(HIST);
    return fetch('data/history.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (h) { HIST = h; histAt = DATA.generated_at; return h; });
  }
  function fmtV(s, v) {
    var u = s.unit || '';
    return (s.prefix || '') + fmt(v, s.decimals) + (u.length > 2 ? ' ' + u : u);
  }
  function niceStep(raw) {
    var p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }
  function openChart(id) {
    chart.id = id; chart.range = null;
    var s = DATA.series[id];
    $('chart-title').textContent = s.name;
    $('chart-sub').textContent = '불러오는 중입니다…';
    $('chart-ranges').innerHTML = ''; $('chart-plot').innerHTML = ''; $('chart-table').innerHTML = ''; $('chart-src').textContent = '';
    $('chart-dialog').showModal();
    loadHistory().then(drawChart).catch(function (err) { $('chart-sub').textContent = '차트 데이터를 불러오지 못했습니다 (' + err.message + ').'; });
  }
  function drawChart() {
    var s = DATA.series[chart.id], h = HIST[chart.id];
    if (!h || h.dates.length < 2) { $('chart-sub').textContent = '이 지표는 아직 쌓인 이력이 없습니다.'; return; }
    var t = h.dates.map(function (d) { return Date.parse(d + 'T00:00:00Z'); }), DAY = 864e5;
    var spanDays = (t[t.length - 1] - t[0]) / DAY;
    // 데이터 길이에 맞는 기간만 보여 준다. 점이 3개 미만인 기간은 뺀다
    var ranges = RANGES.slice(0, 3).filter(function (r) {
      var cut = t[t.length - 1] - r[2] * DAY;
      return r[2] <= spanDays * 1.05 && t.filter(function (v) { return v >= cut; }).length >= 3;
    });
    if (!ranges.length || spanDays > ranges[ranges.length - 1][2] * 1.05) ranges.push(RANGES[3]);
    if (!chart.range) chart.range = ranges.some(function (r) { return r[0] === '1y'; }) ? '1y' : ranges[ranges.length - 1][0];
    var days = RANGES.filter(function (r) { return r[0] === chart.range; })[0][2];
    var from = t[t.length - 1] - days * DAY, start = 0;
    while (start < t.length - 2 && t[start] < from) start++;
    var X = t.slice(start), Y = h.values.slice(start), D = h.dates.slice(start), n = X.length;
    var monthly = /월|분기/.test(s.period || '');
    function label(d, long) { return monthly ? d.slice(0, 4) + '.' + d.slice(5, 7) : long ? d : (X[n - 1] - X[0]) / DAY > 400 ? d.slice(2, 4) + '.' + d.slice(5, 7) : md(d); }

    $('chart-ranges').innerHTML = ranges.length > 1 ? ranges.map(function (r) {
      return '<button type="button" class="btn small" data-range="' + r[0] + '" aria-pressed="' + (r[0] === chart.range) + '">' + r[1] + '</button>';
    }).join('') : '';
    var first = Y[0], last = Y[n - 1], diff = last - first;
    var moved = s.change === 'diff' ? signed(diff, s.diff_decimals || 0, s.diff_unit) : signed(first ? (last / first - 1) * 100 : 0, 1, '%');
    $('chart-sub').innerHTML = '<b class="now">' + esc(fmtV(s, last)) + '</b> · ' + label(D[0], true) + ' 이후 <span class="' + dir(diff) + '">' + moved + '</span>';

    var W = 720, H = 300, L = 58, R = 18, T = 14, B = 28;
    var lo = Math.min.apply(null, Y), hi = Math.max.apply(null, Y), padv = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
    lo -= padv; hi += padv;
    var step = niceStep((hi - lo) / 5), mant = step / Math.pow(10, Math.floor(Math.log10(step)));
    var dec = Math.max(0, -Math.floor(Math.log10(step) + 1e-9)) + (Math.abs(mant - 2.5) < 1e-9 ? 1 : 0);
    function x(v) { return L + (v - X[0]) / ((X[n - 1] - X[0]) || 1) * (W - L - R); }
    function y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
    var grid = '';
    for (var g0 = Math.ceil(lo / step) * step; g0 <= hi + 1e-9; g0 += step) {
      var g = Math.abs(g0) < step / 1e6 ? 0 : g0;
      grid += '<line class="' + (g === 0 ? 'zero' : 'grid') + '" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(g).toFixed(1) + '" y2="' + y(g).toFixed(1) + '"></line>' +
        '<text class="axis" x="' + (L - 8) + '" y="' + (y(g) + 4).toFixed(1) + '" text-anchor="end">' + fmt(g, Math.min(dec, 4)) + '</text>';
    }
    var ticks = [0, 1, 2, 3].map(function (k) {
      var want = X[0] + k * (X[n - 1] - X[0]) / 3, i = 0;      // 시간 간격이 고르게 눈금을 놓는다
      for (var j = 1; j < n; j++) if (Math.abs(X[j] - want) < Math.abs(X[i] - want)) i = j;
      return '<text class="axis" x="' + x(X[i]).toFixed(1) + '" y="' + (H - 8) + '" text-anchor="' + (k === 0 ? 'start' : k === 3 ? 'end' : 'middle') + '">' + label(D[i]) + '</text>';
    }).join('');
    var pts = X.map(function (v, i) { return x(v).toFixed(1) + ',' + y(Y[i]).toFixed(1); }).join(' ');
    $('chart-plot').innerHTML = '<svg class="curve big" role="img" aria-label="' + esc(s.name) + ' 추이. 아래 표에 같은 값이 있습니다." viewBox="0 0 ' + W + ' ' + H + '">' +
      grid + ticks + '<polyline class="line" points="' + pts + '"></polyline>' +
      '<circle class="end" cx="' + x(X[n - 1]).toFixed(1) + '" cy="' + y(last).toFixed(1) + '" r="4"></circle>' +
      '<g class="hover" visibility="hidden"><line class="cross" y1="' + T + '" y2="' + (H - B) + '"></line><circle class="end" r="5"></circle></g>' +
      '<rect class="hit" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '"></rect></svg><div class="tip" hidden></div>';
    var svg = $('chart-plot').querySelector('svg'), hov = svg.querySelector('.hover'), tip = $('chart-plot').querySelector('.tip');
    function show(e) {
      var box = svg.getBoundingClientRect(), px = (e.clientX - box.left) / box.width * W;
      var tv = X[0] + (px - L) / (W - L - R) * (X[n - 1] - X[0]), i = 0;
      for (var k = 1; k < n; k++) if (Math.abs(X[k] - tv) < Math.abs(X[i] - tv)) i = k;
      hov.setAttribute('visibility', 'visible');
      hov.querySelector('line').setAttribute('x1', x(X[i])); hov.querySelector('line').setAttribute('x2', x(X[i]));
      hov.querySelector('circle').setAttribute('cx', x(X[i])); hov.querySelector('circle').setAttribute('cy', y(Y[i]));
      tip.hidden = false; tip.innerHTML = '<span>' + label(D[i], true) + '</span><b>' + esc(fmtV(s, Y[i])) + '</b>';
      var left = x(X[i]) / W * box.width, tw = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(box.width - tw, left + (left > box.width / 2 ? -tw - 10 : 10))) + 'px';
      tip.style.top = Math.max(0, y(Y[i]) / H * box.height - 44) + 'px';
    }
    function hide() { hov.setAttribute('visibility', 'hidden'); tip.hidden = true; }
    svg.addEventListener('pointermove', show); svg.addEventListener('pointerdown', show); svg.addEventListener('pointerleave', hide);

    var recent = D.map(function (d, i) { return [d, Y[i]]; }).slice(-12).reverse();
    $('chart-table').innerHTML = '<div class="ctable"><div class="ctr c2 th"><span>날짜</span><span>값</span></div>' + recent.map(function (r) {
      return '<div class="ctr c2"><span>' + label(r[0], true) + '</span><span>' + esc(fmtV(s, r[1])) + '</span></div>';
    }).join('') + '</div>';
    $('chart-src').textContent = '출처: ' + (s.source || '') + ' · 최근 1년은 발표된 값 그대로, 그 이전은 주 단위로 줄여 그립니다. 선 위에 마우스를 올리거나 손가락으로 누르면 그 날의 값이 나옵니다.';
  }
  function openHelp(key) {
    var g = DATA.glossary[key];
    $('help-title').textContent = g.title;
    $('help-text').textContent = g.text;
    $('help-link').href = DATA.site.notion_glossary || '#';
    $('help-link').hidden = !DATA.site.notion_glossary;
    $('help-dialog').showModal();
  }
  $('help-dialog').addEventListener('click', function (e) {
    if (e.target === this || e.target.closest('[data-close]')) this.close();
  });
  $('chart-dialog').addEventListener('click', function (e) {
    var r = e.target.closest('[data-range]');
    if (r) { chart.range = r.dataset.range; drawChart(); return; }
    if (e.target === this || e.target.closest('[data-close]')) this.close();
  });

  // ───────── 화면 조립 ─────────
  function renderTabs() {
    $('tabs').innerHTML = DATA.tabs.map(function (t) {
      return '<button type="button" class="tab" role="tab" data-tab="' + esc(t.id) + '" aria-selected="' + (t.id === state.tab) + '">' + esc(t.label) + '</button>';
    }).join('');
  }
  function renderView() {
    var tab = DATA.tabs.filter(function (t) { return t.id === state.tab; })[0] || DATA.tabs[0];
    state.tab = tab.id;
    if (renderView.last !== state.tab + '/' + state.stock) { renderView.last = state.tab + '/' + state.stock; window.scrollTo(0, 0); }
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
    if ($('tv')) loadTradingView($('tv'));   // 종목 요약을 열면 차트를 바로 불러온다
    loadFin();
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
    $('foot').innerHTML = esc(DATA.site.disclaimer) + '<br>출처: Yahoo Finance(주가·환율·지수·원자재·재무), FRED(금리·스프레드·경제지표), 연준(FOMC 일정), CFTC(선물 포지션), SEC(공시·내부자 매매·13F). 무료 데이터는 개인 용도로만 씁니다.';
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
    if ($('tv')) loadTradingView($('tv'));
  });
  $('btn-color').addEventListener('click', function () {
    root.dataset.color = root.dataset.color === 'us' ? 'kr' : 'us';
    store.set('colorStyle', root.dataset.color); renderButtons();
  });
  $('tabs').addEventListener('click', function (e) {
    var b = e.target.closest('[data-tab]');
    if (!b || !DATA) return;
    location.hash = b.dataset.tab;
  });
  window.addEventListener('hashchange', function () { route(); if (DATA) { renderTabs(); renderView(); } });
  $('view').addEventListener('click', function (e) {
    if (!DATA) return;
    var b = e.target.closest('[data-market]');
    if (b) { state.market = b.dataset.market; store.set('market', state.market); renderView(); return; }
    var hp = e.target.closest('[data-help]');
    if (hp) { openHelp(hp.dataset.help); return; }
    var ch = e.target.closest('[data-chart]');
    if (ch) { openChart(ch.dataset.chart); return; }
    var fv = e.target.closest('[data-fin]');
    if (fv) { state.finView = fv.dataset.fin; var key = $('fin').dataset.t + DATA.generated_at; if (AIF[key]) { $('fin').innerHTML = finBody(AIF[key]); finScroll(); } return; }
    var cp = e.target.closest('[data-copy]');
    if (cp) {
      var done = function () { cp.textContent = '복사했습니다'; setTimeout(function () { cp.textContent = '주소 복사'; }, 2000); };
      if (navigator.clipboard) navigator.clipboard.writeText(cp.dataset.copy).then(done, function () { window.prompt('주소를 복사하세요', cp.dataset.copy); });
      else window.prompt('주소를 복사하세요', cp.dataset.copy);
      return;
    }
    var ht = e.target.closest('[data-heat]');
    if (ht) { state.heat = ht.dataset.heat; renderView(); return; }
    var mo = e.target.closest('[data-month]'), ki = e.target.closest('[data-kind]');
    if (mo) { state.month = mo.dataset.month; renderView(); return; }
    if (ki) { state.kinds[ki.dataset.kind] = !state.kinds[ki.dataset.kind]; renderView(); return; }
    var a = e.target.closest('[data-act]');
    if (!a) return;
    var act = a.dataset.act, t = a.dataset.t;
    if (act === 'edit') state.edit = !state.edit;
    else if (act === 'fav') { toggle(prefs.fav, t); savePrefs(); }
    else if (act === 'hide') { toggle(prefs.hidden, t); savePrefs(); }
    else if (act === 'up' || act === 'down') move(a.dataset.m, t, act === 'up' ? -1 : 1);
    renderView();
  });
  $('view').addEventListener('submit', function (e) {
    var form = e.target.closest('[data-add]');
    if (!form || !DATA) return;
    e.preventDefault();
    var ticker = form.ticker.value.trim().toUpperCase();
    if (ticker) window.open(issueUrl('추가', ticker, form.name.value.trim()), '_blank', 'noopener');
  });
  $('view').addEventListener('change', function (e) {
    if (!e.target.matches('[data-compare]') || !DATA) return;
    state.compare = e.target.value;
    $('strength').innerHTML = strengthChart(DATA.stocks[state.stock]);   // 이 묶음만 다시 그린다
  });

  function load() {
    return fetch('data/dashboard.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        var first = !DATA; DATA = d;
        if (first || !(state.edit || document.querySelector('.tv-on'))) render(); else renderChrome();
      })
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
