import json, baostock as bs
out={}; bs.login()
for code in ('sh.000852','sh.000001','sh.512100','sz.159915','sh.510500','sh.600000'):
    for st,en in (('2020-03-02','2020-03-03'),('2016-03-01','2016-03-01'),('2026-11-20','2026-11-20')):
        rs=bs.query_history_k_data_plus(code,'date,time,open,close,amount',start_date=st,end_date=en,frequency='5',adjustflag='3')
        rows=[]
        while rs.error_code=='0' and rs.next(): rows.append(rs.get_row_data())
        out[f'{code}_{st}']=dict(err=rs.error_code,msg=rs.error_msg,n=len(rows),head=rows[:2])
bs.logout(); json.dump(out,open('data/probe_min.json','w'),ensure_ascii=False,indent=1)
