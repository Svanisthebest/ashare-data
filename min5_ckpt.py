#!/usr/bin/env python3
"""
baostock 全天 5 分钟线 → 每只股票每天 7 个检查点（10:00 10:30 11:00 11:30 13:30 14:00 14:30）的
收盘价 c、累计成交量 v、累计成交额 a、到此为止的最低 lo / 最高 hi，加当天开盘 o。研究「盘中弱转强即时买入」用。
每 20 只保存并上传 Release（min5ckpt），可断点续传；每只更新心跳。
"""
import argparse, json, os, subprocess, time
import pandas as pd

CK = ["1000", "1030", "1100", "1130", "1330", "1400", "1430"]

def pull(bs, code, start, end):
    for _ in range(3):
        rs = bs.query_history_k_data_plus(code, "date,time,open,high,low,close,volume,amount",
                                          start_date=start, end_date=end, frequency="5", adjustflag="3")
        if rs.error_code == "0":
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            return rows
        time.sleep(2)
        try: bs.login()
        except Exception: pass
    return []

def ckpt(rows, code):
    df = pd.DataFrame(rows, columns=["date", "time", "open", "high", "low", "close", "volume", "amount"])
    for k in ["open", "high", "low", "close", "volume", "amount"]:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    df["t"] = df.time.str[8:12]
    df = df.sort_values(["date", "t"])
    g = df.groupby("date")
    df["v"] = g.volume.cumsum(); df["a"] = g.amount.cumsum(); df["lo"] = g.low.cummin(); df["hi"] = g.high.cummax()
    o = g.open.first()
    k = df[df.t.isin(CK)].pivot(index="date", columns="t", values=["close", "v", "a", "lo", "hi"])
    k.columns = [f"{a if a != 'close' else 'c'}{t}" for a, t in k.columns]
    k["o"] = o; k["code"] = code[3:]
    return k.reset_index()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default=pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    import baostock as bs
    bs.login()
    codes = pd.read_csv("min5_codes.csv").code.tolist()[a.shard::a.nshards]
    if a.limit: codes = codes[:a.limit]
    repo = os.environ.get("GITHUB_REPOSITORY"); tag = f"{a.shard:02d}of{a.nshards:02d}"
    os.makedirs("out", exist_ok=True); f = f"out/ckpt_{tag}.csv.gz"; pf = f"out/ckpt_progress_{tag}.json"
    up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "min5ckpt", *fs, "--clobber", "-R", repo], check=False)
    if repo:
        subprocess.run(["gh", "release", "download", "min5ckpt", "-R", repo, "-p", os.path.basename(f), "-D", "out", "--clobber"], check=False)
    old = pd.read_csv(f, dtype={"code": str}) if os.path.exists(f) else None
    done = set(old.code.unique()) if old is not None else set()
    todo = [c for c in codes if c[3:] not in done]
    parts, t0 = ([old] if old is not None else []), time.time()
    print(f"分片{tag}: 共 {len(codes)} 只，已完成 {len(done)}，待拉 {len(todo)}", flush=True)
    def beat(stage, i=0, c=""):
        json.dump(dict(stage=stage, i=i, todo=len(todo), resumed=len(done), code=c, min=round((time.time() - t0) / 60, 1),
                       utc=time.strftime("%H:%M:%S", time.gmtime())), open(pf, "w")); up(pf)
    def save():
        if parts: pd.concat(parts, ignore_index=True).to_csv(f, index=False, float_format="%.4g"); up(f)
    beat("start")
    for i, c in enumerate(todo):
        try:
            rows = pull(bs, c, a.start, a.end)
            if rows: parts.append(ckpt(rows, c))
        except Exception as e:
            print("err", c, e, flush=True)
        print(f"{i + 1}/{len(todo)} {c} {len(rows) if rows else 0}行 {time.time() - t0:.0f}s", flush=True)
        if (i + 1) % 5 == 0: beat("running", i + 1, c)
        if (i + 1) % 20 == 0: save()
    bs.logout(); save(); beat("final", len(todo))

if __name__ == "__main__":
    main()
