from datetime import date
import os
import re
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from farms import farms
from models import Crop, Farm, HealthCase, User, db
from original_workflows import case_rows
from farmer_tools import tools as farmer_tools
from farming_chat import chat
from request_limits import permit_request


DUMMY_PASSWORD_HASH = generate_password_hash("unused-placeholder")
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def credentials(email, password):
    return len(email) <= 254 and EMAIL.fullmatch(email) and 8 <= len(password) <= 128


def create_app(config=None):
    app = Flask(__name__)
    load_dotenv(Path(app.root_path) / ".env")
    environment = os.environ.get("APP_ENV", "production")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI="sqlite:///smart_farming.sqlite3",
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_SECURE=environment != "development",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.config.update(config or {})
    if len(app.config["SECRET_KEY"] or "") < 32:
        raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters.")
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    proxy_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
    if proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops)

    db.init_app(app)
    with app.app_context():
        event.listen(db.engine, "connect", enable_foreign_keys)
    Migrate(app, db, directory=os.path.join(app.root_path, "migrations"))
    CSRFProtect(app)
    app.register_blueprint(farms)
    app.register_blueprint(farmer_tools)
    app.register_blueprint(chat)

    @app.context_processor
    def interface_date():
        return {"now_date": date.today().strftime("%d %B %Y")}

    @app.before_request
    def current_user():
        user_id = session.get("user_id")
        g.user = db.session.get(User, user_id) if user_id else None

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.endpoint == "diagnose":
            response.headers["Content-Security-Policy"] += "; script-src 'self' 'wasm-unsafe-eval'; img-src 'self' blob:"
        if request.is_secure and app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def healthcheck():
        try:
            db.session.execute(text("SELECT 1 FROM users LIMIT 1"))
        except SQLAlchemyError:
            app.logger.exception("Database readiness check failed")
            return {"status": "unavailable"}, 503
        return {"status": "ok"}

    @app.get("/")
    def index():
        if not g.user:
            return redirect(url_for("login"))
        return redirect(url_for("admin" if g.user.is_admin else "farms.dashboard"))

    @app.get("/diseases/diagnose")
    def diagnose():
        if not g.user:
            return redirect(url_for("login"))
        return render_template("diagnose.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template("login.html")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not permit_request("login", request.remote_addr or "unknown", 30):
            flash("Too many attempts. Try again shortly.", "error")
            return render_template("login.html"), 429
        user = db.session.scalar(db.select(User).filter_by(email=email)) if credentials(email, password) else None
        valid_password = check_password_hash(
            user.password_hash if user else DUMMY_PASSWORD_HASH, password[:128]
        )
        role = request.form.get("role", "farmer")
        if not user or not valid_password or role != ("admin" if user.is_admin else "farmer"):
            flash("The details do not match an account with the selected role.", "error")
            return render_template("login.html"), 401
        session.clear()
        session["user_id"] = user.id
        return redirect(url_for("index"), 303)

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if g.user:
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template("signup.html")
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not 1 <= len(name) <= 100 or not credentials(email, password) or len(phone) > 25:
            flash("Enter your name, a valid email, and a password of 8 to 128 characters.", "error")
            return render_template("signup.html"), 422
        db.session.add(User(name=name, email=email, phone=phone or None, password_hash=generate_password_hash(password)))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That email is already registered.", "error")
            return render_template("signup.html"), 409
        flash("Farmer account created. You can now sign in.", "success")
        return redirect(url_for("login"), 303)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"), 303)

    @app.get("/admin")
    def admin():
        if not g.user:
            return redirect(url_for("login"))
        if not g.user.is_admin:
            abort(403)
        counts = {
            label: db.session.scalar(db.select(db.func.count()).select_from(model).filter(*filters))
            for label, model, filters in (
                ("farmers", User, (User.is_admin.is_(False),)),
                ("farms", Farm, ()),
                ("crops", Crop, ()),
                ("active_cases", HealthCase, (HealthCase.status != "Recovered",)),
            )
        }
        recent = db.session.execute(db.select(User.name.label("full_name"), User.email, User.created_at)
                                    .where(User.is_admin.is_(False)).order_by(User.id.desc()).limit(12)).all()
        return render_template("admin.html", stats=counts, recent=recent, cases=case_rows(limit=10))

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(email, name, password):
        email, name = email.strip().lower(), name.strip()
        if not 1 <= len(name) <= 100 or not credentials(email, password):
            raise click.ClickException("Enter a valid name, email and password of 8 to 128 characters.")
        db.session.add(User(name=name, email=email, password_hash=generate_password_hash(password), is_admin=True))
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise click.ClickException("That email is already registered.") from exc
        click.echo("Administrator created.")

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def request_error(error):
        messages = {
            400: "The form could not be submitted. Reload the page and try again.",
            403: "You do not have access to this page.",
            404: "This page could not be found.",
            413: "The submitted form is too large.",
        }
        return render_template("error.html", title="Request unavailable", message=messages[error.code]), error.code

    return app


def enable_foreign_keys(connection, _record):
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
