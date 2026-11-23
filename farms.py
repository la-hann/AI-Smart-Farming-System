from datetime import date
from decimal import Decimal, InvalidOperation

import requests
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import text

from models import CASE_STATUSES, Crop, Farm, HealthCase, HealthUpdate, InputLog, db


farms = Blueprint("farms", __name__)
STAGES = ("Seedling", "Vegetative", "Flowering", "Fruiting", "Harvested")
HEALTH = ("Healthy", "Needs attention", "Under treatment")
INPUT_TYPES = ("Seed", "Fertiliser", "Pesticide", "Irrigation", "Labour", "Other")


@farms.before_request
def farmer_required():
    if not g.user:
        return redirect(url_for("login"))
    if g.user.is_admin:
        abort(403)


def owned_farms():
    return db.session.scalars(db.select(Farm).filter_by(owner_id=g.user.id).order_by(Farm.name)).all()


def owned_farm(farm_id):
    farm = db.session.scalar(db.select(Farm).filter_by(id=farm_id, owner_id=g.user.id))
    if farm is None:
        abort(404)
    return farm


def field(name, limit, required=False):
    value = request.form.get(name, "").strip()
    if len(value) > limit or (required and not value):
        raise ValueError(f"Check the {name.replace('_', ' ')} field.")
    return value or None


def date_field(name, required=False):
    value = field(name, 10, required)
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Enter a valid {name.replace('_', ' ')} date.") from exc
    return None


def choice(name, options):
    value = request.form.get(name)
    if value not in options:
        raise ValueError(f"Choose a valid {name.replace('_', ' ')}.")
    return value


def crop_selection(farm_id):
    crop_id = field("crop", 10)
    if crop_id is None:
        return None
    if not crop_id.isascii() or not crop_id.isdecimal() or int(crop_id) > 2147483647:
        raise ValueError("Choose a crop from this farm.")
    crop_id = int(crop_id)
    if db.session.scalar(db.select(Crop.id).filter_by(id=crop_id, farm_id=farm_id)) is None:
        raise ValueError("Choose a crop from this farm.")
    return crop_id


def save(record, message, endpoint, **params):
    db.session.add(record)
    db.session.commit()
    flash(message)
    return redirect(url_for(endpoint, **params), 303)


@farms.get("/dashboard")
def dashboard():
    records = owned_farms()
    owned = db.select(Farm.id).filter_by(owner_id=g.user.id)
    counts = {"Farms": len(records)}
    counts["Crops"] = db.session.scalar(
        db.select(db.func.count()).select_from(Crop).where(Crop.farm_id.in_(owned))
    )
    counts["Open health cases"] = db.session.scalar(
        db.select(db.func.count()).select_from(HealthCase)
        .where(HealthCase.farm_id.in_(owned), HealthCase.status != "Recovered")
    )
    return render_template("dashboard.html", title="Farm dashboard", counts=counts, farms=records)


@farms.route("/farms", methods=["GET", "POST"])
def farm_list():
    if request.method == "GET":
        return render_template("farms.html", title="Farms", farms=owned_farms())
    try:
        raw_area = field("area", 13)
        area = Decimal(raw_area) if raw_area else None
        if area is not None and (
            not area.is_finite() or not 0 < area < 10**10 or area != round(area, 2)
        ):
            raise ValueError("Enter an area greater than zero with up to two decimal places.")
        farm = Farm(
            owner_id=g.user.id, name=field("name", 100, True), location=field("location", 180, True),
            area=area, soil=field("soil", 80), irrigation=field("irrigation", 80),
            water_source=field("water_source", 80),
        )
    except (ValueError, InvalidOperation) as exc:
        error = str(exc) if isinstance(exc, ValueError) else "Enter a valid farm area."
        return render_template("farms.html", title="Farms", farms=owned_farms(), error=error), 422
    return save(farm, "Farm added.", "farms.farm_list")


def farm_page(farm, error=None):
    crops = db.session.scalars(db.select(Crop).filter_by(farm_id=farm.id).order_by(Crop.name)).all()
    inputs = db.session.scalars(
        db.select(InputLog).filter_by(farm_id=farm.id).order_by(InputLog.applied_on.desc(), InputLog.id.desc())
    ).all()
    cases = db.session.scalars(
        db.select(HealthCase).filter_by(farm_id=farm.id).order_by(HealthCase.reported_on.desc(), HealthCase.id.desc())
    ).all()
    return render_template(
        "farm.html", title=farm.name, farm=farm, crops=crops, inputs=inputs, cases=cases,
        stages=STAGES, health=HEALTH, categories=INPUT_TYPES, error=error,
    ), 422 if error else 200


@farms.get("/farms/<int:farm_id>")
def detail(farm_id):
    return farm_page(owned_farm(farm_id))


@farms.post("/farms/<int:farm_id>/crops")
def add_crop(farm_id):
    farm = owned_farm(farm_id)
    try:
        planted = date_field("planted_on", True)
        harvest = date_field("harvest_on")
        if harvest and harvest < planted:
            raise ValueError("Expected harvest must be on or after planting.")
        crop = Crop(
            farm_id=farm.id, name=field("name", 100, True), variety=field("variety", 100),
            planted_on=planted, harvest_on=harvest, stage=choice("stage", STAGES),
            health=choice("health", HEALTH),
        )
    except ValueError as exc:
        return farm_page(farm, str(exc))
    return save(crop, "Crop added.", "farms.detail", farm_id=farm.id)


@farms.route("/farms/<int:farm_id>/crops/<int:crop_id>", methods=["GET", "POST"])
def edit_crop(farm_id, crop_id):
    farm = owned_farm(farm_id)
    crop = db.session.scalar(db.select(Crop).filter_by(id=crop_id, farm_id=farm.id))
    if crop is None:
        abort(404)
    error = None
    if request.method == "POST":
        try:
            stage = choice("stage", STAGES)
            health = choice("health", HEALTH)
            harvest = date_field("harvest_on")
            if harvest and harvest < crop.planted_on:
                raise ValueError("Expected harvest must be on or after planting.")
        except ValueError as exc:
            error = str(exc)
        else:
            crop.stage, crop.health, crop.harvest_on = stage, health, harvest
            return save(crop, "Crop updated.", "farms.detail", farm_id=farm.id)
    return render_template(
        "crop.html", title=crop.name, farm=farm, crop=crop, stages=STAGES, health=HEALTH, error=error,
    ), 422 if error else 200


@farms.post("/farms/<int:farm_id>/inputs")
def add_input(farm_id):
    farm = owned_farm(farm_id)
    try:
        record = InputLog(
            farm_id=farm.id, crop_id=crop_selection(farm.id), category=choice("category", INPUT_TYPES),
            product=field("product", 120, True), quantity=field("quantity", 80),
            applied_on=date_field("applied_on", True), notes=field("notes", 4000),
        )
    except ValueError as exc:
        return farm_page(farm, str(exc))
    return save(record, "Input logged.", "farms.detail", farm_id=farm.id)


@farms.post("/farms/<int:farm_id>/cases")
def report_case(farm_id):
    farm = owned_farm(farm_id)
    try:
        case = HealthCase(
            farm_id=farm.id, crop_id=crop_selection(farm.id), title=field("title", 150, True),
            symptoms=field("symptoms", 4000, True), reported_on=date_field("reported_on", True),
        )
        if case.reported_on > date.today():
            raise ValueError("Report date cannot be in the future.")
    except ValueError as exc:
        return farm_page(farm, str(exc))
    return save(case, "Health case recorded.", "farms.detail", farm_id=farm.id)


def case_page(farm, case, error=None):
    updates = db.session.scalars(
        db.select(HealthUpdate).filter_by(case_id=case.id).order_by(HealthUpdate.id.desc())
    ).all()
    return render_template(
        "case.html", title=case.title, farm=farm, case=case, updates=updates, statuses=CASE_STATUSES, error=error,
    ), 422 if error else 200


@farms.route("/farms/<int:farm_id>/cases/<int:case_id>", methods=["GET", "POST"])
def health_case(farm_id, case_id):
    if request.method == "POST":
        # Reserve the write before reading the current crop health status.
        db.session.execute(text("BEGIN IMMEDIATE"))
    farm = owned_farm(farm_id)
    statement = db.select(HealthCase).filter_by(farm_id=farm.id, id=case_id)
    case = db.session.scalar(statement)
    if case is None:
        abort(404)
    if request.method == "GET":
        return case_page(farm, case)
    try:
        status = choice("status", CASE_STATUSES)
        notes = field("notes", 4000, True)
    except ValueError as exc:
        return case_page(farm, case, str(exc))
    recovered_on = case.recovered_on or date.today()
    case.status = status
    case.recovered_on = recovered_on if status == "Recovered" else None
    update = HealthUpdate(case_id=case.id, status=status, notes=notes)
    return save(update, "Case updated.", "farms.health_case", farm_id=farm.id, case_id=case.id)


@farms.get("/farms/<int:farm_id>/weather")
def weather(farm_id):
    farm = owned_farm(farm_id)
    place, forecasts, error = None, [], None
    try:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": farm.location, "count": 1}, timeout=(3, 5),
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if results:
            place = results[0]
            response = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"], "longitude": place["longitude"],
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto", "forecast_days": 5,
                },
                timeout=(3, 5),
            )
            response.raise_for_status()
            daily = response.json()["daily"]
            forecasts = list(zip(
                daily["time"], daily["temperature_2m_min"], daily["temperature_2m_max"],
                daily["precipitation_probability_max"], strict=True,
            ))
        else:
            error = "No weather location matched the saved farm location."
    except (requests.RequestException, ValueError, KeyError, TypeError):
        error = "Weather is temporarily unavailable. Try again later."
    return render_template(
        "weather.html", title="Weather", farm=farm, place=place, forecasts=forecasts, error=error,
    )
