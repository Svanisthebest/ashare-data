"""盘中市场宽度（研究用，第六十二轮）：固定 300 只样本股 2020 年起的 5 分钟线，取 9:35 / 10:00 / 10:30 / 11:00 / 14:00 的价格。
   输出 breadth_min.csv.gz（date, code, t0935, t1000, t1030, t1100, t1400, close），上传 Release breadth。"""
import baostock as bs, pandas as pd, subprocess, os, time
S=pd.read_csv('data/helper/breadth_sample.csv',dtype=str).code.tolist()
KEEP={'093500000':'t0935','100000000':'t1000','103000000':'t1030','110000000':'t1100','140000000':'t1400','150000000':'close'}
bs.login(); rows=[]
for i,c in enumerate(S):
    code=('sh.' if c[0]=='6' else 'sz.')+c
    for k in range(3):
        rs=bs.query_history_k_data_plus(code,'date,time,close',start_date='2020-01-01',end_date='2026-12-31',frequency='5',adjustflag='3')
        if rs.error_code=='0': break
        time.sleep(2); bs.login()
    while rs.error_code=='0' and rs.next():
        d,t,cl=rs.get_row_data(); key=t[8:]
        if key in KEEP: rows.append((d,c,KEEP[key],cl))
    if i%20==0: print(i,len(rows),flush=True)
bs.logout()
D=pd.DataFrame(rows,columns=['date','code','k','p']).pivot_table(index=['date','code'],columns='k',values='p',aggfunc='first').reset_index()
D.to_csv('breadth_min.csv.gz',index=False,compression='gzip'); print(D.shape)
R=os.environ['GITHUB_REPOSITORY']
subprocess.run(f'gh release view breadth -R {R} || gh release create breadth -R {R} -t "盘中宽度样本" -n "breadth_pull.py 生成，研究用"',shell=True)
subprocess.run(['gh','release','upload','breadth','breadth_min.csv.gz','--clobber','-R',R],check=True)
