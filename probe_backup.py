"""测试备用日线：东方财富快照 vs 通达信昨天日线（昨收应等于昨天收盘）、成交量单位 vs 腾讯、指数快照。输出 data/probe_backup.json"""
import json, datetime as dt, pandas as pd, backup_daily as B
CN = dt.timezone(dt.timedelta(hours=8)); today = dt.datetime.now(CN).strftime('%Y%m%d')
out = {'today': today}
try:
    em = B.em_snapshot(today); out['em_rows'] = len(em); out['mkt'] = em.market.value_counts().to_dict()
    import glob; last = sorted(f for f in glob.glob('data/daily/*.csv.gz') if f[-15:-7] < today)[-1]
    td = pd.read_csv(last, dtype={'code': str}); td = td[td.volume > 0].set_index('code')
    m = em.set_index('code').join(td[['close', 'name']], rsuffix='_tdx', how='inner')
    d = (m.prev_close - m.close_tdx).abs()
    out['vs_tdx'] = dict(file=last, common=len(m), em_only=int((~em.code.isin(td.index)).sum()), pc_diff_gt1fen=int((d > 0.011).sum()),
                         examples=m[d > 0.011][['name', 'prev_close', 'close_tdx']].head(10).reset_index().values.tolist(),
                         name_diff=int((m.name != m.name_tdx).sum()))
    out['qq'] = B.qq_check(em, today)
    q = B.qq_quotes(list(em.code[:5]) + ['688981', '300750', '920002'])
    e2 = em.set_index('code')
    out['vol_examples'] = {c: [float(e2.volume.get(c, -1)), v['vol'], float(e2.close.get(c, -1)), v['close']] for c, v in q.items()}
except Exception as e:
    out['em_err'] = repr(e)
try:
    out['index'] = B.em_index(today).values.tolist()
except Exception as e:
    out['idx_err'] = repr(e)
json.dump(out, open('data/probe_backup.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
