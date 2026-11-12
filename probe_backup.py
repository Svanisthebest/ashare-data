"""测试备用日线（收盘后跑）：东方财富快照、腾讯快照各取一遍并保存，互相核对；晚上再和通达信包逐只比。输出 data/probe_backup.json"""
import json, glob, time, datetime as dt, pandas as pd, backup_daily as B
CN = dt.timezone(dt.timedelta(hours=8)); today = dt.datetime.now(CN).strftime('%Y%m%d')
out = {'today': today, 'time': dt.datetime.now(CN).strftime('%H:%M:%S')}
last = sorted(f for f in glob.glob('data/daily/*.csv.gz') if f[-15:-7] < today)[-1]
codes = list(pd.read_csv(last, dtype={'code': str}).code)
S = {}
for nm, fn in [('em', lambda: B.em_snapshot(today)), ('qq', lambda: B.qq_snapshot(today, codes))]:
    t = time.time()
    try:
        S[nm] = fn(); S[nm].to_csv(f'data/probe_{nm}_{today}.csv.gz', index=False, compression='gzip')
        out[nm] = dict(rows=len(S[nm]), sec=round(time.time() - t))
    except Exception as e:
        out[nm + '_err'] = repr(e)[:300]
if len(S) == 2:
    m = S['em'].set_index('code').join(S['qq'].set_index('code'), rsuffix='_q', how='inner')
    out['em_vs_qq'] = {k: int(((m[k] - m[k + '_q']).abs() > tol(m[k])).sum()) for k, tol in
                       [('close', lambda x: 0.011), ('open', lambda x: 0.011), ('high', lambda x: 0.011), ('low', lambda x: 0.011), ('prev_close', lambda x: 0.011),
                        ('volume', lambda x: 0.005 * x + 100), ('amount', lambda x: 0.005 * x + 1e4)]}
    out['common'] = len(m)
    d = m[(m.volume - m.volume_q).abs() > 0.005 * m.volume + 100]
    out['vol_diff_examples'] = d[['volume', 'volume_q', 'amount', 'amount_q']].head(8).reset_index().values.tolist()
for nm in S:
    try: out[nm + '_check'] = B.qq_check(S[nm], today)
    except Exception as e: out[nm + '_check_err'] = repr(e)[:300]
json.dump(out, open('data/probe_backup.json', 'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
