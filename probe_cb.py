"""研究：探测东方财富可转债列表与单券历史估值接口字段。输出 data/probe_cb.json"""
import json, requests
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
H = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
out = {}
r = requests.get(URL, params=dict(reportName="RPT_BOND_CB_LIST", columns="ALL", pageSize=5, pageNumber=1, sortColumns="PUBLIC_START_DATE", sortTypes="-1", source="WEB", client="WEB"), headers=H, timeout=20).json()
out['list_count'] = (r.get('result') or {}).get('count'); out['list_sample'] = (r.get('result') or {}).get('data', [])[:2]
for rep, flt in [("RPTA_WEB_KZZ_LS", '(ZCODE="113052")'), ("RPT_BOND_CB_VALUEANALYSIS", '(SECURITY_CODE="113052")')]:
    try:
        r = requests.get(URL, params=dict(reportName=rep, columns="ALL", pageSize=5, pageNumber=1, source="WEB", client="WEB", filter=flt), headers=H, timeout=20).json()
        out[rep] = dict(count=(r.get('result') or {}).get('count'), sample=(r.get('result') or {}).get('data', [])[:2], msg=r.get('message'))
    except Exception as e:
        out[rep] = repr(e)
try:
    r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh113052,day,2020-01-01,2020-02-01,50,", timeout=20).json()
    out['qq_bond'] = str(r)[:600]
except Exception as e: out['qq_bond'] = repr(e)
json.dump(out, open('data/probe_cb.json', 'w'), ensure_ascii=False, indent=1, default=str); print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
