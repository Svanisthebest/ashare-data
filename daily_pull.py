#!/usr/bin/env python3
"""
A股每日复盘数据拉取 v2 —— 按 V3.0 复盘框架补齐数据缺口。

数据源（接口摘自 a-stock-data，见 sources.py）：
    通达信官网盘后包   全A日线（含已停牌以外的全部有价证券），每日约2.7MB，并累积成本地历史库
    东方财富 push2ex   涨停池（首封/末封时间、炸板次数、连板、封板资金）、炸板池、跌停池、昨日涨停池
    同花顺涨停揭秘     涨停原因题材、板型、封板成功率
    东方财富           重点监控池、严重异常波动（红色预警）
    巨潮资讯           重点股票近几日公告（关键词标注）

用法：
    pip install -r requirements.txt
    python daily_pull.py                       # 默认北京时间今天
    python daily_pull.py --date 20261030
    python daily_pull.py --date 20261030 --backfill 130   # 先补齐130个交易日历史再处理当天

输出：
    data/daily/YYYYMMDD.csv.gz   全A日线历史库（每个交易日一份，复盘时直接读取）
    data/index/YYYYMMDD.csv      主要指数
    data/YYYYMMDD/
        00_quality.csv           各模块状态、行数、错误 —— 报告首页的数据状态
        01_market_scan.csv       全A当日扫描：涨跌幅、成交额、按规则算的涨停/触板/炸板/跌停、新鲜度与位置特征
        02_zt_pool.csv           东财涨停池 + 同花顺涨停原因（按代码合并）
        03_zb_pool.csv           炸板池
        04_dt_pool.csv           跌停池
        05_yzt_pool.csv          昨日涨停池今日表现
        06_ths_reason.csv        同花顺涨停揭秘原表
        07_risk_monitor.csv      重点监控池（当前生效）
        08_risk_anomaly.csv      严重异常波动明细
        09_notices.csv           重点股票公告（含风险关键词）
        10_theme_stats.csv       涨停原因题材词频与连板分布
        summary.json             市场总表
"""
import argparse
import datetime as dt
import glob
import json
import os
import time
import traceback
from collections import Counter

import pandas as pd

import sources as S

CN = dt.timezone(dt.timedelta(hours=8))
RISK_WORDS = ["减持", "问询", "关注函", "监管函", "立案", "调查", "处罚", "异常波动", "严重异常", "停牌",
              "核查", "退市", "风险提示", "风险警示", "解禁", "质押", "预亏", "亏损", "终止", "诉讼",
              "冻结", "警示函", "澄清"]
INDEX_KEYS = {("sh", "000001"): "上证指数", ("sz", "399001"): "深证成指", ("sz", "399006"): "创业板指",
              ("sh", "000688"): "科创50", ("sh", "000300"): "沪深300", ("sh", "000905"): "中证500",
              ("sh", "000852"): "中证1000", ("bj", "899050"): "北证50"}


# ----------------------------------------------------------------------------- 工具
def step(q, name, fn):
    t0 = time.time()
    try:
        out = fn()
        n = len(out) if hasattr(out, "__len__") else (0 if out is None else 1)
        q.append({"模块": name, "状态": "成功" if n else "空", "行数": n,
                  "耗时秒": round(time.time() - t0, 1), "错误": ""})
        return out
    except Exception as e:
        q.append({"模块": name, "状态": "失败", "行数": 0, "耗时秒": round(time.time() - t0, 1),
                  "错误": f"{type(e).__name__}: {e}"[:300]})
        traceback.print_exc()
        return None


def is_a_share(market, code):
    if market == "sh":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if market == "sz":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if market == "bj":
        return code.startswith(("4", "8", "92")) and not code.startswith("899")
    return False


def board_of(code):
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("4", "8", "92")):
        return "北交所"
    return "主板"


def limit_pct(board, is_st, ymd):
    if board == "北交所":
        return 0.30
    if board == "科创板":
        return 0.20
    if board == "创业板":
        return 0.20 if ymd >= "20200824" else (0.05 if is_st else 0.10)
    return 0.05 if is_st else 0.10


def rnd(x):
    return (x * 100 + 0.5 + 1e-9) // 1 / 100


def trading_days_back(end_ymd, n):
    """候选日期（自然日倒推，跳过周末）；节假日由通达信 404 自动跳过。"""
    d = dt.datetime.strptime(end_ymd, "%Y%m%d")
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= dt.timedelta(days=1)
    return out


# ----------------------------------------------------------------------------- 通达信日线落库
def save_daily(ymd, root):
    path = os.path.join(root, "daily", f"{ymd}.csv.gz")
    if os.path.exists(path):
        return pd.read_csv(path, dtype={"code": str})
    raw = S.tdx_daily_package(ymd)
    raw["code"] = raw["code"].astype(str).str.zfill(6)
    idx = raw[[(m, c) in INDEX_KEYS for m, c in zip(raw["market"], raw["code"])]].copy()
    if len(idx):
        idx["指数"] = [INDEX_KEYS[(m, c)] for m, c in zip(idx["market"], idx["code"])]
        idx["涨跌幅"] = ((idx["close"] / idx["prev_close"] - 1) * 100).round(2)
        os.makedirs(os.path.join(root, "index"), exist_ok=True)
        idx[["date", "指数", "close", "涨跌幅", "amount"]].to_csv(
            os.path.join(root, "index", f"{ymd}.csv"), index=False, encoding="utf-8-sig")
    st = raw[[is_a_share(m, c) for m, c in zip(raw["market"], raw["code"])]]
    st = st[["date", "market", "code", "name", "prev_close", "open", "high", "low", "close", "volume", "amount"]]
    os.makedirs(os.path.join(root, "daily"), exist_ok=True)
    st.to_csv(path, index=False, compression="gzip")
    return st


def backfill(end_ymd, n, root, q, start_ymd=None, workers=8, budget_min=300):
    """并行回补通达信日线。n>0 时补最近约 n 个交易日；给了 start_ymd 时补 start_ymd 至 end_ymd 的全部工作日。
    已存在的日期跳过；节假日（官网404）计为非交易日；超过 budget_min 分钟不再提交新任务，保证后续步骤能提交。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    t0 = time.time()
    if start_ymd:
        d, end = dt.datetime.strptime(end_ymd, "%Y%m%d"), dt.datetime.strptime(start_ymd, "%Y%m%d")
        cands = []
        while d >= end:
            if d.weekday() < 5:
                cands.append(d.strftime("%Y%m%d"))
            d -= dt.timedelta(days=1)
    else:
        cands = trading_days_back(end_ymd, int(n * 1.5) + 10)
    have = {os.path.basename(f)[:8] for f in glob.glob(os.path.join(root, "daily", "*.csv.gz"))}
    todo = [x for x in cands if x not in have]
    if not start_ymd:
        need = max(0, n - len([x for x in cands if x in have]))
        todo = todo[:int(need * 1.5) + 5]
    ok, miss, fail, skipped = 0, 0, 0, 0

    def job(ymd):
        for attempt in range(3):
            try:
                save_daily(ymd, root)
                return "ok"
            except ValueError:
                return "miss"
            except Exception:
                time.sleep(2 + attempt * 3)
        return "fail"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        it = iter(todo)
        for ymd in it:
            if len(futs) >= workers * 2:
                done = next(as_completed(futs))
                r = done.result(); futs.pop(done)
                ok += r == "ok"; miss += r == "miss"; fail += r == "fail"
            if (time.time() - t0) / 60 > budget_min:
                skipped = 1 + sum(1 for _ in it)
                break
            futs[ex.submit(job, ymd)] = ymd
        for f in as_completed(futs):
            r = f.result()
            ok += r == "ok"; miss += r == "miss"; fail += r == "fail"
    total = len({os.path.basename(f)[:8] for f in glob.glob(os.path.join(root, "daily", "*.csv.gz"))})
    print(f"回补：新增 {ok} 天，非交易日 {miss}，失败 {fail}，因时间预算跳过 {skipped}；历史库共 {total} 天")
    q.append({"模块": "历史回补", "状态": "成功" if ok or not todo else "失败", "行数": total,
              "耗时秒": round(time.time() - t0, 1),
              "错误": f"新增{ok}，非交易日{miss}，失败{fail}，未完成{skipped}"})


# ----------------------------------------------------------------------------- 全A扫描 + 新鲜度
def market_scan(ymd, root, lookback=130):
    files = sorted(glob.glob(os.path.join(root, "daily", "*.csv.gz")))
    files = [f for f in files if os.path.basename(f)[:8] <= ymd][-(lookback + 1):]
    if not files or os.path.basename(files[-1])[:8] != ymd:
        raise RuntimeError(f"历史库里没有 {ymd} 的日线")
    df = pd.concat((pd.read_csv(f, dtype={"code": str}) for f in files), ignore_index=True)
    df["ymd"] = df["date"].str.replace("-", "")
    df = df[(df["prev_close"] > 0) & (df["close"] > 0)].sort_values(["code", "ymd"])
    df["board"] = df["code"].map(board_of)
    df["is_st"] = df["name"].astype(str).str.contains("ST", case=False)
    lp = [limit_pct(b, s, y) for b, s, y in zip(df["board"], df["is_st"], df["ymd"])]
    df["up"] = rnd(df["prev_close"] * (1 + pd.Series(lp, index=df.index)))
    df["dn"] = rnd(df["prev_close"] * (1 - pd.Series(lp, index=df.index)))
    df["ret"] = df["close"] / df["prev_close"] - 1                 # prev_close 为除权参考价，链乘即复权收益
    df["zt"] = df["close"] >= df["up"] - 0.001
    df["touch"] = df["high"] >= df["up"] - 0.001
    df["dt"] = df["close"] <= df["dn"] + 0.001
    big_th = df["board"].map({"主板": 0.098, "创业板": 0.195, "科创板": 0.195, "北交所": 0.295})
    df["big"] = df["ret"] >= big_th
    g = df.groupby("code")
    df["adj"] = g["ret"].transform(lambda r: (1 + r).cumprod())
    df["adj_high"] = df["adj"] * df["high"] / df["close"]
    df["adj_low"] = df["adj"] * df["low"] / df["close"]
    df["n"] = g.cumcount()

    today = df[df["ymd"] == ymd].copy()
    hist = df[df["ymd"] < ymd]
    feats = []
    hg = {k: v for k, v in hist.groupby("code")}
    for _, r in today.iterrows():
        h = hg.get(r["code"])
        row = {}
        if h is not None and len(h):
            a_now = r["adj"]
            for n in (5, 20, 40, 60, 120):
                row[f"R{n}%"] = round((a_now / h["adj"].iloc[-n] - 1) * 100, 2) if len(h) >= n else None
            for n in (20, 40, 60, 120):
                row[f"大涨次数{n}"] = int(h["big"].iloc[-n:].sum()) if len(h) >= n else None
                row[f"涨停次数{n}"] = int(h["zt"].iloc[-n:].sum()) if len(h) >= n else None
            w = pd.concat([h.iloc[-119:], r.to_frame().T])
            hi, lo = w["adj_high"].astype(float).max(), w["adj_low"].astype(float).min()
            row["120日位置%"] = round((a_now - lo) / (hi - lo) * 100, 1) if hi > lo else None
            row["距120日高点%"] = round((a_now / hi - 1) * 100, 2)
            amt20 = h["amount"].iloc[-20:].mean()
            row["成交额/20日均"] = round(r["amount"] / amt20, 2) if amt20 else None
            closes = list(h["adj"].iloc[-19:]) + [a_now]
            row["站上MA5"] = bool(a_now >= sum(closes[-5:]) / 5) if len(closes) >= 5 else None
            row["站上MA20"] = bool(a_now >= sum(closes) / len(closes)) if len(closes) >= 20 else None
            row["历史天数"] = len(h)
        row["新鲜度"] = ("待核：历史不足40日" if row.get("大涨次数40") is None
                         else ("新面孔(40日无大涨)" if row["大涨次数40"] == 0 else f"40日内大涨{row['大涨次数40']}次"))
        feats.append(row)
    f = pd.DataFrame(feats, index=today.index)
    today = pd.concat([today, f], axis=1)
    today["涨跌幅%"] = (today["ret"] * 100).round(2)
    today["成交额亿"] = (today["amount"] / 1e8).round(2)
    today["炸板"] = today["touch"] & ~today["zt"]
    cols = ["code", "name", "market", "board", "is_st", "close", "涨跌幅%", "成交额亿", "zt", "touch", "炸板", "dt",
            "新鲜度", "R5%", "R20%", "R40%", "R60%", "R120%", "大涨次数20", "大涨次数40", "大涨次数60", "大涨次数120",
            "涨停次数20", "涨停次数40", "120日位置%", "距120日高点%", "成交额/20日均", "站上MA5", "站上MA20", "历史天数"]
    return today[[c for c in cols if c in today.columns]].rename(
        columns={"code": "代码", "name": "名称", "board": "板块", "zt": "收盘涨停", "touch": "触板", "dt": "收盘跌停"})


# ----------------------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(CN).strftime("%Y%m%d"))
    ap.add_argument("--out", default="data")
    ap.add_argument("--backfill", type=int, default=0, help="先补齐最近N个交易日的通达信日线")
    ap.add_argument("--backfill-start", default="", help="回补起始日 YYYYMMDD，补到 --date 为止（优先于 --backfill）")
    ap.add_argument("--workers", type=int, default=8, help="回补并行下载数")
    ap.add_argument("--watch-file", default="watchlist.txt")
    ap.add_argument("--notice-days", type=int, default=4)
    args = ap.parse_args()
    d, root = args.date, args.out
    out = os.path.join(root, d)
    os.makedirs(out, exist_ok=True)
    P = lambda n: os.path.join(out, n)  # noqa: E731
    q = []
    s = {"交易日": d, "运行时间(北京)": dt.datetime.now(CN).strftime("%Y-%m-%d %H:%M:%S")}

    if args.backfill or args.backfill_start:
        backfill(d, args.backfill, root, q, start_ymd=args.backfill_start or None, workers=args.workers)
    step(q, "通达信全A日线", lambda: save_daily(d, root))
    scan = step(q, "全A扫描与新鲜度", lambda: market_scan(d, root))
    if scan is not None:
        scan.to_csv(P("01_market_scan.csv"), index=False, encoding="utf-8-sig")

    zt = step(q, "东财涨停池", lambda: pd.DataFrame(S.em_zt_pool(d)))
    zb = step(q, "东财炸板池", lambda: pd.DataFrame(S.em_zb_pool(d)))
    dtp = step(q, "东财跌停池", lambda: pd.DataFrame(S.em_dt_pool(d)))
    yzt = step(q, "东财昨日涨停池", lambda: pd.DataFrame(S.em_yzt_pool(d)))
    ths = step(q, "同花顺涨停原因", lambda: pd.DataFrame(S.ths_limit_up_pool(d)))
    mon = step(q, "重点监控池", lambda: pd.DataFrame(S.em_stock_monitor()))
    ano = step(q, "严重异常波动", lambda: pd.DataFrame(S.em_price_anomaly(page_size=200)["items"]))

    if ths is not None and len(ths):
        ths["code"] = ths["code"].astype(str).str.zfill(6)
        ths.to_csv(P("06_ths_reason.csv"), index=False, encoding="utf-8-sig")
    if zt is not None and len(zt):
        zt["code"] = zt["code"].astype(str).str.zfill(6)
        if ths is not None and len(ths):
            zt = zt.merge(ths[["code", "reason", "board_type", "seal_rate", "high_days", "is_again"]],
                          on="code", how="left")
        zt.to_csv(P("02_zt_pool.csv"), index=False, encoding="utf-8-sig")
    for df, name in ((zb, "03_zb_pool.csv"), (dtp, "04_dt_pool.csv"), (yzt, "05_yzt_pool.csv"),
                     (mon, "07_risk_monitor.csv"), (ano, "08_risk_anomaly.csv")):
        if df is not None and len(df):
            df.to_csv(P(name), index=False, encoding="utf-8-sig")

    # 重点股票：涨停、炸板、跌停、昨日2板以上、观察股
    focus = set()
    for df in (zt, zb, dtp):
        if df is not None and len(df):
            focus |= set(df["code"].astype(str).str.zfill(6))
    if yzt is not None and len(yzt):
        focus |= set(yzt.loc[yzt["y_limit_days"] >= 2, "code"].astype(str).str.zfill(6))
    if os.path.exists(args.watch_file):
        with open(args.watch_file, encoding="utf-8") as f:
            focus |= {ln.split("#")[0].strip().zfill(6) for ln in f if ln.split("#")[0].strip()}
    if zt is None and scan is not None:     # 东财不可用时，用日线推算的涨停/炸板/跌停补位
        focus |= set(scan.loc[scan["收盘涨停"] | scan["炸板"] | scan["收盘跌停"], "代码"])

    def notices():
        start = (dt.datetime.strptime(d, "%Y%m%d") - dt.timedelta(days=args.notice_days)).strftime("%Y-%m-%d")
        rows, fail = [], 0
        for c in sorted(focus):
            try:
                for a in S.cninfo_announcements(c, page_size=15):
                    if a["date"] >= start:
                        rows.append({"代码": c, **a})
            except Exception:
                fail += 1
            time.sleep(0.4)
        df = pd.DataFrame(rows)
        if len(df):
            df["风险关键词"] = df["title"].astype(str).apply(lambda t: "、".join(w for w in RISK_WORDS if w in t))
        if fail and fail == len(focus):
            raise RuntimeError(f"巨潮全部{fail}只请求失败")
        return df
    nt = step(q, "重点股票公告", notices)
    if nt is not None and len(nt):
        nt.to_csv(P("09_notices.csv"), index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------ 市场总表
    if scan is not None:
        x = scan[scan["成交额亿"] > 0]
        s.update({
            "有效样本": len(x), "上涨": int((x["涨跌幅%"] > 0).sum()), "下跌": int((x["涨跌幅%"] < 0).sum()),
            "平盘": int((x["涨跌幅%"] == 0).sum()), "红盘率%": round((x["涨跌幅%"] > 0).mean() * 100, 1),
            "涨跌幅中位数%": round(x["涨跌幅%"].median(), 2), "成交额(亿)": round(x["成交额亿"].sum(), 0),
            "涨幅≥10%": int((x["涨跌幅%"] >= 10).sum()), "涨幅5%至10%": int(((x["涨跌幅%"] >= 5) & (x["涨跌幅%"] < 10)).sum()),
            "跌幅≥5%": int((x["涨跌幅%"] <= -5).sum()), "跌幅≥9%": int((x["涨跌幅%"] <= -9).sum()),
            "日线推算_涨停": int(x["收盘涨停"].sum()), "日线推算_炸板": int(x["炸板"].sum()),
            "日线推算_跌停": int(x["收盘跌停"].sum()),
            "涨幅≥10%中新面孔": int(((x["涨跌幅%"] >= 10) & (x["新鲜度"].str.startswith("新面孔"))).sum()),
        })
    idx_path = os.path.join(root, "index", f"{d}.csv")
    if os.path.exists(idx_path):
        s["指数"] = pd.read_csv(idx_path)[["指数", "close", "涨跌幅"]].to_dict("records")
    if zt is not None:
        s["涨停(东财)"] = len(zt)
        if len(zt):
            s["最高连板"] = int(zt["limit_days"].max())
            s["连板梯队"] = {int(k): list(v) for k, v in zt.groupby("limit_days")["name"]}
            s["涨停行业分布"] = zt["industry"].value_counts().head(15).to_dict()
    if zb is not None:
        s["炸板(东财)"] = len(zb)
    if zt is not None and zb is not None and len(zt) + len(zb):
        s["封板率%"] = round(len(zt) / (len(zt) + len(zb)) * 100, 1)
    if dtp is not None:
        s["跌停(东财)"] = len(dtp)
    if yzt is not None and len(yzt):
        s["昨日涨停今日均涨幅%"] = round(yzt["pct"].mean(), 2)
        s["昨日涨停今日红盘率%"] = round((yzt["pct"] > 0).mean() * 100, 1)
        s["昨日涨停今日大面(跌超5%)"] = int((yzt["pct"] < -5).sum())
        promoted = yzt["code"].astype(str).isin(zt["code"]) if zt is not None and len(zt) else yzt["pct"] >= 9.8
        s["晋级率%"] = round(promoted.mean() * 100, 1)
        for lo, label in ((1, "1进2"), (2, "2板及以上")):
            m = (yzt["y_limit_days"] == 1) if lo == 1 else (yzt["y_limit_days"] >= 2)
            if m.any():
                s[f"{label}晋级率%"] = round(promoted[m].mean() * 100, 1)
                s[f"{label}今日均涨幅%"] = round(yzt.loc[m, "pct"].mean(), 2)
    # 题材词频（同花顺涨停原因按“+”拆分）
    theme_rows = []
    if ths is not None and len(ths):
        cnt = Counter()
        for r in ths["reason"].fillna(""):
            for t in str(r).replace("＋", "+").split("+"):
                t = t.strip()
                if t:
                    cnt[t] += 1
        theme_rows = [{"题材": k, "涨停家数": v} for k, v in cnt.most_common(40)]
        s["涨停原因前10"] = dict(cnt.most_common(10))
    if theme_rows:
        pd.DataFrame(theme_rows).to_csv(P("10_theme_stats.csv"), index=False, encoding="utf-8-sig")
    if mon is not None:
        s["重点监控(生效中)"] = len(mon)
    if ano is not None:
        s["严重异常波动条数"] = len(ano)
    if nt is not None and len(nt):
        s["重点股票风险公告"] = int((nt["风险关键词"] != "").sum())

    with open(P("summary.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2, default=str)
    pd.DataFrame(q).to_csv(P("00_quality.csv"), index=False, encoding="utf-8-sig")
    ok = sum(1 for r in q if r["状态"] == "成功")
    print(json.dumps(s, ensure_ascii=False, indent=2, default=str)[:3000])
    print(f"\n模块成功 {ok}/{len(q)}，输出：{out}")
    for r in q:
        if r["状态"] != "成功":
            print(f"  [{r['状态']}] {r['模块']} {r['错误']}")


if __name__ == "__main__":
    main()
