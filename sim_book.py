#!/usr/bin/env python3
"""
v1 模拟账本：按前一交易日的候选清单（data/plan/上一日.csv）和当天行情，模拟当天 9:25 竞价决策、开盘买入、收盘卖出。
    python sim_book.py --date 20261102 --out data
状态：data/sim/book.json（现金、持仓），流水：data/sim/trades.csv，当日报告：data/sim/YYYYMMDD.md
不能用日线数据模拟的条件：试验仓（要竞价成交额）、低位跟随（要 9:40 成交量），模拟盘不做这两条，报告里注明。
"""
import argparse, glob, json, os
import numpy as np, pandas as pd

START = '20261102'; CAP = {'RB': 2, 'C': 3, 'D': 3}; W = {'RB': 0.10, 'T': 0.10}
ORDER = ['B', 'RB', 'L', 'LD', 'C', 'D', 'A', 'M', 'T']
NAME = {'B': '恐慌低吸', 'RB': '跌深反弹', 'L': '2板龙头', 'LD': '总龙头强势首阴', 'C': '强势回调', 'D': '低位启动', 'A': '低位跟随', 'M': '周一放宽', 'T': '试验仓'}


def day_file(root, d): return os.path.join(root, 'daily', f'{d}.csv.gz')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--date', required=True); ap.add_argument('--out', default='data'); a = ap.parse_args()
    D = a.date; root = a.out; simd = os.path.join(root, 'sim'); os.makedirs(simd, exist_ok=True)
    days = sorted(os.path.basename(f)[:8] for f in glob.glob(os.path.join(root, 'daily', '*.csv.gz')))
    if D not in days: raise SystemExit(f'没有 {D} 的行情')
    P = days[days.index(D) - 1]
    bk_f = os.path.join(simd, 'book.json')
    book = json.load(open(bk_f)) if os.path.exists(bk_f) else {'cash': 1.0, 'pos': [], 'last': None}
    if book['last'] and book['last'] >= D: raise SystemExit(f'{D} 已经处理过')
    if D < START: raise SystemExit('模拟盘从 ' + START + ' 开始')
    t = pd.read_csv(day_file(root, D), dtype={'code': str}).set_index('code')
    t = t[(t.prev_close > 0)]
    nm = t.name.astype(str)
    big = t.index.str.match(r'^(30|68)')
    st = nm.str.contains('ST')
    lim = np.where(big, 0.2, np.where(st, 0.05, 0.1))
    up = np.floor(t.prev_close * (1 + lim) * 100 + 0.5) / 100; dn = np.floor(t.prev_close * (1 - lim) * 100 + 0.5) / 100
    t = t.assign(up=up, dn=dn, lim=lim)
    univ = t[~t.index.str.match(r'^(4|8|92)') & ~st & ~nm.str.contains('退') & (t.open > 0)]
    red = float((univ.open > univ.prev_close).mean())
    # 持仓按昨收估值
    def px(code, col):
        return float(t.loc[code, col]) if code in t.index and t.loc[code, col] > 0 else None
    eq_open = book['cash'] + sum(p['val'] * (px(p['code'], 'prev_close') or p['last']) / p['last'] for p in book['pos'])
    # ---------- 开盘买入 ----------
    plan_f = os.path.join(root, 'plan', f'{P}.csv')
    cand = pd.read_csv(plan_f, dtype={'代码': str}) if os.path.exists(plan_f) else pd.DataFrame(columns=['src', '代码', '名称'])
    friday = pd.Timestamp(P).weekday() == 4
    allowed = set(ORDER) if red > 0.55 else ({'RB', 'LD', 'T'} | ({'M'} if friday else set())) if red >= 0.40 else {'LD'}
    buys, skips = [], []
    held = {p['code'] for p in book['pos']}
    for s in ORDER:
        for _, r in cand[cand.src == s].iterrows():
            c = r['代码']
            if s not in allowed: continue
            if s in ('T', 'A'): skips.append(f"{NAME[s]} {r['名称']}：需要竞价额 / 9:40 数据，模拟盘不做"); continue
            if len(book['pos']) >= 5: skips.append(f"{NAME[s]} {r['名称']}：满仓"); continue
            if s in CAP and sum(1 for p in book['pos'] if p['src'] == s) >= CAP[s]: continue
            if c in held: continue
            o = px(c, 'open')
            if o is None: skips.append(f"{NAME[s]} {r['名称']}：停牌"); continue
            if t.loc[c, 'high'] == t.loc[c, 'low'] and o >= t.loc[c, 'up'] - 0.005: skips.append(f"{NAME[s]} {r['名称']}：一字涨停买不到"); continue
            if s == 'L' and o >= t.loc[c, 'prev_close'] * 1.02: skips.append(f"{NAME[s]} {r['名称']}：高开 {o / t.loc[c, 'prev_close'] - 1:+.1%}，超过 2% 放弃"); continue
            val = min(W.get(s, 0.20) * eq_open, book['cash'])
            if val <= 0.01 * eq_open: break
            book['cash'] -= val
            book['pos'].append(dict(code=c, name=r['名称'], src=s, entry=D, ep=o, val=val, last=o, peak=o, held=0, extra=0))
            held.add(c); buys.append((NAME[s], c, r['名称'], o, val))
    # ---------- 收盘卖出 ----------
    sells, keep = [], []
    for p in book['pos']:
        c = p['code']; cl = px(c, 'close')
        if cl is None: keep.append(p); continue          # 停牌
        p['held'] += 1; p['peak'] = max(p['peak'], cl)
        locked = t.loc[c, 'high'] == t.loc[c, 'low'] and cl <= t.loc[c, 'dn'] + 0.005
        zt = cl >= t.loc[c, 'up'] - 0.005; dr = cl / t.loc[c, 'prev_close'] - 1; L = t.loc[c, 'lim']
        why = None
        if p['entry'] != D and not locked:
            cs = 0.15 if p['src'] in ('B', 'RB') else 0.08
            if cl < p['ep'] * (1 - cs): why = f'收盘亏超 {cs:.0%} 止损'
            elif p['src'] == 'RB' and p['held'] >= 5: why = '拿满 5 天'
            elif p['src'] == 'B' and cl < p['peak'] * 0.9: why = '高点回撤 10%'
            elif p['src'] not in ('RB', 'B') and not zt:
                if p['src'] == 'LD' and dr >= 0.7 * L and p['extra'] < 3: p['extra'] += 1
                else: why = '没涨停，尾盘卖'
        if why:
            r_ = cl / p['ep'] - 1 - 0.003; book['cash'] += p['val'] * p['ep'] / p['last'] * (1 + r_)   # val 已按上一收盘估值，先还原成买入金额再乘全程收益，避免重复计算
            sells.append((NAME[p['src']], c, p['name'], p['ep'], cl, r_, why))
        else:
            p['val'] = p['val'] * cl / p['last']; p['last'] = cl; keep.append(p)
    # 已卖的按卖出处理；未卖的 val 已按收盘更新
    book['pos'] = keep; book['last'] = D
    eq = book['cash'] + sum(p['val'] for p in book['pos'])
    json.dump(book, open(bk_f, 'w'), ensure_ascii=False, indent=1)
    tf = os.path.join(simd, 'trades.csv')
    rows = [dict(日期=D, 动作='买入', 路线=b[0], 代码=b[1], 名称=b[2], 价格=round(b[3], 2), 仓位=round(b[4], 4)) for b in buys] + \
           [dict(日期=D, 动作='卖出', 路线=s_[0], 代码=s_[1], 名称=s_[2], 价格=round(s_[4], 2), 收益=round(s_[5], 4), 原因=s_[6]) for s_ in sells]
    if rows: pd.DataFrame(rows).to_csv(tf, mode='a', header=not os.path.exists(tf), index=False, encoding='utf-8-sig')
    gate = '> 55%，正常开仓' if red > 0.55 else ('40–55%，只做跌深反弹 / 周一放宽 / 试验仓' if red >= 0.40 else '< 40%，不开新仓')
    L_ = [f'## 模拟盘（{D}）', '', f'- 今天 9:25 全A竞价红盘率 **{red:.1%}**（{gate}）；按 {P} 收盘的候选执行。',
          f'- 账户净值 **{eq:.4f}**（2026-11-02 起始 1.0000），现金 {book["cash"] / eq:.0%}，持仓 {len(book["pos"])} 只。', '']
    L_ += ['**今天开盘买入**', ''] + ([f'- {b[0]}：{b[2]}（{b[1]}）开盘价 {b[3]:.2f}，仓位 {b[4] / eq_open:.0%}' for b in buys] or ['- 无']) + ['']
    na = [x for x in skips if '9:40' in x]; other = [x for x in skips if '9:40' not in x]
    if na: other.append(f"低位跟随 / 试验仓 {len(na)} 只：要用 9:40 成交量或竞价成交额判断，日线数据模拟不了，模拟盘不做（实盘按规则自己判断）")
    if other: L_ += ['**按规则没买**', ''] + [f'- {x}' for x in other] + ['']
    L_ += ['**今天收盘卖出**', ''] + ([f'- {x[0]}：{x[2]} 买入 {x[3]:.2f} → 卖出 {x[4]:.2f}，{x[5]:+.1%}（{x[6]}）' for x in sells] or ['- 无']) + ['']
    L_ += ['**收盘持仓**', '']
    if book['pos']:
        L_ += ['| 路线 | 名称 | 买入日 | 买入价 | 今收 | 浮动 | 下一步 |', '|---|---|---|---|---|---|---|']
        for p in book['pos']:
            nxt = f"拿满 5 天（已 {p['held']} 天）" if p['src'] == 'RB' else ('高点回撤 10% 卖' if p['src'] == 'B' else ('明天不涨停且涨不到 7%（20cm 14%）就尾盘卖' if p['src'] == 'LD' else '明天不涨停就尾盘卖'))
            L_.append(f"| {NAME[p['src']]} | {p['name']} | {p['entry']} | {p['ep']:.2f} | {p['last']:.2f} | {p['last'] / p['ep'] - 1:+.1%} | {nxt} |")
    else: L_.append('- 空仓')
    L_ += ['', f'明天开仓前先扣掉以上持仓：已占 {len(book["pos"])} / 5 个仓位' + (f'（跌深反弹 {sum(1 for p in book["pos"] if p["src"] == "RB")} / 2）' if any(p['src'] == 'RB' for p in book['pos']) else '') + '。']
    open(os.path.join(simd, f'{D}.md'), 'w').write('\n'.join(L_))
    print('\n'.join(L_))


if __name__ == '__main__':
    main()
