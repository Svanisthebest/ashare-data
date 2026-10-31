#!/usr/bin/env python3
"""
用通达信历史逐笔成交，为候选股票的指定交易日合成：
  - 9:25 集合竞价成交（价格、手数）
  - 9:30–10:30、14:30–15:00 每分钟的开高低收、成交手数、主动买卖手数
输入 tick_targets.csv（列 d1=YYYYMMDD, code），按分片处理，输出 csv.gz。
"""
import argparse, os, time
import pandas as pd
from mootdx.quotes import Quotes

KEEP_DEFAULT = lambda t: ("09:25" <= t <= "10:30") or ("14:30" <= t <= "15:00")
KEEP = KEEP_DEFAULT

def connect():
    for i in range(5):
        try:
            return Quotes.factory(market="std", bestip=(i > 0), timeout=15)
        except Exception as e:
            print("connect fail", e, flush=True); time.sleep(3)
    raise SystemExit("无法连接通达信服务器")

def day_ticks(c, code, d):
    pages, st = [], 0
    while st < 40000:
        df = c.transactions(symbol=code, date=d, start=st, offset=2000)
        if df is None or not len(df):
            break
        pages.append(df)
        if len(df) < 2000:
            break
        st += 2000
    if not pages:
        return None
    return pd.concat(pages[::-1], ignore_index=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="ticks")
    ap.add_argument("--targets", default="tick_targets.csv")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--fullday", action="store_true")
    a = ap.parse_args()
    tg = pd.read_csv(a.targets, dtype={"d1": str, "code": str})
    tg = tg.iloc[a.shard::a.nshards]
    if a.limit:
        tg = tg.head(a.limit)
    print(f"分片{a.shard}: {len(tg)} 个(股票,日期)", flush=True)
    global KEEP
    if a.fullday:
        KEEP = lambda t: True
    c = connect(); bars, auc, t0, fails = [], [], time.time(), 0
    for i, (d, code) in enumerate(zip(tg.d1, tg.code)):
        try:
            df = day_ticks(c, code, d)
        except Exception as e:
            fails += 1; print("err", d, code, e, flush=True)
            try:
                c = connect(); df = day_ticks(c, code, d)
            except Exception:
                continue
        if df is None:
            continue
        df["time"] = df["time"].astype(str)
        a925 = df[df.time <= "09:25"]
        auc.append(dict(date=d, code=code, auc_price=float(a925.price.iloc[-1]) if len(a925) else None,
                        auc_vol=int(a925.vol.sum()) if len(a925) else 0, day_vol=int(df.vol.sum()), n_ticks=len(df),
                        last_time=df.time.iloc[-1]))
        k = df[df.time.map(KEEP) & (df.time > "09:25")].copy()
        if len(k):
            k["buy"] = k.vol.where(k.buyorsell == 0, 0); k["sell"] = k.vol.where(k.buyorsell == 1, 0)
            g = k.groupby("time").agg(open=("price", "first"), high=("price", "max"), low=("price", "min"),
                                      close=("price", "last"), vol=("vol", "sum"), buy=("buy", "sum"), sell=("sell", "sum")).reset_index()
            g.insert(0, "code", code); g.insert(0, "date", d); bars.append(g)
        if i % 200 == 0:
            print(f"{i}/{len(tg)} 用时{time.time() - t0:.0f}s 失败{fails}", flush=True)
    os.makedirs(a.out, exist_ok=True)
    tag = f"{a.prefix}{a.shard:02d}of{a.nshards:02d}"
    pd.DataFrame(auc).to_csv(f"{a.out}/auction_{tag}.csv.gz", index=False)
    if bars:
        b = pd.concat(bars, ignore_index=True)
        for col in ["open", "high", "low", "close"]:
            b[col] = b[col].astype("float32")
        b.to_csv(f"{a.out}/minbars_{tag}.csv.gz", index=False)
    print("完成", len(auc), "失败", fails, f"{time.time() - t0:.0f}s")

if __name__ == "__main__":
    main()
