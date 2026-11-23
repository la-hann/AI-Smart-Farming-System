from hashlib import sha256
import os
import re
from time import time

import click
from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from farms import farms
from models import Crop, Farm, HealthCase, LoginAttempt, User, db


DUMMY_PASSWORD_HASH = generate_password_hash("unused-placeholder")
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def credentials(email, password):
    return len(email) <= 254 and EMAIL.fullmatch(email) and 12 <= len(password) <= 128


def permit_login(ip):
    window = int(time() // 900)
    key = sha256(ip.encode()).hexdigest()
    table = LoginAttempt.__table__
    statement = insert(table).values(key=key, window=window, attempts=1)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.key, table.c.window],
        set_={"attempts": table.c.attempts + 1},
        where=table.c.attempts < 30,
    ).returning(table.c.attempts)
    allowed = db.session.execute(statement).scalar_one_or_none() is not None
    db.session.execute(delete(LoginAttempt).where(LoginAttempt.window < window - 1))
    db.session.commit()
    return allowed


def create_app(config=None):
    app = Flask(__name__)
    environment = os.environ.get("APP_ENV", "production")
    database_url = os.environ.get("DATABASE_URL", "")
    database_url = re.sub(r"^postgres(?:ql)?://", "postgresql+psycopg://", database_url)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_SECURE=environment != "development",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    app.config.update(config or {})
    if len(app.config["SECRET_KEY"] or "") < 32:
        raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters.")
    if not app.config["TESTING"] and not app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://"):
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL connection URL.")
    proxy_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
    if proxy_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops)

    db.init_app(app)
    Migrate(app, db, directory=os.path.join(app.root_path, "migrations"))
    CSRFProtect(app)
    app.register_blueprint(farms)

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

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template("auth.html", title="Sign in")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not permit_login(request.remote_addr or "unknown"):
            return render_template("auth.html", title="Sign in", error="Too many attempts. Try again shortly."), 429
        user = db.session.scalar(db.select(User).filter_by(email=email)) if credentials(email, password) else None
        valid_password = check_password_hash(
            user.password_hash if user else DUMMY_PASSWORD_HASH, password[:128]
        )
        if not user or not valid_password:
            return render_template("auth.html", title="Sign in", error="Email or password is incorrect."), 401
        session.clear()
        session["user_id"] = user.id
        return redirect(url_for("index"), 303)

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if g.user:
            return redirect(url_for("index"))
        if request.method == "GET":
            return render_template("auth.html", title="Create account", register=True)
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not 1 <= len(name) <= 100 or not credentials(email, password):
            return render_template(
                "auth.html", title="Create account", register=True,
                error="Enter your name, a valid email and a password of 12 to 128 characters.",
            ), 422
        db.session.add(User(name=name, email=email, password_hash=generate_password_hash(password)))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
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
                ("Farmers", User, (User.is_admin.is_(False),)),
                ("Farms", Farm, ()),
                ("Crops", Crop, ()),
                ("Open health cases", HealthCase, (HealthCase.status != "Recovered",)),
            )
        }
        return render_template("dashboard.html", title="Administration", counts=counts)

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(email, name, password):
        email, name = email.strip().lower(), name.strip()
        if not 1 <= len(name) <= 100 or not credentials(email, password):
            raise click.ClickException("Enter a valid name, email and password of 12 to 128 characters.")
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
