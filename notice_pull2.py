#!/usr/bin/env python3
"""研究用（第四十四轮）：按股票 + 关键词查巨潮公告（stock_zh_a_disclosure_report_cninfo），2015-01-01 至今，关键词：异常波动 / 风险提示 / 停牌核查。上传 Release notices2。"""
import argparse, os, re, subprocess, time
import pandas as pd
import akshare as ak
ap = argparse.ArgumentParser(); ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1); a = ap.parse_args()
os.makedirs("out", exist_ok=True)
repo = os.environ.get("GITHUB_REPOSITORY")
up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "notices2", *fs, "--clobber", "-R", repo], check=False)
def call(name, **kw):
    for _ in range(3):
        try: return getattr(ak, name)(**kw)
        except AttributeError as e:
            m = re.search(r"更名为\s*([A-Za-z0-9_]+)", str(e))
            if not m: raise
            print("改名", name, "->", m.group(1), flush=True); name = m.group(1)
codes = pd.read_csv("notice_codes.csv", dtype=str).code.tolist()[a.shard::a.nshards]
f = f"out/n2_{a.shard:02d}of{a.nshards:02d}.csv.gz"; parts = []; t0 = time.time()
for i, c in enumerate(codes):
    for kw in ("异常波动", "风险提示", "停牌核查"):
        for k in range(3):
            try:
                x = call("stock_zh_a_disclosure_report_cninfo", symbol=c, market="沪深京", keyword=kw, category="", start_date="20150101", end_date="20261231")
                if x is not None and len(x): x["kw"] = kw; x["code6"] = c; parts.append(x)
                if i == 0: print(c, kw, None if x is None else x.shape, None if x is None else list(x.columns), flush=True)
                break
            except Exception as e:
                print("err", c, kw, k, str(e)[:150], flush=True); time.sleep(2 + 4 * k)
    if (i + 1) % 50 == 0:
        if parts: pd.concat(parts).to_csv(f, index=False); up(f)
        print(i + 1, len(codes), f"{time.time()-t0:.0f}s", flush=True)
if parts: pd.concat(parts).to_csv(f, index=False); up(f)
print("完成", len(codes), flush=True)
