#!/bin/bash
# A股开单助手：云服务器一键安装（Ubuntu / Debian / CentOS / OpenCloudOS / Alibaba Cloud Linux）
# 用法（在服务器上用 root 运行）：
#   curl -fsSL https://ghfast.top/https://raw.githubusercontent.com/Svanisthebest/ashare-data/main/helper/install_server.sh | bash -s -- '你的访问密码'
# 装好后：开单工具开机自启、出错自动重启、每个交易日 8:40 自动重启一次（自动更新到最新版本）。
set -e
PW="$1"
PORT="${2:-8765}"
if [ -z "$PW" ]; then read -r -p "设置网页访问密码（至少 6 位）：" PW < /dev/tty; fi
if [ ${#PW} -lt 6 ]; then echo "密码至少 6 位"; exit 1; fi
if ! printf '%s' "$PW" | grep -Eq '^[A-Za-z0-9_@#%+=.-]+$'; then echo "密码只能用字母、数字和 _ @ # % + = . - 这些符号"; exit 1; fi
if [ "$(id -u)" != "0" ]; then echo "请用 root 运行（前面加 sudo）"; exit 1; fi

echo "== 1/4 检查 Python 3"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then apt-get update -y && apt-get install -y python3
  elif command -v dnf >/dev/null 2>&1; then dnf install -y python3
  elif command -v yum >/dev/null 2>&1; then yum install -y python3
  else echo "找不到安装工具，请先手动安装 python3"; exit 1; fi
fi
python3 --version

echo "== 2/4 下载启动器"
mkdir -p /opt/ashare/data
REPO=Svanisthebest/ashare-data
ok=0
for u in "https://raw.githubusercontent.com/$REPO/main/helper/launcher.py" \
         "https://ghfast.top/https://raw.githubusercontent.com/$REPO/main/helper/launcher.py" \
         "https://gh-proxy.com/https://raw.githubusercontent.com/$REPO/main/helper/launcher.py" \
         "https://ghproxy.net/https://raw.githubusercontent.com/$REPO/main/helper/launcher.py" \
         "https://fastly.jsdelivr.net/gh/$REPO@main/helper/launcher.py" \
         "https://cdn.jsdelivr.net/gh/$REPO@main/helper/launcher.py"; do
  if curl -fsSL --max-time 20 "$u" -o /opt/ashare/launcher.py.tmp && grep -q "def fetch" /opt/ashare/launcher.py.tmp; then
    mv /opt/ashare/launcher.py.tmp /opt/ashare/launcher.py; echo "已下载：$u"; ok=1; break
  fi
done
[ "$ok" = "1" ] || { echo "下载启动器失败，请检查服务器网络"; exit 1; }

echo "== 3/4 配置系统服务（开机自启、出错自动重启、交易日 8:40 自动重启更新）"
umask 077
cat > /opt/ashare/env <<EOF
ASH_HOST=0.0.0.0
ASH_PORT=$PORT
ASH_PASSWORD=$PW
ASH_NOBROWSER=1
ASH_SERVER=1
APPDATA=/opt/ashare/data
PYTHONUNBUFFERED=1
EOF
chmod 600 /opt/ashare/env
cat > /etc/systemd/system/ashare-helper.service <<EOF
[Unit]
Description=A股开单助手
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/opt/ashare/env
WorkingDirectory=/opt/ashare
ExecStart=$(command -v python3) /opt/ashare/launcher.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/ashare-helper-restart.service <<EOF
[Unit]
Description=每天重启A股开单助手（自动更新到最新版本）
[Service]
Type=oneshot
ExecStart=/bin/systemctl restart ashare-helper.service
EOF
cat > /etc/systemd/system/ashare-helper-restart.timer <<EOF
[Unit]
Description=交易日 8:40（北京时间）重启A股开单助手
[Timer]
OnCalendar=Mon..Fri *-*-* 00:40:00 UTC
Persistent=false
[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now ashare-helper.service
systemctl enable --now ashare-helper-restart.timer

echo "== 4/4 放行端口 $PORT"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow "$PORT"/tcp; fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then firewall-cmd --permanent --add-port="$PORT"/tcp && firewall-cmd --reload; fi

sleep 6
if systemctl is-active --quiet ashare-helper.service; then
  echo
  echo "✅ 安装完成，开单工具已经在后台运行。"
  IP=$(curl -fsS --max-time 5 https://ip.3322.net 2>/dev/null || curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || echo "<服务器公网IP>")
  echo "   手机或电脑浏览器打开：http://$IP:$PORT/   （用户名随便填，密码是刚才设置的）"
  echo "   还要在云服务器控制台的「防火墙 / 安全组」里放行 TCP $PORT 端口，否则手机打不开。"
  echo "   查看运行日志：journalctl -u ashare-helper -n 50 --no-pager"
else
  echo "❌ 服务没有启动成功，下面是日志："; journalctl -u ashare-helper -n 50 --no-pager; exit 1
fi
