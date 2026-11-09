"""探测：历史涨停池（含涨停原因/题材、首次封板时间、炸板次数、封单）能回溯多远"""
import json, requests, time
S = requests.Session(); S.headers['User-Agent'] = 'Mozilla/5.0'; out = {}
for d in ['20160315', '20180608', '20190308', '20200603', '20210104', '20220608', '20231106', '20250310', '20261106']:
    r = {}
    try:
        j = S.get('https://push2ex.eastmoney.com/getTopicZTPool', params=dict(ut='7eea3edcaed734bea9cbfc24409ed989', dpt='wz.ztzt', Pageindex=0, pagesize=500, sort='fbt:asc', date=d), timeout=15).json()
        p = (j.get('data') or {}).get('pool') or []
        r['em_n'] = len(p); r['em_sample'] = p[:2]
    except Exception as e: r['em_err'] = str(e)[:100]
    try:
        j = S.get('https://apphis.longhuvip.com/w1/api/index.php', params=dict(a='DailyLimitPerformance', c='HisHomeDingPan', PhoneOSNew=1, apiv='w31', Day=f'{d[:4]}-{d[4:6]}-{d[6:]}', st=10, Index=0, VerSion='5.8.0.2'), timeout=15)
        r['kpl_status'] = j.status_code; r['kpl'] = j.text[:600]
    except Exception as e: r['kpl_err'] = str(e)[:100]
    out[d] = r; time.sleep(1)
json.dump(out, open('data/probe_zt.json', 'w'), ensure_ascii=False, indent=1)
for k, v in out.items(): print(k, v.get('em_n'), v.get('em_err'), v.get('kpl_status'), str(v.get('kpl'))[:150])
