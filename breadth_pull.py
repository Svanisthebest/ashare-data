"""盘中市场宽度（研究用，第六十二轮）：固定 300 只样本股 2020 年起的 5 分钟线，取 9:35 / 10:00 / 10:30 / 11:00 / 14:00 / 收盘价。
   按年分段查询、失败重登重试；CHUNK 分块（每块 30 只）。输出 breadth_min_XX.csv.gz 上传 Release breadth。"""
import baostock as bs, pandas as pd, subprocess, os, time
S=pd.read_csv('data/helper/breadth_sample.csv',dtype=str).code.tolist()
CH=int(os.environ.get('CHUNK','-1'))
if CH>=0: S=S[CH*30:(CH+1)*30]
KEEP={'093500000':'t0935','100000000':'t1000','103000000':'t1030','110000000':'t1100','140000000':'t1400','150000000':'close'}
YEARS=[(f'{y}-01-01',f'{y}-12-31') for y in range(2020,2027)]
def q(code,st,en):
    for k in range(6):
        rs=bs.query_history_k_data_plus(code,'date,time,close',start_date=st,end_date=en,frequency='5',adjustflag='3')
        out=[]
        while rs.error_code=='0' and rs.next(): out.append(rs.get_row_data())
        if rs.error_code=='0': return out
        print('  失败',code,st,rs.error_code,rs.error_msg,'重试',k+1,flush=True); time.sleep(3*(k+1))
        try: bs.logout()
        except Exception: pass
        bs.login()
    return None
bs.login(); rows=[]; fail=[]
for i,c in enumerate(S):
    code=('sh.' if c[0]=='6' else 'sz.')+c; n0=len(rows)
    for st,en in YEARS:
        r=q(code,st,en)
        if r is None: fail.append((c,st)); continue
        for d,t,cl in r:
            key=t[8:]
            if key in KEEP: rows.append((d,c,KEEP[key],cl))
    print(i,c,'新增',len(rows)-n0,flush=True)
bs.logout()
print('失败',len(fail),fail[:20])
D=pd.DataFrame(rows,columns=['date','code','k','p']).pivot_table(index=['date','code'],columns='k',values='p',aggfunc='first').reset_index()
FN=f'breadth_min_{CH:02d}.csv.gz' if CH>=0 else 'breadth_min.csv.gz'
D.to_csv(FN,index=False,compression='gzip'); print(D.shape, D.code.nunique(),'只')
R=os.environ['GITHUB_REPOSITORY']
subprocess.run(['gh','release','upload','breadth',FN,'--clobber','-R',R],check=True)
