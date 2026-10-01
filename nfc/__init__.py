import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()
csrf = CSRFProtect()


def now():
    return datetime.now(timezone.utc)


class Plate(db.Model):
    __tablename__ = 'plates'
    id = db.Column(db.String(64), primary_key=True)
    business_name = db.Column(db.String(200), nullable=False)
    yandex_url = db.Column(db.String(2048), nullable=False, default='')
    two_gis_url = db.Column(db.String(2048), nullable=False, default='')
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, onupdate=now)


class Setting(db.Model):
    __tablename__ = 'settings'
    key = db.Column(db.String(80), primary_key=True)


class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'
    id = db.Column(db.String(32), primary_key=True)
    address = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now, index=True)


def validate_url(value):
    if not value:
        return True
    try:
        parsed = urlsplit(value)
        return (len(value) <= 2048 and parsed.scheme in ('http', 'https')
                and bool(parsed.hostname) and '.' in parsed.hostname
                and not parsed.username and not parsed.password
                and not any(c.isspace() or ord(c) < 32 for c in value)
                and '\\' not in value and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    production = os.getenv('APP_ENV', 'production') != 'development'
    database = os.getenv('DATABASE_URL', 'sqlite:///reviews.db')
    if database.startswith(('postgres://', 'postgresql://')):
        database = 'postgresql+psycopg://' + database.split('://', 1)[1]
    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY'), ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD'),
        SQLALCHEMY_DATABASE_URI=database, SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=production, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=16384, DEBUG=False,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('Set SECRET_KEY to a random string of at least 32 characters.')
    if not app.config['ADMIN_PASSWORD'] or len(app.config['ADMIN_PASSWORD']) < 12:
        raise RuntimeError('Set ADMIN_PASSWORD to at least 12 characters.')
    auth_version = hmac.new(app.config['SECRET_KEY'].encode(),
                            app.config['ADMIN_PASSWORD'].encode(), hashlib.sha256).hexdigest()
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        db.create_all()
        if not db.session.get(Setting, 'demo_seeded'):
            if not db.session.get(Plate, '001'):
                db.session.add(Plate(id='001', business_name='Демо-компания',
                                     yandex_url='https://yandex.ru/maps/', two_gis_url='https://2gis.ru/'))
            db.session.add(Setting(key='demo_seeded'))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()

    def authenticated():
        return hmac.compare_digest(str(session.get('admin', '')), auth_version)

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not authenticated():
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        if request.path.startswith('/admin'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.get('/')
    def index():
        return redirect(url_for('review', plate_id='001'))

    @app.get('/health')
    def health():
        return {'ok': True}

    @app.get('/r/<plate_id>')
    def review(plate_id):
        plate = db.get_or_404(Plate, plate_id)
        if not plate.active:
            abort(404)
        return render_template('review.html', plate=plate)

    @app.route('/admin/login', methods=['GET', 'POST'])
    def login():
        if authenticated():
            return redirect(url_for('admin'))
        if request.method == 'POST':
            # Use the direct peer address, never an untrusted X-Forwarded-For value.
            # Behind a shared proxy this intentionally becomes a shared limit.
            address = hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
            cutoff = now() - timedelta(minutes=15)
            db.session.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
            count = db.session.scalar(select(func.count()).select_from(LoginAttempt).where(
                LoginAttempt.address == address, LoginAttempt.created_at >= cutoff))
            if count >= 10:
                db.session.commit()
                flash('Слишком много попыток. Попробуйте через 15 минут.', 'error')
                return render_template('login.html'), 429
            db.session.add(LoginAttempt(id=secrets.token_hex(16), address=address))
            db.session.commit()
            if hmac.compare_digest(request.form.get('password', '').encode(), app.config['ADMIN_PASSWORD'].encode()):
                session.clear()
                session.permanent = True
                session['admin'] = auth_version
                flash('Вы вошли в панель управления.', 'success')
                return redirect(url_for('admin'))
            flash('Неверный пароль.', 'error')
            return render_template('login.html'), 401
        return render_template('login.html')

    @app.post('/admin/logout')
    @admin_required
    def logout():
        session.clear()
        flash('Вы вышли из системы.', 'success')
        return redirect(url_for('login'))

    @app.get('/admin')
    @admin_required
    def admin():
        plates = db.session.scalars(select(Plate).order_by(Plate.created_at.desc())).all()
        return render_template('admin.html', plates=plates)

    @app.route('/admin/new', methods=['GET', 'POST'])
    @app.route('/admin/<plate_id>/edit', methods=['GET', 'POST'])
    @admin_required
    def edit(plate_id=None):
        plate = db.get_or_404(Plate, plate_id) if plate_id else None
        values = request.form if request.method == 'POST' else (plate or {})
        if request.method == 'POST':
            new_id = request.form.get('id', '').strip()
            name = request.form.get('business_name', '').strip()
            yandex = request.form.get('yandex_url', '').strip()
            gis = request.form.get('two_gis_url', '').strip()
            error = None
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', new_id):
                error = 'ID: от 1 до 64 латинских букв, цифр, дефисов или подчёркиваний.'
            elif not 1 <= len(name) <= 200:
                error = 'Введите название бизнеса (до 200 символов).'
            elif not validate_url(yandex) or not validate_url(gis):
                error = 'Введите корректную ссылку с http:// или https:// либо оставьте поле пустым.'
            if not error:
                record = plate or Plate()
                record.id, record.business_name = new_id, name
                record.yandex_url, record.two_gis_url = yandex, gis
                record.active = request.form.get('active') == 'on'
                db.session.add(record)
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
                    error = 'Такой ID уже существует. Выберите другой.'
                else:
                    flash('Табличка сохранена.', 'success')
                    return redirect(url_for('admin'))
            flash(error, 'error')
            return render_template('edit.html', plate=plate, values=values), 400
        return render_template('edit.html', plate=plate, values=values)

    @app.post('/admin/<plate_id>/toggle')
    @admin_required
    def toggle(plate_id):
        plate = db.get_or_404(Plate, plate_id)
        plate.active = not plate.active
        db.session.commit()
        flash('Статус таблички изменён.', 'success')
        return redirect(url_for('admin'))

    @app.route('/admin/<plate_id>/delete', methods=['GET', 'POST'])
    @admin_required
    def remove(plate_id):
        plate = db.get_or_404(Plate, plate_id)
        if request.method == 'POST':
            db.session.delete(plate)
            db.session.commit()
            flash('Табличка удалена.', 'success')
            return redirect(url_for('admin'))
        return render_template('delete.html', plate=plate)

    @app.errorhandler(404)
    def not_found(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template('500.html'), 500

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template('error.html', heading='Форма устарела',
                               message='Обновите страницу и попробуйте ещё раз.'), 400

    return app
