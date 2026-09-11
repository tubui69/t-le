#!/bin/bash
# Setup va chay Telegram Bot tren VPS Ubuntu
# Chay: bash setup_bot.sh

echo "=== SETUP TELEGRAM BOT ==="

# 1. Cap nhat system
apt update -y

# 2. Cai Python3 + pip
apt install -y python3 python3-pip
# python3-venv (Ubuntu 18/20/22/24)
apt install -y python3-venv python3-full 2>/dev/null || apt install -y python3-venv || true

# 3. Tim thu muc t-le
cd /root/t-le || cd ~/t-le || { echo "Khong tim thay thu muc t-le! Hay clone repo truoc."; exit 1; }

# 4. Tao virtual environment
if [ ! -d "venv" ]; then
    python3 -m venv venv || { echo "Loi tao venv! Thu cai: apt install python3-venv"; exit 1; }
    echo "Da tao virtual environment"
fi

source venv/bin/activate

# 5. Cai dependencies
pip install --upgrade pip
pip install flask flask-sqlalchemy "python-telegram-bot==20.7"
echo "Da cai dependencies"

# 6. Tao systemd service de bot chay nen
cat > /etc/systemd/system/tgbot.service << EOF
[Unit]
Description=Telegram Bot - Lay Ma Tu Dong
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python bot_telegram.py
Restart=always
RestartSec=5
Environment=TELEGRAM_BOT_TOKEN=8845577933:AAHBEsql9VNOy78rYNFCxx-iqRE84pJfJgM
Environment=WEB_BASE_URL=http://180.93.61.127:5000
Environment=DATABASE_URL=sqlite:///data.db

[Install]
WantedBy=multi-user.target
EOF

# 7. Enable va start service
systemctl daemon-reload
systemctl enable tgbot
systemctl restart tgbot

sleep 3
echo ""
echo "=== DA SETUP XONG ==="
systemctl status tgbot --no-pager | head -5
echo ""
echo "Kiem tra trang thai: systemctl status tgbot"
echo "Xem log: journalctl -u tgbot -f"
echo "Khoi dong lai: systemctl restart tgbot"
echo "Dung bot: systemctl stop tgbot"
