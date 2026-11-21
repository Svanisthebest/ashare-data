#!/usr/bin/env python3
"""研究用（第四十二轮：T+0 品种上的「错杀修复」）：拉 T+0 ETF（跨境/黄金/商品/债券）日线 + 股指期货主力连续日线，上传 Release t0data。"""
import os, re, subprocess, time, traceback
import pandas as pd
import akshare as ak
os.makedirs("out", exist_ok=True)
repo = os.environ.get("GITHUB_REPOSITORY")
up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "t0data", *fs, "--clobber", "-R", repo], check=False)
def call(name, **kw):
    for _ in range(3):
        try: return getattr(ak, name)(**kw)
        except AttributeError as e:
            m = re.search(r"更名为\s*([A-Za-z0-9_]+)", str(e))
            if not m: raise
            print("改名", name, "->", m.group(1), flush=True); name = m.group(1)
# 1) 股指期货主力连续
fut = []
for s in ("IF0", "IH0", "IC0", "IM0"):
    try:
        d = call("futures_main_sina", symbol=s); d["sym"] = s; fut.append(d); print(s, d.shape, list(d.columns)[:8], flush=True)
    except Exception: traceback.print_exc()
if fut: pd.concat(fut).to_csv("out/fut_daily.csv", index=False); up("out/fut_daily.csv")
# 2) ETF 清单 → 名称关键词筛 T+0（跨境、黄金、商品、债券）
lst = call("fund_etf_spot_em"); print("ETF 清单", lst.shape, list(lst.columns)[:10], flush=True)
lst.to_csv("out/etf_list.csv", index=False); up("out/etf_list.csv")
kw = "纳指|纳斯达克|标普|道琼斯|日经|东证|恒生|港股|H股|中概|德国|法国|欧洲|亚太|沙特|东南亚|美国|海外|全球|黄金|白银|豆粕|有色|能源化工|原油|债|国债|信用|可转债"
ncol = [c for c in lst.columns if "名称" in c][0]; ccol = [c for c in lst.columns if "代码" in c][0]
sel = lst[lst[ncol].astype(str).str.contains(kw) & ~lst[ncol].astype(str).str.contains("货币")]
print("候选 T+0 ETF", len(sel), flush=True)
parts = []
for i, (c, n) in enumerate(zip(sel[ccol].astype(str), sel[ncol])):
    try:
        d = call("fund_etf_hist_em", symbol=c, period="daily", start_date="20150101", end_date="20261231", adjust=""); d["code"] = c; d["name"] = n; parts.append(d)
    except Exception as e: print("err", c, e, flush=True)
    if (i + 1) % 40 == 0:
        pd.concat(parts).to_csv("out/etf_daily.csv.gz", index=False); up("out/etf_daily.csv.gz"); print(i + 1, flush=True)
    time.sleep(0.3)
if parts: pd.concat(parts).to_csv("out/etf_daily.csv.gz", index=False); up("out/etf_daily.csv.gz")
print("完成", len(parts), flush=True)
