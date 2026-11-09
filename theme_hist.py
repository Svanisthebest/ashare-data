"""东方财富概念/行业板块的完整历史日线（用于判断每个板块哪天开始存在、历史上每天哪些题材最热）"""
import time, random, requests, pandas as pd
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'})
B = pd.read_csv('data/theme/boards.csv', dtype=str); rows = []; bad = 0
for i, r in enumerate(B.itertuples(index=False)):
    for t in range(4):
        try:
            j = S.get(random.choice(['https://push2his.eastmoney.com', 'https://7.push2his.eastmoney.com']) + '/api/qt/stock/kline/get',
                      params={'secid': f'90.{r.bk}', 'klt': 101, 'fqt': 0, 'beg': '0', 'end': '20500101', 'lmt': 100000,
                              'fields1': 'f1,f2,f3', 'fields2': 'f51,f53,f57,f59', 'ut': 'fa5fd1943c7b386f172d6893dbfba10b'}, timeout=20).json()
            for line in ((j or {}).get('data') or {}).get('klines') or []:
                d, c, amt, pct = line.split(','); rows.append((r.bk, d, c, amt, pct))
            break
        except Exception as e:
            time.sleep(2 + 2 * t)
    else:
        bad += 1
    time.sleep(0.3 + random.random() * 0.3)
    if i % 50 == 0: print(i, len(B), len(rows), 'bad', bad, flush=True)
K = pd.DataFrame(rows, columns=['bk', 'date', 'close', 'amount', 'pct'])
K.to_csv('data/theme/board_kline_full.csv.gz', index=False, compression='gzip')
print('完成', K.bk.nunique(), '个板块', len(K), '行，失败', bad, '最早', K.date.min())
