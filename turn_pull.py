#!/usr/bin/env python3
"""
baostock 全天 日线换手率 turn（%）、交易状态，研究换手率用。
收盘价 c、累计成交量 v、累计成交额 a、到此为止的最低 lo / 最高 hi，加当天开盘 o。研究「盘中弱转强即时买入」用。
每 20 只保存并上传 Release（min5ckpt），可断点续传；每只更新心跳。
"""
import argparse, json, os, subprocess, time
import pandas as pd


def pull(bs, code, start, end):
    for _ in range(3):
        rs = bs.query_history_k_data_plus(code, "date,turn,tradestatus",
                                          start_date=start, end_date=end, frequency="d", adjustflag="3")
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
    df = pd.DataFrame(rows, columns=["date", "turn", "ts"]); df["turn"] = pd.to_numeric(df.turn, errors="coerce")
    df["code"] = code[3:]; return df[df.ts == "1"][["date", "code", "turn"]]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default=pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    import baostock as bs
    bs.login()
    codes = pd.read_csv("turn_codes.csv").code.tolist()[a.shard::a.nshards]
    if a.limit: codes = codes[:a.limit]
    repo = os.environ.get("GITHUB_REPOSITORY"); tag = f"{a.shard:02d}of{a.nshards:02d}"
    os.makedirs("out", exist_ok=True); f = f"out/turn_{tag}.csv.gz"; pf = f"out/turn_progress_{tag}.json"
    up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", "turnover", *fs, "--clobber", "-R", repo], check=False)
    if repo:
        subprocess.run(["gh", "release", "download", "turnover", "-R", repo, "-p", os.path.basename(f), "-D", "out", "--clobber"], check=False)
    old = pd.read_csv(f, dtype={"code": str}) if os.path.exists(f) else None
    done = set(old.code.unique()) if old is not None else set()
    todo = [c for c in codes if c[3:] not in done]
    parts, t0 = ([old] if old is not None else []), time.time()
    print(f"分片{tag}: 共 {len(codes)} 只，已完成 {len(done)}，待拉 {len(todo)}", flush=True)
    def beat(stage, i=0, c=""):
        json.dump(dict(stage=stage, i=i, todo=len(todo), resumed=len(done), code=c, min=round((time.time() - t0) / 60, 1),
                       utc=time.strftime("%H:%M:%S", time.gmtime())), open(pf, "w")); up(pf)
    def save():
        if parts: pd.concat(parts, ignore_index=True).to_csv(f, index=False, float_format="%.5g"); up(f)
    beat("start")
    for i, c in enumerate(todo):
        try:
            rows = pull(bs, c, a.start, a.end)
            if rows: parts.append(ckpt(rows, c))
        except Exception as e:
            print("err", c, e, flush=True)
        print(f"{i + 1}/{len(todo)} {c} {len(rows) if rows else 0}行 {time.time() - t0:.0f}s", flush=True)
        if (i + 1) % 5 == 0: beat("running", i + 1, c)
        if (i + 1) % 100 == 0: save()
    bs.logout(); save(); beat("final", len(todo))

if __name__ == "__main__":
    main()
