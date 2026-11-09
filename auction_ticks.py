#!/usr/bin/env python3
"""9:15–9:25 集合竞价过程采集（研究用）。

每 10 秒抓一次观察名单的竞价快照（腾讯行情）：虚拟匹配价、匹配量、匹配额、买一/卖一价和量（≈未匹配量）。
观察名单 = 上一交易日涨停股 + 涨幅 ≥7% 的强势股 + 当晚计划候选 + 成交额前 30。
输出 data/auction_ticks/YYYYMMDD.csv.gz。历史上没有这类数据，攒几个月后用于研究 9:20 撤单、量价是否同步等竞价信号。
"""
import datetime as dt, glob, json, os, sys, time
import pandas as pd, requests

BJ = dt.timezone(dt.timedelta(hours=8))
now = lambda: dt.datetime.now(BJ)
day = now().strftime('%Y%m%d')
OUT = 'data/auction_ticks'; os.makedirs(OUT, exist_ok=True)


def limit_rate(code, name):
    if 'ST' in str(name).upper(): return 0.05
    return 0.2 if code.startswith(('300', '301', '688', '689')) else 0.1


def watch_list():
    f = sorted(glob.glob('data/daily/*.csv.gz'))[-1]
    d = pd.read_csv(f, dtype={'code': str})
    d = d[~d.code.str.match(r'^(4|8|92)')]
    d['ret'] = d.close / d.prev_close - 1
    d['up'] = [round(p * (1 + limit_rate(c, n)) + 1e-9, 2) for p, c, n in zip(d.prev_close, d.code, d.name)]
    zt = d[d.close >= d.up - 0.005].code.tolist()
    strong = d[d.ret >= 0.07].code.tolist()
    top = d.nlargest(30, 'amount').code.tolist()
    cand = []
    try:
        lt = json.load(open('data/helper/latest.json', encoding='utf-8'))
        cand = pd.read_csv(lt['csv'], dtype={'代码': str}, encoding='utf-8-sig')['代码'].str.zfill(6).tolist()
    except Exception as e:
        print('读计划候选失败', e)
    codes = list(dict.fromkeys(cand + zt + strong + top))
    print(f'基准日 {os.path.basename(f)[:8]}：涨停 {len(zt)}、强势 {len(strong)}、候选 {len(cand)}、观察共 {len(codes)} 只')
    return codes, os.path.basename(f)[:8]


def sym(c): return ('sh' if c.startswith(('6', '9')) else 'sz') + c


def snap(codes, S):
    rows = []; t = now().strftime('%H:%M:%S')
    for i in range(0, len(codes), 60):
        try:
            txt = S.get('https://qt.gtimg.cn/q=' + ','.join(sym(c) for c in codes[i:i + 60]), timeout=8).content.decode('gbk', 'ignore')
        except Exception as e:
            print(t, '请求失败', e); continue
        for line in txt.strip().split(';'):
            if '="' not in line: continue
            k, v = line.split('="', 1); f = v.strip('"\n').split('~')
            if len(f) < 40: continue
            try:
                rows.append(dict(t=t, code=k[-6:], qdate=f[30][:8], qtime=f[30][8:14], price=float(f[3]), pc=float(f[4]), open=float(f[5]),
                                 vol=float(f[6]), amount=float(f[37] or 0) * 1e4,
                                 b1=float(f[9]), b1v=float(f[10]), b2v=float(f[12]), a1=float(f[19]), a1v=float(f[20]), a2v=float(f[22])))
            except Exception:
                pass
    return rows


def main():
    codes, base = watch_list()
    if os.environ.get('TEST'):
        S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0'
        r = pd.DataFrame(snap(codes, S)); print(r.head(8).to_string()); print('取到', len(r), '只'); return
    if now().strftime('%H%M') > '0930':
        print('已过竞价时间，退出'); return
    while now().strftime('%H:%M:%S') < '09:14:50': time.sleep(5)
    S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0'
    allrows = []; n = 0
    while now().strftime('%H:%M:%S') <= '09:26:00':
        t0 = time.time(); r = snap(codes, S); allrows += r; n += 1
        if n % 6 == 1: print(now().strftime('%H:%M:%S'), f'快照 {len(r)} 只')
        time.sleep(max(0, 10 - (time.time() - t0)))
    # 9:30–9:31 开盘第一分钟再记两次，方便对照
    while now().strftime('%H:%M:%S') < '09:30:20': time.sleep(5)
    allrows += snap(codes, S); time.sleep(40); allrows += snap(codes, S)
    df = pd.DataFrame(allrows)
    if df.empty or (df.qdate != day).mean() > 0.5:
        print('今天不是交易日或行情日期不对，不保存'); return
    df = df[df.qdate == day]
    df.to_csv(f'{OUT}/{day}.csv.gz', index=False, compression='gzip')
    print(f'已保存 {OUT}/{day}.csv.gz：{df.code.nunique()} 只 × {df.t.nunique()} 个时点（基准日 {base}）')


if __name__ == '__main__':
    main()
