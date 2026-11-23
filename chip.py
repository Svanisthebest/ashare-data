"""筹码结构（v1.7 观察项）：取候选股最新一期前十大流通股东（东方财富 F10），算
   - 大股东合计：持流通 ≥5% 的股东合计占比（自由流通比例 = 1 − 它）
   - 前十大集中度、前十大里个人股东数
   标签：控盘（大股东合计 >50%）/ 筹码分散（前十大个人 ≥7 人）/ 一般。
   研究依据：research_log 第五十八轮（全市场 12.45 万次涨停，两段一致）。只做标注，不影响买入。
   顺带缓存股东户数（gdrs）和限售解禁计划（xsjj），供后续研究。"""
import json, os, time, datetime as dt
CACHE = 'data/holders/cache.json'
def _load(out):
    p = os.path.join(out, 'holders', 'cache.json')
    try: return json.load(open(p, encoding='utf-8')), p
    except Exception: return {}, p
def fetch(code, S):
    mk = 'SH' if code[0] == '6' else 'SZ'
    j = S.get('https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax', params={'code': mk + code}, timeout=15).json()
    rows = j.get('sdltgd') or []
    if not rows: return None
    end = str(rows[0].get('END_DATE', ''))[:10]
    rt = [float(r.get('FREE_HOLDNUM_RATIO') or 0) for r in rows]
    big5 = sum(x for x in rt if x >= 5)
    nat = sum(1 for r in rows if (r.get('HOLDER_TYPE') or '') in ('个人', '自然人'))
    g = (j.get('gdrs') or [])[:4]; xs = (j.get('xsjj') or [])[:6]
    return dict(end=end, big5=round(big5, 2), conc=round(sum(rt), 2), nat=nat, n=len(rows),
                types=sorted({r.get('HOLDER_TYPE') or '' for r in rows}),
                gdrs=[dict(end=str(x.get('END_DATE'))[:10], num=x.get('HOLDER_TOTAL_NUM'), chg=x.get('TOTAL_NUM_RATIO')) for x in g],
                xsjj=[dict(date=str(x.get('LIFT_DATE'))[:10], ratio=x.get('UNLIMITED_A_SHARES_RATIO'), type=x.get('LIFT_TYPE')) for x in xs])
def label(f):
    if not f: return '未取到'
    if f['big5'] > 50: return f"控盘（大股东合计 {f['big5']:.0f}%）"
    if f['nat'] >= 7: return f"筹码分散（前十大个人 {f['nat']} 人）"
    return f"一般（大股东合计 {f['big5']:.0f}%，个人 {f['nat']} 人）"
def annotate(codes, out='data', max_age_days=7):
    import requests
    C, p = _load(out); S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0'
    today = dt.date.today().isoformat(); res = {}
    for c in codes:
        e = C.get(c)
        if not e or (dt.date.fromisoformat(today) - dt.date.fromisoformat(e.get('fetched', '2000-01-01'))).days > max_age_days:
            try:
                f = fetch(c, S); time.sleep(0.3)
                if f: e = dict(f, fetched=today); C[c] = e
            except Exception as ex:
                print('筹码数据没取到', c, ex)
        res[c] = e
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True); json.dump(C, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    except Exception as ex: print('筹码缓存写入失败', ex)
    return {c: dict(label=label(f), **({k: f[k] for k in ('end', 'big5', 'nat', 'conc')} if f else {})) for c, f in res.items()}
if __name__ == '__main__':
    import sys; print(json.dumps(annotate(sys.argv[1:] or ['600000', '300750', '002050']), ensure_ascii=False, indent=1))
