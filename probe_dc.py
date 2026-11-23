import requests, json
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0'; out={}
U='https://datacenter-web.eastmoney.com/api/data/v1/get'
for rn,sort in (('RPT_HOLDERNUM_DET','END_DATE'),('RPT_LIFT_STAGE','FREE_DATE')):
    try:
        j=S.get(U,params={'reportName':rn,'columns':'ALL','pageSize':3,'pageNumber':1,'sortColumns':sort,'sortTypes':'-1','source':'WEB','client':'WEB'},timeout=20).json()
        out[rn]={'pages':(j.get('result') or {}).get('pages'),'count':(j.get('result') or {}).get('count'),'sample':(j.get('result') or {}).get('data'),'msg':j.get('message')}
    except Exception as e: out[rn]=str(e)
json.dump(out,open('data/probe_dc.json','w'),ensure_ascii=False,indent=1,default=str)
