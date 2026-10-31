#!/usr/bin/env python3
"""通达信历史分时：主要指数每天 240 根 1 分钟线（价格、成交量），按日期分片，输出 csv.gz 并写心跳"""
import argparse, glob, json, os, subprocess, time
import pandas as pd
from mootdx.quotes import Quotes

IDX = [(1, "000001", "上证指数"), (1, "000300", "沪深300"), (1, "000905", "中证500"), (1, "000852", "中证1000"),
       (0, "399001", "深证成指"), (0, "399006", "创业板指"), (0, "399303", "国证2000"), (1, "000688", "科创50")]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1)
    a = ap.parse_args()
    dates = sorted(os.path.basename(f)[:8] for f in glob.glob("data/daily/*.csv.gz"))[a.shard::a.nshards]
    repo = os.environ.get("GITHUB_REPOSITORY"); tag = f"{a.shard:02d}of{a.nshards:02d}"
    pf = f"out/idxmin_progress_{tag}.json"; os.makedirs("out", exist_ok=True)
    def beat(**k):
        json.dump(dict(k, utc=time.strftime("%H:%M:%S", time.gmtime())), open(pf, "w"), ensure_ascii=False)
        if repo: subprocess.run(["gh", "release", "upload", "min5-data", pf, "--clobber", "-R", repo], check=False)
    c = Quotes.factory(market="std", bestip=True, timeout=15)
    rows, t0, empty = [], time.time(), 0
    for i, d in enumerate(dates):
        for mk, code, name in IDX:
            for att in range(3):
                try:
                    r = c.client.get_history_minute_time_data(mk, code, int(d)); break
                except Exception as e:
                    r = None; time.sleep(1)
                    try: c = Quotes.factory(market="std", bestip=True, timeout=15)
                    except Exception: pass
            if not r:
                empty += 1; continue
            for j, x in enumerate(r):
                rows.append((d, code, name, j, x.get("price"), x.get("vol")))
        if i % 20 == 0:
            beat(done=i + 1, total=len(dates), rows=len(rows), empty=empty, elapsed_min=round((time.time() - t0) / 60, 1))
    df = pd.DataFrame(rows, columns=["date", "code", "name", "minute_idx", "price", "vol"])
    f = f"out/idxmin_{tag}.csv.gz"; df.to_csv(f, index=False)
    if repo: subprocess.run(["gh", "release", "upload", "min5-data", f, "--clobber", "-R", repo], check=False)
    beat(done=len(dates), total=len(dates), rows=len(rows), empty=empty, final=True, elapsed_min=round((time.time() - t0) / 60, 1))

if __name__ == "__main__":
    main()
