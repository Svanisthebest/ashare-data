import requests, json
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0'; out={}
for code in ('SH600000','SZ300750','SZ002050'):
    try:
        r=S.get('https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax',params={'code':code},timeout=20); j=r.json()
        out[code+'_ajax_keys']=list(j.keys())
        for k in j:
            v=j[k]; out[f'{code}_{k}_sample']=v[:2] if isinstance(v,list) else v
    except Exception as e: out[code+'_ajax_err']=str(e)
    try:
        r=S.get('https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDLTGD',params={'code':code,'date':'2026-09-30'},timeout=20); j=r.json()
        out[code+'_sdltgd']=j
    except Exception as e: out[code+'_sdltgd_err']=str(e)
json.dump(out,open('data/probe_holders.json','w'),ensure_ascii=False,indent=1,default=str)
print(json.dumps(out,ensure_ascii=False,default=str)[:3000])
