from datetime import timedelta


STORMS = {95, 96, 97, 99}
CONDITIONS = {
    0: "Clear skies",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Rain showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorms",
    96: "Thunderstorms with hail",
    97: "Strong thunderstorms",
    99: "Thunderstorms with heavy hail",
}


def rain_expected(rain, chance):
    return (rain is not None and rain >= 3) or (chance is not None and chance >= 65)


def forecast_guidance(daily):
    def daily_value(key, index):
        values = daily.get(key) or []
        return values[index] if index < len(values) else None

    outlook = []
    for index, _ in enumerate(daily.get("time") or []):
        code = daily_value("weather_code", index)
        rain = daily_value("precipitation_sum", index)
        chance = daily_value("precipitation_probability_max", index)
        temperature = daily_value("temperature_2m_max", index)
        gust = daily_value("wind_gusts_10m_max", index)
        actions = []
        if code in STORMS:
            actions.append("Plan field checks around the storms. Stay out of fields while thunder is present.")
        if (rain is not None and rain >= 10) or code in (65, 82):
            actions.append("Check drainage before the rain. Check the root zone after rain before irrigating.")
        elif rain_expected(rain, chance):
            actions.append("If the root zone is still moist, wait for the rain and check the soil again afterwards.")
        if temperature is not None and temperature >= 32:
            actions.append("Check soil moisture early. If the root zone is dry, water near the roots in the cooler part of the day.")
        if gust is not None and gust >= 45:
            actions.append("Secure crop supports and avoid spraying during strong winds.")
        if not actions:
            actions.append("Check moisture near the roots. Water if the root zone is dry and no useful rain is expected.")
        outlook.append({"condition": CONDITIONS.get(code, "Condition unavailable"), "actions": actions})
    return outlook


def watering_check(forecast, today, last_watered):
    if not forecast:
        return today, "The forecast is unavailable. Check soil moisture and the latest local forecast before watering."

    recently_watered = last_watered == today
    first_check = today + timedelta(days=1) if recently_watered else today
    eligible = [day for day in forecast if day[0] >= first_check]
    for day, _, rain, chance, *_ in eligible:
        if not rain_expected(rain, chance):
            if day > first_check:
                reason = "Rain is forecast before this date. Check again after the rain and water only if the root zone is dry."
            elif recently_watered:
                reason = "Whole-farm irrigation was logged today. Check the root zone before adding more water."
            else:
                reason = "Little rain is forecast for this day. Check the root zone and water if it is dry."
            return day, reason
    return forecast[-1][0] + timedelta(days=1), (
        "Rain is possible on the remaining forecast days. Check the soil after rain and review a fresh forecast on this date."
    )
