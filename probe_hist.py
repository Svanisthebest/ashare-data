"""研究数据核对：baostock 历史日线抽样 400 行 vs 腾讯不复权日线。输出 data/probe_hist.json"""
import json, requests, pandas as pd, time
S = pd.read_csv('probe_hist_sample.csv', dtype={'code': str}); out = []; err = 0
for code, g in S.groupby('code'):
    sym = ('sh' if code.startswith('6') else 'sz') + code
    y0, y1 = g.date.min()[:4], g.date.max()[:4]
    try:
        r = requests.get(f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{g.date.min()},{g.date.max()},2000,', timeout=20).json()
        k = r['data'][sym].get('day') or r['data'][sym].get('qfqday') or []
        m = {x[0]: x for x in k}
    except Exception as e:
        err += 1; continue
    for x in g.itertuples():
        q = m.get(x.date)
        if not q: out.append((code, x.date, 'missing')); continue
        o, c, h, l = map(float, q[1:5])
        d = {k: round(v - w, 3) for k, v, w in [('open', x.open, o), ('close', x.close, c), ('high', x.high, h), ('low', x.low, l)] if abs(v - w) > 0.011}
        out.append((code, x.date, d or 'ok'))
    time.sleep(0.2)
ok = sum(1 for o in out if o[2] == 'ok'); miss = sum(1 for o in out if o[2] == 'missing')
res = dict(total=len(S), compared=len(out), ok=ok, missing=miss, diff=[o for o in out if isinstance(o[2], dict)][:30], err=err)
json.dump(res, open('data/probe_hist.json', 'w'), ensure_ascii=False, indent=1); print(json.dumps(res, ensure_ascii=False)[:2000])
