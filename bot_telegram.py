import logging, re, os, sys, secrets
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
logging.basicConfig(format='%(asctime)s-%(name)s-%(levelname)s', level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8845577933:AAHBEsql9VNOy78rYNFCxx-iqRE84pJfJgM')
WEB = os.environ.get('WEB_BASE_URL', 'http://74.81.39.45')
DB = os.environ.get('DATABASE_URL', 'sqlite:///data.db')
engine = create_engine(DB); Session = sessionmaker(bind=engine)
sys.path.insert(0, os.path.dirname(__file__))
from models import Order, db
DL_DOMAINS = ['dlg.llii.me']
WINK_DOMAINS = ['wmrjkf.com']
def detect_type(url):
    for d in DL_DOMAINS:
        if d in url.lower(): return 'duolingo'
    for d in WINK_DOMAINS:
        if d in url.lower(): return 'wink'
    return 'xingtu'
def get_link(token, ot):
    if ot == 'duolingo': return f'{WEB}/dl/{token}'
    if ot in ('wink','wink_account'): return f'{WEB}/wink/?token={token}'
    return f'{WEB}/xingtu/{token}'
def extract_urls(text):
    pat = r"https?://[^\s<>\[\](){}\"'`,;]+"
    urls = re.findall(pat, text)
    seen = set(); result = []
    for u in urls:
        u = u.rstrip('.,;:!?)]}')
        if u not in seen: seen.add(u); result.append(u)
    return result
def create_order(url, name='TG User', login_mode='otp', extra_urls=None):
    s = Session()
    try:
        ot = detect_type(url)
        # Neu la wink va co login_mode=password_otp => order_type=wink_account
        if ot == 'wink' and login_mode == 'password_otp':
            ot = 'wink_account'
        o = Order(customer_name=name, source_url=url, status='pending',
                  token=secrets.token_urlsafe(16), order_type=ot, error_count=0,
                  scraping_active=False, login_mode=login_mode)
        o.set_expiry(3); s.add(o); s.flush()
        # Luu nhieu link dai ly cho Wink
        if ot in ('wink', 'wink_account') and extra_urls:
            from models import WinkAgentLink
            all_urls = [url] + extra_urls
            for u in all_urls:
                parts = u.split('|', 1)
                link = parts[0].strip()
                agent_name = parts[1].strip() if len(parts) > 1 else None
                if link:
                    s.add(WinkAgentLink(order_id=o.id, url=link, agent_name=agent_name))
        s.commit(); s.refresh(o)
        return o.id, get_link(o.token, ot), ot
    except Exception as e:
        s.rollback(); logger.error(f'Error: {e}'); return None, None, None
    finally: s.close()
async def cmd_start(update, ctx):
    t = ('\U0001f510 *Bot Lay Ma Tu Dong* \U0001f510\n\n'
         'Gui link -> Bot tao don va tra ve link lay ma.\n\n'
         '\U0001f989 Duolingo: `https://dlg.llii.me/idxx?k=ABC`\n'
         '\U0001f511 Xingtu: `http://47.103.212.73/wap?key=ABC`\n'
         '\U0001f4f1 Wink SDT+OTP: `https://a.wmrjkf.com/url/xxx`\n'
         '\U0001f512 Wink SDT+MK+OTP: dung lenh /winkmk\n\n'
         '\U0001f4ce Gui *nhieu link* trong 1 tin nhan!\n'
         '\U0001f4dd Loc link tu van ban.\n\n'
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
    s = Session()
    try:
        t = s.query(Order).count()
        sc = s.query(Order).filter_by(status='scraping').count()
        ok = s.query(Order).filter_by(status='success').count()
        wk = s.query(Order).filter(Order.order_type.in_(['wink','wink_account'])).count()
        await update.message.reply_text(f'\U0001f4ca Tong: *{t}* | Quet: {sc} | Xong: {ok} | Wink: {wk}', parse_mode='Markdown')
    except: await update.message.reply_text('Loi!')
    finally: s.close()

# Che do winkmk: SDT + Mat khau + OTP
_winkmk_users = set()
async def cmd_winkmk(update, ctx):
    uid = update.effective_user.id
    _winkmk_users.add(uid)
    await update.message.reply_text(
        '\U0001f512 *Che do Wink SDT + MK + OTP*\n\n'
        'Gui link Wink (nhieu link duoc) de tao don.\n'
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
    wink_urls = [u for u in urls if detect_type(u) == 'wink']
    other_urls = [u for u in urls if detect_type(u) != 'wink']
    lines = []
    # Che do winkmk: gop tat ca link wink thanh 1 order
    if is_winkmk and wink_urls:
        first_url = wink_urls[0]
        extra = wink_urls[1:] if len(wink_urls) > 1 else None
        oid, link, ot = create_order(first_url, name, login_mode='password_otp', extra_urls=extra)
        if oid:
            n = len(wink_urls)
            hdr = f'\U0001f512 Wink SDT+MK+OTP #{oid}' + (f' ({n} link)' if n > 1 else '')
            lines.append(f'{hdr}\n{link}')
            _winkmk_users.discard(uid)
        else:
            lines.append('❌ Loi tao don Wink MK!')
        # Link khac (non-wink) them vao cung tin nhan
        for url in other_urls:
            oid2, link2, ot2 = create_order(url, name)
            if oid2:
                ic = '\U0001f989' if ot2 == 'duolingo' else '\U0001f511'
                lb = 'Duolingo' if ot2 == 'duolingo' else 'Xingtu'
                lines.append(f'{ic} {lb} #{oid2}\n{link2}')
            else:
                lines.append(f'❌ Loi: {url}')
    else:
        # Binh thuong: moi link 1 dong trong cung 1 tin nhan
        for url in urls:
            oid, link, ot = create_order(url, name)
            if oid:
                ic = '\U0001f989' if ot == 'duolingo' else ('\U0001f4f1' if ot in ('wink','wink_account') else '\U0001f511')
                lb = 'Duolingo' if ot == 'duolingo' else ('Wink SDT+Ma' if ot == 'wink' else ('Wink SDT+MK+Ma' if ot == 'wink_account' else 'Xingtu'))
                lines.append(f'{ic} {lb} #{oid}\n{link}')
            else:
                lines.append(f'❌ Loi: {url}')
    # Gui 1 tin nhan duy nhat
    msg = '\n\n'.join(lines)
    await update.message.reply_text(msg, parse_mode='Markdown')
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
