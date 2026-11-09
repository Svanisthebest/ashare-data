"""探测通达信历史分时/逐笔能回溯多远、速度如何"""
import subprocess, sys, json, time
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'mootdx'], check=False)
from mootdx.quotes import Quotes
c = Quotes.factory(market='std', bestip=True, timeout=15)
out = {}
for d in ['20160315', '20170612', '20190308', '20210104', '20231106']:
    for code in ['000001', '600519', '300750' if d >= '2018' else '300059']:
        r = {}
        t0 = time.time()
        try:
            m = c.minutes(symbol=code, date=d); r['min_rows'] = 0 if m is None else len(m)
            if m is not None and len(m): r['min_head'] = m.head(2).astype(str).to_dict('records'); r['min_cols'] = list(m.columns)
        except Exception as e: r['min_err'] = str(e)[:100]
        r['min_sec'] = round(time.time() - t0, 2); t0 = time.time()
        try:
            n = 0; first = None; st = 0; pages = 0
            while True:
                tx = c.transactions(symbol=code, date=d, start=st, offset=2000); pages += 1
                if tx is None or not len(tx): break
                n += len(tx); first = tx.head(3).astype(str).to_dict('records')
                if len(tx) < 2000: break
                st += 2000
            r['tick_rows'] = n; r['tick_first'] = first; r['pages'] = pages
        except Exception as e: r['tick_err'] = str(e)[:100]
        r['tick_sec'] = round(time.time() - t0, 2)
        out[f'{d}_{code}'] = r
json.dump(out, open('data/probe_tdx.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
