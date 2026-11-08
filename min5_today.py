#!/usr/bin/env python3
"""收盘后给模拟盘用：取当天模拟盘持仓（今天以前买入的）的 5 分钟线（baostock），存 data/min5/YYYYMMDD.csv。
sim_book.py 用它执行「10:30 后冲到涨停又打开就立即卖」。取不到就不写文件，模拟盘按收盘价处理。"""
import argparse, json, os, signal
import pandas as pd


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date', required=True); ap.add_argument('--out', default='data'); a = ap.parse_args()
    D = a.date; d = f'{D[:4]}-{D[4:6]}-{D[6:]}'
    bk = os.path.join(a.out, 'sim', 'book.json')
    if not os.path.exists(bk): print('没有模拟盘账本'); return
    book = json.load(open(bk))
    if book.get('last') == D: print('当天模拟盘已处理过'); return
    codes = sorted({p['code'] for p in book['pos'] if p['entry'] != D and p['src'] not in ('B', 'RB')})
    if not codes: print('没有需要看分钟线的持仓'); return
    import baostock as bs
    bs.login(); rows = []
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('超时')))
    for c in codes:
        sym = ('sh.' if c.startswith(('6', '9')) else 'sz.') + c
        try:
            signal.alarm(60)
            rs = bs.query_history_k_data_plus(sym, 'date,time,open,high,low,close,volume,amount', start_date=d, end_date=d, frequency='5', adjustflag='3')
            while rs.error_code == '0' and rs.next(): rows.append([c] + rs.get_row_data())
            signal.alarm(0)
        except Exception as e:
            signal.alarm(0); print('取分钟线失败', c, e)
    bs.logout()
    got = {r[0] for r in rows}; miss = [c for c in codes if c not in got]
    if miss:   # baostock 当天数据可能还没更新 → 改用通达信 5 分钟 K 线
        try:
            import subprocess, sys
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'mootdx'], check=False)
            from mootdx.quotes import Quotes
            q = Quotes.factory(market='std', bestip=True, timeout=15)
            for c in miss:
                b = q.bars(symbol=c, frequency=0, offset=100)
                if b is None or not len(b): continue
                b = b.reset_index(drop=False)
                tcol = 'datetime' if 'datetime' in b.columns else b.columns[0]
                b['dt'] = pd.to_datetime(b[tcol]); b = b[b.dt.dt.strftime('%Y-%m-%d') == d]
                for _, r in b.iterrows():
                    rows.append([c, d, r.dt.strftime('%Y%m%d%H%M%S000'), r['open'], r['high'], r['low'], r['close'], r.get('vol', r.get('volume', 0)), r.get('amount', 0)])
            print('通达信补取', len(miss), '只')
        except Exception as e:
            print('通达信也没取到', e)
    if not rows: print('分钟线还没有当天数据'); return
    df = pd.DataFrame(rows, columns=['code', 'date', 'time', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    df['time'] = df.time.str[8:12]
    os.makedirs(os.path.join(a.out, 'min5'), exist_ok=True)
    df.to_csv(os.path.join(a.out, 'min5', f'{D}.csv'), index=False); print('分钟线', df.code.nunique(), '只', len(df), '行')


if __name__ == '__main__':
    main()
