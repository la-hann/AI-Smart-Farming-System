from collections import defaultdict
from datetime import date

from sqlalchemy import func, literal, union_all

from .farmer_tools import local_today
from models import Crop, Farm, HealthCase, HealthUpdate, InputLog, IrrigationEntry, User, db


ACTIVITY_LABELS = ("Plantings", "Farm inputs", "Irrigation entries", "Health reports", "Health updates")
MONTH_COUNT = 6


def recent_months(today):
    current_month = today.year * 12 + today.month - 1
    return [
        date(index // 12, index % 12 + 1, 1)
        for index in range(current_month - MONTH_COUNT + 1, current_month + 1)
    ]


def farm_activity():
    today = local_today()
    months = recent_months(today)
    # Crop health updates are stored in UTC. Group them by the Kenyan calendar date.
    sources = (
        (Crop.farm_id, Crop.planted_on, Crop.__table__),
        (InputLog.farm_id, InputLog.applied_on, InputLog.__table__),
        (IrrigationEntry.farm_id, IrrigationEntry.applied_on, IrrigationEntry.__table__),
        (HealthCase.farm_id, HealthCase.reported_on, HealthCase.__table__),
        (HealthCase.farm_id, func.date(HealthUpdate.created_at, "+3 hours"),
         HealthUpdate.__table__.join(HealthCase.__table__)),
    )
    activity = union_all(*(
        db.select(farm_id.label("farm_id"), func.strftime("%Y-%m", day).label("month"),
                  literal(category).label("category"), func.count().label("entries"))
        .select_from(table).where(day.between(months[0], today))
        .group_by(farm_id, func.strftime("%Y-%m", day))
        for category, (farm_id, day, table) in enumerate(sources)
    ))
    counts = defaultdict(dict)
    for farm_id, month, category, entries in db.session.execute(activity):
        counts[farm_id, month][category] = entries

    farms = db.session.execute(db.select(Farm.name, Farm.id, User.name)
                               .join(User, Farm.owner_id == User.id)
                               .order_by(Farm.name, User.name, Farm.id))
    charts = []
    for farm, farm_id, farmer in farms:
        rows = []
        for month in months:
            by_category = counts.get((farm_id, month.strftime("%Y-%m")), {})
            values = [by_category.get(category, 0) for category in range(len(ACTIVITY_LABELS))]
            rows.append(dict(month=month.strftime("%b %Y"), total=sum(values), values=values))
        charts.append(dict(farm=farm, farmer=farmer, months=rows))
    maximum = max((row["total"] for chart in charts for row in chart["months"]), default=0)
    return charts, max(1, maximum)
