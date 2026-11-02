#!/usr/bin/env python3
"""盘中用：抓全部沪深A股的今开（=9:25竞价价）和昨收，算竞价红盘率，并查看候选股的开盘与现价。
输出 data/auction/YYYYMMDD.json"""
import glob, json, os, subprocess, sys, time, datetime as dt
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'mootdx'], check=False)
import traceback
import pandas as pd
os.makedirs('data/auction', exist_ok=True)
ERR = f"data/auction/{dt.datetime.utcnow() + dt.timedelta(hours=8):%Y%m%d}_err.txt"
try:
    from mootdx.quotes import Quotes
except Exception:
    open(ERR, 'w').write(traceback.format_exc()); raise
WATCH = os.environ.get('WATCH', '002384,000938,600105,688347,300418,300286,688411,301071,688765,001219').split(',')
f = sorted(glob.glob('data/daily/*.csv.gz'))[-1]
base = pd.read_csv(f, dtype={'code': str})
base = base[~base.code.str.match(r'^(4|8|92)')]
codes = base.code.tolist(); name = base.set_index('code').name
def client():
    for i in range(3):
        try:
            return Quotes.factory(market='std', bestip=(i > 0), timeout=15)
        except Exception:
            time.sleep(2)
    raise RuntimeError('连不上通达信')
try:
  c = client()
  rows = []
  for i in range(0, len(codes), 80):
      for t in range(3):
          try:
              q = c.quotes(symbol=codes[i:i + 80]); rows.append(q); break
          except Exception as e:
              time.sleep(1)
  Q = pd.concat(rows, ignore_index=True)
  Q['code'] = Q['code'].astype(str).str.zfill(6)
  Q = Q[(Q.last_close > 0)]
  Q['name'] = Q.code.map(name).fillna('')
  Q['st'] = Q.name.str.contains('ST')
  traded = Q[Q.open > 0]
  def share(x): return dict(上涨=int((x.open > x.last_close).sum()), 下跌=int((x.open < x.last_close).sum()), 平盘=int((x.open == x.last_close).sum()), 红盘率=round(float((x.open > x.last_close).mean()), 4))
  out = {'抓取时间': dt.datetime.utcnow().strftime('%H:%M:%S UTC'), '数据日昨收来自': os.path.basename(f), '股票数': len(Q), '已开盘数': len(traded),
         '不含ST': share(traded[~traded.st]), '含ST': share(traded)}
  w = Q[Q.code.isin(WATCH)][['code', 'name', 'last_close', 'open', 'price', 'high', 'low']].copy()
  w['开盘涨跌%'] = ((w.open / w.last_close - 1) * 100).round(2); w['现价涨跌%'] = ((w.price / w.last_close - 1) * 100).round(2)
  w['现价较开盘%'] = ((w.price / w.open - 1) * 100).round(2)
  out['候选'] = w.to_dict('records')
  os.makedirs('data/auction', exist_ok=True)
  p = f"data/auction/{dt.datetime.utcnow() + dt.timedelta(hours=8):%Y%m%d}.json"
  json.dump(out, open(p, 'w'), ensure_ascii=False, indent=1, default=str)
  print(json.dumps(out, ensure_ascii=False, indent=1, default=str))

except Exception:
  open(ERR, 'w').write(traceback.format_exc()); raise
