"""研究用：baostock 证监会行业分类（全部 A 股），输出 data/industry.csv。"""
import subprocess, sys
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'baostock'], check=False)
import baostock as bs, pandas as pd
bs.login(); rs = bs.query_stock_industry(); rows = []
while rs.error_code == '0' and rs.next(): rows.append(rs.get_row_data())
df = pd.DataFrame(rows, columns=rs.fields); bs.logout()
df.to_csv('data/industry.csv', index=False); print(len(df), df.industry.nunique()); print(df.head())
