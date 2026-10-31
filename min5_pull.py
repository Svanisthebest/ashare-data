#!/usr/bin/env python3
"""
用 baostock 拉全市场（沪深主板、创业板、科创板）5 分钟线，只保留研究需要的时段，
按分片保存为 csv.gz，由工作流上传到 GitHub Release（不进仓库，避免体积问题）。

保留时段：9:35–10:30（开盘第一小时，前 12 根）和 14:30–15:00（尾盘 6 根）。
用法：
    python min5_pull.py --shard 0 --nshards 8 --start 2022-01-01 --out min5
"""
import argparse
import glob
import os
import time

import pandas as pd

KEEP = {f"{h:02d}{m:02d}" for h, m in [(9, 35), (9, 40), (9, 45), (9, 50), (9, 55), (10, 0), (10, 5), (10, 10),
                                         (10, 15), (10, 20), (10, 25), (10, 30), (14, 35), (14, 40), (14, 45),
                                         (14, 50), (14, 55), (15, 0)]}


def universe(root="data/daily"):
    codes = set()
    for f in sorted(glob.glob(os.path.join(root, "*.csv.gz")))[::5] + sorted(glob.glob(os.path.join(root, "*.csv.gz")))[-3:]:
        d = pd.read_csv(f, dtype={"code": str}, usecols=["market", "code"])
        ok = ((d.market == "sh") & d.code.str.match(r"^(60|68)")) | ((d.market == "sz") & d.code.str.match(r"^(00|30)"))
        codes |= set((d.market[ok] + "." + d.code[ok]).tolist())
    return sorted(codes)


def pull(bs, code, start, end):
    for attempt in range(3):
        rs = bs.query_history_k_data_plus(code, "date,time,open,high,low,close,volume,amount",
                                          start_date=start, end_date=end, frequency="5", adjustflag="3")
        if rs.error_code == "0":
            rows = []
            while rs.next():
                r = rs.get_row_data()
                if r[1][8:12] in KEEP:
                    rows.append(r)
            return rows
        time.sleep(2)
        try:
            bs.login()
        except Exception:
            pass
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default=pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d"))
    ap.add_argument("--out", default="min5")
    ap.add_argument("--limit", type=int, default=0, help="只拉前N只（测试用）")
    ap.add_argument("--sample", type=int, default=0, help="随机抽N只（固定种子），0=全部")
    a = ap.parse_args()
    import baostock as bs
    bs.login()
    codes = universe()
    if a.sample:
        import random
        random.Random(42).shuffle(codes)
        codes = sorted(codes[:a.sample])
    codes = codes[a.shard::a.nshards]
    if a.limit:
        codes = codes[:a.limit]
    print(f"分片 {a.shard}/{a.nshards}: {len(codes)} 只", flush=True)
    os.makedirs(a.out, exist_ok=True)
    import json, subprocess
    tag = f"{a.start[:4]}_s{a.sample}_{a.shard:02d}of{a.nshards:02d}"
    f = os.path.join(a.out, f"min5_{tag}.csv.gz")
    pf = os.path.join(a.out, f"progress_{tag}.json")
    repo = os.environ.get("GITHUB_REPOSITORY")
    # 断点续传：先从 Release 取回已有的分片
    if repo:
        subprocess.run(["gh", "release", "download", "min5-data", "-R", repo, "-p", os.path.basename(f), "-D", a.out, "--clobber"], check=False)
    old = pd.read_csv(f, dtype={"code": str, "time": str}) if os.path.exists(f) else None
    done = set(old.code.unique()) if old is not None else set()
    todo = [c for c in codes if c[3:] not in done]
    print(f"已完成 {len(done)}，待拉 {len(todo)}", flush=True)
    parts, t0, secs = ([old] if old is not None else []), time.time(), []

    def save(final=False):
        if not parts:
            return
        df = pd.concat(parts, ignore_index=True)
        df.to_csv(f, index=False)
        json.dump({"done": int(df.code.nunique()), "total": len(codes), "rows": len(df), "avg_sec": round(sum(secs) / max(len(secs), 1), 1),
                   "elapsed_min": round((time.time() - t0) / 60, 1), "final": final}, open(pf, "w"))
        if repo:
            subprocess.run(["gh", "release", "upload", "min5-data", f, pf, "--clobber", "-R", repo], check=False)

    for i, c in enumerate(todo):
        t1 = time.time()
        rows = pull(bs, c, a.start, a.end)
        secs.append(time.time() - t1)
        if rows:
            df = pd.DataFrame([[c[3:]] + r for r in rows], columns=["code", "date", "time", "open", "high", "low", "close", "volume", "amount"])
            for k in ["open", "high", "low", "close", "amount"]:
                df[k] = pd.to_numeric(df[k], errors="coerce").astype("float32")
            df["volume"] = pd.to_numeric(df.volume, errors="coerce").fillna(0).astype("int64")
            df["time"] = df.time.str[8:12]
            df["date"] = pd.to_datetime(df.date)
            parts.append(df)
        print(f"{i + 1}/{len(todo)} {c} 行{len(rows)} {secs[-1]:.0f}s", flush=True)
        if (i + 1) % 10 == 0:
            save()
    bs.logout()
    save(final=True)
    print("完成", f)


if __name__ == "__main__":
    main()
