#!/usr/bin/env python3
"""研究用（第四十四轮：风险类公告）：逐日拉沪深全部公告标题（akshare stock_notice_report），只保留含「异常波动 / 风险提示 / 停牌核查 / 严重异常 / 偏离」的，上传 Release notices。
按年份分片（--shard 年份序号）。"""
import argparse, os, re, subprocess, time
import pandas as pd
import akshare as ak
ap = argparse.ArgumentParser(); ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1); a = ap.parse_args()
os.makedirs("out", exist_ok=True)
repo = os.environ.get("GITHUB_REPOSITORY")
up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "notices", *fs, "--clobber", "-R", repo], check=False)
def call(name, **kw):
    for _ in range(3):
        try: return getattr(ak, name)(**kw)
        except AttributeError as e:
            m = re.search(r"更名为\s*([A-Za-z0-9_]+)", str(e))
            if not m: raise
            print("改名", name, "->", m.group(1), flush=True); name = m.group(1)
years = list(range(2015, 2027)); ys = years[a.shard::a.nshards]
pat = "异常波动|风险提示|停牌核查|严重异常|偏离"
for y in ys:
    days = pd.bdate_range(f"{y}-01-01", f"{y}-12-31"); parts = []; f = f"out/notice_{y}.csv.gz"
    for i, d in enumerate(days):
        ds = d.strftime("%Y%m%d")
        for k in range(3):
            try:
                x = call("stock_notice_report", symbol="全部", date=ds)
                if x is not None and len(x):
                    tcol = [c for c in x.columns if "标题" in c][0]
                    x = x[x[tcol].astype(str).str.contains(pat)]; x["date"] = ds; parts.append(x)
                if i == 0: print(y, ds, list(x.columns) if x is not None else None, flush=True)
                break
            except Exception as e:
                print("err", ds, k, str(e)[:150], flush=True); time.sleep(3 + 5 * k)
        if (i + 1) % 60 == 0 and parts:
            pd.concat(parts).to_csv(f, index=False); up(f); print(y, i + 1, flush=True)
    if parts: pd.concat(parts).to_csv(f, index=False); up(f)
    print("完成", y, sum(len(p) for p in parts), flush=True)
