import logging, re, os, sys, secrets
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
logging.basicConfig(format='%(asctime)s-%(name)s-%(levelname)s', level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
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
def create_order(url, name='TG User'):
    s = Session()
    try:
        ot = detect_type(url)
        o = Order(customer_name=name, source_url=url, status='pending',
                  token=secrets.token_urlsafe(16), order_type=ot, error_count=0, scraping_active=False)
        o.set_expiry(3); s.add(o); s.commit(); s.refresh(o)
        return o.id, get_link(o.token, ot), ot
    except Exception as e:
        s.rollback(); logger.error(f'Error: {e}'); return None, None, None
    finally: s.close()
async def cmd_start(update, ctx):
    t = ('\U0001f510 *Bot Lay Ma Tu Dong* \U0001f510\n\n'
         'Gui link -> Bot tao don va tra ve link lay ma.\n\n'
         '\U0001f989 Duolingo: `https://dlg.llii.me/idxx?k=ABC`\n'
         '\U0001f511 Xingtu: `http://47.103.212.73/wap?key=ABC`\n'
         '\U0001f4f1 Wink: `https://a.wmrjkf.com/url/xxx`\n\n'
         '\U0001f4ce Gui *nhieu link* trong 1 tin nhan!\n'
         '\U0001f4dd Loc link tu van ban.\n\n'
         '/help | /stats')
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
        await update.message.reply_text(f'\U0001f4ca Tong: *{t}* | Quet: {sc} | Xong: {ok}', parse_mode='Markdown')
    except: await update.message.reply_text('Loi!')
    finally: s.close()
async def handle_msg(update, ctx):
    urls = extract_urls(update.message.text)
    if not urls:
        await update.message.reply_text(
            '❌ Khong tim thay link!\nGui nhieu link cung luc duoc!', parse_mode='Markdown')
        return
    name = f'TG: {update.effective_user.first_name or update.effective_user.username}'
    if len(urls) > 1:
        await update.message.reply_text(f'⏳ Tao *{len(urls)}* don...', parse_mode='Markdown')
    for url in urls:
        oid, link, ot = create_order(url, name)
        if oid:
            ic = '\U0001f989' if ot == 'duolingo' else ('\U0001f4f1' if ot in ('wink','wink_account') else '\U0001f511')
            lb = 'Duolingo' if ot == 'duolingo' else ('Wink SDT+Ma' if ot == 'wink' else ('Wink SDT+MK+Ma' if ot == 'wink_account' else 'Xingtu'))
            await update.message.reply_text(
                f'{ic} *{lb}* #{oid}\n`{url}`\n\U0001f310 {link}', parse_mode='Markdown')
        else:
            await update.message.reply_text(f'❌ Loi: `{url}`', parse_mode='Markdown')
async def on_error(update, ctx):
    logger.error(f'Error: {ctx.error}')
    if update and update.message: await update.message.reply_text('❌ Loi!')
def main():
    if TOKEN == 'YOUR_BOT_TOKEN_HERE': print('CHUA SET TOKEN!'); return
    a = Application.builder().token(TOKEN).build()
    a.add_handler(CommandHandler('start', cmd_start))
    a.add_handler(CommandHandler('help', cmd_help))
    a.add_handler(CommandHandler('stats', cmd_stats))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    a.add_error_handler(on_error)
    print('Bot started!'); a.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__ == '__main__': main()
