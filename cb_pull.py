#!/usr/bin/env python3
"""研究用（第四十一轮：T+0 可转债承接买入当天修复）：
1) akshare 拉全部可转债清单（含正股代码、上市日期），2) 对候选股出现过的正股，拉转债日线历史；结果上传 Release cbdata。"""
import os, subprocess, time, traceback
import pandas as pd
import akshare as ak, re
def call(name, **kw):
    for _ in range(3):
        try:
            return getattr(ak, name)(**kw)
        except AttributeError as e:
            m = re.search(r"更名为\s*([A-Za-z0-9_]+)", str(e))
            if not m: raise
            print("改名", name, "->", m.group(1), flush=True); name = m.group(1)
    raise RuntimeError("改名次数过多")
names = [n for n in dir(ak) if ("cov" in n or "bond_cb" in n)]
print("可用转债函数（部分）:", names[:80], flush=True)
os.makedirs("out", exist_ok=True)
repo = os.environ.get("GITHUB_REPOSITORY")
up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "cbdata", *fs, "--clobber", "-R", repo], check=False)
cand = pd.read_csv("cb_cands.csv", dtype=str); stocks = set(cand.code.str.zfill(6))
lst = None
for fn in ("bond_cb_list_em", "bond_zh_cov"):
    try:
        lst = call(fn); print(fn, lst.shape, list(lst.columns), flush=True); print(lst.head(3).to_string(), flush=True); break
    except Exception:
        traceback.print_exc()
lst.to_csv("out/cb_list.csv", index=False); up("out/cb_list.csv")
ccol = [c for c in lst.columns if "债券代码" in c][0]; scol = [c for c in lst.columns if "正股代码" in c][0]
lst[scol] = lst[scol].astype(str).str.zfill(6); lst[ccol] = lst[ccol].astype(str).str.zfill(6)
sel = lst[lst[scol].isin(stocks)]
print("候选正股有转债的转债数", len(sel), "/", len(lst), flush=True)
parts = []; t0 = time.time()
for i, c in enumerate(sel[ccol]):
    sym = ("sh" if c.startswith("11") else "sz") + c
    try:
        d = call("bond_zh_hs_cov_daily", symbol=sym); d["cb"] = c; parts.append(d)
        if i == 0: print(d.tail(2).to_string(), flush=True)
    except Exception as e:
        print("err", sym, e, flush=True)
    if (i + 1) % 50 == 0:
        print(i + 1, f"{time.time()-t0:.0f}s", flush=True)
        pd.concat(parts, ignore_index=True).to_csv("out/cb_daily.csv.gz", index=False); up("out/cb_daily.csv.gz")
    time.sleep(0.3)
if parts:
    pd.concat(parts, ignore_index=True).to_csv("out/cb_daily.csv.gz", index=False); up("out/cb_daily.csv.gz")
print("完成", len(parts), flush=True)
