import json, time, requests
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36","Referer":"https://data.eastmoney.com/"})
out={}
def t(k,f):
    try: out[k]=f()
    except Exception as e: out[k]={"error":repr(e)[:200]}
    print(k,str(out[k])[:400],flush=True)
def dc(report,flt="",ps=5):
    r=S.get("https://datacenter-web.eastmoney.com/api/data/v1/get",params={"reportName":report,"columns":"ALL","filter":flt,"pageNumber":1,"pageSize":ps,"source":"WEB","client":"WEB"},timeout=20)
    j=r.json(); res=j.get("result") or {}
    return {"status":r.status_code,"pages":res.get("pages"),"count":res.get("count"),"sample":(res.get("data") or [])[:3],"msg":j.get("message")}
t("dc_coretheme_boardtype",lambda:dc("RPT_F10_CORETHEME_BOARDTYPE"))
t("dc_coretheme_boardtype_600261",lambda:dc("RPT_F10_CORETHEME_BOARDTYPE",'(SECURITY_CODE="600261")',50))
t("dc_coretheme_content_600261",lambda:dc("RPT_F10_CORETHEME_CONTENT",'(SECUCODE="600261.SH")',10))
def emweb():
    r=S.get("https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax",params={"code":"SH600261"},timeout=20)
    j=r.json(); return {"status":r.status_code,"keys":list(j.keys()),"ssbk":[x.get("BOARD_NAME") for x in (j.get("ssbk") or [])][:30]}
t("emweb_coreconception_600261",emweb)
def cl(host):
    time.sleep(1.2)
    r=S.get(host+"/api/qt/clist/get",params={"pn":1,"pz":100,"po":1,"np":1,"ut":"bd1d9ddb04089700cf9c27f6f7426281","fltt":2,"invt":2,"fid":"f12","fs":"b:BK0963 f:!50","fields":"f12,f14"},timeout=20)
    return {"status":r.status_code,"txt":r.text[:200]}
for h in ["https://29.push2.eastmoney.com","https://push2.eastmoney.com","https://82.push2.eastmoney.com"]: t("clist_"+h[8:12],lambda h=h:cl(h))
def slist():
    r=S.get("https://push2.eastmoney.com/api/qt/slist/get",params={"spt":3,"secid":"1.600261","fields":"f12,f14","ut":"bd1d9ddb04089700cf9c27f6f7426281","pn":1,"pz":100,"po":1,"fid":"f3"},timeout=20)
    return {"status":r.status_code,"txt":r.text[:300]}
t("slist_600261",slist)
json.dump(out,open("data/probe_theme.json","w"),ensure_ascii=False,indent=1,default=str)
