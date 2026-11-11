#!/usr/bin/env python3
"""
v1.4 短线系统：收盘后生成次日候选清单（不看未来数据）。
v1.4 相对 v1.3：新增 2板断板强收（Q，15%，最多 2 只，排最后、不受竞价开关限制）；卖出加「10:30 后持仓冲到涨停又打开就立即卖」。
v1.3 相对 v1.2：核心路线排最前（总龙头首阴 30%、2板龙头 25%、周一放宽 25%）；新增缩量断板低开（N，30%，最多 2 只）、
首板强势未封低开（P，15%，最多 2 只），两者不受竞价开关限制；高标被砸 20%，信号日涨停 ≥ 60 家不做，改为开盘后挂开盘价 −3% 买单；
去掉跌深反弹、强势回调、低位跟随。
v1.2 相对 v1.1：新增高标被砸路线（只在竞价红盘 < 55% 时做，每笔 10%，最多 2 只；开盘低开 0–3% 开盘买，低开 3–5% 等 9:40 确认）。
v1.1 相对 v1：总龙头首阴要求昨日最高板 ≥ 4；强势回调要求昨日涨停股今日溢价 > 0；去掉试验仓；总龙头首阴、低位启动每笔 25%。
先运行 clusters_daily.py 生成当天联动分组，再运行本脚本：
    python clusters_daily.py --date 20261030 --out data
    python v1_plan.py --date 20261030 --out data
输出 data/plan/YYYYMMDD.md（次日计划）和 data/plan/YYYYMMDD.csv（全部候选）。
"""
import argparse, time, glob, os, datetime as dt
import numpy as np, pandas as pd
import clusters_daily


def load(root, date, n_days=130):
    """与 clusters_daily.load 相同，但历史上的 ST 日子不删（只在信号当天排除 ST），与研究口径一致。"""
    return _load(root, date, n_days)


def _load(root, date, n_days):
    fs = sorted(f for f in glob.glob(os.path.join(root, 'daily', '*.csv.gz')) if os.path.basename(f)[:8] <= date)[-n_days:]
    df = pd.concat((pd.read_csv(f, dtype={'code': str}) for f in fs), ignore_index=True)
    df = df[(df.prev_close > 0) & (df.close > 0) & (df.volume > 0)].copy()   # 停牌日（成交量 0）剔除，与研究口径一致
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

NAME = {'B': '恐慌低吸', 'L': '2板龙头', 'LD': '总龙头强势首阴', 'D': '低位启动', 'M': '周一放宽', 'K': '高标被砸',
        'N': '缩量断板低开', 'P': '首板强势未封低开', 'Q': '2板断板强收', 'Y': '炸板弱转强'}
ORDER = ['LD', 'L', 'M', 'N', 'B', 'K', 'D', 'P', 'Q', 'Y']
CAP = {'N': 2, 'P': 2, 'Q': 2, 'K': 2, 'D': 3, 'Y': 2}
SIZE = {'LD': 30, 'L': 25, 'M': 25, 'N': 30, 'B': 20, 'K': 20, 'D': 25, 'P': 15, 'Q': 15, 'Y': 15}


def sealed_minutes(codes, D, ups):
    """收盘后取当天 1 分钟线，返回 {code: 在涨停价的分钟数}（≥1 分钟才算封过）；取不到的列在第二个返回值。
    先用通达信（与研究相同），失败再用 baostock 5 分钟线（5 分钟收盘在涨停价）。"""
    res, miss = {}, []
    if not codes: return res, miss
    c = None
    try:
        from mootdx.quotes import Quotes
        c = Quotes.factory(market='std', bestip=False, timeout=15)
    except Exception as e:
        print('通达信连接失败', e)
    left = []
    for code in codes:
        n = None
        if c is not None:
            for k in range(2):
                try:
                    m = c.minutes(symbol=code, date=D)          # 只取指定交易日；取不到就走 baostock（带日期），不用不带日期的接口
                    if m is not None and len(m) >= 200:
                        n = int((m.price.astype(float) >= ups[code] - 0.005).sum()); break
                except Exception:
                    time.sleep(1)
        if n is None: left.append(code)
        elif n >= 1: res[code] = n
    if left:
        try:
            import baostock as bs
            bs.login(); d_ = f'{D[:4]}-{D[4:6]}-{D[6:]}'
            for code in left:
                sym = ('sh.' if code.startswith(('6', '9')) else 'sz.') + code
                rs = bs.query_history_k_data_plus(sym, 'time,close', start_date=d_, end_date=d_, frequency='5', adjustflag='3')
                rows = []
                while rs.error_code == '0' and rs.next(): rows.append(rs.get_row_data())
                if len(rows) >= 40:
                    n = sum(float(x[1]) >= ups[code] - 0.005 for x in rows) * 5
                    if n: res[code] = n
                else: miss.append(code)
            bs.logout()
        except Exception as e:
            print('baostock 失败', e); miss += [x for x in left if x not in res and x not in miss]
    return res, miss


BAD_BOARD = r'百元|昨日|连板|涨停|炸板|触板|首板|多板|融资融券|沪股通|深股通|标准普尔|富时|MSCI|重仓|增仓|减仓|新进|持股|破净|破发|破增发|低市|高市盈|低价|价值|成长|风格|大盘|中盘|小盘|微盘|微利|权重|股权|举牌|增持|中证|深成|上证|HS300|深证100|央视50|创业板综|连续亏损|中报|季报|年报|预增|预减|扭亏|首亏|ST|摘帽|题材股|趋势股|反转股|超跌|新高|热股|行业龙头|周期股|红利|茅指数|宁组合|转债|GDR|AB股|AH股|B股|北交所|做市|IPO受益|金股|贬值受益|养老金|近期|参股|改革|特区|长江三角|西部大开发|京津冀|一带一路|东北振兴|滨海新区|自贸|新材料|高端装备|节能环保|^新能源$|先进制造|数字经济|新零售|新消费|独角兽|中字头|稀缺资源|军民融合|智慧城市|大数据|创投|AI应用|人工智能'


def board_volume(root, D, codes):
    """每只候选所属最强板块（当天涨幅最大的题材/行业板块）今天的量能：板块成交额 / 前 5 日均额、板块近 20 日涨幅。
    只是提示，不是开单条件。研究（R160）：板块量比 ≥1.8 或 高位（20 日涨 >15%）再放量 ≥1.5 时，次日买入的结果明显变差（近两年）。
    板块日线用 data/theme/board_kline.csv.gz（到上一交易日），今天的涨幅和成交额现取东方财富板块列表；取不到就返回空。"""
    try:
        import requests
        tp = os.path.join(root, 'theme')
        K = pd.read_csv(os.path.join(tp, 'board_kline.csv.gz'), dtype={'bk': str, 'date': str})[['bk', 'date', 'close', 'amount', 'pct']]
        M = pd.read_csv(os.path.join(tp, 'members.csv.gz'), dtype=str)[['bk', 'code', 'board_name']]
        M = M[~M.board_name.astype(str).str.contains(BAD_BOARD)]
        M = M[M.bk.map(M.groupby('bk').size()) >= 5]          # 与研究一致：成分股不足 5 只的小板块不用
        d = f'{D[:4]}-{D[4:6]}-{D[6:]}'
        K = K[K.date <= d]
        if K.date.max() < d:                         # 板块日线还没更新到今天：取当天快照补一行
            S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'})
            rows = []
            for fs in ['m:90 t:3 f:!50', 'm:90 t:2 f:!50']:
                pn = 1
                while pn < 20:
                    j = None
                    for host in ['https://push2.eastmoney.com', 'https://29.push2.eastmoney.com', 'https://82.push2.eastmoney.com']:
                        try:
                            j = S.get(host + '/api/qt/clist/get', params=dict(pn=pn, pz=100, po=1, np=1, ut='bd1d9ddb04089700cf9c27f6f7426281', fltt=2, invt=2,
                                                                             fid='f3', fs=fs, fields='f12,f3,f6'), timeout=15).json(); break
                        except Exception: time.sleep(1)
                    diff = ((j or {}).get('data') or {}).get('diff') or []
                    rows += diff
                    if not diff or len(diff) < 100: break
                    pn += 1
            T = pd.DataFrame([dict(bk=r['f12'], pct=r['f3'], amount=r['f6']) for r in rows if r.get('f3') not in ('-', None) and r.get('f6') not in ('-', None)])
            if len(T) < 100: return {}
            last = K.sort_values('date').groupby('bk').close.last()
            T['date'] = d; T['close'] = T.bk.map(last) * (1 + T.pct.astype(float) / 100)
            K = pd.concat([K, T.dropna(subset=['close'])], ignore_index=True)
        for c in ['close', 'amount', 'pct']: K[c] = pd.to_numeric(K[c], errors='coerce')
        K = K.sort_values(['bk', 'date']); g = K.groupby('bk')
        K['vr'] = K.amount / g.amount.transform(lambda s: s.rolling(5, min_periods=3).mean().shift(1))
        K['r20'] = g.close.transform(lambda s: s / s.shift(20) - 1)
        t = K[K.date == d].drop_duplicates('bk').set_index('bk')
        out = {}
        for code in codes:
            bs = [b for b in set(M.bk[M.code == code]) if b in t.index and pd.notna(t.at[b, 'vr'])]
            if not bs: continue
            x = t.loc[bs]; b = x.pct.idxmax(); y = x.loc[b]
            nm = M.board_name[M.bk == b].iloc[0]; r20 = float(y.r20) if pd.notna(y.r20) else 0.0
            warn = '⚠板块爆量' if y.vr >= 1.8 else ('⚠板块高位放量' if (r20 > 0.15 and y.vr >= 1.5) else '')
            out[code] = dict(板块=nm, 板块涨幅=round(float(y.pct), 1), 板块量比=round(float(y.vr), 2), 板块20日=round(r20 * 100, 1), 板块提示=warn)
        return out
    except Exception as e:
        print('板块量能未取到：', e); return {}


def write_helper_files(out, D):
    """给电脑端开单助手用：规则参数（与本脚本、sim_book.py 一致）和最新计划的位置。模型升级时只改这里，助手启动时自动读取。"""
    import json
    hp = os.path.join(out, 'helper'); os.makedirs(hp, exist_ok=True)
    rules = dict(version='v1.5', min_core=9, max_positions=5, order=ORDER, names=NAME, size=SIZE, cap=CAP,
                 gate=dict(high=0.55, low=0.40,
                           allowed_high=[s for s in ORDER if s not in ('K', 'M')],
                           allowed_mid=['LD', 'K', 'N', 'P', 'Q', 'M', 'Y'],
                           allowed_low=['LD', 'K', 'N', 'P', 'Q', 'Y']),
                 entry={'L': dict(type='open', max_gap=0.02),
                        'N': dict(type='open', min_gap=-0.05, max_gap=0.0),
                        'P': dict(type='open', min_gap=-0.05, max_gap=0.0),
                        'Q': dict(type='open', min_gap=-0.05, max_gap=0.0),
                        'K': dict(type='limit_from_open', min_gap=-0.03, max_gap=0.0, limit_mult=0.97),
                        'Y': dict(type='open', min_gap=0.03, auc_ratio=[0.03, 0.10])},
                 sell=dict(stop=0.08, stop_B=0.15, B_trail=0.10, B_max_days=20, max_days=11,
                           LD_extra_ratio=0.7, LD_extra_max=3, delay_index_drop=-0.01, delay_once=True, break_after='10:30', break_exempt=['B'], check_time='14:55', order='closing_auction'),
                 notes=['Y（炸板弱转强）：竞价高开 ≥3% 且 竞价成交额是近 5 日平均成交额的 3%–10% 才开盘买；N、P、Q 只在低开 0–5% 时开盘买；K 开盘在昨收 −3%~0 时挂开盘价×0.97，收盘前未成交撤单',
                        '卖出：10:30 后冲到涨停又打开就立即卖；其余 14:55 判定、不涨停就在 14:57–15:00 收盘集合竞价卖（按收盘价成交）；亏 8% 止损；总龙头首阴涨 ≥ 7%（20cm ≥ 14%）可多拿最多 3 天；亏损且中证1000 跌 ≥ 1% 推迟一天'])
    json.dump(rules, open(os.path.join(hp, 'rules.json'), 'w'), ensure_ascii=False, indent=1)
    import hashlib
    h = lambda f: hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16] if os.path.exists(f) else None
    json.dump(dict(plan_date=D, csv=f'data/plan/{D}.csv', md=f'data/plan/{D}.md', rules='data/helper/rules.json', version='v1.5',
                   csv_sha256=h(os.path.join(out, 'plan', f'{D}.csv')), rules_sha256=h(os.path.join(hp, 'rules.json')),
                   generated=dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')), open(os.path.join(hp, 'latest.json'), 'w'), ensure_ascii=False, indent=1)


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
    df['mlb15'] = g.lb.transform(lambda s: s.rolling(15, min_periods=1).max())   # 近 15 个交易日最高连板
    df['amt5'] = g.amount.transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())   # 今天之前 5 日平均成交额（量比用）
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
    # 大盘量能：全市场（不含 ST）成交额 / 前 5 日均额、5 日均量 / 20 日均量（盘前参考，不是开单条件）
    tot = df[~df.st].groupby('date').amount.sum().sort_index()
    v5 = float(tot.iloc[-1] / tot.iloc[-6:-1].mean()) if len(tot) >= 6 else float('nan')
    v520 = float(tot.iloc[-5:].mean() / tot.iloc[-20:].mean()) if len(tot) >= 20 else float('nan')
    vol_txt = f"大盘成交额 {tot.iloc[-1] / 1e8:,.0f} 亿，是前 5 日均额的 {v5:.0%}（{'明显放量' if v5 >= 1.2 else '放量' if v5 >= 1.05 else '平量' if v5 >= 0.95 else '缩量' if v5 >= 0.85 else '明显缩量'}），5 日均量是 20 日均量的 {v520:.0%}"
    nxt = '下一交易日'; monday = pd.Timestamp(d).weekday() == 4   # 周一放宽：信号日为周五
    C = []
    def add(src, code, why, rk):
        r = td.loc[code]; C.append(dict(路线=NAME[src], src=src, 代码=code, 名称=r['name'], 收盘=r.close,
                                        涨跌=round(r.ret * 100, 1), 成交额亿=round(r.amount / 1e8, 1), 均额5日亿=round(r.amt5 / 1e8, 3) if pd.notna(r.amt5) else None,
                                        位置120=round(r.pos120 * 100, 1) if pd.notna(r.pos120) else None, 说明=why, rk=rk))
    # 恐慌低吸
    if ndt >= 200:
        for code, r in td[td.r5 < -0.20].sort_values('r5').iterrows(): add('B', code, f'5日 {r.r5*100:.0f}%', r.r5)
    # 联动分组：2板龙头、低位跟随
    cf = os.path.join(a.out, D, '11_clusters.csv'); sf = os.path.join(a.out, D, '12_cluster_summary.csv')
    if os.path.exists(cf):
        cl = pd.read_csv(cf, dtype={'代码': str}); sm = pd.read_csv(sf).set_index('组')
        # 2板龙头：与回测一致，联动组至少 3 只
        for _, r in cl[(cl['角色'] == '龙头') & (cl['连板'] == 2)].iterrows():
            if r['代码'] in td.index and sm.loc[r['组'], '规模'] >= 3: add('L', r['代码'], f"组{r['组']}（{int(sm.loc[r['组'],'规模'])}只）开盘<+2%才买，即 < {td.loc[r['代码'],'close']*1.02:.2f}", -sm.loc[r['组'], '规模'])
    # 总龙头强势首阴：前一天全市场最高板（v1.1：≥4板），今天没涨停但收涨 > 3%
    pmax = pv.lb[pv.zt].max() if pv.zt.any() else 0
    if pmax >= 4:
        for code in pv[(pv.zt) & (pv.lb == pmax)].index:
            if code in td.index and not td.loc[code, 'zt'] and td.loc[code, 'ret'] > 0.03: add('LD', code, f'昨日 {int(pmax)} 板，今日断板收涨', 0)
    # 高标被砸：近 15 日最高 ≥ 4 板，昨天涨停，今天跌停（非天地板）或跌 ≥ 7%。v1.3：今天涨停 ≥ 60 家不做；
    # 次日竞价红盘 < 55% 且开盘在昨收 −3% 到 0 之间，开盘后挂「开盘价 × 0.97」买单，收盘前没成交就撤单
    kk = td[td.index.isin(pv[pv.zt & (pv.mlb15 >= 4)].index) & ((td['dt'] & (td.high < td.up - 0.001)) | ((td.ret <= -0.07) & ~td['dt']))]
    if nzt < 60:
        for code, r in kk.iterrows():
            m15 = int(pv.loc[code, 'mlb15'])
            add('K', code, f"近15日最高 {m15} 板，昨涨停今{'跌停' if r['dt'] else '大跌'}；红盘 < 55% 且开盘在 {r.close*0.97:.2f}–{r.close-0.01:.2f} 时，挂 开盘价×0.97 买单，没成交就撤", -m15)
    # v1.3 缩量断板低开：昨天涨停且 ≥ 3 板，今天没涨停但收涨，成交额 ≤ 前 5 日均额 × 2.5；次日低开 0–5% 开盘买
    lim_ = np.where(td.board == '主板', 0.1, 0.2)
    nn = td[td.index.isin(pv[pv.zt & (pv.lb >= 3)].index) & ~td.zt & (td.ret > 0) & (td.amount <= 2.5 * td.amt5) & (td.n >= 60)]
    for code, r in nn.iterrows():
        add('N', code, f"昨 {int(pv.loc[code, 'lb'])} 板断板，量比 {r.amount / r.amt5:.1f}；开盘在 {r.close*0.95:.2f}–{r.close-0.01:.2f}（低开 0–5%）才开盘买", -int(pv.loc[code, 'lb']))
    # v1.3 首板强势未封低开：昨天首板，今天没涨停但涨 ≥ 涨停幅 70%（主板 7%、20cm 14%），成交额 ≤ 前 5 日均额 × 2.5；次日低开 0–5% 开盘买
    pp = td[td.index.isin(pv[pv.zt & (pv.lb == 1)].index) & ~td.zt & (td.ret >= 0.7 * lim_) & (td.amount <= 2.5 * td.amt5) & (td.n >= 60)]
    for code, r in pp.iterrows():   # 与回测一致：按代码顺序
        add('P', code, f"昨首板今涨 {r.ret*100:.1f}% 未封，量比 {r.amount / r.amt5:.1f}；开盘在 {r.close*0.95:.2f}–{r.close-0.01:.2f}（低开 0–5%）才开盘买", -r.ret)
    # v1.4 2板断板强收：昨天 2 板，今天没涨停但涨 ≥ 涨停幅 50%（主板 5%、20cm 10%），成交额 ≤ 前 5 日均额 × 2.5；次日低开 0–5% 开盘买
    qq = td[td.index.isin(pv[pv.zt & (pv.lb == 2)].index) & ~td.zt & (td.ret >= 0.5 * lim_) & (td.amount <= 2.5 * td.amt5) & (td.n >= 60)]
    for code, r in qq.iterrows():
        add('Q', code, f"昨 2 板今涨 {r.ret*100:.1f}% 断板，量比 {r.amount / r.amt5:.1f}；开盘在 {r.close*0.95:.2f}–{r.close-0.01:.2f}（低开 0–5%）才开盘买", -r.ret)
    # v1.5 炸板弱转强：今天盘中封住过涨停（分钟线至少 1 分钟在涨停价）但收盘没封住，收盘涨 ≥ 涨停幅 70%，上市 ≥ 60 日；
    # 次日竞价高开 ≥ 3%（不是涨停价）且 竞价成交额 / 近 5 日平均成交额 在 3%–10% 才开盘买
    zb = td[~td.zt & (td.ret >= 0.7 * lim_) & (td.high >= td.up - 0.005) & (td.n >= 60)]
    seal, unk = sealed_minutes(list(zb.index), D, zb.up.to_dict())
    for code, r in zb.sort_index().iterrows():
        if code not in seal: continue
        add('Y', code, f"今天封过涨停 {seal[code]} 分钟后被砸，收涨 {r.ret*100:.1f}%；明天竞价高开 ≥3%（≥ {r.close*1.03:.2f}）、且竞价成交额在 {r.amt5*0.03/1e4:.0f}–{r.amt5*0.10/1e4:.0f} 万（5 日均额的 3–10%）才开盘买", 0)
    y_note = f"炸板 {len(zb)} 只，分钟线确认封过 {len(seal)} 只" + (f"，{len(unk)} 只没取到分钟线已跳过（{'、'.join(unk[:8])}）" if unk else '')
    # 周一放宽（v1.3 去掉强势回调，候选池不变）：近 6 日 ≥ 2 个涨停、今天没涨停、从 5 日高点回撤 > 8%、在 10 日线上，中证1000 在 5 日线上
    cc = td[(td.n >= 60) & (td.zt5 >= 2) & (~td.zt) & (td.adj < td.hi5 * 0.92) & (td.adj > td.ma10)]
    if above5 and monday:
        for code, r in cc.iterrows(): add('M', code, '只在周一竞价红盘 40–55% 时做', 0)
    # 低位启动
    # 排序（R161）：按当天成交额从大到小。原来按 120 日位置从低到高，回测不比随机好；成交额大的略好、也更容易按价成交
    for i, (code, r) in enumerate(td[td.ret.between(0.05, 0.095) & (td.pos120 < 0.10)].sort_values('amount', ascending=False).iterrows()):
        add('D', code, '首选（成交额最大）' if i < 3 else '备选', i)
    P = pd.DataFrame(C)
    # 板块量能提示（不改变开单规则）
    BV = board_volume(a.out, D, list(P['代码'].unique())) if len(P) else {}
    if len(P):
        for col in ['板块', '板块涨幅', '板块量比', '板块20日', '板块提示']: P[col] = P['代码'].map(lambda c: BV.get(c, {}).get(col))
        P['说明'] = [f"{w}【{BV[c]['板块']} 今天量比 {BV[c]['板块量比']}、20日 {BV[c]['板块20日']:+.0f}%：{BV[c]['板块提示'][1:]}，次日容易分歧，可少买或不买】" + ' ' + str(x) if c in BV and BV[c]['板块提示'] else x
                       for c, x, w in zip(P['代码'], P['说明'], ['⚠'] * len(P))]
    os.makedirs(os.path.join(a.out, 'plan'), exist_ok=True)
    if len(P): P['优先级'] = P.groupby('src').cumcount() + 1          # 路线内执行顺序 = 加入顺序（与回测、模拟盘、开单工具一致）
    if len(P): P.drop(columns='rk').to_csv(os.path.join(a.out, 'plan', f'{D}.csv'), index=False, encoding='utf-8-sig')
    # 写计划
    L = [f'# v1.5 计划：{d} 收盘 → {nxt}', '',
         f'- 当天：红盘率 {red:.0%}，涨停 {nzt}，跌停 {ndt}，最高 {maxlb} 板；中证1000 {zr:+.2%}，距 20 日高点 {fh:+.1%}，{"在" if above5 else "不在"} 5 日线上。',
         f'- 量能：{vol_txt}。大票缩量上涨一般走不远，明显放量的上涨才有延续性（仅供参考）。',
         '- 板块量能：候选表里的「所属板块（量比）」是该股当天最强板块的成交额 ÷ 前 5 日均额。量比 ≥1.8，或板块 20 日已涨 >15% 且量比 ≥1.5，会标 ⚠：板块爆量多是情绪高潮，次日容易分歧，可少买或不买（提示，不是规则）。',
         f'- 特殊状态：恐慌低吸{"已触发" if ndt >= 200 else "未触发"}（跌停 ≥ 200）；昨日涨停溢价 {prem:+.2%}；总龙头首阴{"有资格" if pmax >= 4 else "不做（昨日最高板 < 4）"}（昨日最高 {int(pmax)} 板）；{y_note}；高标被砸{"可做" if nzt < 60 else "不做（今天涨停 ≥ 60 家）"}；{("今天是周五，下一交易日适用周一放宽" if above5 else "今天是周五，但中证1000 在 5 日线下，周一放宽不做") if monday else ""}', '',
         '## 9:25 竞价决定动作', '',
         '| 全A竞价红盘率 | 可做的路线 |', '|---|---|',
         '| > 55% | 总龙头首阴、2板龙头、缩量断板低开、恐慌低吸、低位启动、首板强势未封低开、2板断板强收、炸板弱转强（高标被砸、周一放宽不做） |',
         '| 40–55% | 总龙头首阴、缩量断板低开、高标被砸、首板强势未封低开、2板断板强收、炸板弱转强；周一另做周一放宽 |',
         '| < 40% | 总龙头首阴、缩量断板低开、高标被砸、首板强势未封低开、2板断板强收、炸板弱转强 |', '',
         '最多同时 5 只（含已有持仓）；缩量断板低开、首板强势未封低开、2板断板强收、高标被砸、炸板弱转强各最多 2 只，低位启动最多 3 只。顺序：总龙头首阴 → 2板龙头 → 周一放宽 → 缩量断板低开 → 恐慌低吸 → 高标被砸 → 低位启动 → 首板强势未封低开 → 2板断板强收 → 炸板弱转强。一字涨停或停牌跳过，用同路线下一只补；同一只股票只买一次（已持有或已在前面路线买过的跳过）。', '竞价红盘率口径：沪深 A 股（不含北交所、ST、退市、停牌），9:25 竞价价高于昨收的家数 ÷ 全部，平盘不算红；目前约 5,020 只，> 55% 约需 2,765 家，40% 约 2,010 家。', '']
    for src in ORDER:
        x = P[P.src == src] if len(P) else P          # 按执行顺序显示，不另排
        L.append(f'## {NAME[src]}（每笔 {SIZE[src]}%{"，最多 " + str(CAP[src]) + " 只" if src in CAP else ""}）')
        if not len(x): L += ['', '无候选。', '']; continue
        L += ['', '| 代码 | 名称 | 收盘 | 涨跌% | 成交额亿 | 位置% | 所属板块（量比） | 说明 |', '|---|---|---|---|---|---|---|---|']
        L += [f"| {r['代码']} | {r['名称']} | {r['收盘']:.2f} | {r['涨跌']} | {r['成交额亿']} | {r['位置120']} | {(str(r['板块']) + ' ' + str(r['板块量比'])) if pd.notna(r.get('板块')) else '—'} | {r['说明']} |" for _, r in x.head(10).iterrows()]
        L.append('')
    L += ['## 卖出', '', '- 恐慌低吸从高点回撤 10% 卖，收盘亏 15% 止损，最多拿 20 天。',
          '- 其他路线：买入后第一个可卖日起，10:30 以后盘中冲到涨停又打开（5 分钟收在涨停价下方）就立即卖；其余不涨停就尾盘卖；总龙头首阴当天涨 ≥ 7%（20cm ≥ 14%）也可多拿，最多 3 天；收盘亏 8% 止损；最多拿 11 天。',
          '- v1.1：到了该卖的那天，14:55 若持仓亏损且中证1000 当天跌 ≥ 1%，推迟一天再卖（只推迟一次；亏 8% 仍止损）。',
          '- 尾盘卖：14:55 看价格和中证1000 判定（开单工具 14:55 自动检查），要卖的在 14:57–15:00 收盘集合竞价挂比现价低约 2% 的限价单，按收盘价成交。回测显示 14:45 就判定会少赚不少（尾盘才封板的票会被卖掉）。封死跌停卖不出就次日开盘卖；不用盘中止损单。', '',
          '## 执行', '', '- 9:25 竞价确认后开盘买：9:25–9:30 挂「竞价价 +0.5%」限价单；9:30 没成交最多改到竞价价 +1%，再高就不买（晚买平均多付 1% 以上，回测收益会明显下降）。2板龙头挂单价不超过昨收 +2%，低开路线不超过昨收；缩量断板低开、首板强势未封低开、2板断板强收只在开盘价低于昨收、且不低于昨收 −5% 时买，平开或高开不买。',
          '- 炸板弱转强（v1.5）：竞价高开 ≥3%（不是涨停价）且竞价成交额在说明里给出的区间（近 5 日平均成交额的 3%–10%）才买，按竞价价 +0.5% 挂单。量太小是诱多、太大是出货，都不买。约三分之一买完当天会被砸，属于这条路线的正常情况，按卖出规则处理即可。',
          '- 高标被砸：开盘在昨收 −3% 到 0 之间时，开盘后挂「开盘价 × 0.97」限价买单，收盘前没成交就撤单（不追）。',
          '- 资金大时 9:30–10:00 分几次买，单只不超过该股昨日成交额的 4%。',
          '- 空闲资金放国债逆回购或货币 ETF，要用时开盘先卖。']
    open(os.path.join(a.out, 'plan', f'{D}.md'), 'w').write('\n'.join(L))
    write_helper_files(a.out, D)
    print('\n'.join(L))


if __name__ == '__main__':
    main()
