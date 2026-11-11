#!/usr/bin/env python3
"""研究用：给定日期，找出当天摸过涨停但没封住的强势股，用通达信 1 分钟线数封在涨停价的分钟数。输出 data/probe_seal.json。"""
import json, os, subprocess, sys, time
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'mootdx'], check=False)
import numpy as np, pandas as pd
from mootdx.quotes import Quotes

DATES = os.environ.get('DATES', '20261104,20261105,20261106,20261109').split(',')
c = Quotes.factory(market='std', bestip=True, timeout=15)
out = {}
for D in DATES:
    f = f'data/daily/{D}.csv.gz'
    if not os.path.exists(f): continue
    d = pd.read_csv(f, dtype={'code': str})
    d = d[~d.code.str.match(r'^(4|8|92)') & (d.volume > 0) & ~d.name.astype(str).str.contains('ST|退')]
    big = d.code.str.startswith(('300', '301', '688', '689'))
    lim = np.where(big, 0.2, 0.1)
    d['up'] = np.floor(d.prev_close * (1 + lim) * 100 + 0.5) / 100
    d['ret'] = d.close / d.prev_close - 1
    z = d[(d.high >= d.up - 0.005) & (d.close < d.up - 0.001) & (d.ret >= 0.6 * lim)]
    res = {}
    for r in z.itertuples():
        n = None
        for k in range(3):
            try:
                m = c.minutes(symbol=r.code, date=D)
                if m is not None and len(m) >= 200: n = int((m.price.astype(float) >= r.up - 0.005).sum()); break
            except Exception as e:
                print('err', D, r.code, e); time.sleep(2)
        res[r.code] = n
    out[D] = res
    print(D, len(z), '只摸板未封，取到', sum(v is not None for v in res.values()), flush=True)
os.makedirs('data', exist_ok=True)
json.dump(out, open('data/probe_seal.json', 'w'), ensure_ascii=False, indent=1)
