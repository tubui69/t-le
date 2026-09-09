import secrets, atexit
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
        cols = [c[chr(34)+chr(110)+chr(97)+chr(109)+chr(101)+chr(34)] for c in inspect(db.engine).get_columns(chr(34)+chr(111)+chr(114)+chr(100)+chr(101)+chr(114)+chr(115)+chr(34))]
        for col, ddl in [(chr(34)+chr(108)+chr(97)+chr(116)+chr(101)+chr(115)+chr(116)+chr(95)+chr(112)+chr(104)+chr(111)+chr(110)+chr(101)+chr(34),chr(34)+chr(86)+chr(65)+chr(82)+chr(67)+chr(72)+chr(65)+chr(82)+chr(40)+chr(51)+chr(48)+chr(41)+chr(34))]:
            pass
    except Exception as e: print(e)
scraper = CodeScraper(app); scraper.start()