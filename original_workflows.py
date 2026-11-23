from datetime import date
from decimal import Decimal, InvalidOperation

import requests
from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import text

from farms import farms, owned_farm, field, date_field, choice, save
from models import CASE_STATUSES, Crop, Farm, HealthCase, HealthUpdate, InputLog, User, db
from weather_guidance import forecast_guidance


def farm_rows():
    records = db.session.scalars(db.select(Farm).filter_by(owner_id=g.user.id).order_by(Farm.id.desc()))
    return [dict(farm_id=f.id, farm_name=f.name, farm_size=f.area, location=f.location,
                 soil_type=f.soil, irrigation_method=f.irrigation) for f in records]


def crop_rows():
    statement = (db.select(Crop, Farm.name).join(Farm).where(Farm.owner_id == g.user.id)
                 .order_by(Crop.id.desc()))
    return [dict(crop_id=c.id, crop_name=c.name, farm_name=farm, variety=c.variety,
                 growth_stage=c.stage, health_status=c.health, planting_date=c.planted_on)
            for c, farm in db.session.execute(statement)]


def case_rows(owner_id=None, limit=None):
    statement = (db.select(HealthCase, Farm.name, User.name, Crop.name)
                 .join(Farm, HealthCase.farm_id == Farm.id).join(User, Farm.owner_id == User.id)
                 .outerjoin(Crop, HealthCase.crop_id == Crop.id)
                 .order_by(HealthCase.reported_on.desc(), HealthCase.id.desc()))
    if owner_id is not None:
        statement = statement.where(Farm.owner_id == owner_id)
    records = db.session.execute(statement.limit(limit)).all()
    ids = [case.id for case, *_ in records]
    latest = {}
    if ids and limit is None:
        for update in db.session.scalars(db.select(HealthUpdate).where(HealthUpdate.case_id.in_(ids))
                                         .order_by(HealthUpdate.id.desc())):
            latest.setdefault(update.case_id, update.notes)
    return [dict(case_id=c.id, farm_name=f, full_name=u, crop_name=p, issue_name=c.title,
                 symptoms=c.symptoms, reported_date=c.reported_on, status=c.status,
                 days_open=((c.recovered_on or date.today()) - c.reported_on).days,
                 resolved_date=c.recovered_on, treatment_notes=latest.get(c.id))
            for c, f, u, p in records]


def selected_farm(value):
    try:
        farm_id = int(value)
        if not 0 < farm_id <= 2147483647:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose one of your farms.") from exc
    return owned_farm(farm_id)


def submitted_farm():
    return selected_farm(request.form.get("farm_id"))


def optional_crop(farm_id):
    value = request.form.get("crop_id", "")
    if value.isascii() and value.isdecimal() and len(value) <= 10 and int(value) <= 2147483647:
        return db.session.scalar(db.select(Crop.id).filter_by(id=int(value), farm_id=farm_id))
    return None


@farms.get("/dashboard")
def dashboard():
    records = farm_rows()
    owned = db.select(Farm.id).filter_by(owner_id=g.user.id)
    counts = {"farms": len(records)}
    counts["crops"] = db.session.scalar(
        db.select(db.func.count()).select_from(Crop).where(Crop.farm_id.in_(owned))
    )
    counts["active_cases"] = db.session.scalar(
        db.select(db.func.count()).select_from(HealthCase)
        .where(HealthCase.farm_id.in_(owned), HealthCase.status != "Recovered")
    )
    return render_template("dashboard.html", stats=counts, farms=records, cases=case_rows(g.user.id, 5))


@farms.route("/farms", methods=["GET", "POST"])
def farm_list():
    if request.method == "GET":
        return farm_dashboard()
    try:
        raw_area = field("farm_size", 13)
        area = Decimal(raw_area) if raw_area else None
        if area is not None and (
            not area.is_finite() or not 0 <= area < 10**10 or area != round(area, 2)
        ):
            raise ValueError("Enter a non-negative area with up to two decimal places.")
        farm = Farm(
            owner_id=g.user.id, name=field("farm_name", 100, True), location=field("location", 180, True),
            area=area or None, soil=field("soil_type", 80), irrigation=field("irrigation_method", 80),
            water_source=field("water_source", 80),
        )
    except (ValueError, InvalidOperation) as exc:
        error = str(exc) if isinstance(exc, ValueError) else "Enter a valid farm area."
        flash(error, "error")
        return farm_dashboard(), 422
    return save(farm, "Farm saved.", "farms.farm_list")


@farms.route("/crops", methods=["GET", "POST"])
def crops_page():
    if request.method == "POST":
        try:
            farm = submitted_farm()
            planted = date_field("planting_date")
            harvest = date_field("expected_harvest")
            if planted and harvest and harvest < planted:
                raise ValueError("Expected harvest must be on or after planting.")
            record = Crop(
                farm_id=farm.id, name=field("crop_name", 100, True), variety=field("variety", 100),
                planted_on=planted, harvest_on=harvest,
                stage=choice("growth_stage", ("Seedling", "Vegetative", "Flowering", "Fruiting", "Maturity", "Harvested")),
                health=choice("health_status", ("Healthy", "Needs attention", "Under treatment")),
                notes=field("notes", 4000),
            )
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            return save(record, "Crop record saved.", "farms.crops_page")
    return render_template("crops.html", farms=farm_rows(), crops=crop_rows())


@farms.route("/inputs", methods=["GET", "POST"])
def inputs_page():
    if request.method == "GET":
        return redirect(url_for("farms.farm_list", _anchor="farm-inputs"))
    if request.method == "POST":
        try:
            farm = submitted_farm()
            record = InputLog(
                farm_id=farm.id, crop_id=optional_crop(farm.id), product=field("product_name", 120) or "",
                category=choice("input_type", ("Fertiliser", "Seeds", "Pesticide", "Herbicide", "Water / irrigation", "Labour", "Other")),
                quantity=field("quantity", 80), notes=field("notes", 4000), applied_on=date_field("input_date", True),
            )
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            return save(record, "Farm input recorded.", "farms.farm_list", _anchor="farm-inputs")
    return farm_dashboard(), 422


def farm_dashboard():
    statement = (db.select(InputLog, Farm.name, Crop.name).join(Farm, InputLog.farm_id == Farm.id)
                 .outerjoin(Crop, InputLog.crop_id == Crop.id).where(Farm.owner_id == g.user.id)
                 .order_by(InputLog.applied_on.desc(), InputLog.id.desc()))
    logs = [dict(input_date=i.applied_on, farm_name=f, crop_name=c, input_type=i.category,
                 product_name=i.product, quantity=i.quantity) for i, f, c in db.session.execute(statement)]
    return render_template("farms.html", farms=farm_rows(), crops=crop_rows(), logs=logs, today=date.today())


@farms.route("/diseases", methods=["GET", "POST"])
def diseases_page():
    if request.method == "POST":
        try:
            farm = submitted_farm()
            record = HealthCase(farm_id=farm.id, crop_id=optional_crop(farm.id),
                                title=field("issue_name", 150, True), symptoms=field("symptoms", 4000) or "",
                                reported_on=date_field("reported_date", True))
            if record.reported_on > date.today():
                raise ValueError("Report date cannot be in the future.")
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            return save(record, "Crop health case recorded.", "farms.diseases_page")
    return render_template("diseases.html", farms=farm_rows(), crops=crop_rows(),
                           cases=case_rows(g.user.id), today=date.today())


@farms.post("/diseases/<int:case_id>/update")
def update_case(case_id):
    try:
        status = choice("status", CASE_STATUSES)
        notes = field("treatment_notes", 4000) or ""
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("farms.diseases_page"), 303)
    db.session.execute(text("BEGIN IMMEDIATE"))
    case = db.session.scalar(db.select(HealthCase).join(Farm)
                             .where(HealthCase.id == case_id, Farm.owner_id == g.user.id))
    if case is None:
        abort(404)
    case.status = status
    case.recovered_on = (case.recovered_on or date.today()) if status == "Recovered" else None
    if case.recovered_on and case.crop_id:
        db.session.get(Crop, case.crop_id).health = "Healthy"
    return save(HealthUpdate(case_id=case.id, status=status, notes=notes),
                "Crop health progress updated.", "farms.diseases_page")


@farms.route("/weather", methods=["GET", "POST"])
def weather_page():
    report = error = None
    farms_available = farm_rows()
    selected = request.values.get("farm_id", "")
    if request.method == "GET" and not selected and len(farms_available) == 1:
        selected = farms_available[0]["farm_id"]
    if selected:
        try:
            farm = selected_farm(selected)
            geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                               params={"name": farm.location, "count": 1}, timeout=(3, 5))
            geo.raise_for_status()
            results = geo.json().get("results") or []
            if not results:
                raise ValueError("Could not find that farm location. Try a nearby town or county name.")
            place = results[0]
            response = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": place["latitude"], "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m",
                "daily": (
                    "precipitation_probability_max,precipitation_sum,temperature_2m_max,"
                    "temperature_2m_min,weather_code,wind_gusts_10m_max"
                ),
                "forecast_days": 3, "timezone": "auto",
            }, timeout=(3, 5))
            response.raise_for_status()
            payload = response.json()
            report = {"place": ", ".join(place[key] for key in ("name", "admin1", "country") if place.get(key)),
                      "current": payload["current"], "daily": payload["daily"],
                      "guidance": forecast_guidance(payload["daily"])}
        except (requests.RequestException, KeyError, TypeError):
            error = "Weather service is temporarily unavailable. Please try again."
        except ValueError as exc:
            error = str(exc)
    return render_template("weather.html", farms=farms_available, selected=selected, report=report, error_message=error)
