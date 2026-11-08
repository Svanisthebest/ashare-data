# -*- coding: utf-8 -*-
"""
A股短线开单助手（核心程序）。由 launcher.py 启动时从仓库下载最新版本运行，规则和每日计划也从仓库读取，
所以模型升级（改 v1_plan.py → data/helper/rules.json）后，各台电脑重启助手就自动同步。

功能：
  - 9:25 抓全市场竞价价，算全A竞价红盘率 → 竞价开关 → 按排队顺序、仓位、入场条件生成开单单（股数、挂单价）
  - 盘中盯高标被砸挂单是否可能成交
  - 14:47 起逐只检查持仓：涨停拿、不涨停尾盘卖、止损、多拿、推迟一天
  - 本地记录持仓（买入价、股数、多拿 / 推迟状态），数据只存在本机
只用 Python 标准库。仅供参考，不构成投资建议；下单以券商软件为准。
"""
import csv, io, json, math, os, sys, threading, time, traceback, webbrowser
import datetime as dt
import urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CORE_VERSION = 3
REPO = 'Svanisthebest/ashare-data'
MIRRORS = ['https://raw.githubusercontent.com/{repo}/main/{path}',
           'https://ghfast.top/https://raw.githubusercontent.com/{repo}/main/{path}',
           'https://cdn.jsdelivr.net/gh/{repo}@main/{path}']
HOME = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'ashare_helper')
os.makedirs(HOME, exist_ok=True)
STATE_F = os.path.join(HOME, 'state.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Referer': 'https://quote.eastmoney.com/'}
MOCK = os.environ.get('ASH_MOCK')            # 测试用：本地仓库路径;YYYYMMDD（用当天日线模拟行情）
LOCK = threading.RLock()


def bj_now():
    if os.environ.get('ASH_NOW'): return dt.datetime.strptime(os.environ['ASH_NOW'], '%Y%m%d %H:%M')
    return dt.datetime.utcnow() + dt.timedelta(hours=8)


def log(msg):
    with LOCK:
        S['log'] = (S.get('log', []) + [f'{bj_now():%m-%d %H:%M:%S} {msg}'])[-200:]
    print(msg, flush=True)


# ------------------------------------------------------------------ 本地状态
def load_state():
    try: return json.load(open(STATE_F, encoding='utf-8'))
    except Exception: return {}


def save_state():
    with LOCK:
        keep = {k: S.get(k) for k in ['equity', 'holdings', 'history', 'mirror', 'orders', 'sells', 'manual_red', 'orders_date', 'sells_date']}
        tmp = STATE_F + '.tmp'; json.dump(keep, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1); os.replace(tmp, STATE_F)


S = load_state()
S.setdefault('equity', 0.0); S.setdefault('holdings', []); S.setdefault('history', []); S.setdefault('log', [])


# ------------------------------------------------------------------ 网络
def http_get(url, params=None, timeout=10, enc=None, tries=3):
    if params: url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    last = None
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            b = urllib.request.urlopen(req, timeout=timeout).read()
            return b.decode(enc or 'utf-8', errors='replace')
        except Exception as e:
            last = e; time.sleep(0.5 + t)
    raise last


def repo_get(path):
    if MOCK: return open(os.path.join(MOCK.split(';')[0], path), encoding='utf-8-sig').read()
    urls = ([S['mirror'].rstrip('/') + '/' + path] if S.get('mirror') else []) + [m.format(repo=REPO, path=path) for m in MIRRORS]
    err = []
    for u in urls:
        try: return http_get(u + ('' if 'jsdelivr' in u else f'?t={int(time.time())}'), timeout=15, tries=1)
        except Exception as e: err.append(f'{u[:40]}… {e}')
    raise RuntimeError('仓库读取失败：' + '；'.join(err))


def market(code): return '1' if code.startswith(('6', '9')) else '0'


def lim_of(code, name=''):
    if 'ST' in name: return 0.05
    return 0.2 if code.startswith(('30', '68')) else 0.1


def limit_price(pc, lim, up=True): return math.floor(pc * (1 + (lim if up else -lim)) * 100 + 0.5) / 100


def _mock_rows():
    root, d = MOCK.split(';'); import gzip
    f = os.path.join(root, 'data', 'daily', f'{d}.csv.gz'); rows = {}
    for r in csv.DictReader(io.StringIO(gzip.open(f).read().decode('utf-8-sig'))):
        try: rows[r['code']] = dict(code=r['code'], name=r['name'], open=float(r['open']), pc=float(r['prev_close']), price=float(r['close']), high=float(r['high']), low=float(r['low']), amount=float(r.get('amount') or 0))
        except Exception: pass
    return rows


def quotes_all():
    """东方财富全市场（沪深京 A 股）今开 / 昨收 / 现价 / 最高 / 最低。返回 {code: {...}}"""
    if MOCK: return _mock_rows()
    rows = {}; hosts = ['push2', '82.push2', '72.push2', '7.push2', '28.push2']
    for pn in range(1, 80):
        p = dict(pn=pn, pz=100, po=1, np=1, fltt=2, invt=2, fid='f12', fs='m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
                 fields='f12,f14,f17,f18,f2,f15,f16,f6', ut='bd1d9ddb04089700cf9c27f6f7426281')
        j = None
        for t in range(4):
            try:
                j = json.loads(http_get(f'https://{hosts[(pn + t) % len(hosts)]}.eastmoney.com/api/qt/clist/get', p, tries=1)); break
            except Exception: time.sleep(1 + t)
        d = (j or {}).get('data') or {}; diff = d.get('diff') or []
        if isinstance(diff, dict): diff = list(diff.values())
        if not diff: break
        for x in diff:
            try:
                rows[str(x['f12'])] = dict(code=str(x['f12']), name=x.get('f14', ''), open=float(x['f17']) if x['f17'] not in ('-', None) else 0.0,
                                           pc=float(x['f18']) if x['f18'] not in ('-', None) else 0.0, price=float(x['f2']) if x['f2'] not in ('-', None) else 0.0,
                                           high=float(x['f15']) if x['f15'] not in ('-', None) else 0.0, low=float(x['f16']) if x['f16'] not in ('-', None) else 0.0,
                                           amount=float(x['f6']) if x.get('f6') not in ('-', None) else 0.0)
            except Exception: pass
        if len(rows) >= d.get('total', 0): break
        time.sleep(0.2)
    return rows


def quotes_some(codes):
    """腾讯行情：指定股票 + 中证1000（sh000852）。返回 {code: {...}}，并含 'ZZ1000'"""
    if MOCK:
        allr = _mock_rows(); out = {c: allr[c] for c in codes if c in allr}
        out['ZZ1000'] = dict(code='000852', name='中证1000', open=0, pc=1.0, price=1.0 + float(os.environ.get('ASH_ZZ', '0')), high=0, low=0, date=MOCK.split(';')[1])
        return out
    sym = [('sh' if market(c) == '1' else 'sz') + c for c in codes] + ['sh000852']; out = {}
    for i in range(0, len(sym), 60):
        txt = http_get('https://qt.gtimg.cn/q=' + ','.join(sym[i:i + 60]), enc='gbk')
        for line in txt.strip().split(';'):
            if '="' not in line: continue
            k, v = line.split('="', 1); f = v.strip('"\n').split('~')
            if len(f) < 35: continue
            c = k[-6:]; key = 'ZZ1000' if k.endswith('sh000852') else c
            try: out[key] = dict(code=c, name=f[1], price=float(f[3]), pc=float(f[4]), open=float(f[5]), high=float(f[33]), low=float(f[34]), date=f[30][:8])
            except Exception: pass
    return out


# ------------------------------------------------------------------ 计划与规则
def refresh_plan():
    try:
        latest = json.loads(repo_get('data/helper/latest.json'))
        rules = json.loads(repo_get(latest['rules']))
        txt = repo_get(latest['csv'])
        cand = [r for r in csv.DictReader(io.StringIO(txt.lstrip('﻿')))]
        md = repo_get(latest['md'])
        with LOCK:
            S['latest'] = latest; S['rules'] = rules; S['cand'] = cand; S['md'] = md; S['plan_err'] = None
            S['plan_loaded'] = f'{bj_now():%H:%M:%S}'
        if rules.get('min_core', 1) > CORE_VERSION: log('规则需要更新版本的助手：请重启助手（会自动下载新版）')
        log(f"已读取计划 {latest['plan_date']}（规则 {rules.get('version')}，候选 {len(cand)} 只）")
    except Exception as e:
        with LOCK: S['plan_err'] = str(e)
        log(f'读取计划失败：{e}')


def plan_status():
    """计划是给哪一天用的。"""
    lt = S.get('latest') or {}; pd_ = lt.get('plan_date'); now = bj_now(); today = now.strftime('%Y%m%d')
    if not pd_: return '未读取计划'
    if pd_ == today: return f'这是今天（{pd_}）收盘生成的，供下一交易日使用'
    gap = (now.date() - dt.datetime.strptime(pd_, '%Y%m%d').date()).days
    if now.weekday() >= 5: return f'今天是周末；计划 {pd_} 供下一交易日使用'
    if gap > 4: return f'⚠ 计划日期 {pd_} 已过期（{gap} 天前），可能数据没更新'
    return f'计划 {pd_} 收盘生成，供今天使用'


def held_days(entry, today):
    """买入当天算第 1 天，按工作日数（节假日未扣，可能偏多 1–2 天）。"""
    a = dt.datetime.strptime(entry, '%Y%m%d').date(); b = dt.datetime.strptime(today, '%Y%m%d').date(); n = 0
    while a <= b:
        if a.weekday() < 5: n += 1
        a += dt.timedelta(days=1)
    return n


# ------------------------------------------------------------------ 9:25 开单
def build_orders(red_override=None):
    R = S.get('rules'); cand = S.get('cand') or []
    if not R: raise RuntimeError('还没读到规则 / 计划')
    today = bj_now().strftime('%Y%m%d')
    allq = {} if red_override is not None else quotes_all()
    red = red_override
    if red is None:
        univ = [q for q in allq.values() if not q['code'].startswith(('4', '8', '92')) and 'ST' not in q['name'] and '退' not in q['name'] and q['open'] > 0 and q['pc'] > 0]
        if len(univ) < 3000: raise RuntimeError(f'全市场行情只有 {len(univ)} 只，算不了红盘率；可以在页面上手动填写红盘率')
        red = sum(q['open'] > q['pc'] for q in univ) / len(univ)
    some = quotes_some(list({c['代码'] for c in cand} | {h['code'] for h in S['holdings']}))
    for c, q in some.items(): allq.setdefault(c, q)
    g = R['gate']
    allowed = set(g['allowed_high']) if red > g['high'] else set(g['allowed_mid']) if red >= g['low'] else set(g['allowed_low'])
    gate_txt = f"> {g['high']:.0%}" if red > g['high'] else (f"{g['low']:.0%}–{g['high']:.0%}" if red >= g['low'] else f"< {g['low']:.0%}")
    equity = float(S.get('equity') or 0)
    hold = [h for h in S['holdings']]
    hv = 0.0
    for h in hold:
        q = allq.get(h['code']); hv += h['shares'] * (q['pc'] if q and q.get('pc') else h['buy_price'])
    cash = max(equity - hv, 0.0)
    npos = len(hold); held = {h['code'] for h in hold}; per = {}
    for h in hold: per[h['src']] = per.get(h['src'], 0) + 1
    out = []
    for s in R['order']:
        for c in [x for x in cand if x['src'] == s]:
            code = c['代码']; nm = c['名称']; q = allq.get(code)
            row = dict(src=s, route=R['names'].get(s, s), code=code, name=nm, note=c.get('说明', ''), action='不买', why='', price=None, limit=None, shares=0, amount=0)
            out.append(row)
            if s not in allowed: row['why'] = f'竞价 {gate_txt} 时这条路线不做'; continue
            if npos >= R['max_positions']: row['why'] = '已满 5 只'; continue
            if s in R['cap'] and per.get(s, 0) >= R['cap'][s]: row['why'] = f"本路线已满 {R['cap'][s]} 只"; continue
            if code in held: row['why'] = '已持有 / 已在前面买'; continue
            if not q or not q.get('open'): row['why'] = '没有竞价价（停牌？）'; continue
            o, pc = q['open'], q['pc']; gap = o / pc - 1; lim = lim_of(code, nm); up = limit_price(pc, lim)
            row['price'] = o; row['gap'] = round(gap * 100, 2)
            if o >= up - 0.005: row['why'] = '竞价在涨停价，买不到'; continue
            e = R['entry'].get(s, {'type': 'open'})
            if 'max_gap' in e and not gap < e['max_gap']: row['why'] = f"竞价 {gap:+.1%}，要低于 {e['max_gap']:+.0%}"; continue
            if 'min_gap' in e and not gap >= e['min_gap']: row['why'] = f"竞价 {gap:+.1%}，低于 {e['min_gap']:+.0%} 不买"; continue
            val = min(R['size'].get(s, 20) / 100 * equity, cash)
            if equity <= 0: row['why'] = '先在页面上填写账户总资产'; continue
            if val <= 0.01 * equity: row['why'] = '可用资金不足'; continue
            if e['type'] == 'limit_from_open':
                lp = math.floor(o * e['limit_mult'] * 100) / 100; row['limit'] = lp; px = lp
                row['action'] = '挂单'; row['why'] = f'开盘后挂 {lp:.2f}（开盘价 ×{e["limit_mult"]}），收盘前没成交就撤单'
            else:
                # 挂单价：竞价价 +0.5%（至少 +1 分钱），不超过路线的入场上限（2板龙头 < 昨收+2%，低开路线 < 昨收）和涨停价
                cap = up
                if 'max_gap' in e: cap = min(cap, math.ceil(pc * (1 + e['max_gap']) * 100) / 100 - 0.01)
                px = min(max(math.floor(o * 1.005 * 100) / 100, round(o + 0.01, 2)), cap)
                give = min(math.floor(o * 1.01 * 100) / 100, cap)     # 最高追价：竞价价 +1%
                row['limit'] = px; row['give'] = give
                row['action'] = '买入'
                row['why'] = f'9:25–9:30 挂 {px:.2f}（竞价价 {o:.2f} +0.5%）；9:30 没成交可改到 {give:.2f}，再高就不买'
            lot = 200 if code.startswith('68') else 100
            sh = int(val / px // 100 * 100)
            if sh < lot: row['action'] = '不买'; row['why'] = f'资金不够买 {lot} 股'; continue
            row['shares'] = sh; row['amount'] = round(sh * px, 2)
            try:
                amt_yi = float(c.get('成交额亿') or 0)
                if amt_yi > 0 and sh * px > 0.04 * amt_yi * 1e8: row['why'] += f'；⚠ 超过该股昨日成交额 4%（{amt_yi} 亿），分批买'
            except Exception: pass
            cash -= sh * px; npos += 1; held.add(code); per[s] = per.get(s, 0) + 1
    with LOCK:
        S['orders'] = dict(time=f'{bj_now():%H:%M:%S}', date=today, red=round(red, 4), gate=gate_txt, red_src='手动' if red_override is not None else '全市场竞价',
                           allowed=[R['names'][x] for x in R['order'] if x in allowed], equity=equity, cash_left=round(cash, 2), rows=out)
        S['orders_date'] = today
    save_state(); log(f'开单单已生成：红盘率 {red:.1%}（{gate_txt}），买入 {sum(r["action"] != "不买" for r in out)} 只')


# ------------------------------------------------------------------ 14:47 卖出检查
def build_sells():
    R = S.get('rules') or {}; sl = R.get('sell', {}); names = R.get('names', {})
    today = bj_now().strftime('%Y%m%d'); hold = S['holdings']
    if not hold:
        with LOCK: S['sells'] = dict(time=f'{bj_now():%H:%M:%S}', date=today, rows=[]); S['sells_date'] = today
        return
    q = quotes_some([h['code'] for h in hold]); z = q.get('ZZ1000'); zr = (z['price'] / z['pc'] - 1) if z and z.get('pc') else 0.0
    rows = []
    for h in hold:
        x = q.get(h['code']); s = h['src']; r = dict(code=h['code'], name=h['name'], route=names.get(s, s), buy=h['buy_price'], shares=h['shares'])
        rows.append(r)
        if h['entry'] == today: r.update(action='持有', why='今天买入，T+1 不能卖'); continue
        if not x or not x.get('price'): r.update(action='?', why='没取到行情（停牌？）'); continue
        p, pc = x['price'], x['pc']; lim = lim_of(h['code'], h['name']); up = limit_price(pc, lim); dn = limit_price(pc, lim, False)
        ret = p / pc - 1; pnl = p / h['buy_price'] - 1; n = held_days(h['entry'], today)
        r.update(price=p, ret=round(ret * 100, 2), pnl=round(pnl * 100, 2), days=n)
        if p <= dn + 0.005 and x.get('high') == x.get('low'): r.update(action='卖不出', why='跌停封死，明天开盘卖'); continue
        zt = p >= up - 0.005
        if s == 'B':
            peak = max(h.get('peak', h['buy_price']), p)
            if pnl < -sl.get('stop_B', 0.15): r.update(action='卖出', why=f'亏 {pnl:.1%}，超过 {sl.get("stop_B", .15):.0%} 止损')
            elif p < peak * (1 - sl.get('B_trail', 0.1)): r.update(action='卖出', why=f'从高点 {peak:.2f} 回撤超过 10%')
            elif n >= sl.get('B_max_days', 20): r.update(action='卖出', why=f'已拿 {n} 天')
            else: r.update(action='持有', why=f'恐慌低吸：高点 {peak:.2f}，跌破 {peak * 0.9:.2f} 再卖', set=dict(peak=peak))
            continue
        if pnl < -sl.get('stop', 0.08): r.update(action='卖出', why=f'亏 {pnl:.1%}，超过 8% 止损'); continue
        if zt: act, why, st = '持有', '涨停，继续拿', {}
        elif s == 'LD' and ret >= sl.get('LD_extra_ratio', 0.7) * lim and h.get('extra', 0) < sl.get('LD_extra_max', 3):
            act, why, st = '持有', f'总龙头首阴涨 {ret:.1%}（≥ 涨停幅 70%），多拿一天（第 {h.get("extra", 0) + 1} 次）', dict(extra=h.get('extra', 0) + 1)
        elif p < h['buy_price'] and zr <= sl.get('delay_index_drop', -0.01) and not h.get('delayed'):
            act, why, st = '推迟', f'亏损且中证1000 {zr:+.2%}（≤ −1%），推迟到明天尾盘卖（只推迟一次）', dict(delayed=1)
        else: act, why, st = '卖出', '没涨停，尾盘卖', {}
        if act != '卖出' and n >= sl.get('max_days', 11): act, why, st = '卖出', f'已拿 {n} 天，到期', {}
        r.update(action=act, why=why, set=st)
    with LOCK:
        S['sells'] = dict(time=f'{bj_now():%H:%M:%S}', date=today, zz1000=round(zr * 100, 2), rows=rows); S['sells_date'] = today
    save_state(); log(f'卖出检查：{sum(r.get("action") == "卖出" for r in rows)} 只要卖，中证1000 {zr:+.2%}')


def watch_breaks():
    """v1.4：10:30 以后，持仓（今天以前买的、非恐慌低吸）盘中冲到涨停又打开 → 提醒立即卖出。"""
    R = S.get('rules') or {}; sl = R.get('sell', {}); today = bj_now().strftime('%Y%m%d')
    hold = [h for h in S['holdings'] if h['entry'] != today and h['src'] not in sl.get('break_exempt', ['B'])]
    if not hold: return
    q = quotes_some([h['code'] for h in hold]); names = R.get('names', {})
    al = [a for a in S.get('breaks', []) if a['date'] == today]; seen = {a['code'] for a in al}
    # 与回测一致：按 5 分钟 K 线收盘判断——只在每个 5 分钟整点（如 10:35、10:40）看一次价格，盘中一闪而过又回封的不算
    now = bj_now(); slot = now.strftime('%H') + f'{now.minute // 5 * 5:02d}'
    if S.get('break_slot') == slot: return
    S['break_slot'] = slot
    for h in hold:
        x = q.get(h['code'])
        if not x or not x.get('pc'): continue
        up = limit_price(x['pc'], lim_of(h['code'], h['name']))
        if x['high'] >= up - 0.005 and x['price'] < up - 0.005 and h['code'] not in seen:
            al.append(dict(date=today, time=f'{bj_now():%H:%M:%S}', code=h['code'], name=h['name'], route=names.get(h['src'], h['src']),
                           price=x['price'], up=up, buy=h['buy_price'], pnl=round((x['price'] / h['buy_price'] - 1) * 100, 2)))
            log(f"炸板提醒：{h['name']}（{h['code']}）冲到涨停 {up:.2f} 后打开，现价 {x['price']:.2f}，按规则立即卖出")
    with LOCK: S['breaks'] = al


def pending_k():
    """盘中：高标被砸挂单是否可能已成交（最低价 ≤ 挂单价）。"""
    o = S.get('orders') or {}
    ks = [r for r in o.get('rows', []) if r.get('action') == '挂单' and not r.get('done')]
    if not ks: return []
    q = quotes_some([r['code'] for r in ks]); out = []
    for r in ks:
        x = q.get(r['code'])
        if x: out.append(dict(code=r['code'], name=r['name'], limit=r['limit'], low=x['low'], price=x['price'], hit=x['low'] <= r['limit']))
    return out


# ------------------------------------------------------------------ 自动任务
def scheduler():
    last_plan = 0
    while True:
        try:
            now = bj_now(); today = now.strftime('%Y%m%d'); hm = now.strftime('%H%M'); wk = now.weekday() < 5
            if time.time() - last_plan > (600 if '0900' <= hm <= '0930' else 3600): refresh_plan(); last_plan = time.time()
            if wk and '0925' <= hm < '0931' and S.get('orders_date') != today and (hm >= '0926' or now.second >= 15):
                try: build_orders()
                except Exception as e: log(f'自动生成开单单失败：{e}（可在页面手动填写红盘率后生成）'); S['orders_date'] = today + '_fail'
            if wk and '1447' <= hm < '1456' and S.get('sells_date') != today:
                try: build_sells()
                except Exception as e: log(f'卖出检查失败：{e}'); S['sells_date'] = today + '_fail'
            if wk and '0930' <= hm <= '1500':
                try:
                    with LOCK: S['k_watch'] = pending_k()
                except Exception: pass
            ba = ((S.get('rules') or {}).get('sell', {}).get('break_after') or '').replace(':', '')
            if wk and ba and ba <= hm < '1457':
                try: watch_breaks()
                except Exception as e: log(f'炸板检查出错：{e}')
        except Exception: log('调度出错：' + traceback.format_exc()[-300:])
        time.sleep(15)


# ------------------------------------------------------------------ 网页
def api_state():
    today = bj_now().strftime('%Y%m%d')
    with LOCK:
        R = S.get('rules') or {}; o = S.get('orders') or {}; x = S.get('sells') or {}
        return dict(core=CORE_VERSION, now=f'{bj_now():%Y-%m-%d %H:%M:%S}', rules_version=R.get('version'), plan=S.get('latest'), plan_status=plan_status(),
                    plan_err=S.get('plan_err'), plan_loaded=S.get('plan_loaded'), cand=S.get('cand') or [], names=R.get('names', {}), size=R.get('size', {}),
                    notes=R.get('notes', []), equity=S.get('equity'), holdings=S['holdings'], orders=o if o.get('date') == today else None, sells=x if x.get('date') == today else None,
                    k_watch=S.get('k_watch'), breaks=[a for a in S.get('breaks', []) if a['date'] == today], md=S.get('md', ''), log=S.get('log', [])[-30:], mirror=S.get('mirror', ''), home=HOME)


def api_post(path, body):
    today = bj_now().strftime('%Y%m%d')
    if path == '/api/equity': S['equity'] = float(body['equity'])
    elif path == '/api/mirror': S['mirror'] = body.get('mirror', '').strip(); refresh_plan()
    elif path == '/api/refresh': refresh_plan()
    elif path == '/api/orders': build_orders(float(body['red']) / 100 if body.get('red') not in (None, '') else None)
    elif path == '/api/sells': build_sells()
    elif path == '/api/bought':   # 已成交 → 记入持仓
        r = next(x for x in S['orders']['rows'] if x['code'] == body['code'])
        S['holdings'].append(dict(code=r['code'], name=r['name'], src=r['src'], entry=today, buy_price=float(body.get('price') or r['limit'] or r['price']),
                                  shares=int(body.get('shares') or r['shares']), peak=float(body.get('price') or r['limit'] or r['price']), extra=0, delayed=0))
        r['done'] = True
    elif path == '/api/add_holding':
        S['holdings'].append(dict(code=body['code'].strip(), name=body.get('name', '').strip(), src=body['src'], entry=body.get('entry') or today,
                                  buy_price=float(body['price']), shares=int(body['shares']), peak=float(body['price']), extra=0, delayed=0))
    elif path == '/api/sold':
        h = next(x for x in S['holdings'] if x['code'] == body['code'])
        S['holdings'].remove(h); px = float(body.get('price') or 0)
        S['history'].append(dict(h, exit=today, sell_price=px, ret=round(px / h['buy_price'] - 1, 4) if px else None))
    elif path == '/api/keep':     # 按建议继续持有：保存多拿 / 推迟 / 高点状态
        r = next(x for x in (S.get('sells') or {}).get('rows', []) if x['code'] == body['code'])
        h = next(x for x in S['holdings'] if x['code'] == body['code']); h.update(r.get('set') or {}); r['done'] = True
    elif path == '/api/remove': S['holdings'] = [x for x in S['holdings'] if x['code'] != body['code']]
    save_state(); return {'ok': True}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, data, ctype='application/json; charset=utf-8'):
        b = data if isinstance(data, bytes) else (json.dumps(data, ensure_ascii=False, default=str) if not isinstance(data, str) else data).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith('/api/state'): return self._send(200, api_state())
        return self._send(200, PAGE, 'text/html; charset=utf-8')
    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length') or 0); body = json.loads(self.rfile.read(n) or b'{}')
            self._send(200, api_post(self.path, body))
        except Exception as e:
            self._send(200, {'ok': False, 'err': str(e)})


PAGE = r'''<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股开单助手</title><style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e1dc;--buy:#c0392b;--sell:#1e7d4f;--warn:#b7791f;--acc:#2f5bd3}
@media (prefers-color-scheme:dark){:root{--bg:#17171a;--card:#212125;--ink:#ececf0;--mute:#9a9aa3;--line:#35353b;--buy:#ff6b5b;--sell:#3ccf8e;--warn:#e0a84a;--acc:#7c9bff}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,"Microsoft YaHei","PingFang SC",sans-serif}
header{padding:12px 18px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header b{font-size:17px} .mute{color:var(--mute)} main{padding:14px 18px;display:grid;gap:14px;max-width:1200px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
h2{font-size:15px;margin:0 0 8px} table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;font-size:13px;vertical-align:top}
th{color:var(--mute);font-weight:500} .buy{color:var(--buy);font-weight:600} .sell{color:var(--sell);font-weight:600} .warn{color:var(--warn)}
button{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:13px} button.ghost{background:transparent;color:var(--acc);border:1px solid var(--acc)}
input,select{padding:4px 6px;border:1px solid var(--line);border-radius:5px;background:var(--card);color:var(--ink);font-size:13px}
pre{white-space:pre-wrap;font-size:12px;max-height:340px;overflow:auto;margin:0} .big{font-size:22px;font-weight:700} .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
</style></head><body>
<header><b>A股开单助手</b><span id="hd" class="mute"></span><button class="ghost" onclick="post('/api/refresh')">重新读取计划</button></header>
<main>
<div class="card"><h2>账户</h2><div class="row">账户总资产（元）<input id="eq" size="12"><button onclick="post('/api/equity',{equity:val('eq')})">保存</button>
<span id="acct" class="mute"></span></div></div>
<div class="card"><h2>① 9:25 开单（9:25:15 后自动生成，也可手动）</h2>
<div class="row">手动红盘率%（抓不到全市场时填，留空=自动）<input id="red" size="6"><button onclick="post('/api/orders',{red:val('red')})">生成开单单</button><span id="gate"></span></div>
<div id="orders"></div></div>
<div class="card"><h2>② 盘中：高标被砸挂单</h2><div id="kw" class="mute">无</div></div>
<div class="card"><h2>②b 盘中：持仓炸板提醒（10:30 后冲到涨停又打开 → 立即卖）</h2><div id="brk" class="mute">无</div></div>
<div class="card"><h2>③ 14:47 卖出检查（自动，也可手动）</h2><button onclick="post('/api/sells')">现在检查</button> <span id="zz" class="mute"></span><div id="sells"></div></div>
<div class="card"><h2>持仓（只存在本机）</h2><div id="hold"></div>
<div class="row" style="margin-top:8px">手动添加：代码<input id="hc" size="7">名称<input id="hn" size="7">路线<select id="hs"></select>买入价<input id="hp" size="7">股数<input id="hq" size="6">买入日<input id="he" size="9" placeholder="YYYYMMDD"><button onclick="addh()">添加</button></div></div>
<div class="card"><h2>今日计划候选</h2><div id="cand"></div></div>
<div class="card"><h2>计划全文</h2><pre id="md"></pre></div>
<div class="card"><h2>设置与日志</h2><div class="row">仓库镜像（读不到 GitHub 时填，例如 https://ghfast.top/https://raw.githubusercontent.com/Svanisthebest/ashare-data/main）<input id="mir" size="60"><button onclick="post('/api/mirror',{mirror:val('mir')})">保存</button></div><pre id="log" class="mute"></pre>
<p class="mute">仅供参考，不构成投资建议；规则来自历史回测，下单以券商软件为准。数据：东方财富、腾讯行情；计划与规则来自 GitHub 仓库，每次启动自动同步。</p></div>
</main><script>
let st={},seenO='',seenS='',seenB=-1;const $=id=>document.getElementById(id),val=id=>$(id).value;
function esc(s){return String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function post(p,b={}){const r=await (await fetch(p,{method:'POST',body:JSON.stringify(b)})).json();if(!r.ok)alert(r.err);load()}
function beep(){try{const a=new AudioContext(),o=a.createOscillator();o.connect(a.destination);o.frequency.value=880;o.start();setTimeout(()=>o.stop(),400)}catch(e){}}
function notify(t){beep();document.title='【新】'+t;if(window.Notification){if(Notification.permission==='granted')new Notification(t);else Notification.requestPermission()}}
function addh(){post('/api/add_holding',{code:val('hc'),name:val('hn'),src:val('hs'),price:val('hp'),shares:val('hq'),entry:val('he')})}
function tbl(h,rows){return '<table><tr>'+h.map(x=>'<th>'+x+'</th>').join('')+'</tr>'+rows.join('')+'</table>'}
async function load(){st=await (await fetch('/api/state')).json();
$('hd').textContent=`北京时间 ${st.now} ｜ 规则 ${st.rules_version||'?'} ｜ ${st.plan_status}${st.plan_err?' ｜ ⚠ '+st.plan_err:''}`;
if(document.activeElement!==$('eq'))$('eq').value=st.equity||'';if(document.activeElement!==$('mir'))$('mir').value=st.mirror||'';
$('acct').textContent=`持仓 ${st.holdings.length} / 5 只；数据目录 ${st.home}`;
if(!$('hs').options.length)for(const k in st.names){const o=document.createElement('option');o.value=k;o.textContent=st.names[k];$('hs').appendChild(o)}
const O=st.orders;if(O){$('gate').innerHTML=` <span class="big">${(O.red*100).toFixed(1)}%</span>（${O.red_src}，${esc(O.time)}）→ 竞价 ${O.gate}，可做：${O.allowed.join('、')}`;
$('orders').innerHTML=tbl(['路线','代码','名称','竞价价','竞价涨跌','动作','股数','金额','说明',''],O.rows.map(r=>`<tr><td>${esc(r.route)}</td><td>${r.code}</td><td>${esc(r.name)}</td><td>${r.price??''}</td><td>${r.gap!=null?r.gap+'%':''}</td><td class="${r.action!=='不买'?'buy':'mute'}">${r.action}${r.limit&&r.action!=='不买'?' '+r.limit:''}</td><td>${r.shares||''}</td><td>${r.amount||''}</td><td>${esc(r.why)}</td><td>${r.action!=='不买'&&!r.done?`<button onclick="bought('${r.code}',${r.limit},${r.shares})">已成交</button>`:(r.done?'已记入':'')}</td></tr>`))+`<p class="mute">开单后剩余可用约 ${O.cash_left} 元</p>`;
if(O.time!==seenO&&seenO!==''){notify('开单单已生成')}seenO=O.time}
const K=st.k_watch||[];$('kw').innerHTML=K.length?tbl(['代码','名称','挂单价','最低','现价',''],K.map(k=>`<tr><td>${k.code}</td><td>${esc(k.name)}</td><td>${k.limit}</td><td>${k.low}</td><td>${k.price}</td><td class="${k.hit?'buy':'mute'}">${k.hit?'最低价已到挂单价，去券商确认是否成交':'未到'}</td></tr>`)):'无';
const BR=st.breaks||[];$('brk').innerHTML=BR.length?tbl(['时间','代码','名称','路线','涨停价','现价','盈亏',''],BR.map(a=>`<tr><td>${a.time}</td><td>${a.code}</td><td>${esc(a.name)}</td><td>${esc(a.route)}</td><td>${a.up}</td><td>${a.price}</td><td>${a.pnl}%</td><td class="sell">立即卖出 <button onclick="sold('${a.code}',${a.price})">已卖出</button></td></tr>`)):'无';
if(BR.length>seenB&&seenB>=0){notify('持仓炸板，按规则卖出')}seenB=BR.length;
const X=st.sells;if(X){$('zz').textContent=`（${X.time}，中证1000 ${X.zz1000??''}%）`;
$('sells').innerHTML=tbl(['代码','名称','路线','买入价','现价','今日','盈亏','天数','建议','原因',''],X.rows.map(r=>`<tr><td>${r.code}</td><td>${esc(r.name)}</td><td>${esc(r.route)}</td><td>${r.buy}</td><td>${r.price??''}</td><td>${r.ret!=null?r.ret+'%':''}</td><td>${r.pnl!=null?r.pnl+'%':''}</td><td>${r.days??''}</td><td class="${r.action==='卖出'?'sell':'warn'}">${r.action}</td><td>${esc(r.why)}</td><td>${r.action==='卖出'?`<button onclick="sold('${r.code}',${r.price})">已卖出</button>`:(r.action!=='?'&&!r.done&&r.set?`<button class="ghost" onclick="post('/api/keep',{code:'${r.code}'})">按建议记录</button>`:'')}</td></tr>`));
if(X.time!==seenS&&seenS!==''){notify('卖出检查已完成')}seenS=X.time}
$('hold').innerHTML=st.holdings.length?tbl(['代码','名称','路线','买入日','买入价','股数','多拿','已推迟',''],st.holdings.map(h=>`<tr><td>${h.code}</td><td>${esc(h.name)}</td><td>${esc(st.names[h.src]||h.src)}</td><td>${h.entry}</td><td>${h.buy_price}</td><td>${h.shares}</td><td>${h.extra||0}</td><td>${h.delayed?'是':''}</td><td><button class="ghost" onclick="sold('${h.code}','')">已卖出</button> <button class="ghost" onclick="if(confirm('删除这条持仓记录？'))post('/api/remove',{code:'${h.code}'})">删除</button></td></tr>`)):'<span class="mute">空仓</span>';
$('cand').innerHTML=st.cand.length?tbl(['路线','代码','名称','收盘','涨跌%','成交额亿','说明'],st.cand.map(c=>`<tr><td>${esc(c['路线'])}</td><td>${c['代码']}</td><td>${esc(c['名称'])}</td><td>${c['收盘']}</td><td>${c['涨跌']}</td><td>${c['成交额亿']}</td><td>${esc(c['说明'])}</td></tr>`)):'无候选';
$('md').textContent=st.md||'';$('log').textContent=st.log.slice().reverse().join('\n')}
function bought(c,p,q){const px=prompt('实际成交价',p),n=prompt('实际成交股数',q);if(px&&n)post('/api/bought',{code:c,price:px,shares:n})}
function sold(c,p){const px=prompt('实际卖出价（可留空）',p||'');if(px!==null)post('/api/sold',{code:c,price:px})}
if(window.Notification&&Notification.permission==='default')Notification.requestPermission();load();setInterval(load,5000);
</script></body></html>'''


def main():
    log(f'助手核心 v{CORE_VERSION} 启动，数据目录 {HOME}')
    refresh_plan()
    threading.Thread(target=scheduler, daemon=True).start()
    for port in range(8765, 8775):
        try: srv = ThreadingHTTPServer(('127.0.0.1', port), H); break
        except OSError: continue
    url = f'http://127.0.0.1:{port}/'; log(f'页面：{url}（关掉这个窗口助手就停止）')
    if not os.environ.get('ASH_NOBROWSER'): webbrowser.open(url)
    srv.serve_forever()


if __name__ == '__main__':
    main()
