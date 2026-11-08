#!/usr/bin/env python3
"""
v1.4 模拟账本：按前一交易日的候选清单（data/plan/上一日.csv）和当天行情，模拟当天 9:25 竞价决策、开盘买入、收盘卖出。
    python sim_book.py --date 20261102 --out data
状态：data/sim/book.json（现金、持仓），流水：data/sim/trades.csv，当日报告：data/sim/YYYYMMDD.md
v1.3：核心优先（总龙头首阴 30%、2板龙头 25%、周一放宽 25%）；新增缩量断板低开（30%，≤2 只）、首板强势未封低开（15%，≤2 只），
两者不受竞价开关限制、只在低开 0–5% 时开盘买；高标被砸 20%，开盘在昨收 −3%~0 时挂开盘价 ×0.97 买单（日线按最低价判断是否成交）；
去掉跌深反弹、强势回调、低位跟随（已有的旧路线持仓仍按原规则卖）。
v1.4：新增 2板断板强收（15%，≤2 只，同样低开 0–5% 开盘买、不受开关限制）。「10:30 后炸板即卖」要分时数据，日线模拟盘做不了，仍按收盘价卖（比实盘略保守）。
v1.2：新增高标被砸（竞价红盘 < 55% 且开盘在昨收 −3% 到 0 之间开盘买，10%，最多 2 只；低开 3–5% 要 9:40 确认，模拟盘不做）。
v1.1：去掉试验仓；总龙头首阴、低位启动每笔 25%；该卖那天若亏损且中证1000 跌 ≥ 1%，推迟一天卖（只推迟一次）。
"""
import argparse, glob, json, os
import numpy as np, pandas as pd

START = '20261102'; CAP = {'N': 2, 'P': 2, 'Q': 2, 'K': 2, 'D': 3}
W = {'LD': 0.30, 'L': 0.25, 'M': 0.25, 'N': 0.30, 'B': 0.20, 'K': 0.20, 'D': 0.25, 'P': 0.15, 'Q': 0.15}
ORDER = ['LD', 'L', 'M', 'N', 'B', 'K', 'D', 'P', 'Q']
NAME = {'B': '恐慌低吸', 'RB': '跌深反弹（v1.3 已停用）', 'L': '2板龙头', 'LD': '总龙头强势首阴', 'C': '强势回调（v1.3 已停用）', 'D': '低位启动',
        'A': '低位跟随（v1.3 已停用）', 'M': '周一放宽', 'K': '高标被砸', 'N': '缩量断板低开', 'P': '首板强势未封低开', 'Q': '2板断板强收', 'T': '试验仓（v1 已停用）'}


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
    allowed = (set(ORDER) - {'K', 'M'}) if red > 0.55 else ({'LD', 'K', 'N', 'P', 'Q'} | ({'M'} if friday else set())) if red >= 0.40 else {'LD', 'K', 'N', 'P', 'Q'}   # 与回测一致：周一放宽只在 40–55%；N、P 不受开关限制
    zf = os.path.join(root, 'index', f'{D}.csv')
    zr = float(pd.read_csv(zf).set_index('指数').loc['中证1000', '涨跌幅']) / 100 if os.path.exists(zf) else 0.0   # 中证1000 当天涨跌
    buys, skips = [], []
    held = {p['code'] for p in book['pos']}
    for s in ORDER:
        for _, r in cand[cand.src == s].iterrows():
            c = r['代码']
            if s not in allowed: continue
            if len(book['pos']) >= 5: skips.append(f"{NAME[s]} {r['名称']}：满仓"); continue
            if s in CAP and sum(1 for p in book['pos'] if p['src'] == s) >= CAP[s]: continue
            if c in held: continue
            o = px(c, 'open')
            if o is None: skips.append(f"{NAME[s]} {r['名称']}：停牌"); continue
            if t.loc[c, 'high'] == t.loc[c, 'low'] and o >= t.loc[c, 'up'] - 0.005: skips.append(f"{NAME[s]} {r['名称']}：一字涨停买不到"); continue
            if s == 'L' and o >= t.loc[c, 'prev_close'] * 1.02: skips.append(f"{NAME[s]} {r['名称']}：高开 {o / t.loc[c, 'prev_close'] - 1:+.1%}，超过 2% 放弃"); continue
            pc_ = t.loc[c, 'prev_close']; ep = o
            if s in ('N', 'P', 'Q') and not (pc_ * 0.95 <= o < pc_): skips.append(f"{NAME[s]} {r['名称']}：开盘 {o / pc_ - 1:+.1%}，不在低开 0–5% 区间"); continue
            if s == 'K':
                if not (pc_ * 0.97 <= o < pc_): skips.append(f"{NAME[s]} {r['名称']}：开盘 {o / pc_ - 1:+.1%}，不在 −3% 到 0 之间"); continue
                ep = round(o * 0.97, 2)
                if t.loc[c, 'low'] > ep: skips.append(f"{NAME[s]} {r['名称']}：挂 {ep:.2f}（开盘价 −3%）未成交"); continue
            val = min(W.get(s, 0.20) * eq_open, book['cash'])
            if val <= 0.01 * eq_open: break
            book['cash'] -= val
            book['pos'].append(dict(code=c, name=r['名称'], src=s, entry=D, ep=ep, val=val, cost=val, last=ep, peak=ep, held=0, extra=0))
            held.add(c); buys.append((NAME[s], c, r['名称'], ep, val))
    # ---------- 收盘卖出 ----------
    sells, keep = [], []
    for p in book['pos']:
        p.pop('note', None)
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
            elif p['src'] == 'B' and p['held'] >= 20: why = '拿满 20 天'
            elif p['src'] not in ('RB', 'B') and not zt:
                if p['src'] == 'LD' and dr >= 0.7 * L and p['extra'] < 3: p['extra'] += 1
                elif cl < p['ep'] and zr <= -0.01 and not p.get('delayed'): p['delayed'] = 1; p['note'] = '亏损且中证1000 跌 ≥ 1%，推迟一天卖'
                else: why = '没涨停，尾盘卖'
            if why is None and p['src'] not in ('RB', 'B') and p['held'] >= 11: why = '拿满 11 天'
        if why:
            cost = p.get('cost', p['val'] * p['ep'] / p['last'])   # 买入时投入的金额
            r_ = cl / p['ep'] - 1 - 0.003; book['cash'] += cost * (1 + r_)   # 按买入金额 × 买入以来收益结算，不能用已逐日更新的市值再乘一次
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
    gate = '> 55%，正常开仓（高标被砸、周一放宽不做）' if red > 0.55 else ('40–55%，只做总龙头首阴 / 缩量断板低开 / 高标被砸 / 首板强势未封低开 / 2板断板强收 / 周一放宽' if red >= 0.40 else '< 40%，只做总龙头首阴 / 缩量断板低开 / 高标被砸 / 首板强势未封低开 / 2板断板强收')
    L_ = [f'## 模拟盘（{D}）', '', f'- 今天 9:25 全A竞价红盘率 **{red:.1%}**（{gate}）；按 {P} 收盘的候选执行。',
          f'- 账户净值 **{eq:.4f}**（2026-11-02 起始 1.0000），现金 {book["cash"] / eq:.0%}，持仓 {len(book["pos"])} 只。', '']
    L_ += ['**今天买入**', ''] + ([f'- {b[0]}：{b[2]}（{b[1]}）买入价 {b[3]:.2f}，仓位 {b[4] / eq_open:.0%}' for b in buys] or ['- 无']) + ['']
    other = skips
    if other: L_ += ['**按规则没买**', ''] + [f'- {x}' for x in other] + ['']
    L_ += ['**今天收盘卖出**', ''] + ([f'- {x[0]}：{x[2]} 买入 {x[3]:.2f} → 卖出 {x[4]:.2f}，{x[5]:+.1%}（{x[6]}）' for x in sells] or ['- 无']) + ['']
    L_ += ['**收盘持仓**', '']
    if book['pos']:
        L_ += ['| 路线 | 名称 | 买入日 | 买入价 | 今收 | 浮动 | 下一步 |', '|---|---|---|---|---|---|---|']
        for p in book['pos']:
            nxt = '亏损且中证1000 跌 ≥ 1%，推迟到明天尾盘卖' if p.pop('note', None) else f"拿满 5 天（已 {p['held']} 天）" if p['src'] == 'RB' else ('高点回撤 10% 卖' if p['src'] == 'B' else ('明天不涨停且涨不到 7%（20cm 14%）就尾盘卖' if p['src'] == 'LD' else '明天不涨停就尾盘卖'))
            L_.append(f"| {NAME[p['src']]} | {p['name']} | {p['entry']} | {p['ep']:.2f} | {p['last']:.2f} | {p['last'] / p['ep'] - 1:+.1%} | {nxt} |")
    else: L_.append('- 空仓')
    L_ += ['', f'明天开仓前先扣掉以上持仓：已占 {len(book["pos"])} / 5 个仓位。']
    open(os.path.join(simd, f'{D}.md'), 'w').write('\n'.join(L_))
    print('\n'.join(L_))


if __name__ == '__main__':
    main()
