import logging, re, os, sys, secrets
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
logging.basicConfig(format='%(asctime)s-%(name)s-%(levelname)s', level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8845577933:AAHBEsql9VNOy78rYNFCxx-iqRE84pJfJgM')
WEB = os.environ.get('WEB_BASE_URL', 'http://180.93.61.127:5000')
DB_PATH = os.environ.get('DATABASE_URL', 'sqlite:///data.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Khoi tao Flask app de dung Flask-SQLalchemy
from flask import Flask
from models import db, Order, WinkAgentLink
flask_app = Flask(__name__)
flask_app.config['SQLALCHEMY_DATABASE_URI'] = DB_PATH
flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(flask_app)
with flask_app.app_context():
    db.create_all()
    # Migration them cot login_mode neu chua co
    try:
        from sqlalchemy import text, inspect
        cols = [c["name"] for c in inspect(db.engine).get_columns("orders")]
        if "login_mode" not in cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN login_mode VARCHAR(20) DEFAULT 'otp'"))
            db.session.commit()
    except Exception as e:
        logger.info(f"Migration skip: {e}")
logger.info("DB tables ready")
DL_DOMAINS = ['dlg.llii.me']
WINK_DOMAINS = ['wmrjkf.com']
def get_setting(key, default=''):
    """Doc cai dat tu DB (admin settings) de khong phai sua code khi doi domain."""
    with flask_app.app_context():
        try:
            from models import Setting
            s = Setting.query.get(key)
            return s.value if s and s.value else default
        except Exception:
            return default
def meitu_domains():
    return [d.strip().lower() for d in get_setting('meitu_domains').split(',') if d.strip()]
def wink_domains():
    extra = [d.strip().lower() for d in get_setting('wink_domains').split(',') if d.strip()]
    return [d.lower() for d in WINK_DOMAINS] + extra
def duolingo_domains():
    extra = [d.strip().lower() for d in get_setting('duolingo_domains').split(',') if d.strip()]
    return [d.lower() for d in DL_DOMAINS] + extra
def detect_type(url):
    u = url.lower()
    # Meitu check truoc de domain cu the thang domain chung
    for d in meitu_domains():
        if d in u: return 'meitu'
    return 'wink'

def get_link(token, ot):
    if ot in ('meitu', 'meitu_account'): return f'{WEB}/meitu/?token={token}'
    return f'{WEB}/wink/?token={token}'
def extract_urls(text):
    pat = r"https?://[^\s<>\[\](){}\"'`,;]+"
    urls = re.findall(pat, text)
    seen = set(); result = []
    for u in urls:
        u = u.rstrip('.,;:!?)]}')
        if u not in seen: seen.add(u); result.append(u)
    return result
def create_order(url, name='TG User', login_mode='otp', extra_urls=None):
    with flask_app.app_context():
        try:
            ot = detect_type(url)
            if ot == 'wink' and login_mode == 'password_otp':
                ot = 'wink_account'
            if ot == 'meitu' and login_mode == 'password_otp':
                ot = 'meitu_account'
            from models import WINK_TYPES, MEITU_TYPES, AGENT_TYPES, Setting
            # Mat khau mac dinh theo loai, lay tu admin settings
            pwd = None
            if ot in AGENT_TYPES:
                skey = 'wink_default_password' if ot in WINK_TYPES else 'meitu_default_password'
                s = Setting.query.get(skey)
                pwd = s.value if s and s.value else None
            o = Order(customer_name=name, source_url=url, status='pending',
                      token=secrets.token_urlsafe(16), order_type=ot, error_count=0,
                      scraping_active=False, login_mode=login_mode, account_password=pwd)
            o.set_expiry(3); db.session.add(o); db.session.flush()
            if ot in AGENT_TYPES and extra_urls:
                all_urls = [url] + extra_urls
                for u in all_urls:
                    parts = u.split('|', 1)
                    link = parts[0].strip()
                    agent_name = parts[1].strip() if len(parts) > 1 else None
                    if link:
                        db.session.add(WinkAgentLink(order_id=o.id, url=link, agent_name=agent_name))
            db.session.commit()
            oid = o.id; otoken = o.token
            return oid, get_link(otoken, ot), ot
        except Exception as e:
            db.session.rollback(); logger.error(f'Error: {e}'); return None, None, None
async def cmd_start(update, ctx):
    t = ('\U0001f510 *Bot Lay Ma Tu Dong* \U0001f510\n\n'
         'Gui link goc -> Bot tao don va tra ve link lay ma.\n\n'
         '\U0001f989 Duolingo: `https://dlg.llii.me/idxx?k=ABC`\n'
         '\U0001f511 Xingtu: `http://47.103.212.73/wap?key=ABC`\n'
         '\U0001f4f1 Wink SDT+OTP: gui link trang goc co chu \u624b\u673a\u53f7/\u9a8c\u8bc1\u7801\n'
         '\U0001f3a8 Meitu SDT+OTP: domain cai trong Admin Settings\n'
         '\U0001f512 SDT+MK+OTP: dung lenh /winkmk\n\n'
         '\U0001f4ce Gui *nhieu link* trong 1 tin nhan -> tao nhieu don!\n'
         '\U0001f4dd Bot tu dong loc link tu van ban.\n\n'
         '*Lenh:* /start | /help | /stats | /winkmk')
    await update.message.reply_text(t, parse_mode='Markdown')
async def cmd_help(update, ctx):
    t = (f'*Huong dan:*\n\n'
         f'1. Gui 1 link\n'
         f'2. Gui nhieu link cung luc\n'
         f'3. Dan link kem ghi chu -> Bot tu loc URL\n\n'
         f'Admin: {WEB}/admin')
    await update.message.reply_text(t, parse_mode='Markdown')
async def cmd_stats(update, ctx):
    with flask_app.app_context():
        try:
            from sqlalchemy import func
            from models import WINK_TYPES, MEITU_TYPES
            by_status = dict(db.session.query(Order.status, func.count()).group_by(Order.status).all())
            by_type = dict(db.session.query(Order.order_type, func.count()).group_by(Order.order_type).all())
            t = sum(by_status.values())
            sc = by_status.get('scraping', 0)
            ok = by_status.get('success', 0)
            wk = sum(by_type.get(x, 0) for x in WINK_TYPES)
            mt = sum(by_type.get(x, 0) for x in MEITU_TYPES)
            await update.message.reply_text(
                f'\U0001f4ca Tong: *{t}* | Quet: {sc} | Xong: {ok}\n\U0001f4f1 Wink: {wk} | \U0001f3a8 Meitu: {mt}',
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f'Stats error: {e}')
            await update.message.reply_text('Loi!')

_winkmk_users = set()
async def cmd_winkmk(update, ctx):
    uid = update.effective_user.id
    _winkmk_users.add(uid)
    await update.message.reply_text(
        '\U0001f512 *Che do Dai ly SDT + MK + OTP*\n\n'
        'Gui link Wink/Meitu (nhieu link gop thanh 1 don).\n'
        'Trang web se co o nhap mat khau + nut lay OTP.\n\n'
        'Dung /start de quay ve che do binh thuong.',
        parse_mode='Markdown')
async def handle_msg(update, ctx):
    urls = extract_urls(update.message.text)
    if not urls:
        await update.message.reply_text(
            '❌ Khong tim thay link!\nGui nhieu link cung luc duoc!', parse_mode='Markdown')
        return
    name = f'TG: {update.effective_user.first_name or update.effective_user.username}'
    uid = update.effective_user.id
    is_winkmk = uid in _winkmk_users
    # Tao order cho tung link, luu ket qua theo loai
    results = {'xingtu': [], 'duolingo': [], 'wink': [], 'wink_account': []}
    results = {'wink': [], 'wink_account': [], 'meitu': [], 'meitu_account': []}
    wink_urls = [u for u in urls if detect_type(u) == 'wink']
    other_urls = [u for u in urls if detect_type(u) != 'wink']
    # Che do winkmk: gop tat ca link wink thanh 1 order
    if is_winkmk and wink_urls:
        first_url = wink_urls[0]
        extra = wink_urls[1:] if len(wink_urls) > 1 else None
        oid, link, ot = create_order(first_url, name, login_mode='password_otp', extra_urls=extra)
        if oid:
            n = len(wink_urls)
            if ot not in results: results[ot] = []
            results[ot].append({'oid': oid, 'link': link, 'n': n})
            _winkmk_users.discard(uid)
        # Link khac (khong cung loai dai ly) tao binh thuong
        for url in other_urls:
            oid2, link2, ot2 = create_order(url, name)
            if oid2:
                if ot2 not in results: results[ot2] = []
                results[ot2].append({'oid': oid2, 'link': link2})
    else:
        # Binh thuong: moi link tao 1 order rieng
        for url in urls:
            oid, link, ot = create_order(url, name)
            if oid:
                if ot not in results: results[ot] = []
                results[ot].append({'oid': oid, 'link': link})
    # Gom tin nhan theo loai
    blocks = []
    type_labels = {
        'xingtu': '\U0001f511 Xingtu:',
        'duolingo': '\U0001f989 Duolingo:',
        'wink': '\U0001f4f1 Wink SDT+Ma:',
        'wink_account': '\U0001f512 Wink SDT+MK+OTP:',
        'meitu': '\U0001f3a8 Meitu SDT+Ma:',
        'meitu_account': '\U0001f512 Meitu SDT+MK+OTP:'
    }
    for ot_key in ['xingtu', 'duolingo', 'wink', 'wink_account', 'meitu', 'meitu_account']:
    for ot_key in ['wink', 'wink_account', 'meitu', 'meitu_account']:
        items = results[ot_key]
        if not items:
            continue
        header = type_labels[ot_key]
        link_lines = []
        for item in items:
            n = item.get('n')
            if n and n > 1:
                link_lines.append(f'{item["link"]} ({n} link dai ly)')
            else:
                link_lines.append(item['link'])
        block = header + '\n' + '\n'.join(link_lines)
        blocks.append(block)
    if not blocks:
        await update.message.reply_text('❌ Loi tao don!', parse_mode='Markdown')
        return
    msg = '\n\n'.join(blocks)
    await update.message.reply_text(msg)
async def on_error(update, ctx):
    logger.error(f'Error: {ctx.error}')
    if update and update.message: await update.message.reply_text('❌ Loi!')
def main():
    if TOKEN == 'YOUR_BOT_TOKEN_HERE': print('CHUA SET TOKEN!'); return
    a = Application.builder().token(TOKEN).build()
    a.add_handler(CommandHandler('start', cmd_start))
    a.add_handler(CommandHandler('help', cmd_help))
    a.add_handler(CommandHandler('stats', cmd_stats))
    a.add_handler(CommandHandler('winkmk', cmd_winkmk))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    a.add_error_handler(on_error)
    print('Bot started!'); a.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__ == '__main__': main()
