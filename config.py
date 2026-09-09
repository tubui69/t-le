import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'thay-doi-key-nay-thanh-chuoi-bi-mat-dac-biet-cua-ban')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    SCRAPE_INTERVAL = int(os.environ.get('SCRAPE_INTERVAL', 5))
    AUTO_EXPIRE_DAYS = int(os.environ.get('AUTO_EXPIRE_DAYS', 7))
    SQLALCHEMY_DATABASE_URI = 'sqlite:///data.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
