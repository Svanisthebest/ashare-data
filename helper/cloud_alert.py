# -*- coding: utf-8 -*-
"""GitHub 云端提醒（备份）：交易日在 GitHub 上运行开单工具的核心逻辑，按「模拟盘持仓」推送到手机。

- 9:25:15 起：算全 A 竞价红盘率 → 生成开单单 → 推送（失败每 20 秒重试到 9:30:30，最终失败也推送）
- 9:30–15:00：高标被砸挂单可能成交 → 推送
- 10:30–14:57：持仓冲到涨停又打开 → 推送
- 14:55：卖出检查 → 推送
推送标题带「云端备份·」，内容按模拟盘持仓和 CLOUD_EQUITY（默认 100 万）估算股数，和你的真实持仓可能不同。

用法：python3 helper/cloud_alert.py [--selftest]
环境变量：PUSH_DEST（推送 token / 地址，GitHub Secrets）、CLOUD_EQUITY（账户金额，可选）、CLOUD_ALERT=off 时不运行。
"""
import json, os, sys, tempfile, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('ASH_LOCAL_REPO', ROOT)
os.environ.setdefault('ASH_NOBROWSER', '1')
os.environ.setdefault('ASH_PUSH_PREFIX', '云端备份·')
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ash_cloud_')
sys.path.insert(0, os.path.join(ROOT, 'helper'))
import core  # noqa: E402

S = core.S


def setup():
    S['push'] = os.environ.get('PUSH_DEST', '').strip()
    eq = float(os.environ.get('CLOUD_EQUITY') or 1_000_000)
    b = json.load(open(os.path.join(ROOT, 'data', 'sim', 'book.json'), encoding='utf-8'))
    tot = b['cash'] + sum(p['val'] for p in b['pos'])
    k = eq / tot if tot > 0 else eq
    hold = []
    for p in b['pos']:
        px = p.get('last') or p['ep']
        sh = max(100, int(p['val'] * k / px / 100) * 100)
        hold.append(dict(code=p['code'], name=p['name'], src=p['src'], entry=p['entry'], buy_price=p['ep'], shares=sh,
                         peak=p.get('peak', p['ep']), extra=p.get('extra', 0), delayed=1 if '推迟' in (p.get('note') or '') and p.get('delayed', 0) else p.get('delayed', 0)))
    S['equity'] = eq; S['holdings'] = hold
    core.refresh_plan()
    core.log(f"云端提醒启动：模拟盘持仓 {len(hold)} 只（{'、'.join(h['name'] for h in hold) or '无'}），账户按 {eq:,.0f} 元估算；推送{'已设置' if core._push_channel(S['push']) else '未设置（只打日志）'}")


def selftest():
    """周末 / 随时可跑：检查能否读到计划、行情（东方财富 / 腾讯）、推送配置。"""
    setup()
    t0 = time.time(); rows = core.quotes_all()
    print(f"全市场行情：{len(rows)} 只，来源 {core.QSRC['src']}，{time.time() - t0:.1f} 秒")
    some = core.quotes_some([h['code'] for h in S['holdings']] or ['600000'])
    print('腾讯个股行情：', {k: v.get('price') for k, v in list(some.items())[:5]})
    print('计划日期：', (S.get('latest') or {}).get('plan_date'), '规则', (S.get('rules') or {}).get('version'), '候选', len(S.get('cand') or []))
    if core._push_channel(S['push']):
        ok, msg = core.push_send('云端提醒自检', f"GitHub 云端提醒可以正常运行：行情 {len(rows)} 只（{core.QSRC['src']}），模拟盘持仓 {len(S['holdings'])} 只")
        print('推送测试：', '成功' if ok else f'失败 {msg}')
    else:
        print('推送：没有设置 PUSH_DEST，跳过')


def run():
    setup()
    now = core.bj_now(); today = now.strftime('%Y%m%d')
    if now.weekday() >= 5: print('周末，不运行'); return
    if now.strftime('%H%M') >= '1450': print('已经接近收盘（可能是排队的重复运行），不运行'); return
    try:
        days = core.trade_days()
        if days and today not in days and max(days) >= today: print('今天不是交易日，不运行'); return
    except Exception: pass
    next_try = 0; k_done = False
    while True:
        now = core.bj_now(); hm = now.strftime('%H%M')
        if hm >= '1500': break
        try:
            if '0925' <= hm < '0931' and S.get('orders_date') != today and (hm >= '0926' or now.second >= 15) and time.time() >= next_try:
                try: core.build_orders()
                except Exception as e:
                    next_try = time.time() + 20
                    if '不是今天' in str(e) and hm >= '0926':
                        print(f'行情不是今天的（节假日休市），云端提醒结束：{e}'); return
                    if hm >= '0930' and now.second >= 30:
                        core.log(f'开单单最终没生成：{e}'); S['orders_date'] = today + '_fail'
                        core.push('开单单没生成', f'{e}\n（这是云端备份；以开单工具为准）', key='orders_fail')
                    else: core.log(f'开单单这次没成功：{e}；20 秒后重试')
            if '0930' <= hm <= '1500':
                try: core.pending_k()
                except Exception: pass
            ba = ((S.get('rules') or {}).get('sell', {}).get('break_after') or '10:30').replace(':', '')
            if ba <= hm < '1457':
                try: core.watch_breaks()
                except Exception as e: core.log(f'炸板检查出错：{e}')
            if '1455' <= hm < '1500' and S.get('sells_date') != today:
                try: core.build_sells()
                except Exception as e: core.log(f'卖出检查失败：{e}'); S['sells_date'] = today + '_fail'
            if S.get('sells_date') in (today, today + '_fail') and hm >= '1456': break
        except Exception:
            core.log('出错：' + traceback.format_exc()[-300:])
        # 9:24 前睡长一点，9:25–9:31 每 5 秒，其余 15 秒
        time.sleep(30 if hm < '0924' else 5 if hm < '0931' else 15)
    time.sleep(8)   # 等后台推送发完
    print('今天的云端提醒结束')


def testpush(day=None):
    """用最近一个交易日（或指定日期 day，用仓库里那天的日线回放）的行情，把 9:25 开单单和 14:55 卖出检查各走一遍并真的推送（标题注明测试）。"""
    if day:
        core.MOCK = f'{ROOT};{day}'; os.environ['ASH_PUSH_TEST'] = '1'
    setup()
    if day: S['holdings'] = []   # 回放过去的日子：现在的模拟盘持仓那天还不存在，只测开单单
    days = core.trade_days() or []
    last = day or (max(d for d in days if d <= core.bj_now().strftime('%Y%m%d')) if days else core.bj_now().strftime('%Y%m%d'))
    os.environ['ASH_PUSH_PREFIX'] = f'云端备份·测试（{last[4:6]}-{last[6:]} 数据）·'
    os.environ['ASH_NOW'] = f'{last} 09:26'
    S['pushed'] = {}; S['orders_date'] = None
    # 用测试那天真正在用的计划：前一个交易日收盘后生成的那份（不是最新的）
    import csv as _csv, io as _io
    prev = core.prev_trade_day(last)
    if prev and (S.get('latest') or {}).get('plan_date') != prev:
        txt = core.repo_get(f'data/plan/{prev}.csv') if os.path.exists(os.path.join(ROOT, 'data', 'plan', f'{prev}.csv')) else 'src,代码\n'
        S['cand'] = [r for r in _csv.DictReader(_io.StringIO(txt.lstrip('\ufeff')))]
        S['latest'] = dict(S['latest'], plan_date=prev, csv=f'data/plan/{prev}.csv', md=f'data/plan/{prev}.md')
        core.log(f'测试改用 {prev} 的计划（{last} 开盘时实际用的那份），候选 {len(S["cand"])} 只')
    core.build_orders()
    os.environ['ASH_NOW'] = f'{last} 14:55'
    S['sells_date'] = None
    core.build_sells()
    time.sleep(8)
    print('测试推送完成')


if __name__ == '__main__':
    if os.environ.get('CLOUD_ALERT', '').lower() == 'off':
        print('CLOUD_ALERT=off，不运行'); sys.exit(0)
    if '--testpush' in sys.argv:
        i = sys.argv.index('--testpush'); testpush(sys.argv[i + 1] if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else None)
    else: (selftest if '--selftest' in sys.argv else run)()
