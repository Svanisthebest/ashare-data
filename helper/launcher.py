# -*- coding: utf-8 -*-
"""A股开单助手 启动器：每次启动从 GitHub 仓库下载最新的核心程序 helper/core.py 运行（下载失败就用上次缓存的版本）。
所以以后模型或助手升级，只要仓库更新，各台电脑重新打开助手就同步。打包成 exe 后在任何 Windows 电脑双击即可。"""
# 下面这些 import 是给打包工具看的：核心程序用到的标准库都要打进 exe
import csv, io, json, math, os, sys, threading, time, traceback, webbrowser, gzip, ssl, socketserver, email, html  # noqa: F401
import datetime, urllib.request, urllib.parse, urllib.error, http.server, http.client  # noqa: F401

REPO = 'Svanisthebest/ashare-data'
URLS = ['https://raw.githubusercontent.com/{r}/main/helper/core.py',
        'https://ghfast.top/https://raw.githubusercontent.com/{r}/main/helper/core.py',
        'https://gh-proxy.com/https://raw.githubusercontent.com/{r}/main/helper/core.py',
        'https://ghproxy.net/https://raw.githubusercontent.com/{r}/main/helper/core.py',
        'https://fastly.jsdelivr.net/gh/{r}@main/helper/core.py',
        'https://cdn.jsdelivr.net/gh/{r}@main/helper/core.py']
HOME = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'ashare_helper'); os.makedirs(HOME, exist_ok=True)
CACHE = os.path.join(HOME, 'core_cache.py')


def fetch():
    mir = ''
    try: mir = json.load(open(os.path.join(HOME, 'state.json'), encoding='utf-8')).get('mirror', '')
    except Exception: pass
    urls = ([mir.rstrip('/') + '/helper/core.py'] if mir else []) + [u.format(r=REPO) for u in URLS]
    for u in urls:
        try:
            req = urllib.request.Request(u + ('' if 'jsdelivr' in u else f'?t={int(time.time())}'), headers={'User-Agent': 'Mozilla/5.0'})
            code = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
            if 'CORE_VERSION' in code and 'def main' in code:
                open(CACHE, 'w', encoding='utf-8').write(code); print('已下载最新核心程序：', u.split('/')[2]); return code
        except Exception as e:
            print('下载失败', u.split('/')[2], e)
    if os.path.exists(CACHE):
        print('网络不通，使用上次缓存的核心程序'); return open(CACHE, encoding='utf-8').read()
    return None


if __name__ == '__main__':
    print('A股开单助手 启动中…')
    local = os.environ.get('ASH_CORE')            # 开发测试：直接用本地 core.py
    code = open(local, encoding='utf-8').read() if local else fetch()
    if not code:
        print('第一次运行需要联网下载核心程序，请检查网络后重试。'); input('按回车退出'); sys.exit(1)
    g = {'__name__': '__main__', '__file__': CACHE}
    try:
        exec(compile(code, CACHE, 'exec'), g)
    except SystemExit: pass
    except Exception:
        traceback.print_exc(); input('出错了，按回车退出（把上面的信息发给 Claude）')
