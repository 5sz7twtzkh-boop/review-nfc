import os

bind = '0.0.0.0:' + os.getenv('PORT', '8000')
workers = 1
threads = 4
timeout = 30
accesslog = '-'
errorlog = '-'
# Initialize schema once before workers start.
preload_app = True


def post_fork(server, worker):
    from app import app
    from nfc import db
    with app.app_context():
        db.engine.dispose(close=False)
