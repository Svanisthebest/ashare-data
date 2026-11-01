#!/usr/bin/env python3
"""
每日价格联动分组（板块强度 + 板块内角色 + 低位跟随者），不依赖任何概念标签。

方法：
  强势股   主板涨幅 ≥ 7%，创业板/科创板 ≥ 10%（剔除ST、北交所、上市不足60日）
  分组     强势股之间过去60个交易日（不含当天）日收益的相关性，平均连接层次聚类，平均相关 ≥ 0.45 归为一组
  角色     龙头 = 组内最高连板（同高度取成交额大者）；中军 = 其余成员中成交额最大；
           前排首板 = 其他涨停；强势未涨停 = 涨幅达标但未封板
  跟随者   当天未达强势、上涨、成交额 > 2亿，与该组平均走势相关 ≥ 0.6 的前8只，标注120日位置与新鲜度
输出：
  data/YYYYMMDD/11_clusters.csv        每只股票一行（组号、角色、相关性、位置、新鲜度）
  data/YYYYMMDD/12_cluster_summary.csv 每组一行（规模、涨停数、最高板、新旧、成交额、成员名）
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

WIN, CUT, FOLLOW_CORR = 60, 0.55, 0.6


def load(root, date, n_days=125):
    fs = sorted(f for f in glob.glob(os.path.join(root, "daily", "*.csv.gz")) if os.path.basename(f)[:8] <= date)
    fs = fs[-n_days:]
    if not fs or os.path.basename(fs[-1])[:8] != date:
        raise SystemExit(f"历史库没有 {date}")
    df = pd.concat((pd.read_csv(f, dtype={"code": str}) for f in fs), ignore_index=True)
    df = df[(df.prev_close > 0) & (df.close > 0)].copy()
    c = df.code
    df["board"] = np.select([c.str.startswith(("688", "689")), c.str.startswith(("300", "301")),
                             c.str.match(r"^(4|8|92)")], ["科创", "创业", "北交"], "主板")
    df = df[(df.board != "北交") & ~df.name.astype(str).str.contains("ST")]
    lim = np.where(df.board.isin(["科创", "创业"]), 0.2, 0.1)
    df["up"] = np.floor(df.prev_close * (1 + lim) * 100 + 0.5) / 100
    df["ret"] = df.close / df.prev_close - 1
    df["zt"] = df.close >= df.up - 0.001
    df = df.sort_values(["code", "date"])
    blk = (~df.zt).astype(int).groupby(df.code).cumsum()
    df["lb"] = df.zt.astype(int).groupby([df.code, blk]).cumsum()
    big = np.where(df.board == "主板", 0.098, 0.195)
    df["big"] = df.ret >= big
    df["strong"] = df.ret >= np.where(df.board == "主板", 0.07, 0.10)
    g = df.groupby("code")
    df["adj"] = g.ret.transform(lambda r: (1 + r).cumprod())
    df["adj_hi"] = df.adj * df.high / df.close
    df["adj_lo"] = df.adj * df.low / df.close
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    d = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}"
    df = load(args.out, args.date)
    R = df.pivot(index="date", columns="code", values="ret")
    if d not in R.index:
        raise SystemExit("没有当天数据")
    i = list(R.index).index(d)
    if i < WIN:
        raise SystemExit(f"历史不足{WIN}日")
    win = R.iloc[i - WIN:i]
    ok = win.notna().sum() >= 40
    td = df[df.date == d].set_index("code")
    hist = df[df.date < d]
    # 位置与新鲜度
    last120 = df[df.date <= d].groupby("code").tail(120)
    pos = last120.groupby("code").apply(
        lambda h: (h.adj.iloc[-1] - h.adj_lo.min()) / (h.adj_hi.max() - h.adj_lo.min()) if h.adj_hi.max() > h.adj_lo.min() else np.nan)
    big40 = hist.groupby("code").tail(40).groupby("code").big.sum()
    td["pos120"] = pos.reindex(td.index)
    td["big40"] = big40.reindex(td.index)
    td["新鲜度"] = np.where(td.big40.isna(), "待核", np.where(td.big40 == 0, "新面孔", "40日大涨" + td.big40.fillna(0).astype(int).astype(str) + "次"))

    s = td[td.strong & td.index.isin(ok[ok].index)]
    rows, summ = [], []
    if len(s) >= 2:
        X = win[s.index].fillna(0)
        C = np.nan_to_num(np.corrcoef(X.T.values))
        D = np.clip(1 - C, 0, 2)
        np.fill_diagonal(D, 0)
        lab = fcluster(linkage(squareform(D, checks=False), "average"), CUT, criterion="distance")
        s = s.assign(cl=lab)
        sizes = s.cl.value_counts()
        order = {k: n + 1 for n, k in enumerate(sizes.index)}
        prev5 = hist[hist.date.isin(sorted(hist.date.unique())[-5:])].groupby("code").strong.sum()
        for k, grp in s.groupby("cl"):
            gid = order[k]
            grp = grp.assign(rs=grp.ret / np.where(grp.board == "主板", 0.1, 0.2)).sort_values(["lb", "zt", "rs", "amount"], ascending=False)   # 与研究一致
            lead = grp.index[0]
            zj = grp.drop(lead).amount.idxmax() if len(grp) > 1 else None
            for code, r in grp.iterrows():
                role = "龙头" if code == lead else ("中军" if code == zj else ("前排首板" if r.zt else "强势未涨停"))
                if len(grp) == 1:
                    role = "孤立强势"
                rows.append(dict(组=gid, 代码=code, 名称=r["name"], 角色=role, 连板=int(r.lb), 涨幅=round(r.ret * 100, 2),
                                 成交额亿=round(r.amount / 1e8, 2), 与组相关=None, 位置120=round(r.pos120 * 100, 1) if pd.notna(r.pos120) else None,
                                 新鲜度=r["新鲜度"]))
            new_share = (prev5.reindex(grp.index).fillna(0) == 0).mean()
            summ.append(dict(组=gid, 规模=len(grp), 涨停=int(grp.zt.sum()), 最高板=int(grp.lb.max()),
                             新旧="新组" if new_share >= 0.67 else "老组", 成交额亿=round(grp.amount.sum() / 1e8, 1),
                             龙头=td.loc[lead, "name"], 成员="、".join(td.loc[grp.index, "name"].astype(str))))
            # 跟随者
            if len(grp) >= 3:
                cm = win[list(grp.index)].mean(axis=1)
                cand = td[(~td.strong) & (td.ret > 0) & (td.amount > 2e8)].index
                cand = [x for x in cand if x in win.columns and ok.get(x, False)]
                if cand:
                    corr = win[cand].apply(lambda col: col.corr(cm)).dropna()
                    for code, cv in corr[corr >= FOLLOW_CORR].sort_values(ascending=False).head(5).items():   # 与研究一致：每组最多 5 只
                        r = td.loc[code]
                        p = r.pos120
                        tag = "低位跟随" if pd.notna(p) and p < 0.33 else ("中位跟随" if pd.notna(p) and p < 0.66 else "高位跟随")
                        rows.append(dict(组=gid, 代码=code, 名称=r["name"], 角色=tag, 连板=0, 涨幅=round(r.ret * 100, 2),
                                         成交额亿=round(r.amount / 1e8, 2), 与组相关=round(cv, 2),
                                         位置120=round(p * 100, 1) if pd.notna(p) else None, 新鲜度=r["新鲜度"]))
    out = os.path.join(args.out, args.date)
    os.makedirs(out, exist_ok=True)
    pd.DataFrame(rows).sort_values(["组", "连板", "涨幅"], ascending=[True, False, False]).to_csv(
        os.path.join(out, "11_clusters.csv"), index=False, encoding="utf-8-sig")
    sm = pd.DataFrame(summ).sort_values(["规模", "涨停"], ascending=False)
    sm.to_csv(os.path.join(out, "12_cluster_summary.csv"), index=False, encoding="utf-8-sig")
    print(sm.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
