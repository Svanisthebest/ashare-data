#!/usr/bin/env python3
"""研究用（第四十三轮：龙虎榜）：按月拉 2015-06 起龙虎榜明细（stock_lhb_detail_em）与机构买卖统计（stock_lhb_jgmmtj_em），上传 Release lhbdata。"""
import os, re, subprocess, time, traceback
import pandas as pd
import akshare as ak
os.makedirs("out", exist_ok=True)
repo = os.environ.get("GITHUB_REPOSITORY")
up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "lhbdata", *fs, "--clobber", "-R", repo], check=False)
def call(name, **kw):
    for _ in range(3):
        try: return getattr(ak, name)(**kw)
        except AttributeError as e:
            m = re.search(r"更名为\s*([A-Za-z0-9_]+)", str(e))
            if not m: raise
            print("改名", name, "->", m.group(1), flush=True); name = m.group(1)
months = pd.period_range("2015-06", "2026-11", freq="M")
for fn, out in (("stock_lhb_detail_em", "lhb_detail.csv.gz"), ("stock_lhb_jgmmtj_em", "lhb_jg.csv.gz")):
    parts = []; t0 = time.time()
    for i, m in enumerate(months):
        s = m.start_time.strftime("%Y%m%d"); e = m.end_time.strftime("%Y%m%d")
        for k in range(3):
            try:
                d = call(fn, start_date=s, end_date=e)
                if d is not None and len(d): parts.append(d)
                if i == 0 or i == len(months) - 1: print(fn, m, d.shape, list(d.columns), flush=True)
                break
            except Exception as ex:
                print("err", fn, m, k, str(ex)[:200], flush=True); time.sleep(3 + 5 * k)
        time.sleep(0.5)
        if (i + 1) % 24 == 0 and parts:
            pd.concat(parts, ignore_index=True).to_csv("out/" + out, index=False); up("out/" + out); print(fn, i + 1, f"{time.time()-t0:.0f}s", flush=True)
    if parts:
        pd.concat(parts, ignore_index=True).to_csv("out/" + out, index=False); up("out/" + out)
    print("完成", fn, len(parts), flush=True)
