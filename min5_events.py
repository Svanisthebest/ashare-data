#!/usr/bin/env python3
"""
研究用：按 min5_events.csv 里的（代码, 日期）拉 baostock 当天全天 5 分钟线，输出 out/ev5_SSofNN.csv.gz，上传 Release min5ev。
单只 60 秒超时后重连；可断点续传。
"""
import argparse, os, subprocess, time, signal
import pandas as pd

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1); a = ap.parse_args()
    import baostock as bs
    bs.login()
    ev = pd.read_csv("min5_events.csv").iloc[a.shard::a.nshards]
    repo = os.environ.get("GITHUB_REPOSITORY"); tag = f"{a.shard:02d}of{a.nshards:02d}"
    os.makedirs("out", exist_ok=True); f = f"out/ev5_{tag}.csv.gz"
    up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "min5ev", *fs, "--clobber", "-R", repo], check=False)
    if repo: subprocess.run(["gh", "release", "download", "min5ev", "-R", repo, "-p", os.path.basename(f), "-D", "out", "--clobber"], check=False)
    old = pd.read_csv(f, dtype=str) if os.path.exists(f) else None
    done = set(zip(old.code, old.date)) if old is not None else set()
    parts = [old] if old is not None else []
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("超时")))
    todo = [(c, d) for c, d in zip(ev.code, ev.date) if (c, d) not in done]
    print(f"分片{tag}: 待拉 {len(todo)}", flush=True); t0 = time.time()
    for i, (c, d) in enumerate(todo):
        rows = []
        try:
            signal.alarm(60)
            rs = bs.query_history_k_data_plus(c, "date,time,open,high,low,close,volume,amount", start_date=d, end_date=d, frequency="5", adjustflag="3")
            while rs.error_code == "0" and rs.next(): rows.append(rs.get_row_data())
            signal.alarm(0)
        except Exception as e:
            signal.alarm(0); print("err", c, d, e, flush=True)
            try: bs.logout()
            except Exception: pass
            bs.login()
        df = pd.DataFrame(rows or [[d, "", "", "", "", "", "", ""]], columns=["date", "time", "open", "high", "low", "close", "volume", "amount"]); df["code"] = c; df["date"] = d
        parts.append(df)
        if (i + 1) % 50 == 0:
            pd.concat(parts, ignore_index=True).to_csv(f, index=False); up(f); print(i + 1, f"{time.time() - t0:.0f}s", flush=True)
    bs.logout(); pd.concat(parts, ignore_index=True).to_csv(f, index=False); up(f)

if __name__ == "__main__":
    main()
