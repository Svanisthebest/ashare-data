#!/usr/bin/env python3
"""测速：baostock 5分钟线 和 通达信历史分时，各取几只，记录耗时，写入 data/min5_timing.json"""
import json, time, os, glob
import pandas as pd
out = {}
def log(k, v):
    out[k] = v; print(k, v, flush=True)
    os.makedirs("data", exist_ok=True); json.dump(out, open("data/min5_timing.json", "w"), ensure_ascii=False, indent=1, default=str)
t = time.time()
import baostock as bs
lg = bs.login(); log("bs_login", [lg.error_code, lg.error_msg, round(time.time() - t, 1)])
for code, s, e in [("sh.600519", "2026-01-01", "2026-10-30"), ("sz.300750", "2026-01-01", "2026-10-30"), ("sh.600000", "2022-01-01", "2022-12-31"), ("sz.000001", "2022-01-01", "2026-10-30")]:
    t = time.time()
    rs = bs.query_history_k_data_plus(code, "date,time,close", start_date=s, end_date=e, frequency="5", adjustflag="3")
    n = 0
    while rs.error_code == "0" and rs.next():
        rs.get_row_data(); n += 1
    log(f"bs_{code}_{s[:4]}-{e[:4]}", {"rows": n, "sec": round(time.time() - t, 1), "err": rs.error_msg})
bs.logout()
from mootdx.quotes import Quotes
t = time.time(); c = Quotes.factory(market="std", bestip=True, timeout=15); log("tdx_connect_sec", round(time.time() - t, 1))
t = time.time(); n = 0
for d in ["20240102", "20240103", "20240104", "20240105", "20240108"]:
    for s in ["600519", "300750", "000001", "600000"]:
        df = c.minutes(symbol=s, date=d); n += 0 if df is None else len(df)
log("tdx_history_minute_20req", {"rows": n, "sec": round(time.time() - t, 1)})
t = time.time()
df = c.transactions(symbol="600519", date="20240102", start=0, offset=2000)
pages = 1; first = None
st = 2000
while df is not None and len(df):
    first = df.iloc[0].to_dict()
    df = c.transactions(symbol="600519", date="20240102", start=st, offset=2000); st += 2000; pages += 1
    if pages > 20: break
log("tdx_ticks_full_day", {"pages": pages, "sec": round(time.time() - t, 1), "earliest_tick": first})
