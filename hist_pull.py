#!/usr/bin/env python3
"""
研究用：baostock 2015-06-01 ~ 2021-12-31 全部 A 股（含已退市）日线，不复权。
字段 date,code,open,high,low,close,preclose,volume,amount,tradestatus,isST；另拉中证1000、上证指数日线。
输出 out/hist_SSofNN.csv.gz，上传 Release hist；单只 60 秒超时后重连；可断点续传。
"""
import argparse, os, subprocess, time, signal
import pandas as pd
START, END = "2015-06-01", "2021-12-31"
F = "date,code,open,high,low,close,preclose,volume,amount,tradestatus,isST"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1); a = ap.parse_args()
    import baostock as bs
    bs.login()
    repo = os.environ.get("GITHUB_REPOSITORY"); tag = f"{a.shard:02d}of{a.nshards:02d}"
    up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "hist", *fs, "--clobber", "-R", repo], check=False)
    os.makedirs("out", exist_ok=True)
    rs = bs.query_stock_basic(); rows = []
    while rs.error_code == "0" and rs.next(): rows.append(rs.get_row_data())
    B = pd.DataFrame(rows, columns=rs.fields)
    B = B[(B.type == "1") & B.code.str.match(r"^(sh\.60|sh\.68|sz\.00|sz\.30)")]
    B = B[(B.ipoDate <= END) & ((B.outDate == "") | (B.outDate >= START))].sort_values("code")
    if a.shard == 0:
        B.to_csv("out/hist_basic.csv", index=False); up("out/hist_basic.csv")
        ix = []
        for c in ["sh.000852", "sh.000001", "sz.399006"]:
            r = bs.query_history_k_data_plus(c, "date,code,open,high,low,close,preclose,volume,amount", start_date=START, end_date=END, frequency="d")
            while r.error_code == "0" and r.next(): ix.append(r.get_row_data())
        pd.DataFrame(ix, columns="date,code,open,high,low,close,preclose,volume,amount".split(",")).to_csv("out/hist_index.csv.gz", index=False); up("out/hist_index.csv.gz")
    codes = B.code.tolist()[a.shard::a.nshards]
    f = f"out/hist_{tag}.csv.gz"
    if repo: subprocess.run(["gh", "release", "download", "hist", "-R", repo, "-p", os.path.basename(f), "-D", "out", "--clobber"], check=False)
    old = pd.read_csv(f, dtype=str) if os.path.exists(f) else None
    done = set(old.code.unique()) if old is not None else set()
    parts = [old] if old is not None else []
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("超时")))
    todo = [c for c in codes if c not in done]; t0 = time.time()
    print(f"分片{tag}: 共 {len(codes)}，待拉 {len(todo)}", flush=True)
    for i, c in enumerate(todo):
        rows = []
        for attempt in range(2):
            try:
                signal.alarm(90)
                r = bs.query_history_k_data_plus(c, F, start_date=START, end_date=END, frequency="d", adjustflag="3")
                while r.error_code == "0" and r.next(): rows.append(r.get_row_data())
                signal.alarm(0); break
            except Exception as e:
                signal.alarm(0); print("err", c, e, flush=True); rows = []
                try: bs.logout()
                except Exception: pass
                bs.login()
        if rows: parts.append(pd.DataFrame(rows, columns=F.split(",")))
        else: parts.append(pd.DataFrame([[START, c] + [""] * 9], columns=F.split(",")))
        if (i + 1) % 40 == 0:
            pd.concat(parts, ignore_index=True).to_csv(f, index=False); up(f); print(i + 1, f"{time.time() - t0:.0f}s", flush=True)
    bs.logout(); pd.concat(parts, ignore_index=True).to_csv(f, index=False); up(f)

if __name__ == "__main__":
    main()
