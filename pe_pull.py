#!/usr/bin/env python3
"""研究用：按 pe_sigdays.csv 的（代码, 信号日）拉 baostock 日线估值（peTTM、pbMRQ、psTTM、总市值近似用 close×流通股不可得，故只取估值），输出 out/pe_SSofNN.csv.gz 上传 Release pesig。"""
import argparse, os, subprocess, signal, time
import pandas as pd
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,default=0); ap.add_argument("--nshards",type=int,default=1); a=ap.parse_args()
    import baostock as bs
    bs.login()
    ev=pd.read_csv("pe_sigdays.csv").iloc[a.shard::a.nshards]
    repo=os.environ.get("GITHUB_REPOSITORY"); tag=f"{a.shard:02d}of{a.nshards:02d}"
    os.makedirs("out",exist_ok=True); f=f"out/pe_{tag}.csv.gz"
    up=lambda *fs: repo and subprocess.run(["gh","release","upload","pesig",*fs,"--clobber","-R",repo],check=False)
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("超时")))
    rows=[]; t0=time.time()
    for i,(c,d) in enumerate(zip(ev.code,ev.date)):
        r=None
        try:
            signal.alarm(60)
            rs=bs.query_history_k_data_plus(c,"date,code,close,peTTM,pbMRQ,psTTM,isST,turn",start_date=d,end_date=d,frequency="d",adjustflag="3")
            while rs.error_code=="0" and rs.next(): r=rs.get_row_data()
            signal.alarm(0)
        except Exception as e:
            signal.alarm(0); print("err",c,d,e,flush=True)
            try: bs.logout()
            except Exception: pass
            bs.login()
        rows.append(r or [d,c,"","","","","",""])
        if (i+1)%300==0:
            pd.DataFrame(rows,columns=["date","code","close","peTTM","pbMRQ","psTTM","isST","turn"]).to_csv(f,index=False); up(f); print(i+1,f"{time.time()-t0:.0f}s",flush=True)
    bs.logout(); pd.DataFrame(rows,columns=["date","code","close","peTTM","pbMRQ","psTTM","isST","turn"]).to_csv(f,index=False); up(f)
if __name__=="__main__": main()
