from datetime import date, datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    phone = db.Column(db.String(25))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)


class Farm(db.Model):
    __tablename__ = "farms"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(180), nullable=False)
    area = db.Column(db.Numeric(12, 2))
    soil = db.Column(db.String(80))
    irrigation = db.Column(db.String(80))
    water_source = db.Column(db.String(80))

    __table_args__ = (CheckConstraint("area > 0", name="positive_farm_area"),)


class Crop(db.Model):
    __tablename__ = "crops"

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.ForeignKey("farms.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    variety = db.Column(db.String(100))
    planted_on = db.Column(db.Date)
    harvest_on = db.Column(db.Date)
    notes = db.Column(db.Text)
    stage = db.Column(db.String(32), nullable=False)
    health = db.Column(db.String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "farm_id"),
        CheckConstraint("harvest_on >= planted_on", name="harvest_after_planting"),
    )


class InputLog(db.Model):
    __tablename__ = "farm_inputs"

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.ForeignKey("farms.id"), nullable=False, index=True)
    crop_id = db.Column(db.Integer)
    category = db.Column(db.String(40), nullable=False)
    product = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.String(80))
    applied_on = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)

    __table_args__ = (ForeignKeyConstraint(("crop_id", "farm_id"), ("crops.id", "crops.farm_id")),)


CASE_STATUSES = ("Reported", "Under treatment", "Monitoring", "Recovered")


class HealthCase(db.Model):
    __tablename__ = "health_cases"

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.ForeignKey("farms.id"), nullable=False, index=True)
    crop_id = db.Column(db.Integer)
    title = db.Column(db.String(150), nullable=False)
    symptoms = db.Column(db.Text, nullable=False)
    reported_on = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(32), nullable=False, default="Reported")
    recovered_on = db.Column(db.Date)

    __table_args__ = (
        ForeignKeyConstraint(("crop_id", "farm_id"), ("crops.id", "crops.farm_id")),
        CheckConstraint(
            "(status = 'Recovered' AND recovered_on IS NOT NULL) OR "
            "(status IN ('Reported', 'Under treatment', 'Monitoring') AND recovered_on IS NULL)",
            name="valid_health_status",
        ),
    )


class HealthUpdate(db.Model):
    __tablename__ = "health_updates"

    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.ForeignKey("health_cases.id"), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False)
    notes = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    key = db.Column(db.String(64), primary_key=True)
    window = db.Column(db.BigInteger, primary_key=True)
    attempts = db.Column(db.Integer, nullable=False)


class IrrigationEntry(db.Model):
    __tablename__ = "irrigation_entries"

    id = db.Column(db.Integer, primary_key=True)
    crop_id = db.Column(db.ForeignKey("crops.id"), nullable=False, index=True)
    applied_on = db.Column(db.Date, nullable=False)
    litres = db.Column(db.Numeric(14, 3), nullable=False)

    __table_args__ = (CheckConstraint("litres > 0", name="positive_irrigation_volume"),)


class CropCheck(db.Model):
    __tablename__ = "crop_checks"

    crop_id = db.Column(db.ForeignKey("crops.id"), primary_key=True)
    checked_on = db.Column(db.Date, nullable=False)


class IrrigationPlan(db.Model):
    __tablename__ = "irrigation_plans"

    crop_id = db.Column(db.ForeignKey("crops.id"), primary_key=True)
    acres = db.Column(db.Numeric(9, 3), nullable=False)
    efficiency = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("acres > 0", name="positive_irrigated_area"),
        CheckConstraint("efficiency BETWEEN 30 AND 100", name="valid_irrigation_efficiency"),
    )
