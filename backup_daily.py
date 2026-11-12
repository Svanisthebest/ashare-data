"""备用日线数据源（通达信盘后包取不到时用）+ 收盘价交叉核对。

- em_snapshot(ymd)：东方财富全市场快照（收盘后取，等于当天日线），换算成与通达信相同的格式（volume=股，amount=元）。
  只能取「今天」：快照里每只股票的最后成交时间（f124）必须是 ymd，多数不是就报错（节假日 / 还没收盘）。
- qq_check(df, ymd)：随机抽样用腾讯行情核对收盘价、昨收、成交量；不一致比例超过阈值就报错。
"""
import datetime as dt
import random
import time

import pandas as pd
import requests

CN = dt.timezone(dt.timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
EM_HOSTS = ["https://push2.eastmoney.com", "https://82.push2.eastmoney.com", "https://29.push2.eastmoney.com"]
FS_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"      # 深主板、创业板、沪主板、科创板、北交所
INDEX = {"1.000001": "上证指数", "0.399001": "深证成指", "0.399006": "创业板指", "1.000688": "科创50",
         "1.000300": "沪深300", "1.000905": "中证500", "1.000852": "中证1000", "0.899050": "北证50"}


def _get(path, params, tries=3):
    err = None
    for k in range(tries):
        for h in EM_HOSTS:
            try:
                r = requests.get(h + path, params=params, headers=UA, timeout=20)
                r.raise_for_status()
                return r.json()
            except Exception as e:      # noqa: BLE001
                err = e
        time.sleep(2 * (k + 1))
    raise RuntimeError(f"东方财富接口失败：{err}")


def _market(code, f13):
    if code.startswith(("4", "8", "92")):
        return "bj"
    return "sh" if int(f13) == 1 else "sz"


def _ts_day(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), CN).strftime("%Y%m%d")
    except Exception:       # noqa: BLE001
        return ""


def em_snapshot(ymd):
    rows, pn, total = [], 1, None
    while True:
        j = _get("/api/qt/clist/get", dict(pn=pn, pz=100, po=0, np=1, fltt=2, invt=2, fid="f12", fs=FS_A,
                                            ut="bd1d9ddb04089700cf9c27f6f7426281",
                                            fields="f12,f13,f14,f2,f15,f16,f17,f18,f5,f6,f124"))
        data = (j or {}).get("data") or {}
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        total = data.get("total", total)
        rows += diff
        if not diff or (total and len(rows) >= total) or pn > 120:
            break
        pn += 1
    if not total or len(rows) < 0.98 * total or len(rows) < 5000:
        raise RuntimeError(f"东方财富快照不完整：取到 {len(rows)} / {total}")
    out, days = [], []
    for r in rows:
        code = str(r.get("f12", "")).zfill(6)
        vals = [r.get(k) for k in ("f18", "f17", "f15", "f16", "f2", "f5", "f6")]
        if any(v in ("-", None, "") for v in vals):
            continue                       # 停牌 / 当天无成交：不写（下游本来就只用成交量 > 0 的行）
        pc, o, h, lo, c, vol, amt = map(float, vals)
        if c <= 0 or vol <= 0:
            continue
        days.append(_ts_day(r.get("f124")))
        out.append({"date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", "market": _market(code, r.get("f13", 0)), "code": code,
                    "name": str(r.get("f14", "")).strip(), "prev_close": pc, "open": o, "high": h, "low": lo, "close": c,
                    "volume": int(round(vol * 100)), "amount": round(amt, 2)})
    n_today = sum(d == ymd for d in days)
    if n_today < 0.9 * max(len(days), 1):
        latest = max(days) if days else "?"
        raise ValueError(f"东方财富快照的成交日期不是 {ymd}（最新 {latest}，{n_today}/{len(days)} 只是当天）：非交易日或还没收盘")
    df = pd.DataFrame(out)
    if len(df) < 4800:
        raise RuntimeError(f"东方财富快照有成交的股票只有 {len(df)} 只，太少")
    bad = df[(df.high < df[["open", "close"]].max(axis=1) - 1e-6) | (df.low > df[["open", "close"]].min(axis=1) + 1e-6)]
    if len(bad) > 5:
        raise RuntimeError(f"东方财富快照有 {len(bad)} 只高低价不合理")
    return df


def em_index(ymd):
    j = _get("/api/qt/ulist.np/get", dict(secids=",".join(INDEX), fltt=2, invt=2, ut="bd1d9ddb04089700cf9c27f6f7426281",
                                           fields="f12,f13,f2,f18,f6,f124"))
    diff = ((j or {}).get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    out = []
    for r in diff:
        key = f"{r.get('f13')}.{str(r.get('f12')).zfill(6)}"
        if key not in INDEX or r.get("f2") in ("-", None) or _ts_day(r.get("f124")) != ymd:
            continue
        c, pc = float(r["f2"]), float(r["f18"])
        out.append({"date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}", "指数": INDEX[key], "close": c,
                    "涨跌幅": round((c / pc - 1) * 100, 2), "amount": float(r.get("f6") or 0)})
    if not any(x["指数"] == "中证1000" for x in out):
        raise RuntimeError("东方财富指数快照没有当天的中证1000")
    return pd.DataFrame(out)


def qq_quotes(codes):
    out = {}
    for i in range(0, len(codes), 60):
        sym = [("sh" if c.startswith(("6", "9")) else "bj" if c.startswith(("4", "8")) else "sz") + c for c in codes[i:i + 60]]
        txt = None
        for k in range(3):
            try:
                r = requests.get("https://qt.gtimg.cn/q=" + ",".join(sym), headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                r.encoding = "gbk"; txt = r.text; break
            except Exception:       # noqa: BLE001
                time.sleep(2)
        for line in (txt or "").strip().split(";"):
            if '="' not in line:
                continue
            k, v = line.split('="', 1); f = v.strip('"\n').split("~")
            if len(f) < 38:
                continue
            try:
                out[k[-6:]] = dict(close=float(f[3]), pc=float(f[4]), vol=float(f[6]) * 100, date=f[30][:8])
            except ValueError:
                pass
    return out


def qq_check(df, ymd, n=300, max_bad=0.02):
    """抽 n 只有成交的股票，与腾讯行情核对收盘价 / 昨收（差 > 0.011 元算不一致）和成交量（差 > 2% 算不一致）。返回说明文字；不一致太多抛错。"""
    x = df[df.volume > 0]
    codes = random.Random(int(ymd)).sample(list(x.code), min(n, len(x)))
    q = qq_quotes(codes)
    q = {c: v for c, v in q.items() if v["date"] == ymd}
    if len(q) < 0.5 * len(codes):
        return f"腾讯行情只取到 {len(q)}/{len(codes)} 只当天数据，未核对"
    x = x.set_index("code")
    bad = []
    for c, v in q.items():
        r = x.loc[c]
        if abs(r.close - v["close"]) > 0.011 or abs(r.prev_close - v["pc"]) > 0.011 or abs(r.volume - v["vol"]) > 0.02 * max(v["vol"], 1):
            bad.append(f"{c}({r.close}/{v['close']})")
    msg = f"与腾讯核对 {len(q)} 只，不一致 {len(bad)} 只" + (("：" + "、".join(bad[:5])) if bad else "")
    if len(bad) > max_bad * len(q):
        raise RuntimeError(msg)
    return msg
