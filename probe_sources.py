#!/usr/bin/env python3
"""探测各免费数据源的分钟/分时/分笔/竞价数据能回溯到哪一天。结果写入 data/probe_sources.json"""
import json, time, traceback, datetime as dt
import requests
import pandas as pd

OUT = {}
SYMS = ["600519", "300750", "000001"]
DATES = ["20220104", "20230104", "20240103", "20250103", "20260105"]

def rec(k, v):
    OUT[k] = v
    print(k, "=>", json.dumps(v, ensure_ascii=False, default=str)[:600], flush=True)

def safe(k, f):
    try:
        rec(k, f())
    except Exception as e:
        rec(k, {"error": repr(e)[:300]})

# ---------- 通达信（mootdx） ----------
try:
    from mootdx.quotes import Quotes
    c = Quotes.factory(market="std", bestip=True, timeout=15)
except Exception as e:
    c = None
    rec("mootdx_init", {"error": repr(e)})

def tdx_bars_depth(sym, freq):
    first = None; n = 0; start = 0
    while start < 800 * 200:
        df = c.bars(symbol=sym, frequency=freq, start=start, offset=800)
        if df is None or len(df) == 0:
            break
        n += len(df); first = str(df["datetime"].iloc[0]) if "datetime" in df else str(df.index[0])
        start += 800
        time.sleep(0.05)
    return {"bars": n, "earliest": first}

if c:
    for s in SYMS[:2]:
        safe(f"tdx_1min_bars_{s}", lambda s=s: tdx_bars_depth(s, 8))
        safe(f"tdx_5min_bars_{s}", lambda s=s: tdx_bars_depth(s, 0))
        for d in DATES:
            def hm(s=s, d=d):
                df = c.minutes(symbol=s, date=d)
                return {"rows": 0 if df is None else len(df), "head": None if df is None or not len(df) else df.head(3).to_dict("records")}
            safe(f"tdx_history_minute_{s}_{d}", hm)
            def ht(s=s, d=d):
                df = c.transactions(symbol=s, date=d, start=0, offset=2000)
                if df is None or not len(df):
                    return {"rows": 0}
                return {"rows": len(df), "first": df.head(3).to_dict("records"), "last": df.tail(2).to_dict("records")}
            safe(f"tdx_history_ticks_{s}_{d}", ht)

# ---------- 东方财富 ----------
H = {"User-Agent": "Mozilla/5.0"}
def em_kline(sym, klt):
    secid = f"{1 if sym.startswith('6') else 0}.{sym}"
    r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", headers=H, timeout=20, params={
        "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57", "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": klt, "fqt": 0, "secid": secid, "beg": "0", "end": "20500000"})
    k = (r.json().get("data") or {}).get("klines") or []
    return {"bars": len(k), "earliest": k[0][:16] if k else None, "latest": k[-1][:16] if k else None}
for klt in [1, 5, 15, 30, 60]:
    safe(f"em_kline_klt{klt}_600519", lambda klt=klt: em_kline("600519", klt))
def em_trends(ndays):
    r = requests.get("https://push2his.eastmoney.com/api/qt/stock/trends2/get", headers=H, timeout=20, params={
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "ut": "7eea3edcaed734bea9cbfc24409ed989", "ndays": ndays, "iscr": 1, "secid": "1.600519"})
    t = (r.json().get("data") or {}).get("trends") or []
    return {"rows": len(t), "earliest": t[0][:16] if t else None, "first3": t[:3]}
safe("em_trends_ndays5_with_auction", lambda: em_trends(5))
safe("em_trends_ndays30", lambda: em_trends(30))

# ---------- baostock ----------
try:
    import baostock as bs
    bs.login()
    for f in ["5", "15", "60"]:
        def b(f=f):
            rs = bs.query_history_k_data_plus("sh.600519", "date,time,open,close,volume", start_date="2015-01-01",
                                              end_date="2026-12-31", frequency=f, adjustflag="3")
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
            return {"rows": len(rows), "earliest": rows[0] if rows else None, "latest": rows[-1] if rows else None, "err": rs.error_msg}
        safe(f"baostock_{f}min_600519", b)
    bs.logout()
except Exception as e:
    rec("baostock", {"error": repr(e)})

# ---------- 新浪 ----------
def sina(scale):
    r = requests.get("https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData", headers=H, timeout=20,
                     params={"symbol": "sh600519", "scale": scale, "ma": "no", "datalen": 100000})
    txt = r.text; i = txt.find("["); data = json.loads(txt[i:txt.rfind("]") + 1]) if i >= 0 else []
    return {"bars": len(data), "earliest": data[0]["day"] if data else None}
for sc in [1, 5, 15]:
    safe(f"sina_{sc}min_600519", lambda sc=sc: sina(sc))

OUT["_run_at"] = dt.datetime.utcnow().isoformat()
import os
os.makedirs("data", exist_ok=True)
json.dump(OUT, open("data/probe_sources.json", "w"), ensure_ascii=False, indent=1, default=str)
print("done")
