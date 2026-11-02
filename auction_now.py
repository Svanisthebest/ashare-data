#!/usr/bin/env python3
"""盘中用：抓全部沪深A股的今开（=9:25竞价价）和昨收，算竞价红盘率，并查看候选股。输出 data/auction/YYYYMMDD.json"""
import glob, json, os, time, traceback, datetime as dt
import pandas as pd, requests
WATCH = os.environ.get('WATCH', '002384,000938,600105,688347,300418,300286,688411,301071,688765,001219').split(',')
os.makedirs('data/auction', exist_ok=True)
day = f"{dt.datetime.utcnow() + dt.timedelta(hours=8):%Y%m%d}"
ERR = f'data/auction/{day}_err.txt'; log = []
def em():
    rows = []; hosts = ['push2', '82.push2', '72.push2', '7.push2', '28.push2', '17.push2']
    for pn in range(1, 80):
        p = dict(pn=pn, pz=100, po=1, np=1, fltt=2, invt=2, fid='f12', fs='m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
                 fields='f12,f14,f17,f18,f2,f15,f16', ut='bd1d9ddb04089700cf9c27f6f7426281')
        for t in range(6):
            url = f'https://{hosts[(pn + t) % len(hosts)]}.eastmoney.com/api/qt/clist/get'
            try:
                j = requests.get(url, params=p, timeout=15, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}).json(); break
            except Exception as e:
                log.append(f'em p{pn} {url[:30]} {e}'); time.sleep(3 + 2 * t); j = None
        d = (j or {}).get('data') or {}
        diff = d.get('diff') or []
        if isinstance(diff, dict): diff = list(diff.values())
        if not diff: break
        rows += diff; time.sleep(2)
        if len(rows) >= d.get('total', 0): break
    Q = pd.DataFrame(rows).rename(columns={'f12': 'code', 'f14': 'name', 'f17': 'open', 'f18': 'last_close', 'f2': 'price', 'f15': 'high', 'f16': 'low'})
    for c in ['open', 'last_close', 'price', 'high', 'low']: Q[c] = pd.to_numeric(Q[c], errors='coerce')
    return Q
def tdx():
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'mootdx'], check=False)
    from mootdx.quotes import Quotes
    f = sorted(glob.glob('data/daily/*.csv.gz'))[-1]; base = pd.read_csv(f, dtype={'code': str})
    base = base[~base.code.str.match(r'^(4|8|92)')]; codes = base.code.tolist()
    c = Quotes.factory(market='std', bestip=True, timeout=15); rows = []
    for i in range(0, len(codes), 30):
        q = c.quotes(symbol=codes[i:i + 30])
        if hasattr(q, 'columns') and len(q): rows.append(q)
    Q = pd.concat(rows, ignore_index=True); Q['code'] = Q.code.astype(str).str.zfill(6)
    Q['name'] = Q.code.map(base.set_index('code').name); return Q
try:
    Q = em(); src = '东方财富'
    if len(Q) < 3000: log.append(f'东财只有 {len(Q)} 行，改用通达信'); Q = tdx(); src = '通达信'
    Q = Q[(Q.last_close > 0) & ~Q.code.astype(str).str.match(r'^(4|8|92)')].copy()
    Q['name'] = Q.name.fillna(''); Q['st'] = Q.name.str.contains('ST')
    T = Q[Q.open > 0]
    def share(x): return dict(上涨=int((x.open > x.last_close).sum()), 下跌=int((x.open < x.last_close).sum()), 平盘=int((x.open == x.last_close).sum()), 红盘率=round(float((x.open > x.last_close).mean()), 4))
    out = {'来源': src, '抓取时间北京': f"{dt.datetime.utcnow() + dt.timedelta(hours=8):%H:%M:%S}", '股票数': len(Q), '已开盘': len(T), '不含ST': share(T[~T.st]), '含ST': share(T)}
    w = Q[Q.code.astype(str).isin(WATCH)][['code', 'name', 'last_close', 'open', 'price', 'high', 'low']].copy()
    w['开盘涨跌%'] = ((w.open / w.last_close - 1) * 100).round(2); w['现价涨跌%'] = ((w.price / w.last_close - 1) * 100).round(2); w['现价较开盘%'] = ((w.price / w.open - 1) * 100).round(2)
    out['候选'] = w.to_dict('records'); out['日志'] = log[-10:]
    json.dump(out, open(f'data/auction/{day}.json', 'w'), ensure_ascii=False, indent=1, default=str); print(out)
except Exception:
    open(ERR, 'w').write('\n'.join(log) + '\n' + traceback.format_exc()); raise
