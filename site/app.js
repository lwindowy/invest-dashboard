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
      var list = ordered(state.market);
      var rows = list.map(function (s) {
        var name = '<div class="stock-name"><a href="#stocks/' + encodeURIComponent(s.ticker) + '"><b>' + (has(prefs.fav, s.ticker) ? '★ ' : '') + esc(s.name) + '</b></a><span>' + esc(s.ticker.replace('.KS', '')) + (s.stale ? ' · 이전 값' : '') + '</span></div>';
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
        '<p class="src">종목 이름을 누르면 종목 한 장 요약으로 이동합니다. RSI 70 이상은 과매수, 30 이하는 과매도로 표시합니다. 출처: Yahoo Finance · ' + md(asof) + ' 기준 · 주가는 15분가량 지연됩니다.</p></section>';
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
    return '<div class="fact"><span class="k">' + esc(label) + '</span><b>' + val + '</b>' + (sub ? '<span class="s">' + sub + '</span>' : '') + '</div>';
  }
  function box(title, body, src) {
    return '<section class="card" aria-label="' + esc(title) + '"><h2>' + esc(title) + '</h2>' + body + (src ? '<p class="src">' + src + '</p>' : '') + '</section>';
  }
  function rangeBar(lo, hi, at, cur, label) {
    if (lo == null || hi == null || at == null || hi <= lo) return '';
    var pct = Math.max(0, Math.min(100, (at - lo) / (hi - lo) * 100));
    return '<div class="range"><div class="track"><span class="mark" style="left:' + pct.toFixed(1) + '%"></span></div>' +
      '<div class="ends"><span>' + price(lo, cur) + '</span><span>' + esc(label) + ' ' + price(at, cur) + '</span><span>' + price(hi, cur) + '</span></div></div>';
  }
  function barChart(quarters, key, cur, title, isMoney) {
    var q = quarters.filter(function (x) { return x[key] != null; });
    if (!q.length) return '<div class="mini"><h3>' + esc(title) + '</h3><p class="empty">데이터 없음</p></div>';
    var W = 300, H = 150, T = 20, B = 38, bw = Math.min(44, (W - 20) / q.length - 10);
    var vals = q.map(function (x) { return x[key]; });
    var hi = Math.max(0, Math.max.apply(null, vals)), lo = Math.min(0, Math.min.apply(null, vals)), span = (hi - lo) || 1;
    function y(v) { return T + (hi - v) / span * (H - T - B); }
    var bars = q.map(function (x, i) {
      var cx = (i + 0.5) * W / q.length, v = x[key], top = Math.min(y(v), y(0)), h = Math.max(1, Math.abs(y(v) - y(0)));
      var text = isMoney ? money(v, cur, true) : (v < 0 ? '−' : '') + fmt(Math.abs(v), cur === 'KRW' ? 0 : 2);
      return '<rect class="' + (v < 0 ? 'neg' : 'pos') + '" x="' + (cx - bw / 2).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="2"></rect>' +
        '<text class="val" x="' + cx.toFixed(1) + '" y="' + (v < 0 ? top + h + 12 : top - 5).toFixed(1) + '" text-anchor="middle">' + text + '</text>' +
        '<text class="axis" x="' + cx.toFixed(1) + '" y="' + (H - 2) + '" text-anchor="middle">' + esc(x.period) + '</text>';
    }).join('');
    return '<div class="mini"><h3>' + esc(title) + '</h3><svg class="bars" role="img" aria-label="' + esc(title) + ' 분기별 막대 그래프" viewBox="0 0 ' + W + ' ' + H + '">' +
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
    var t = s.ticker, code = t.replace('.KS', ''), f = s.fund || {}, L = [];
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
    if (s.links && s.links.notion) L.push(['노션 기업분석 노트', s.links.notion]);
    return '<div class="links">' + L.map(function (l) { return '<a class="btn link" href="' + esc(l[1]) + '" target="_blank" rel="noopener">' + esc(l[0]) + '</a>'; }).join('') + '</div>';
  }
  function stockDetail(s) {
    var f = s.fund || {}, cur = s.currency, fc = f.currency || cur, d = dir(s.change_pct), e = f.earnings || {}, tg = f.target || {}, sh = f.short || {};
    var none = '<p class="empty">재무 데이터를 받지 못했습니다.</p>';
    var fsrc = s.fund ? esc(f.source) + ' · ' + md(f.fetched) + ' 수집' + (f.stale ? ' · 수집 실패로 이전 값' : '') : '';
    var head = '<section class="card stock-head"><a class="back" href="#stocks">← 종목 목록</a>' +
      '<div class="card-head"><div><h2 class="big">' + esc(s.name) + '</h2><p class="sub">' + esc(s.ticker.replace('.KS', '')) + (f.long_name ? ' · ' + esc(f.long_name) : '') + (f.industry ? ' · ' + esc(f.industry) : '') + '</p></div>' +
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

    var charts = box('나스닥 대비 상대 강도와 종목 비교', strengthChart(s), '시작일을 100으로 맞춘 값입니다. 비교 종목을 고르면 선이 하나 더 그려집니다.') +
      box('트레이딩뷰 차트', '<div id="tv" data-symbol="' + esc(s.market === 'kr' ? 'KRX:' + s.ticker.replace('.KS', '') : s.ticker) + '"><button type="button" class="btn" data-tv>트레이딩뷰 차트 불러오기</button></div>',
        '트레이딩뷰 무료 위젯입니다. 한국 종목은 무료 위젯에서 표시되지 않을 수 있습니다.');

    return head + '<div class="grid2">' + priceBox + tech + '</div>' + check + charts +
      '<div class="grid2">' + base + val + '</div>' + trend + '<div class="grid2">' + earn + analyst + '</div>' + shortBox;
  }
  function stockList() {
    var html = '';
    [['us', '미국'], ['kr', '한국']].forEach(function (m) {
      var list = ordered(m[0], state.edit);
      var rows = list.map(function (s, i) {
        var hid = has(prefs.hidden, s.ticker), fav = has(prefs.fav, s.ticker), t = esc(s.ticker);
        var name = '<div class="stock-name"><a href="#stocks/' + encodeURIComponent(s.ticker) + '"><b>' + (fav ? '★ ' : '') + esc(s.name) + '</b></a><span>' + esc(s.ticker.replace('.KS', '')) + (hid ? ' · 숨김' : '') + '</span></div>';
        if (state.edit) {
          return '<div class="tr edit' + (hid ? ' dim' : '') + '">' + name + '<div class="tools">' +
            '<button type="button" class="btn" data-act="fav" data-t="' + t + '" aria-pressed="' + fav + '">★ 즐겨찾기</button>' +
            '<button type="button" class="btn" data-act="up" data-m="' + m[0] + '" data-t="' + t + '" aria-label="' + esc(s.name) + ' 위로"' + (i === 0 ? ' disabled' : '') + '>↑</button>' +
            '<button type="button" class="btn" data-act="down" data-m="' + m[0] + '" data-t="' + t + '" aria-label="' + esc(s.name) + ' 아래로"' + (i === list.length - 1 ? ' disabled' : '') + '>↓</button>' +
            '<button type="button" class="btn" data-act="hide" data-t="' + t + '" aria-pressed="' + hid + '">' + (hid ? '다시 보이기' : '숨기기') + '</button></div></div>';
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
        '<div class="scroll-x"><div class="table">' + (state.edit ? '' : '<div class="tr th"><span>종목</span><span>현재가</span><span>등락률</span><span>RSI(14)</span><span>52주 고점 대비</span><span>시가총액</span></div>') +
        (rows || '<p class="empty">표시할 종목이 없습니다. 목록 편집에서 숨긴 종목을 다시 보이게 할 수 있습니다.</p>') + '</div></div></section>';
    });
    return html + '<p class="src">종목 이름을 누르면 종목 한 장 요약이 열립니다. 숨기기·순서·즐겨찾기는 이 브라우저에만 저장됩니다. 종목 추가와 삭제는 config/dashboard.json 에서 합니다.</p>';
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
    $('foot').innerHTML = esc(DATA.site.disclaimer) + '<br>출처: Yahoo Finance(주가·환율·지수·원자재·재무), FRED(금리·스프레드·경제지표), 연준(FOMC 일정). 무료 데이터는 개인 용도로만 씁니다.';
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
    location.hash = b.dataset.tab;
  });
  window.addEventListener('hashchange', function () { route(); if (DATA) { renderTabs(); renderView(); } });
  $('view').addEventListener('click', function (e) {
    if (!DATA) return;
    var b = e.target.closest('[data-market]');
    if (b) { state.market = b.dataset.market; store.set('market', state.market); renderView(); return; }
    if (e.target.closest('[data-tv]')) { loadTradingView($('tv')); return; }
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
  $('view').addEventListener('change', function (e) {
    if (!e.target.matches('[data-compare]') || !DATA) return;
    state.compare = e.target.value; renderView();
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
