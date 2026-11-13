"""研究：可转债全量列表 + 每只每日估值（收盘价、转股价值、转股溢价率、纯债价值）。输出 data/cb/list.csv、data/cb/hist.csv.gz"""
import os, time, requests, pandas as pd
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
os.makedirs('data/cb', exist_ok=True)
def get(**p):
    for k in range(6):
        try:
            j = requests.get(URL, params=dict(columns="ALL", source="WEB", client="WEB", **p), headers=H, timeout=25).json()
            return j.get('result') or {}
        except Exception as e:
            time.sleep(2 * (k + 1))
    return {}
rows, pg = [], 1
while True:
    r = get(reportName="RPT_BOND_CB_LIST", pageSize=500, pageNumber=pg, sortColumns="SECURITY_CODE", sortTypes="1")
    d = r.get('data') or []; rows += d
    if not d or pg >= (r.get('pages') or 1): break
    pg += 1
L = pd.DataFrame(rows)
keep = ['SECURITY_CODE','SECURITY_NAME_ABBR','TRADE_MARKET','LISTING_DATE','DELIST_DATE','CONVERT_STOCK_CODE','RATING','ACTUAL_ISSUE_SCALE','EXPIRE_DATE','INITIAL_TRANSFER_PRICE','REDEEM_TYPE','NOTICE_DATE_SH','NOTICE_DATE_HS','EXECUTE_REASON_SH']
L[[c for c in keep if c in L]].to_csv('data/cb/list.csv', index=False); print('列表', len(L), flush=True)
H_ = []
codes = [c for c, ld in zip(L.SECURITY_CODE, L.LISTING_DATE) if isinstance(ld, str)]
for i, c in enumerate(codes):
    pg = 1
    while True:
        r = get(reportName="RPTA_WEB_KZZ_LS", pageSize=500, pageNumber=pg, filter=f'(ZCODE="{c}")', sortColumns="DATE", sortTypes="1")
        d = r.get('data') or []; H_ += [{k: x.get(k) for k in ['DATE','ZCODE','FCLOSE','SWAPVALUE','SWAPOR','PUREBONDVALUE','PUREBONDOR']} for x in d]
        if not d or pg >= (r.get('pages') or 1): break
        pg += 1
    time.sleep(0.15)
    if (i + 1) % 100 == 0: print(i + 1, len(H_), flush=True)
pd.DataFrame(H_).to_csv('data/cb/hist.csv.gz', index=False, compression='gzip'); print('历史行数', len(H_))
