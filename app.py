import secrets, atexit, subprocess, hmac, hashlib
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from config import Config
from models import db, Order, CodeHistory
from scraper import CodeScraper
app = Flask(__name__); app.config.from_object(Config); db.init_app(app)
with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text, inspect
        cols = [c["name"] for c in inspect(db.engine).get_columns("orders")]
        for col, ddl in [("latest_phone","VARCHAR(30)"),("order_type","VARCHAR(20) DEFAULT \x27xingtu\x27"),
                          ("scraping_active","BOOLEAN DEFAULT 0"),("scraping_started_at","DATETIME"),("completed_at","DATETIME")]:
            if col not in cols:
                db.session.execute(text("ALTER TABLE orders ADD COLUMN " + col + " " + ddl))
                db.session.commit()
    except Exception as e: print("Migration:", e)
scraper = CodeScraper(app); scraper.start()
def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get("admin_logged_in"): return redirect(url_for("admin_login"))
        return f(*a, **kw)
    return d
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password","") == app.config["ADMIN_PASSWORD"]:
            session["admin_logged_in"] = True; session.permanent = True
            return redirect(url_for("admin_dashboard"))
        flash("Sai mat khau!","error")
    return render_template("admin_login.html")
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None); return redirect(url_for("admin_login"))
@app.route("/admin")
@admin_required
def admin_dashboard():
    sf = request.args.get("status","all"); tf = request.args.get("type","all")
    q = Order.query
    if sf != "all": q = q.filter_by(status=sf)
    if tf != "all": q = q.filter_by(order_type=tf)
    orders = q.order_by(Order.created_at.desc()).all()
    stats = {"total":Order.query.count(),"pending":Order.query.filter_by(status="pending").count(),
             "scraping":Order.query.filter_by(status="scraping").count(),"success":Order.query.filter_by(status="success").count(),
             "expired":Order.query.filter_by(status="expired").count(),
             "xingtu":Order.query.filter_by(order_type="xingtu").count(),"duolingo":Order.query.filter_by(order_type="duolingo").count(),
             "wink":Order.query.filter_by(order_type="wink").count()}
    return render_template("admin_dashboard.html", orders=orders, stats=stats, current_filter=sf, current_type=tf)
@app.route("/admin/order/new", methods=["GET","POST"])
@admin_required
def admin_order_new():
    if request.method == "POST":
        name = request.form.get("customer_name","").strip()
        if not name: flash("Nhap ten!"); return render_template("admin_order_form.html", order=None)
        ot = request.form.get("order_type","xingtu")
        o = Order(customer_name=name, customer_phone=request.form.get("customer_phone","").strip() or None,
                  note=request.form.get("note","").strip() or None, status="pending", order_type=ot, token=secrets.token_urlsafe(16))
        db.session.add(o); db.session.commit()
        return redirect(url_for("admin_order_detail", order_id=o.id))
    return render_template("admin_order_form.html", order=None)
@app.route("/admin/order/<int:oid>")
@admin_required
def admin_order_detail(oid):
    o = Order.query.get_or_404(oid)
    codes = CodeHistory.query.filter_by(order_id=oid).order_by(CodeHistory.scraped_at.desc()).limit(50).all()
    return render_template("admin_order_detail.html", order=o, codes=codes)
@app.route("/admin/order/<int:oid>/url", methods=["POST"])
@admin_required
def admin_order_set_url(oid):
    o = Order.query.get_or_404(oid)
    url = request.form.get("source_url","").strip()
    if not url: return redirect(url_for("admin_order_detail", order_id=oid))
    o.source_url = url; o.error_count = 0
    if o.order_type == "xingtu": o.start_scraping()
    else: o.status = "waiting_customer"
    o.set_expiry(app.config["AUTO_EXPIRE_DAYS"]); db.session.commit()
    return redirect(url_for("admin_order_detail", order_id=oid))
@app.route("/admin/order/<int:oid>/complete", methods=["POST"])
@admin_required
def admin_order_complete(oid):
    o = Order.query.get_or_404(oid); o.complete_scraping(); db.session.commit()
    return redirect(url_for("admin_order_detail", order_id=oid))
@app.route("/admin/order/<int:oid>/cancel", methods=["POST"])
@admin_required
def admin_order_cancel(oid):
    o = Order.query.get_or_404(oid); o.status="cancelled"; o.scraping_active=False; db.session.commit()
    return redirect(url_for("admin_order_detail", order_id=oid))
@app.route("/admin/order/<int:oid>/delete", methods=["POST"])
@admin_required
def admin_order_delete(oid):
    o = Order.query.get_or_404(oid); db.session.delete(o); db.session.commit()
    return redirect(url_for("admin_dashboard"))
@app.route("/view/<token>")
def customer_view(token):
    o = Order.query.filter_by(token=token).first_or_404()
    if o.order_type=="duolingo": return _dl(o)
    if o.order_type=="wink": return _wk(o)
    return _xt(o)
@app.route("/xingtu/<token>")
def customer_xingtu(token): return _xt(Order.query.filter_by(token=token).first_or_404())
@app.route("/duolingo/<token>")
@app.route("/dl/<token>")
def customer_duolingo(token): return _dl(Order.query.filter_by(token=token).first_or_404())
@app.route("/wink/<token>")
def customer_wink(token): return _wk(Order.query.filter_by(token=token).first_or_404())
@app.route("/wink/")
def customer_wink_query():
    token = request.args.get("token")
    if not token: return redirect(url_for("admin_login"))
    o = Order.query.filter_by(token=token).first_or_404()
    return _wk(o)
def _xt(o):
    if o.status=="cancelled": return render_template("customer_xingtu.html", order=o, code=None, phone=None, cancelled=True)
    if o.is_expired and o.status in ("scraping","paused"): o.status="expired"; o.scraping_active=False; db.session.commit()
    if o.status=="expired": return render_template("customer_xingtu.html", order=o, code=None, phone=None, expired=True)
    if o.source_url and not o.latest_code:
        if not o.scraping_active: o.start_scraping(); db.session.commit()
        scraper.request_scrape(o.id)
    return render_template("customer_xingtu.html", order=o, code=o.latest_code, phone=o.latest_phone)
def _wk(o):
    if o.status=="cancelled": return render_template("customer_wink.html", order=o, code=None, phone=None, cancelled=True)
    if o.is_expired and o.status in ("scraping","paused"): o.status="expired"; o.scraping_active=False; db.session.commit()
    if o.status=="expired": return render_template("customer_wink.html", order=o, code=None, phone=None, expired=True)
    if o.source_url and not o.latest_code:
        if not o.scraping_active: o.start_scraping(); db.session.commit()
        scraper.request_scrape(o.id)
    return render_template("customer_wink.html", order=o, code=o.latest_code, phone=o.latest_phone)
def _dl(o):
    if o.status=="cancelled": return render_template("customer_duolingo.html", order=o, code=None, cancelled=True, activated=False, paused=False, expired=False)
    if o.is_expired and o.status in ("scraping","paused","waiting_customer"): o.status="expired"; o.scraping_active=False; db.session.commit()
    if o.status=="expired": return render_template("customer_duolingo.html", order=o, code=None, cancelled=False, activated=False, paused=False, expired=True)
    activated = o.scraping_active or o.status in ("scraping","paused")
    paused = o.status == "paused"
    if activated and o.source_url: scraper.request_scrape(o.id)
    return render_template("customer_duolingo.html", order=o, code=o.latest_code, cancelled=False, activated=activated, paused=paused, expired=False)
@app.route("/api/activate/<token>", methods=["POST"])
def api_activate(token):
    o = Order.query.filter_by(token=token).first_or_404()
    if o.order_type!="duolingo" or o.status in ("cancelled","expired","success"): return jsonify({"error":"invalid"}), 400
    o.start_scraping(); db.session.commit(); scraper.request_scrape(o.id)
    return jsonify({"status":"activated"})
@app.route("/api/resume/<token>", methods=["POST"])
def api_resume(token):
    o = Order.query.filter_by(token=token).first_or_404()
    if o.order_type!="duolingo" or o.status!="paused": return jsonify({"error":"invalid"}), 400
    o.resume_scraping(); db.session.commit(); scraper.request_scrape(o.id)
    return jsonify({"status":"resumed"})
@app.route("/api/code/<token>")
def api_code(token):
    o = Order.query.filter_by(token=token).first_or_404()
    return jsonify({"code":o.latest_code,"phone":o.latest_phone,"status":o.status,
        "order_type":o.order_type or "xingtu","scraping_active":o.scraping_active,
        "updated_at":o.codes[0].scraped_at.isoformat() if o.codes else None,
        "expired":o.is_expired,"completed":o.status=="success"})
@app.route("/")
def index():
    token = request.args.get("token")
    if token:
        o = Order.query.filter_by(token=token).first()
        if o and o.order_type == "wink":
            return _wk(o)
        if o:
            return _dl(o) if o.order_type == "duolingo" else _xt(o)
    return redirect(url_for("admin_login"))

WEBHOOK_SECRET = app.config.get("WEBHOOK_SECRET", "my-webhook-secret-123")
DEPLOY_SCRIPT = "/root/auto-deploy.sh"

@app.route("/webhook", methods=["POST"])
def github_webhook():
    sig = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), request.data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 403
    data = request.get_json(silent=True) or {}
    ref = data.get("ref", "")
    if "main" not in ref and "master" not in ref:
        return jsonify({"status": "ignored", "ref": ref})
    try:
        result = subprocess.run(["bash", DEPLOY_SCRIPT], capture_output=True, text=True, timeout=120)
        return jsonify({"status": "deployed", "output": result.stdout[-500:], "errors": result.stderr[-500:]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

atexit.register(lambda: scraper.stop())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
