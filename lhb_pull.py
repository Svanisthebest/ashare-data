#!/usr/bin/env python3
"""东方财富数据中心：龙虎榜营业部买入/卖出明细（2022-01 起），按季度分段翻页，存 data/lhb/。"""
import json, os, time
import pandas as pd, requests
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
os.makedirs("data/lhb", exist_ok=True); log = {}
def get(rep, d0, d1, page):
    p = dict(reportName=rep, columns="ALL", pageSize=500, pageNumber=page, sortColumns="TRADE_DATE,SECURITY_CODE",
             sortTypes="1,1", source="WEB", client="WEB", filter=f"(TRADE_DATE>='{d0}')(TRADE_DATE<='{d1}')")
    for k in range(6):
        try:
            j = requests.get(URL, params=p, headers=H, timeout=20).json()
            if j.get("result") is not None or j.get("code") in (9201,):
                return j
        except Exception as e:
            pass
        time.sleep(2 + 3 * k)
    return None
for rep, tag in [("RPT_BILLBOARD_DAILYDETAILSBUY", "buy"), ("RPT_BILLBOARD_DAILYDETAILSSELL", "sell")]:
    rows = []
    for q in pd.date_range("2022-01-01", pd.Timestamp.now().strftime("%Y-%m-%d"), freq="QS"):
        d0 = q.strftime("%Y-%m-%d"); d1 = (q + pd.offsets.QuarterEnd(0)).strftime("%Y-%m-%d"); page, pages = 1, 1
        while page <= pages:
            j = get(rep, d0, d1, page)
            if not j or not j.get("result"):
                log[f"{tag}_{d0}_p{page}"] = str(j)[:200]; break
            pages = j["result"]["pages"]; rows += j["result"]["data"]; page += 1; time.sleep(0.4)
        log[f"{tag}_{d0}"] = dict(pages=pages, rows=len(rows)); print(tag, d0, pages, len(rows), flush=True)
        json.dump(log, open("data/lhb/log.json", "w"), ensure_ascii=False, indent=1)
    df = pd.DataFrame(rows)
    if len(df):
        log[f"{tag}_cols"] = list(df.columns)
        df.to_csv(f"data/lhb/lhb_{tag}.csv.gz", index=False)
    json.dump(log, open("data/lhb/log.json", "w"), ensure_ascii=False, indent=1)
print("完成")
