#!/usr/bin/env python3
"""
通达信历史分时：为清单里的（日期, 股票）取当天 240 根 1 分钟价格与成交量。
宽表保存：一行一个（日期, 股票），prices/vols 用 ; 连接。每 1500 个保存并上传一次，可断点续传；每 300 个上传心跳。
"""
import argparse, json, os, subprocess, time
import pandas as pd
from mootdx.quotes import Quotes

def connect():
    for i in range(6):
        try:
            return Quotes.factory(market="std", bestip=(i > 0), timeout=15)
        except Exception as e:
            print("connect fail", e, flush=True); time.sleep(3)
    raise SystemExit("无法连接")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default="tick_targets_intraday.csv")
    ap.add_argument("--shard", type=int, default=0); ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--release", default="minute-data")
    a = ap.parse_args()
    tg = pd.read_csv(a.targets, dtype={"d1": str, "code": str}).iloc[a.shard::a.nshards]
    repo = os.environ.get("GITHUB_REPOSITORY"); tag = f"{a.shard:02d}of{a.nshards:02d}"
    os.makedirs("out", exist_ok=True); f = f"out/minute_{tag}.csv.gz"; pf = f"out/minute_progress_{tag}.json"
    up = lambda *fs: repo and subprocess.run(["gh", "release", "upload", a.release, *fs, "--clobber", "-R", repo], check=False)
    if repo:
        subprocess.run(["gh", "release", "download", a.release, "-R", repo, "-p", os.path.basename(f), "-D", "out", "--clobber"], check=False)
    old = pd.read_csv(f, dtype={"d1": str, "code": str}) if os.path.exists(f) else None
    done = set(zip(old.d1, old.code)) if old is not None else set()
    todo = [(d, c) for d, c in zip(tg.d1, tg.code) if (d, c) not in done]
    parts = [old] if old is not None else []; buf = []; t0 = time.time(); empty = 0; fails = 0
    def beat(stage):
        json.dump(dict(stage=stage, done_run=len(buf) + sum(len(p) for p in parts[1 if old is not None else 0:]), resumed=len(done),
                       todo=len(todo), empty=empty, fails=fails, sec_per=round((time.time() - t0) / max(1, i + 1), 2),
                       elapsed_min=round((time.time() - t0) / 60, 1), utc=time.strftime("%H:%M:%S", time.gmtime())), open(pf, "w"))
        up(pf)
    def save():
        nonlocal buf
        if buf:
            parts.append(pd.DataFrame(buf, columns=["d1", "code", "prices", "vols"])); buf = []
        if parts:
            pd.concat(parts, ignore_index=True).to_csv(f, index=False); up(f)
    i = -1; beat("start"); c = connect()
    for i, (d, code) in enumerate(todo):
        mk = 1 if code.startswith("6") else 0
        r = None
        for att in range(3):
            try:
                r = c.client.get_history_minute_time_data(mk, code, int(d)); break
            except Exception:
                fails += 1; time.sleep(1)
                try: c = connect()
                except SystemExit: pass
        if not r:
            empty += 1; continue
        buf.append((d, code, ";".join(f"{x['price']:.3f}" for x in r), ";".join(str(int(x['vol'])) for x in r)))
        if (i + 1) % 300 == 0: beat("running")
        if (i + 1) % 1500 == 0: save()
    save(); beat("final")

if __name__ == "__main__":
    main()
