"""研究用：从腾讯取若干股票 2022 年以来的日线（不复权 + 前复权），独立核对通达信日线和研究用复权因子。输出 data/probe_kline.json"""
import json, random, time, glob, requests, pandas as pd
f = sorted(glob.glob('data/daily/*.csv.gz'))[-1]
codes = sorted(pd.read_csv(f, dtype={'code': str}).query('volume > 0').code)
codes = [c for c in codes if not c.startswith(('4', '8', '92'))]
pick = random.Random(7).sample(codes, 120)
out = {}
for c in pick:
    sym = ('sh' if c.startswith('6') else 'sz') + c
    for fq in ['', 'qfq']:
        for k in range(3):
            try:
                r = requests.get(f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2021-12-01,2026-12-31,2000,{fq}', timeout=20).json()
                d = r['data'][sym]; out[f'{c}_{fq or "raw"}'] = d.get('qfqday' if fq else 'day') or d.get('day'); break
            except Exception as e:
                time.sleep(2)
    time.sleep(0.2)
json.dump(out, open('data/probe_kline.json', 'w'))
print(len(out), 'series')
