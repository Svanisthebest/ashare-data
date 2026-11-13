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
from concurrent.futures import ThreadPoolExecutor
OUT='data/cb/hist.csv.gz'
done=set(); old=None
if os.path.exists(OUT):
    old=pd.read_csv(OUT,dtype={'ZCODE':str}); done=set(old.ZCODE)
codes=[c for c,ld in zip(L.SECURITY_CODE.astype(str),L.LISTING_DATE) if isinstance(ld,str) and c not in done]
print('待拉',len(codes),'已有',len(done),flush=True)
def one(c):
    out=[]; pg=1
    while True:
        r=get(reportName="RPTA_WEB_KZZ_LS",pageSize=500,pageNumber=pg,filter=f'(ZCODE="{c}")',sortColumns="DATE",sortTypes="1")
        d=r.get('data') or []; out+=[{k:x.get(k) for k in ['DATE','ZCODE','FCLOSE','SWAPVALUE','SWAPOR','PUREBONDVALUE','PUREBONDOR']} for x in d]
        if not d or pg>=(r.get('pages') or 1): break
        pg+=1
    return out
t0=time.time(); parts=[old] if old is not None else []
ex=ThreadPoolExecutor(3)
if True:
    buf=[]
    for i,o in enumerate(ex.map(one,codes)):
        buf+=o
        if (i+1)%100==0 or i==len(codes)-1:
            parts.append(pd.DataFrame(buf)); buf=[]
            pd.concat(parts,ignore_index=True).to_csv(OUT,index=False,compression='gzip')
            print(i+1,f'{time.time()-t0:.0f}s',flush=True)
        if time.time()-t0>45*60: 
            if buf: parts.append(pd.DataFrame(buf)); pd.concat(parts,ignore_index=True).to_csv(OUT,index=False,compression='gzip')
            print('时间到，下次续拉'); ex.shutdown(wait=False,cancel_futures=True); break
