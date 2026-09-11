import secrets, atexit, subprocess, hmac, hashlib
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from sqlalchemy import func, or_
from config import Config
from models import (db, Order, CodeHistory, Setting, WinkAgentLink,
                    WINK_TYPES, MEITU_TYPES, AGENT_TYPES)
from scraper import CodeScraper
app = Flask(__name__); app.config.from_object(Config); db.init_app(app)
with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text, inspect
        cols = [c["name"] for c in inspect(db.engine).get_columns("orders")]
        for col, ddl in [("latest_phone","VARCHAR(30)"),("order_type","VARCHAR(20) DEFAULT 'xingtu'"),
                          ("scraping_active","BOOLEAN DEFAULT 0"),("scraping_started_at","DATETIME"),("completed_at","DATETIME"),
                          ("error_count","INTEGER DEFAULT 0"),("login_mode","VARCHAR(20) DEFAULT 'otp'"),
                          ("account_password","VARCHAR(200)")]:
            if col not in cols:
                db.session.execute(text("ALTER TABLE orders ADD COLUMN " + col + " " + ddl))
                db.session.commit()
        # Index cho cac cot hay loc/sap xep (DB cu chua co vi index=True chi ap dung khi tao bang moi)
        for idx, tbl, col in [("ix_orders_status","orders","status"),("ix_orders_order_type","orders","order_type"),
                              ("ix_orders_created_at","orders","created_at"),("ix_orders_expires_at","orders","expires_at"),
                              ("ix_orders_scraping_active","orders","scraping_active"),
                              ("ix_code_history_order_id","code_history","order_id"),
                              ("ix_code_history_scraped_at","code_history","scraped_at"),
                              ("ix_wink_agent_links_order_id","wink_agent_links","order_id")]:
            db.session.execute(text("CREATE INDEX IF NOT EXISTS " + idx + " ON " + tbl + " (" + col + ")"))
        db.session.commit()
        # Backfill mot lan: don Wink/Meitu cu dang luu mat khau o note -> copy sang account_password.
        # Chi chay khi account_password con rong, va khong xoa note.
        ph = ",".join("'" + t + "'" for t in AGENT_TYPES)
        db.session.execute(text(
            "UPDATE orders SET account_password = note WHERE account_password IS NULL "
            "AND note IS NOT NULL AND note <> '' AND order_type IN (" + ph + ")"))
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
SORTABLE = {"id": Order.id, "customer_name": Order.customer_name, "order_type": Order.order_type,
            "status": Order.status, "latest_code": Order.latest_code,
            "latest_phone": Order.latest_phone, "created_at": Order.created_at}

@app.route("/admin")
@admin_required
def admin_dashboard():
    sf = request.args.get("status", "all"); tf = request.args.get("type", "all")
    kw = request.args.get("q", "").strip()
    sort = request.args.get("sort", "created_at")
    direction = "asc" if request.args.get("dir", "desc").lower() == "asc" else "desc"
    if sort not in SORTABLE: sort = "created_at"

    q = Order.query
    if sf != "all": q = q.filter_by(status=sf)
    if tf == "wink": q = q.filter(Order.order_type.in_(WINK_TYPES))
    elif tf == "meitu": q = q.filter(Order.order_type.in_(MEITU_TYPES))
    elif tf != "all": q = q.filter_by(order_type=tf)
    if kw:
        like = "%" + kw + "%"
        q = q.filter(or_(Order.customer_name.ilike(like), Order.customer_phone.ilike(like),
                         Order.latest_code.ilike(like), Order.latest_phone.ilike(like),
                         Order.note.ilike(like), Order.token.ilike(like),
                         Order.id == kw if kw.isdigit() else False))

    col = SORTABLE[sort]
    q = q.order_by(col.asc() if direction == "asc" else col.desc(), Order.id.desc())
    pagination = q.paginate(page=request.args.get("page", 1, type=int), per_page=50, error_out=False)

    # 2 query group-by thay cho 9 query count
    by_status = dict(db.session.query(Order.status, func.count()).group_by(Order.status).all())
    by_type = dict(db.session.query(Order.order_type, func.count()).group_by(Order.order_type).all())
    stats = {"total": sum(by_status.values()),
             "pending": by_status.get("pending", 0), "scraping": by_status.get("scraping", 0),
             "success": by_status.get("success", 0), "expired": by_status.get("expired", 0),
             "xingtu": by_type.get("xingtu", 0), "duolingo": by_type.get("duolingo", 0),
             "wink": sum(by_type.get(t, 0) for t in WINK_TYPES),
             "meitu": sum(by_type.get(t, 0) for t in MEITU_TYPES)}

    return render_template("admin_dashboard.html", orders=pagination.items, pagination=pagination,
                           stats=stats, current_filter=sf, current_type=tf, q=kw,
                           sort=sort, dir=direction)

@app.route("/admin/bulk", methods=["POST"])
@admin_required
def admin_bulk():
    action = request.form.get("action", "")
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    # Giu nguyen bo loc de redirect ve dung cho
    back = {k: request.form.get(k, "") for k in ("status", "type", "q", "sort", "dir", "page")}
    back = {k: v for k, v in back.items() if v}
    if not ids:
        flash("Chua chon don nao!", "error"); return redirect(url_for("admin_dashboard", **back))
    orders = Order.query.filter(Order.id.in_(ids)).all()
    n = len(orders)
    if action == "complete":
        for o in orders: o.complete_scraping()
        flash("Da hoan tat " + str(n) + " don.", "success")
    elif action == "cancel":
        for o in orders: o.status = "cancelled"; o.scraping_active = False
        flash("Da huy " + str(n) + " don.", "success")
    elif action == "start":
        for o in orders:
            if o.source_url: o.start_scraping()
        flash("Da bat dau quet " + str(n) + " don.", "success")
    elif action == "delete":
        for o in orders: db.session.delete(o)
        flash("Da xoa " + str(n) + " don.", "success")
    else:
        flash("Hanh dong khong hop le!", "error"); return redirect(url_for("admin_dashboard", **back))
    db.session.commit()
    return redirect(url_for("admin_dashboard", **back))
@app.route("/admin/order/new", methods=["GET","POST"])
@admin_required
def admin_order_new():
    if request.method == "POST":
        try:
            name = request.form.get("customer_name","").strip()
            if not name: flash("Nhap ten!"); return render_template("admin_order_form.html", order=None)
            ot = request.form.get("order_type","xingtu")
            lm = request.form.get("login_mode","otp") if ot in AGENT_TYPES else "otp"
            pwd = request.form.get("account_password","").strip() or None
            if not pwd and ot in AGENT_TYPES:
                skey = "wink_default_password" if ot in WINK_TYPES else "meitu_default_password"
                s = Setting.query.get(skey)
                pwd = s.value if s and s.value else None
            o = Order(customer_name=name, customer_phone=request.form.get("customer_phone","").strip() or None,
                      note=request.form.get("note","").strip() or None, status="pending", order_type=ot,
                      token=secrets.token_urlsafe(16), login_mode=lm, account_password=pwd)
            db.session.add(o); db.session.flush()
            # Luu nhieu link dai ly cho Wink/Meitu
            if ot in AGENT_TYPES:
                agent_urls_raw = request.form.get("agent_links","").strip()
                if agent_urls_raw:
                    for line in agent_urls_raw.split("\n"):
                        line = line.strip()
                        if line:
                            parts = line.split("|", 1)
                            url = parts[0].strip()
                            agent_name = parts[1].strip() if len(parts) > 1 else None
                            if url:
                                db.session.add(WinkAgentLink(order_id=o.id, url=url, agent_name=agent_name))
                    # Lay link dau tien lam source_url chinh
                    first_link = agent_urls_raw.strip().split("\n")[0].strip().split("|")[0].strip()
                    if first_link:
                        o.source_url = first_link
            db.session.commit()
            return redirect(url_for("admin_order_detail", oid=o.id))
        except Exception as e:
            import traceback; traceback.print_exc()
            db.session.rollback()
            flash(f"Loi tao don: {e}", "error")
            return render_template("admin_order_form.html", order=None)
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
    if not url: return redirect(url_for("admin_order_detail", oid=oid))
    o.source_url = url; o.error_count = 0
    if o.order_type in ("xingtu",) + AGENT_TYPES: o.start_scraping()
    else: o.status = "waiting_customer"
    o.set_expiry(app.config["AUTO_EXPIRE_DAYS"]); db.session.commit()
    return redirect(url_for("admin_order_detail", oid=oid))
@app.route("/admin/order/<int:oid>/complete", methods=["POST"])
@admin_required
def admin_order_complete(oid):
    o = Order.query.get_or_404(oid); o.complete_scraping(); db.session.commit()
    return redirect(url_for("admin_order_detail", oid=oid))
@app.route("/admin/order/<int:oid>/cancel", methods=["POST"])
@admin_required
def admin_order_cancel(oid):
    o = Order.query.get_or_404(oid); o.status="cancelled"; o.scraping_active=False; db.session.commit()
    return redirect(url_for("admin_order_detail", oid=oid))
@app.route("/admin/order/<int:oid>/delete", methods=["POST"])
@admin_required
def admin_order_delete(oid):
    o = Order.query.get_or_404(oid); db.session.delete(o); db.session.commit()
    return redirect(url_for("admin_dashboard"))
@app.route("/view/<token>")
def customer_view(token):
    o = Order.query.filter_by(token=token).first_or_404()
    if o.order_type=="duolingo": return _dl(o)
    if o.order_type in WINK_TYPES: return _wk(o)
    if o.order_type in MEITU_TYPES: return _mt(o)
    return _xt(o)
@app.route("/xingtu/<token>")
def customer_xingtu(token): return _xt(Order.query.filter_by(token=token).first_or_404())
@app.route("/duolingo/<token>")
@app.route("/dl/<token>")
def customer_duolingo(token): return _dl(Order.query.filter_by(token=token).first_or_404())
@app.route("/wink/<token>")
def customer_wink(token): return _wk(Order.query.filter_by(token=token).first_or_404())
@app.route("/meitu/<token>")
def customer_meitu(token): return _mt(Order.query.filter_by(token=token).first_or_404())
@app.route("/wink/")
def customer_wink_query():
    token = request.args.get("token")
    if not token: return redirect(url_for("admin_login"))
    o = Order.query.filter_by(token=token).first_or_404()
    return _wk(o)
@app.route("/meitu/")
def customer_meitu_query():
    token = request.args.get("token")
    if not token: return redirect(url_for("admin_login"))
    o = Order.query.filter_by(token=token).first_or_404()
    return _mt(o)
def _xt(o):
    if o.status=="cancelled": return render_template("customer_xingtu.html", order=o, code=None, phone=None, cancelled=True)
    if o.is_expired and o.status in ("scraping","paused"): o.status="expired"; o.scraping_active=False; db.session.commit()
    if o.status=="expired": return render_template("customer_xingtu.html", order=o, code=None, phone=None, expired=True)
    if o.source_url and not o.latest_code:
        if not o.scraping_active: o.start_scraping(); db.session.commit()
        scraper.request_scrape(o.id)
    return render_template("customer_xingtu.html", order=o, code=o.latest_code, phone=o.latest_phone)
def detect_country(phone):
    """Nhan dien quoc gia tu SDT chi hien so chinh (khong co +).
    Quy tac:
    1. 13 so bat dau 861 -> +86 China (cat bo 86)
    2. 11 so bat dau 852 -> +852 Hongkong (cat bo 852)
    3. 8 so dau 4-9 -> +852 Hongkong noi dia
    4. 11 so bat dau 1 -> +86 China
    5. 10 so dau 2-9 -> +1 Canada/US
    6. Khong khop -> None"""
    empty = {"code": None, "name": "Khong xac dinh", "clean_phone": None}
    if not phone: return empty
    digits = "".join(c for c in phone if c.isdigit())
    ln = len(digits)
    if not digits: return empty
    if ln == 13 and digits.startswith("861"):
        return {"code": "86", "name": "China", "clean_phone": digits[2:]}
    if ln == 11 and digits.startswith("852"):
        return {"code": "852", "name": "Hongkong", "clean_phone": digits[3:]}
    if ln == 8 and digits[0] in "456789":
        return {"code": "852", "name": "Hongkong", "clean_phone": digits}
    if ln == 11 and digits.startswith("1"):
        return {"code": "86", "name": "China", "clean_phone": digits}
    if ln == 10 and digits[0] in "23456789":
        return {"code": "1", "name": "Canada/US", "clean_phone": digits}
    return {"code": None, "name": "Khong xac dinh", "clean_phone": digits}
def _all_settings():
    return {s.key: s.value for s in Setting.query.all()}
def _wk(o):
    try:
        if o.status=="cancelled": return render_template("customer_wink.html", order=o, code=None, phone=None, cancelled=True)
        if o.is_expired and o.status in ("scraping","paused"): o.status="expired"; o.scraping_active=False; db.session.commit()
        if o.status=="expired": return render_template("customer_wink.html", order=o, code=None, phone=None, expired=True)
        if o.source_url and not o.latest_code:
            if not o.scraping_active: o.start_scraping(); db.session.commit()
            scraper.request_scrape(o.id)
        ctry = detect_country(o.latest_phone)
        phone_prefix = ("+" + ctry["code"]) if ctry["code"] else None
        country_name = ctry["name"]
        clean_phone = ctry["clean_phone"]
        login_mode = o.login_mode or "otp"
        agent_links = [{"url": l.url, "name": l.agent_name} for l in o.agent_links] if o.agent_links else []
        return render_template("customer_wink.html", order=o, code=o.latest_code, phone=o.latest_phone,
                               phone_prefix=phone_prefix, country_name=country_name, clean_phone=clean_phone,
                               login_mode=login_mode, agent_links=agent_links,
                               pwd=o.get_display_password(_all_settings()))
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"<h1>Error</h1><pre>{e}</pre>", 500
def _mt(o):
    try:
        if o.status=="cancelled": return render_template("customer_meitu.html", order=o, code=None, phone=None, cancelled=True)
        if o.is_expired and o.status in ("scraping","paused"): o.status="expired"; o.scraping_active=False; db.session.commit()
        if o.status=="expired": return render_template("customer_meitu.html", order=o, code=None, phone=None, expired=True)
        if o.source_url and not o.latest_code:
            if not o.scraping_active: o.start_scraping(); db.session.commit()
            scraper.request_scrape(o.id)
        ctry = detect_country(o.latest_phone)
        phone_prefix = ("+" + ctry["code"]) if ctry["code"] else None
        country_name = ctry["name"]
        clean_phone = ctry["clean_phone"]
        login_mode = o.login_mode or "otp"
        agent_links = [{"url": l.url, "name": l.agent_name} for l in o.agent_links] if o.agent_links else []
        return render_template("customer_meitu.html", order=o, code=o.latest_code, phone=o.latest_phone,
                               phone_prefix=phone_prefix, country_name=country_name, clean_phone=clean_phone,
                               login_mode=login_mode, agent_links=agent_links,
                               pwd=o.get_display_password(_all_settings()))
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"<h1>Error</h1><pre>{e}</pre>", 500
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
@app.route("/api/wink-request-otp/<token>", methods=["POST"])
def api_wink_request_otp(token):
    o = Order.query.filter_by(token=token).first_or_404()
    if o.order_type not in AGENT_TYPES: return jsonify({"error":"invalid order type"}), 400
    if o.status in ("cancelled","expired","success"): return jsonify({"error":"order "+o.status}), 400
    # Xoa code cu de scraper quet lai OTP moi
    o.latest_code = None; o.error_count = 0
    if not o.scraping_active:
        o.start_scraping()
    db.session.commit()
    scraper.request_scrape(o.id)
    return jsonify({"status":"otp_requested"})
@app.route("/api/code/<token>")
def api_code(token):
    o = Order.query.filter_by(token=token).first_or_404()
    last = db.session.query(CodeHistory.scraped_at).filter_by(order_id=o.id)\
             .order_by(CodeHistory.scraped_at.desc()).first()
    return jsonify({"code":o.latest_code,"phone":o.latest_phone,"status":o.status,
        "order_type":o.order_type or "xingtu","scraping_active":o.scraping_active,
        "password":o.get_display_password(_all_settings()) if o.order_type in AGENT_TYPES else None,
        "agent_links":[{"url":l.url,"name":l.agent_name} for l in o.agent_links] if o.order_type in AGENT_TYPES else [],
        "updated_at":last[0].isoformat() if last else None,
        "expired":o.is_expired,"completed":o.status=="success"})
@app.route("/token/<token>")
def token_page(token):
    o = Order.query.filter_by(token=token).first_or_404()
    if o.order_type in WINK_TYPES: return _wk(o)
    if o.order_type in MEITU_TYPES: return _mt(o)
    if o.order_type == "duolingo": return _dl(o)
    return _xt(o)
@app.route("/admin/settings", methods=["GET","POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        for key in ["wink_agent_url", "meitu_agent_url", "wink_mode", "meitu_mode",
                    "wink_default_password", "meitu_default_password", "meitu_domains"]:
            val = request.form.get(key, "").strip()
            s = Setting.query.get(key)
            if s: s.value = val
            else: db.session.add(Setting(key=key, value=val))
        db.session.commit()
        flash("Da luu cai dat!", "success")
        return redirect(url_for("admin_settings"))
    settings = {s.key: s.value for s in Setting.query.all()}
    return render_template("admin_settings.html", settings=settings)
@app.route("/")
def index():
    token = request.args.get("token")
    if token:
        return redirect(url_for("token_page", token=token))
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
