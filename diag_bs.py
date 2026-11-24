import baostock as bs, time, json
out=[]; lg=bs.login(); out.append(('login',lg.error_code,lg.error_msg))
for c in ('sz.002391','sh.600790','sh.688357'):
    for st,en in (('2020-01-01','2020-12-31'),('2023-01-01','2023-12-31'),('2026-01-01','2026-12-31')):
        t=time.time(); rs=bs.query_history_k_data_plus(c,'date,time,close',start_date=st,end_date=en,frequency='5',adjustflag='3'); n=0
        while rs.error_code=='0' and rs.next(): n+=1
        out.append((c,st,rs.error_code,rs.error_msg,n,round(time.time()-t,1)))
bs.logout(); json.dump(out,open('data/diag_bs.json','w'),ensure_ascii=False,indent=0)
