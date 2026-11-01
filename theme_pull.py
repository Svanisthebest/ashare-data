#!/usr/bin/env python3
"""
东方财富 概念板块 + 行业板块：板块列表、成分股、板块日线（近 ~250 个交易日）。
输出 data/theme/boards.csv, members.csv, board_kline.csv.gz, progress.json（每 20 个板块写一次进度）。
"""
import json, os, time, random
import requests, pandas as pd

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                  "Referer": "https://quote.eastmoney.com/"})
UT = "bd1d9ddb04089700cf9c27f6f7426281"
OUT = "data/theme"; os.makedirs(OUT, exist_ok=True)

def get(url, params, tries=4):
    for i in range(tries):
        try:
            time.sleep(0.15 + random.random() * 0.15)
            r = S.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            err = e
        time.sleep(1 + i)
    return None

def clist(fs, fields):
    rows, pn = [], 1
    while True:
        j = get("https://push2.eastmoney.com/api/qt/clist/get", {"pn": pn, "pz": 100, "po": 1, "np": 1, "ut": UT, "fltt": 2, "invt": 2,
                                                                  "fid": "f3", "fs": fs, "fields": fields})
        d = (j or {}).get("data") or {}
        diff = d.get("diff") or []
        rows += diff
        if not diff or len(rows) >= (d.get("total") or 0):
            break
        pn += 1
    return rows

prog = {"start": time.strftime("%H:%M:%S", time.gmtime())}
def beat(**k):
    prog.update(k, utc=time.strftime("%H:%M:%S", time.gmtime())); json.dump(prog, open(f"{OUT}/progress.json", "w"), ensure_ascii=False)

boards = []
for typ, fs in [("概念", "m:90+t:3+f:!50"), ("行业", "m:90+t:2+f:!50")]:
    for r in clist(fs, "f12,f14,f3,f6,f104,f105"):
        boards.append(dict(type=typ, bk=r.get("f12"), name=r.get("f14"), pct=r.get("f3"), amount=r.get("f6"), up=r.get("f104"), down=r.get("f105")))
B = pd.DataFrame(boards).drop_duplicates("bk"); B.to_csv(f"{OUT}/boards.csv", index=False)
beat(boards=len(B))
mem, kl = [], []
for i, r in enumerate(B.itertuples()):
    for m in clist(f"b:{r.bk}+f:!50", "f12,f14"):
        mem.append((r.bk, m.get("f12"), m.get("f14")))
    j = get("https://push2his.eastmoney.com/api/qt/stock/kline/get", {"secid": f"90.{r.bk}", "klt": 101, "fqt": 0, "lmt": 260, "end": "20500101",
                                                                      "ut": UT, "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57,f59"})
    for line in ((j or {}).get("data") or {}).get("klines") or []:
        p = line.split(","); kl.append((r.bk, p[0], p[1], p[2], p[3], p[4], p[6], p[7]))
    if i % 20 == 0:
        beat(done=i + 1, total=len(B), members=len(mem), klines=len(kl))
pd.DataFrame(mem, columns=["bk", "code", "name"]).to_csv(f"{OUT}/members.csv", index=False)
pd.DataFrame(kl, columns=["bk", "date", "open", "close", "high", "low", "amount", "pct"]).to_csv(f"{OUT}/board_kline.csv.gz", index=False)
beat(done=len(B), total=len(B), members=len(mem), klines=len(kl), final=True)
print("boards", len(B), "members", len(mem), "klines", len(kl))
