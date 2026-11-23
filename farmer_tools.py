from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import math
from time import time
from zoneinfo import ZoneInfo

import requests
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy.dialects.sqlite import insert

from farming_chat import chat_context
from farms import date_field, farmer_required, field, owned_farm, owned_farms, save
from models import Crop, CropCheck, Farm, IrrigationEntry, IrrigationPlan, db
from weather_guidance import watering_check


tools = Blueprint("farmer_tools", __name__)
tools.before_request(farmer_required)

ACRE_SQUARE_METRES = 4046.8564224
CROP_COEFFICIENTS = {
    "maize": (0.30, 1.20, 0.60),
    "corn": (0.30, 1.20, 0.60),
    "tomato": (0.60, 1.15, 0.80),
    "tomatoes": (0.60, 1.15, 0.80),
    "potato": (0.50, 1.15, 0.75),
    "potatoes": (0.50, 1.15, 0.75),
    "dry beans": (0.40, 1.15, 0.35),
}
DAILY_FIELDS = (
    "et0_fao_evapotranspiration", "precipitation_sum", "precipitation_probability_max",
    "temperature_2m_max", "wind_gusts_10m_max",
)


def local_today():
    return datetime.now(ZoneInfo("Africa/Nairobi")).date()


def owned_crops():
    statement = db.select(Crop, Farm).join(Farm).where(Farm.owner_id == g.user.id).order_by(Farm.name, Crop.name)
    return db.session.execute(statement).all()


def record_id(raw):
    if raw and len(raw) <= 10 and raw.isascii() and raw.isdecimal():
        number = int(raw)
        if number <= 2147483647:
            return number
    abort(404)


def owned_crop(raw):
    crop_id = record_id(raw)
    statement = db.select(Crop, Farm).join(Farm).where(Crop.id == crop_id, Farm.owner_id == g.user.id)
    row = db.session.execute(statement).one_or_none()
    if row is None:
        abort(404)
    return row


def decimal_field(name, maximum, places):
    try:
        value = Decimal(field(name, 16, True))
        if value.is_finite() and 0 < value <= maximum and value == round(value, places):
            return value
    except InvalidOperation:
        pass
    raise ValueError(f"Enter a positive {name.replace('_', ' ')} with up to {places} decimal places.")


@lru_cache(maxsize=128)
def fetch_forecast(location, _refresh_window):
    geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": location, "count": 1}, timeout=(3, 5))
    geo.raise_for_status()
    matches = geo.json().get("results") or []
    if not matches:
        raise ValueError("The farm location could not be found. Try a nearby town.")
    place = matches[0]
    response = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "Africa/Nairobi",
        "daily": ",".join(DAILY_FIELDS), "forecast_days": 3,
    }, timeout=(3, 5))
    response.raise_for_status()
    daily = response.json()["daily"]
    records = []
    for values in zip(daily["time"], *(daily[key] for key in DAILY_FIELDS), strict=True):
        day, *metrics = values
        if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in metrics):
            raise ValueError("The forecast has missing measurements. Try again later.")
        records.append((date.fromisoformat(day), *metrics))
    return tuple(records)


def weather_for(farm, today):
    try:
        forecast = fetch_forecast(farm.location, int(time() // 1800))
        if [entry[0] for entry in forecast] != [today + timedelta(days=day) for day in range(3)]:
            return (), "A complete three-day forecast is unavailable."
        return forecast, None
    except (requests.RequestException, KeyError, TypeError):
        return (), "Weather is temporarily unavailable. Try again later."
    except ValueError:
        return (), "A complete forecast could not be found for this farm location."


def crop_coefficient(crop):
    coefficients = CROP_COEFFICIENTS.get(crop.name.strip().casefold())
    if not coefficients or crop.stage == "Harvested":
        return None
    initial, mid, end = coefficients
    return {
        "Seedling": initial, "Vegetative": (initial + mid) / 2,
        "Flowering": mid, "Fruiting": mid, "Maturity": end,
    }.get(crop.stage)


def estimate_irrigation(forecast, coefficient, acres, efficiency, applied_today):
    demand = sum(max(0, day[1]) for day in forecast) * coefficient
    # Credit 75% of forecast rain as a planning assumption for infiltration.
    effective_rain = sum(max(0, day[2]) for day in forecast) * 0.75
    gross_litres = max(0, demand - effective_rain) * acres * ACRE_SQUARE_METRES / efficiency
    return max(0, round(gross_litres - applied_today)), demand, effective_rain


def plan_result(crop, plan, forecast, today):
    coefficient = crop_coefficient(crop)
    if not forecast or not plan or coefficient is None:
        return None
    applied = db.session.scalar(db.select(db.func.sum(IrrigationEntry.litres)).where(
        IrrigationEntry.crop_id == crop.id, IrrigationEntry.applied_on == today)) or 0
    litres, demand, rain = estimate_irrigation(
        forecast, coefficient, float(plan.acres), plan.efficiency / 100, float(applied)
    )
    return dict(litres=litres, demand=demand, rain=rain, applied=applied,
                start=forecast[0][0], end=forecast[-1][0])


def weather_alerts(forecast):
    alerts = []
    for day, _, rain, chance, temperature, gust in forecast:
        if rain >= 10:
            alerts.append((day, f"{rain:g} mm of rain forecast. Check drainage and reassess watering after rain."))
        elif chance >= 60:
            alerts.append((day, f"{chance:g}% chance of rain. Check the soil before irrigating."))
        if temperature >= 32:
            alerts.append((day, f"High of {temperature:g} C forecast. Check crops and soil moisture early in the day."))
        if gust >= 45:
            alerts.append((day, f"Gusts up to {gust:g} km/h forecast. Check crop supports and postpone spraying in strong winds."))
    return alerts


def irrigation_target(value):
    kind, _, identifier = value.partition(":")
    if kind == "crop":
        return owned_crop(identifier)
    if kind == "farm":
        return None, owned_farm(record_id(identifier))
    abort(404)


@tools.route("/irrigation", methods=["GET", "POST"])
def irrigation():
    today = local_today()
    selected = request.args.get("target") or ""
    legacy_crop = request.values.get("crop_id")
    if legacy_crop and not selected:
        selected = f"crop:{legacy_crop}"
    if request.method == "POST":
        selected = request.form.get("target") or selected
        try:
            if not selected:
                raise ValueError("Choose a farm or crop.")
            crop, farm = irrigation_target(selected)
            volume = decimal_field("water_amount", 10000000, 3)
            unit = request.form.get("unit")
            if unit not in ("L", "m3"):
                raise ValueError("Choose litres or cubic metres.")
            applied = date_field("applied_on", True)
            if applied > today:
                raise ValueError("The irrigation date cannot be in the future.")
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            entry = IrrigationEntry(farm_id=farm.id, crop_id=crop.id if crop else None, applied_on=applied,
                                    litres=volume * (1000 if unit == "m3" else 1))
            return save(entry, "Irrigation recorded.", "farmer_tools.irrigation", target=selected)
    owner = (db.select(IrrigationEntry).join(Farm, IrrigationEntry.farm_id == Farm.id)
             .outerjoin(Crop, IrrigationEntry.crop_id == Crop.id).where(Farm.owner_id == g.user.id))
    crop = estimate = weather_error = None
    if selected:
        crop, farm = irrigation_target(selected)
        if crop:
            owner = owner.where(IrrigationEntry.crop_id == crop.id)
            plan = db.session.get(IrrigationPlan, crop.id)
            if plan:
                forecast, weather_error = weather_for(farm, today)
                estimate = plan_result(crop, plan, forecast, today)
        else:
            owner = owner.where(IrrigationEntry.farm_id == farm.id)
    total = db.session.scalar(db.select(db.func.sum(owner.subquery().c.litres))) or 0
    entries = db.session.execute(
        owner.with_only_columns(IrrigationEntry, Crop.name, Farm.name)
        .order_by(IrrigationEntry.applied_on.desc(), IrrigationEntry.id.desc()).limit(50)
    ).all()
    return render_template("irrigation.html", farms=owned_farms(), crops=owned_crops(), entries=entries,
                           total=total, selected=selected, selected_crop=crop, today=today,
                           estimate=estimate, weather_error=weather_error)


def plan_values(farm):
    acres = decimal_field("area_acres", 100000, 3)
    if farm.area is not None and acres > farm.area:
        raise ValueError("The crop plot area must fit within the farm.")
    raw_efficiency = request.form.get("efficiency", "")
    if raw_efficiency not in {str(number) for number in range(30, 101)}:
        raise ValueError("Enter a whole-number irrigation efficiency between 30 and 100 percent.")
    return acres, int(raw_efficiency)


@tools.route("/recommendations", methods=["GET", "POST"])
def recommendations():
    saving = request.method == "POST"
    selected = request.form.get("crop_id") if saving else request.args.get("crop_id")
    return ai_dashboard(selected, saving=saving)


@tools.route("/chatbot", methods=["GET", "POST"])
def chatbot():
    selected = request.args.get("crop_id")
    if request.method == "GET":
        return redirect(url_for("farmer_tools.recommendations", crop_id=selected, _anchor="ai-chatbot"))
    if selected:
        owned_crop(selected)
    return ai_dashboard(selected, chat=chat_context(request.form.get("question", ""), g.user.id))


def ai_dashboard(selected, saving=False, chat=None):
    acres_text, efficiency_text = "", "80"
    result = error = crop = None
    alerts = []
    if selected:
        crop, farm = owned_crop(selected)
        plan = db.session.get(IrrigationPlan, crop.id)
        if saving:
            acres_text = request.form.get("area_acres", "")
            efficiency_text = request.form.get("efficiency", "")
            try:
                acres, efficiency = plan_values(farm)
            except ValueError as exc:
                error = str(exc)
            else:
                settings = dict(acres=acres, efficiency=efficiency)
                statement = insert(IrrigationPlan).values(crop_id=crop.id, **settings)
                db.session.execute(statement.on_conflict_do_update(
                    index_elements=[IrrigationPlan.crop_id], set_=settings,
                ))
                db.session.commit()
                return redirect(url_for("farmer_tools.recommendations", crop_id=crop.id,
                                        _anchor="ai-recommendation"), 303)
        elif plan:
            acres_text, efficiency_text = plan.acres, plan.efficiency
        today = local_today()
        forecast, weather_error = weather_for(farm, today)
        alerts = weather_alerts(forecast)
        if crop_coefficient(crop) is None:
            error = error or "An irrigation estimate is available for active maize, tomato, potato, and dry bean crops."
        result = plan_result(crop, plan, forecast, today)
        error = error or weather_error
    elif saving:
        error = "Choose one of your crops."
    return render_template("recommendations.html", crops=owned_crops(), selected=selected,
                           acres=acres_text, efficiency=efficiency_text, result=result, crop=crop,
                           alerts=alerts, error=error, chat=chat or chat_context())


def check_interval(crop):
    if crop.health != "Healthy" or crop.stage in ("Flowering", "Fruiting"):
        return 3
    return 7 if crop.stage == "Seedling" else 14


@tools.get("/alerts")
def alerts():
    today = local_today()
    farms = owned_farms()
    selected = record_id(request.args["farm_id"]) if request.args.get("farm_id") else (farms[0].id if farms else None)
    farm = next((item for item in farms if item.id == selected), None)
    if selected and farm is None:
        abort(404)
    forecast, error = weather_for(farm, today) if farm else ((), None)
    crop_checks = []
    irrigation_alert = None
    if farm:
        last_watered = db.session.scalar(db.select(db.func.max(IrrigationEntry.applied_on)).where(
            IrrigationEntry.farm_id == farm.id, IrrigationEntry.crop_id.is_(None),
            IrrigationEntry.applied_on <= today,
        ))
        due, guidance = watering_check(forecast, today, last_watered)
        days = (due - today).days
        timing = {0: "Today", 1: "Tomorrow"}.get(days, f"In {days} days")
        irrigation_alert = dict(day=due, timing=timing, guidance=guidance, last_watered=last_watered)
        query = db.select(Crop, CropCheck).outerjoin(CropCheck).where(Crop.farm_id == farm.id,
                                                                     Crop.stage != "Harvested")
        for crop, check in db.session.execute(query):
            interval = check_interval(crop)
            due = (check.checked_on if check else crop.planted_on or today - timedelta(days=interval)) + timedelta(days=interval)
            crop_checks.append((crop, due, interval))
    crop_checks.sort(key=lambda item: item[1])
    return render_template("alerts.html", farms=farms, selected=selected, forecast=forecast, error=error,
                           outlook=weather_alerts(forecast), checks=crop_checks, today=today,
                           irrigation_alert=irrigation_alert)


@tools.post("/alerts/<int:crop_id>/checked")
def checked(crop_id):
    crop, farm = owned_crop(str(crop_id))
    stamp = local_today()
    query = insert(CropCheck).values(crop_id=crop.id, checked_on=stamp)
    db.session.execute(query.on_conflict_do_update(index_elements=[CropCheck.crop_id],
                                                    set_={"checked_on": stamp}))
    db.session.commit()
    flash("Crop check recorded.", "success")
    return redirect(url_for("farmer_tools.alerts", farm_id=farm.id), 303)
