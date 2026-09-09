"""
Scraper - QUY TAC MOI:
- Xingtu: scraping_active=True => quet. Co ma => success.
- Duolingo: scraping_active=True (khach bam). 20p tu pause.
"""
import logging, threading, time
from collections import deque
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CodeScraper:
    def __init__(self, app):
        self.app = app
        self._running = False
        self._thread = None
        self._playwright = None
        self._browser = None
        self._lock = threading.Lock()
        self._priority_queue = deque()

    def start(self):
        if self._running: return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scraper started")

    def stop(self):
        self._running = False
        if self._browser:
            try: self._browser.close()
            except: pass
        if self._playwright:
            try: self._playwright.stop()
            except: pass

    def request_scrape(self, order_id):
        with self._lock:
            if order_id not in self._priority_queue:
                self._priority_queue.append(order_id)

    def _ensure_browser(self):
        if self._browser is None or not self._browser.is_connected():
            if self._playwright:
                try: self._playwright.stop()
                except: pass
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])

    def _run_loop(self):
        time.sleep(2)
        while self._running:
            try:
                self._check_auto_pause()
                self._process_priority_queue()
                has = self._scrape_all()
                self._check_expiry()
                interval = self.app.config.get("SCRAPE_INTERVAL", 5) if has else 10
            except Exception as e:
                logger.error(f"Loop error: {e}")
                interval = 5
            time.sleep(interval)

    def _check_auto_pause(self):
        with self.app.app_context():
            from models import Order, db
            for o in Order.query.filter(Order.order_type=="duolingo", Order.status=="scraping",
                                         Order.scraping_active==True, Order.scraping_started_at.isnot(None)).all():
                if o.should_auto_pause:
                    o.pause_scraping()
                    logger.info(f"Order {o.id} auto-pause 20p")
            db.session.commit()

    def _process_priority_queue(self):
        with self._lock:
            q = list(self._priority_queue); self._priority_queue.clear()
        if not q: return
        with self.app.app_context():
            from models import Order, db
            try: self._ensure_browser()
            except Exception as e:
                logger.error(f"Browser error: {e}"); return
            for oid in q:
                try:
                    o = Order.query.get(oid)
                    if o and o.scraping_active and o.source_url:
                        self._scrape_order(o); db.session.commit()
                except Exception as e:
                    logger.error(f"Priority error {oid}: {e}")

    def _scrape_all(self):
        with self.app.app_context():
            from models import Order
            orders = Order.query.filter(Order.scraping_active==True,
                Order.source_url.isnot(None), Order.source_url!="").all()
            if not orders: return False
            try: self._ensure_browser()
            except: return False
            for o in orders:
                try: self._scrape_order(o)
                except Exception as e:
                    logger.error(f"Scrape error {o.id}: {e}")
                    o.error_count = (o.error_count or 0) + 1
                    if o.error_count >= 30:
                        o.status = "error"; o.scraping_active = False
            from models import db; db.session.commit()
            return True

    def _scrape_order(self, order):
        from models import CodeHistory, db, now_vn
        is_dlg = (order.order_type == "duolingo")
        with self._lock:
            page = self._browser.new_page()
            phone = None; code = None
            try:
                page.on("dialog", lambda d: d.accept())
                page.goto(order.source_url, wait_until="domcontentloaded", timeout=15000)
                if not is_dlg:
                    time.sleep(2)
                    try:
                        el = page.query_selector("#phone")
                        if el: phone = el.inner_text().strip()
                    except: pass
                    for _ in range(8):
                        time.sleep(1)
                        try:
                            el = page.query_selector("#msgcode")
                            if el:
                                code = el.inner_text().strip()
                                if code: break
                        except: pass
                else:
                    time.sleep(2)
                    for _ in range(10):
                        time.sleep(1)
                        try:
                            el = page.query_selector("#msgcode")
                            if el:
                                code = el.inner_text().strip()
                                if code: break
                        except: pass
            except Exception as e:
                logger.error(f"Order {order.id} load error: {e}")
            finally:
                page.close()

        if phone or code:
            if (phone and phone != order.latest_phone) or (code and code != order.latest_code):
                order.latest_code = code or order.latest_code
                order.latest_phone = phone or order.latest_phone
                db.session.add(CodeHistory(order_id=order.id, code=code or "", phone=phone or "", scraped_at=now_vn()))
                logger.info(f"Order {order.id}: code={code} phone={phone}")
                order.error_count = 0
            if not is_dlg and code:
                order.complete_scraping()
                logger.info(f"Order {order.id} Xingtu: DONE")

    def _check_expiry(self):
        with self.app.app_context():
            from models import Order, db, now_vn
            for o in Order.query.filter(Order.status.in_(["scraping","paused","waiting_customer"]),
                                         Order.expires_at.isnot(None), Order.expires_at < now_vn()).all():
                o.status = "expired"; o.scraping_active = False
                logger.info(f"Order {o.id} expired")
            db.session.commit()
