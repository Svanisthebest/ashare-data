#!/usr/bin/env python3
"""情绪股（涨停 / 涨幅≥7 成）竞价与分时特征回补（研究用，通达信历史接口）。

输入 emo_targets.csv.gz：d0（信号日）, d1（次日）, code, up0, up1, close0
对每一行：
  信号日 d0 的历史分时（240 分钟）→ 首次封板时间、开板次数、尾盘是否封住、封住的分钟数
  次日 d1 的历史逐笔 → 9:25 竞价价和量；9:30 起合成分钟线，取若干时点的价格、均价线（含竞价量）、最高最低
输出 emo_XXofYY.csv.gz（每行一组特征）。超过时间预算会先保存已完成部分，重跑时跳过已有结果。
"""
import argparse, os, time
import numpy as np, pandas as pd
from mootdx.quotes import Quotes

PTS = ['0931', '0935', '0940', '0945', '1000', '1015', '1030', '1100', '1130', '1330', '1400', '1430', '1455']


def connect():
    for i in range(6):
        try: return Quotes.factory(market='std', bestip=(i > 0), timeout=15)
        except Exception as e: print('connect fail', e, flush=True); time.sleep(3)
    raise SystemExit('无法连接通达信')


def ticks(c, code, d):
    pages, st = [], 0
    while st < 60000:
        df = c.transactions(symbol=code, date=d, start=st, offset=2000)
        if df is None or not len(df): break
        pages.append(df)
        if len(df) < 2000: break
        st += 2000
    return pd.concat(pages[::-1], ignore_index=True) if pages else None


def seal_feats(m, up):
    """信号日分时：m.price 每分钟价格（240 行）"""
    if m is None or not len(m) or not up: return {}
    p = m.price.astype(float).values; at = p >= up - 0.005
    if not at.any(): return dict(s_first=-1, s_breaks=0, s_close=0, s_mins=0)
    first = int(np.argmax(at)); brk = int(((~at[1:]) & at[:-1])[first:].sum())
    return dict(s_first=first, s_breaks=brk, s_close=int(at[-1]), s_mins=int(at.sum()))


def next_feats(tk, up1, pc1):
    if tk is None or not len(tk): return {}
    tk = tk.copy(); tk['time'] = tk.time.astype(str); tk['price'] = tk.price.astype(float); tk['vol'] = tk.vol.astype(float)
    a = tk[tk.time <= '09:25']; o = {}
    o['auc_p'] = float(a.price.iloc[-1]) if len(a) else np.nan
    o['auc_v'] = float(a.vol.sum()) if len(a) else 0.0
    k = tk[tk.time > '09:25']
    if not len(k): return o
    k = k.assign(pv=k.price * k.vol)
    g = k.groupby('time').agg(c=('price', 'last'), h=('price', 'max'), l=('price', 'min'), v=('vol', 'sum'), pv=('pv', 'sum')).reset_index()
    av = o['auc_v'] if o['auc_v'] else 0.0; ap = o['auc_p'] if av else 0.0
    g['cv'] = g.v.cumsum() + av; g['cpv'] = g.pv.cumsum() + ap * av
    g['vw'] = g.cpv / g.cv.replace(0, np.nan); g['hh'] = g.h.cummax(); g['ll'] = g.l.cummin()
    g['t'] = g.time.str.replace(':', '')
    for t in PTS:
        r = g[g.t <= t]
        if len(r):
            r = r.iloc[-1]; o[f'p{t}'] = r.c; o[f'w{t}'] = round(float(r.vw), 4); o[f'h{t}'] = r.hh; o[f'l{t}'] = r.ll; o[f'v{t}'] = float(r.cv)
    o['day_v'] = float(g.v.sum()) + av; o['day_vw'] = round(float(g.cpv.iloc[-1] / g.cv.iloc[-1]), 4) if g.cv.iloc[-1] else np.nan
    if up1:
        at = g.h.values >= up1 - 0.005
        o['n_first'] = g.t.values[int(np.argmax(at))] if at.any() else ''
        cl = g.c.values >= up1 - 0.005
        o['n_breaks'] = int(((~cl[1:]) & cl[:-1]).sum()); o['n_close_up'] = int(cl[-1])
    return o


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--shard', type=int); ap.add_argument('--nshards', type=int)
    ap.add_argument('--budget', type=float, default=325 * 60); ap.add_argument('--out', default='emo')
    ap.add_argument('--start', default='20160101'); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args(); T0 = time.time()
    tg = pd.read_csv('emo_targets.csv.gz', dtype={'d0': str, 'd1': str, 'code': str})
    tg = tg[tg.d0 >= a.start].sort_values(['d0', 'code']).iloc[a.shard::a.nshards]
    if a.limit: tg = tg.head(a.limit)
    os.makedirs(a.out, exist_ok=True); fn = f'{a.out}/emo_{a.shard:02d}of{a.nshards:02d}.csv.gz'
    done = set()
    if os.path.exists(fn):
        old = pd.read_csv(fn, dtype={'d0': str, 'code': str}); done = set(zip(old.d0, old.code))
    rows = []; c = connect(); fails = 0
    print(f'分片 {a.shard}: {len(tg)} 行，已完成 {len(done)}', flush=True)
    for i, r in enumerate(tg.itertuples(index=False)):
        if (r.d0, r.code) in done: continue
        if time.time() - T0 > a.budget: print('到时间预算，先保存', flush=True); break
        o = dict(d0=r.d0, d1=r.d1, code=r.code)
        for k in range(2):
            try:
                m = c.minutes(symbol=r.code, date=r.d0); o.update(seal_feats(m, r.up0))
                o.update(next_feats(ticks(c, r.code, r.d1), r.up1, r.close0)); break
            except Exception as e:
                fails += 1; print('err', r.d0, r.code, str(e)[:80], flush=True)
                try: c = connect()
                except SystemExit: break
        rows.append(o)
        if i % 500 == 0: print(f'{i}/{len(tg)} {time.time() - T0:.0f}s 失败 {fails}', flush=True)
    new = pd.DataFrame(rows)
    if os.path.exists(fn): new = pd.concat([pd.read_csv(fn, dtype={'d0': str, 'd1': str, 'code': str}), new], ignore_index=True)
    new.to_csv(fn, index=False, compression='gzip'); print('保存', fn, len(new), '行，失败', fails, f'{time.time() - T0:.0f}s', flush=True)


if __name__ == '__main__':
    main()
