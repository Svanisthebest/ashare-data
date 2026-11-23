"""股东户数（全市场历史，含公告日）与限售解禁（全历史）。研究用，第五十九轮。上传到 Release hndata。"""
import requests, time, pandas as pd, subprocess, os
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0'
U='https://datacenter-web.eastmoney.com/api/data/v1/get'
def pull(rn,sort,cols,fn,ps=500):
    rows=[];p=1;pages=None
    while True:
        for k in range(5):
            try:
                j=S.get(U,params={'reportName':rn,'columns':cols,'pageSize':ps,'pageNumber':p,'sortColumns':sort,'sortTypes':'-1','source':'WEB','client':'WEB'},timeout=30).json(); break
            except Exception as e: print('重试',rn,p,e); time.sleep(3*(k+1))
        else: raise SystemExit(f'{rn} 第 {p} 页失败')
        r=j.get('result') or {}; pages=r.get('pages',pages); rows+=r.get('data') or []
        if p%50==0: print(rn,p,'/',pages,flush=True)
        if not pages or p>=pages: break
        p+=1; time.sleep(0.15)
    d=pd.DataFrame(rows); d.to_csv(fn,index=False,compression='gzip'); print(rn,len(d),'行 →',fn,flush=True)
    subprocess.run(['gh','release','upload','hndata',fn,'--clobber','-R',os.environ['GITHUB_REPOSITORY']],check=True)
pull('RPT_HOLDERNUM_DET','END_DATE','SECURITY_CODE,END_DATE,HOLD_NOTICE_DATE,HOLDER_NUM,PRE_HOLDER_NUM,HOLDER_NUM_RATIO,PRE_END_DATE,AVG_MARKET_CAP,TOTAL_MARKET_CAP,TOTAL_A_SHARES,CLOSE_PRICE','holdernum.csv.gz')
pull('RPT_LIFT_STAGE','FREE_DATE','SECURITY_CODE,FREE_DATE,FREE_SHARES_TYPE,ABLE_FREE_SHARES,FREE_RATIO,TOTAL_RATIO,LIFT_MARKET_CAP,BATCH_HOLDER_NUM,EUTIME','lift.csv.gz')
