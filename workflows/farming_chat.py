import os
import re

import requests
from .request_limits import permit_request

GUIDES = (
    (r"irrigat\w*|water\w*|drought|wilting|drip",
     "Check soil moisture in the root zone before watering. If the soil is dry and little rain is expected, water near the roots early in the day. Log the litres used under Irrigation and use AI recommendation to estimate the next amount."),
    (r"pest\w*|aphid\w*|worm\w*|insect\w*|caterpillar\w*",
     "Inspect several plants, including the undersides of leaves, and photograph the insect and damage. Note how many plants are affected. Ask an extension officer to identify the pest before selecting a control method."),
    (r"disease\w*|spot\w*|rust|blight|fung\w*|yellow\w*",
     "Check several plants and note where symptoms started, which leaves are affected, and whether the soil is dry or waterlogged. For maize, use the Crop disease scanner with a clear photo. Ask your extension officer to confirm persistent or spreading symptoms."),
    (r"fertili\w*|compost|manure|nutrient\w*|soil test",
     "Start with a soil test so you can match nutrients to the crop and soil. Keep a record of previous fertilizer and compost applications. Ask for a crop-specific local rate before adding more, especially when plants are already stressed."),
    (r"seed\w*|plant\w*|spacing|germinat\w*",
     "Choose seed adapted to your local season and check the supplier instructions for spacing and planting depth. Plant into a moist, well-drained seedbed and check for even emergence. Share your crop and location with an extension officer for local planting dates."),
    (r"rain\w*|weather|wind\w*|heat\w*|flood\w*",
     "Check Weather and Alerts for your saved farm. Before heavy rain, clear drainage channels where appropriate. During hot weather, check root-zone moisture early. In strong winds, check crop supports and postpone spraying."),
    (r"harvest\w*|stor\w*|drying",
     "Use crop-specific maturity signs and inspect several plants before harvesting. Keep harvested produce clean and separate damaged items. For grain, confirm the safe moisture level for your crop and storage method before bagging."),
)


def guide_for(question):
    words = question.casefold()
    matches = [advice for pattern, advice in GUIDES if re.search(r"\b(?:" + pattern + r")\b", words)]
    return "\n\n".join(matches[:2])


def generated_answer(question, key):
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "systemInstruction": {"parts": [{"text": (
                "You are a farming help assistant for beginners, mainly in Kenya. Answer only farming questions in "
                "the user's language, with brief practical steps. State uncertainty. Never invent live forecasts, "
                "diagnoses, local approvals, chemical rates, or precise irrigation doses. Refer those decisions "
                "to the app's tools and a local agricultural extension officer. Ask for crop and growth stage "
                "if required. Do not request personal details. Reply in plain text."
            )}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "generationConfig": {"maxOutputTokens": 450},
        },
        timeout=(3, 12),
    )
    response.raise_for_status()
    candidates = response.json().get("candidates", [])
    if not candidates:
        return ""
    return "\n".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", [])
                     if not part.get("thought")).strip()


def chat_context(question=None, user_id=None):
    key = os.environ.get("GEMINI_API_KEY")
    answer = error = None
    generated = False
    if question is not None:
        question = question.strip()
        if not 3 <= len(question) <= 600:
            error = "Enter a farming question between 3 and 600 characters."
        else:
            if key:
                if permit_request("farming-chat", user_id, 8):
                    try:
                        answer = generated_answer(question, key)
                    except (requests.RequestException, ValueError, TypeError, KeyError):
                        pass
                generated = bool(answer)
            if not generated:
                answer = guide_for(question)
                if not answer:
                    error = "The built-in guide could not match that question. Try a topic such as watering, pests, soil, planting, or harvest."
    return dict(question=question, answer=answer, error=error, generated=generated, configured=bool(key))
