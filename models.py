from datetime import datetime, timedelta, timezone
from flask_sqlalchemy import SQLAlchemy
import secrets

db = SQLAlchemy()
UTC_PLUS_7 = timezone(timedelta(hours=7))

def now_vn():
    return datetime.now(UTC_PLUS_7).replace(tzinfo=None)

class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=True)
    source_url = db.Column(db.Text, nullable=True)
    token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(16))
    status = db.Column(db.String(20), default="pending")
    order_type = db.Column(db.String(20), default="xingtu")
    latest_code = db.Column(db.String(20), nullable=True)
    latest_phone = db.Column(db.String(30), nullable=True)
    created_at = db.Column(db.DateTime, default=now_vn)
    expires_at = db.Column(db.DateTime, nullable=True)
    note = db.Column(db.Text, nullable=True)
    error_count = db.Column(db.Integer, default=0)
    scraping_active = db.Column(db.Boolean, default=False)
    scraping_started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    login_mode = db.Column(db.String(20), default="otp")  # "otp" or "password_otp"
    codes = db.relationship("CodeHistory", backref="order", lazy=True, cascade="all, delete-orphan")
    agent_links = db.relationship("WinkAgentLink", backref="order", lazy=True, cascade="all, delete-orphan")

    @property
    def is_expired(self):
        return self.expires_at and now_vn() > self.expires_at

    @property
    def should_auto_pause(self):
        if self.order_type != "duolingo": return False
        if not self.scraping_active or not self.scraping_started_at: return False
        return (now_vn() - self.scraping_started_at).total_seconds() >= 1200

    @property
    def status_display(self):
        return {"pending":"Cho nhap URL","scraping":"Dang quet","paused":"Tam dung",
                "success":"Thanh cong","expired":"Het han","cancelled":"Da huy",
                "error":"Loi","waiting_customer":"Cho khach bam"}.get(self.status, self.status)

    @property
    def type_display(self):
        return {"xingtu":"Xingtu","duolingo":"Duolingo","wink":"Wink SDT+Ma","wink_account":"Wink SDT+MK+Ma"}.get(self.order_type, self.order_type)

    def generate_token(self):
        self.token = secrets.token_urlsafe(16)
    def set_expiry(self, days=7):
        self.expires_at = now_vn() + timedelta(days=days)
    set_expire = set_expiry
    def start_scraping(self):
        self.scraping_active = True; self.scraping_started_at = now_vn(); self.status = "scraping"
    def pause_scraping(self):
        self.scraping_active = False; self.status = "paused"
    def resume_scraping(self):
        self.scraping_active = True; self.scraping_started_at = now_vn(); self.status = "scraping"
    def complete_scraping(self):
        self.scraping_active = False; self.status = "success"; self.completed_at = now_vn()

class WinkAgentLink(db.Model):
    __tablename__ = "wink_agent_links"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    url = db.Column(db.Text, nullable=False)
    agent_name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=now_vn)

class CodeHistory(db.Model):
    __tablename__ = "code_history"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    scraped_at = db.Column(db.DateTime, default=now_vn)
