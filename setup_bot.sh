#!/bin/bash
# Setup va chay Telegram Bot tren VPS Ubuntu
# Chay: bash setup_bot.sh

echo "=== SETUP TELEGRAM BOT ==="

# 1. Cap nhat system
sudo apt update -y

# 2. Cai Python3 + pip neu chua co
sudo apt install -y python3 python3-pip python3-venv

# 3. Tao virtual environment
cd /root/t-le || cd ~/t-le || { echo "Khong tim thay thu muc t-le! Hay clone repo truoc."; exit 1; }

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Da tao virtual environment"
fi

source venv/bin/activate

# 4. Cai dependencies
pip install -r requirements.txt
echo "Da cai dependencies"

# 5. Tao systemd service de bot chay nen
cat > /etc/systemd/system/tgbot.service << 'EOF'
[Unit]
Description=Telegram Bot - Lay Ma Tu Dong
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/t-le
ExecStart=/root/t-le/venv/bin/python bot_telegram.py
Restart=always
RestartSec=5
Environment=TELEGRAM_BOT_TOKEN=8845577933:AAHBEsql9VNOy78rYNFCxx-iqRE84pJfJgM
Environment=WEB_BASE_URL=http://74.81.39.45
Environment=DATABASE_URL=sqlite:///data.db

[Install]
WantedBy=multi-user.target
EOF

# 6. Enable va start service
systemctl daemon-reload
systemctl enable tgbot
systemctl restart tgbot

echo ""
echo "=== DA SETUP XONG ==="
echo "Kiem tra trang thai: systemctl status tgbot"
echo "Xem log: journalctl -u tgbot -f"
echo "Khoi dong lai: systemctl restart tgbot"
echo "Dung bot: systemctl stop tgbot"