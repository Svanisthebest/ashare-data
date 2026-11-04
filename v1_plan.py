#!/usr/bin/env python3
"""
v1.1 短线系统：收盘后生成次日候选清单（不看未来数据）。
v1.1 相对 v1：总龙头首阴要求昨日最高板 ≥ 4；强势回调要求昨日涨停股今日溢价 > 0；去掉试验仓；总龙头首阴、低位启动每笔 25%。
先运行 clusters_daily.py 生成当天联动分组，再运行本脚本：
    python clusters_daily.py --date 20261030 --out data
    python v1_plan.py --date 20261030 --out data
输出 data/plan/YYYYMMDD.md（次日计划）和 data/plan/YYYYMMDD.csv（全部候选）。
"""
import argparse, glob, os, datetime as dt
import numpy as np, pandas as pd
import clusters_daily


def load(root, date, n_days=130):
    """与 clusters_daily.load 相同，但历史上的 ST 日子不删（只在信号当天排除 ST），与研究口径一致。"""
    return _load(root, date, n_days)


def _load(root, date, n_days):
    fs = sorted(f for f in glob.glob(os.path.join(root, 'daily', '*.csv.gz')) if os.path.basename(f)[:8] <= date)[-n_days:]
    df = pd.concat((pd.read_csv(f, dtype={'code': str}) for f in fs), ignore_index=True)
    df = df[(df.prev_close > 0) & (df.close > 0)].copy()
    c = df.code
    df['board'] = np.select([c.str.startswith(('688', '689')), c.str.startswith(('300', '301')), c.str.match(r'^(4|8|92)')], ['科创', '创业', '北交'], '主板')
    df = df[df.board != '北交']
    df['st'] = df.name.astype(str).str.contains('ST')
    lim = np.where(df.board.isin(['科创', '创业']), 0.2, np.where(df.st, 0.05, 0.1))
    df['up'] = np.floor(df.prev_close * (1 + lim) * 100 + 0.5) / 100
    df['ret'] = df.close / df.prev_close - 1
    df['zt'] = df.close >= df.up - 0.001
    df = df.sort_values(['code', 'date'])
    blk = (~df.zt).astype(int).groupby(df.code).cumsum()
    df['lb'] = df.zt.astype(int).groupby([df.code, blk]).cumsum()
    df['adj'] = df.groupby('code').ret.transform(lambda r: (1 + r).cumprod())
    df['adj_hi'] = df.adj * df.high / df.close
    df['adj_lo'] = df.adj * df.low / df.close
    return df

NAME = {'B': '恐慌低吸', 'RB': '跌深反弹', 'L': '2板龙头', 'LD': '总龙头强势首阴', 'C': '强势回调',
        'D': '低位启动', 'A': '低位跟随', 'M': '周一放宽'}
CAP = {'RB': 2, 'C': 3, 'D': 3}
SIZE = {'B': 20, 'RB': 10, 'L': 20, 'LD': 25, 'C': 20, 'D': 25, 'A': 20, 'M': 20}


def index_state(root, date):
    fs = sorted(f for f in glob.glob(os.path.join(root, 'index', '*.csv')) if os.path.basename(f)[:8] <= date)[-20:]
    z = np.array([pd.read_csv(f).set_index('指数').close['中证1000'] for f in fs])
    return z[-1] / z.max() - 1, z[-1] > z[-5:].mean(), z[-1] / z[-2] - 1


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date', required=True); ap.add_argument('--out', default='data')
    a = ap.parse_args(); D = a.date; d = f'{D[:4]}-{D[4:6]}-{D[6:]}'
    df = load(a.out, D, n_days=130)
    df['dn'] = np.floor(df.prev_close * (1 - np.where(df.board == '主板', 0.1, 0.2)) * 100 + 0.5) / 100   # 与研究相同的取整
    df['dt'] = df.close <= df.dn + 0.001
    g = df.groupby('code')
    df['zt5'] = g.zt.transform(lambda s: s.astype(int).rolling(6, min_periods=1).sum().shift(1))   # 与回测一致：今天之前 6 个交易日的涨停次数
    df['hi5'] = g.adj.transform(lambda s: s.rolling(5, min_periods=1).max())
    df['ma10'] = g.adj.transform(lambda s: s.rolling(10, min_periods=10).mean())
    df['r5'] = g.adj.transform(lambda s: s / s.shift(5) - 1)
    df['n'] = g.adj.transform('size')
    days = sorted(df.date.unique()); prev = days[-2]
    td = df[df.date == d].set_index('code'); pv = df[(df.date == prev) & ~df.st].set_index('code')
    # 次新股：与研究一致，只剔除上市前 5 天和上市初期的连续涨停阶段（强势回调另要求上市满 60 天）
    first = df.date.min()
    lst = df.groupby('code').date.transform('min')
    k = df.groupby('code').cumcount() + 1
    run = df.zt.astype(int).groupby(df.code).cumprod().astype(bool)
    df['newstock'] = (lst > first) & ((k < 5) | (run & (k < 40)))
    td = df[df.date == d].set_index('code')
    td = td[~td.newstock & ~td.st & ~td.name.astype(str).str.contains('退')]
    last120 = df[df.date <= d].groupby('code').tail(120)
    lo = last120.groupby('code').adj_lo.min(); hi = last120.groupby('code').adj_hi.max()
    td['pos120'] = ((td.adj - lo.reindex(td.index)) / (hi - lo).reindex(td.index)).clip(0, 1)
    red = (td.ret > 0).mean(); nzt = int(td.zt.sum())
    ndt = int(td.dt[~td.name.astype(str).str.contains('退')].sum())   # 不含 ST，与研究里 200 家门槛的口径一致
    maxlb = int(td.lb[td.zt].max())
    # 昨日涨停股今日溢价（不含 ST、今日一字板），v1.1 强势回调的情绪过滤
    tdall = df[(df.date == d) & ~df.st].set_index('code')
    yz = tdall.zt & (tdall.high == tdall.low)
    zy = tdall[tdall.index.isin(pv[pv.zt].index) & ~yz]
    prem = float(zy.ret.mean()) if len(zy) else 0.0
    fh, above5, zr = index_state(a.out, D)
    nxt = '下一交易日'; monday = pd.Timestamp(d).weekday() == 4   # 周一放宽：信号日为周五
    C = []
    def add(src, code, why, rk):
        r = td.loc[code]; C.append(dict(路线=NAME[src], src=src, 代码=code, 名称=r['name'], 收盘=r.close,
                                        涨跌=round(r.ret * 100, 1), 成交额亿=round(r.amount / 1e8, 1),
                                        位置120=round(r.pos120 * 100, 1) if pd.notna(r.pos120) else None, 说明=why, rk=rk))
    # 恐慌低吸
    if ndt >= 200:
        for code, r in td[td.r5 < -0.20].sort_values('r5').iterrows(): add('B', code, f'5日 {r.r5*100:.0f}%', r.r5)
    # 跌深反弹：位置最低，并列取成交额最大
    if fh < -0.10:
        x = td[td.pos120 < 0.2].assign(p=lambda v: v.pos120.round(6)).sort_values(['p', 'amount'], ascending=[True, False]).head(5)
        for i, (code, r) in enumerate(x.iterrows()): add('RB', code, '首选' if i < 2 else '备选', i)
    # 联动分组：2板龙头、低位跟随
    cf = os.path.join(a.out, D, '11_clusters.csv'); sf = os.path.join(a.out, D, '12_cluster_summary.csv')
    if os.path.exists(cf):
        cl = pd.read_csv(cf, dtype={'代码': str}); sm = pd.read_csv(sf).set_index('组')
        # 2板龙头：与回测一致，联动组至少 3 只
        for _, r in cl[(cl['角色'] == '龙头') & (cl['连板'] == 2)].iterrows():
            if r['代码'] in td.index and sm.loc[r['组'], '规模'] >= 3: add('L', r['代码'], f"组{r['组']}（{int(sm.loc[r['组'],'规模'])}只）开盘<+2%才买，即 < {td.loc[r['代码'],'close']*1.02:.2f}", -sm.loc[r['组'], '规模'])
        if True:   # 回测未排除弱市形成的组
            lf = cl[cl['角色'] == '低位跟随'].sort_values('与组相关', ascending=False).drop_duplicates('代码')
            for _, r in lf.iterrows():
                if r['代码'] in td.index: add('A', r['代码'], '9:40 再定：前10分钟成交量 ≥ 昨日全天的 18%，且价格在开盘价上方', -r['与组相关'])
    # 总龙头强势首阴：前一天全市场最高板（v1.1：≥4板），今天没涨停但收涨 > 3%
    pmax = pv.lb[pv.zt].max() if pv.zt.any() else 0
    if pmax >= 4:
        for code in pv[(pv.zt) & (pv.lb == pmax)].index:
            if code in td.index and not td.loc[code, 'zt'] and td.loc[code, 'ret'] > 0.03: add('LD', code, f'昨日 {int(pmax)} 板，今日断板收涨', 0)
    # 强势回调（以及周一放宽用同一批）；v1.1：强势回调要求昨日涨停溢价 > 0，周一放宽不受此限
    cc = td[(td.n >= 60) & (td.zt5 >= 2) & (~td.zt) & (td.adj < td.hi5 * 0.92) & (td.adj > td.ma10)]   # 与回测一致：不要求当天收跌
    if above5:
        for code, r in cc.iterrows():
            if prem > 0: add('C', code, '9:25 按竞价额/昨日成交额从大到小买', 0)
            if monday: add('M', code, '周一竞价 40–55% 时做', 0)
    # 低位启动
    for i, (code, r) in enumerate(td[td.ret.between(0.05, 0.095) & (td.pos120 < 0.10)].sort_values('pos120').iterrows()):
        add('D', code, '首选' if i < 3 else '备选', i)
    P = pd.DataFrame(C)
    os.makedirs(os.path.join(a.out, 'plan'), exist_ok=True)
    if len(P): P.drop(columns='rk').to_csv(os.path.join(a.out, 'plan', f'{D}.csv'), index=False, encoding='utf-8-sig')
    # 写计划
    L = [f'# v1.1 计划：{d} 收盘 → {nxt}', '',
         f'- 当天：红盘率 {red:.0%}，涨停 {nzt}，跌停 {ndt}，最高 {maxlb} 板；中证1000 {zr:+.2%}，距 20 日高点 {fh:+.1%}，{"在" if above5 else "不在"} 5 日线上。',
         f'- 特殊状态：恐慌低吸{"已触发" if ndt >= 200 else "未触发"}（跌停 ≥ 200）；跌深反弹{"已触发" if fh < -0.10 else "未触发"}（距高点 < −10%）；昨日涨停溢价 {prem:+.2%}，强势回调{("可做" if prem > 0 else "暂停（昨日涨停溢价 ≤ 0）") if above5 else "暂停（中证1000 在 5 日线下）"}；总龙头首阴{"有资格" if pmax >= 4 else "不做（昨日最高板 < 4）"}（昨日最高 {int(pmax)} 板）；{"今天是周五，下一交易日适用周一放宽" if monday else ""}', '',
         '## 9:25 竞价决定动作', '',
         '| 全A竞价红盘率 | 可做的路线 |', '|---|---|',
         '| > 55% | 全部：恐慌低吸 → 跌深反弹 → 2板龙头 → 总龙头首阴 → 强势回调 → 低位启动 → 低位跟随 |',
         '| 40–55% | 跌深反弹、周一放宽（仅周一）；总龙头首阴照做 |',
         '| < 40% | 不开新仓；总龙头首阴照做 |', '',
         '最多同时 5 只（含已有持仓）；跌深反弹最多 2 只，强势回调、低位启动各最多 3 只。一字涨停或停牌跳过，用同路线下一只补；同一只股票只买一次（已持有或已在前面路线买过的跳过）。', '竞价红盘率口径：沪深 A 股（不含北交所、ST、退市、停牌），9:25 竞价价高于昨收的家数 ÷ 全部，平盘不算红；目前约 5,020 只，> 55% 约需 2,765 家，40% 约 2,010 家。', '']
    for src in ['B', 'RB', 'L', 'LD', 'C', 'D', 'A', 'M']:
        x = P[P.src == src].sort_values('rk') if len(P) else P
        L.append(f'## {NAME[src]}（每笔 {SIZE[src]}%{"，最多 " + str(CAP[src]) + " 只" if src in CAP else ""}）')
        if not len(x): L += ['', '无候选。', '']; continue
        L += ['', '| 代码 | 名称 | 收盘 | 涨跌% | 成交额亿 | 位置% | 说明 |', '|---|---|---|---|---|---|---|']
        L += [f"| {r['代码']} | {r['名称']} | {r['收盘']:.2f} | {r['涨跌']} | {r['成交额亿']} | {r['位置120']} | {r['说明']} |" for _, r in x.head(10).iterrows()]
        L.append('')
    L += ['## 卖出', '', '- 跌深反弹拿 5 天（买入当天算第 1 天）收盘卖；恐慌低吸从高点回撤 10% 卖；两者收盘亏 15% 止损。',
          '- 其他路线：买入后第一个可卖日起，不涨停就尾盘卖；总龙头首阴当天涨 ≥ 7%（20cm ≥ 14%）也可多拿，最多 3 天；收盘亏 8% 止损。',
          '- v1.1：到了该卖的那天，14:50 若持仓亏损且中证1000 当天跌 ≥ 1%，推迟一天再卖（只推迟一次；收盘亏 8% 仍止损）。',
          '- 14:50 前挂尾盘卖单；封死跌停卖不出就次日开盘卖；不用盘中止损单。', '',
          '## 执行', '', '- 9:25 竞价确认后开盘买（低位跟随 9:40 确认）；资金大时 9:30–10:00 分几次买，单只不超过该股昨日成交额的 4%。',
          '- 空闲资金放国债逆回购或货币 ETF，要用时开盘先卖。']
    open(os.path.join(a.out, 'plan', f'{D}.md'), 'w').write('\n'.join(L))
    print('\n'.join(L))


if __name__ == '__main__':
    main()
