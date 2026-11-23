# Smart Farming

A Flask and Jinja app for farmer accounts, farm and crop records, input logs,
manual crop health tracking, and weather forecasts. SQLite stores shared data
in `instance/smart_farming.sqlite3` on the same host as the app.

## PythonAnywhere Free

Create a free Beginner account. Upload and extract the deployment ZIP into
`~/smart-farming`, or clone the deployment branch there if it is on GitHub.
In a PythonAnywhere Bash console, run:

```bash
cd ~/smart-farming
python3.13 -m venv ~/.virtualenvs/smart-farming
source ~/.virtualenvs/smart-farming/bin/activate
python -m pip install -r requirements.txt
(umask 077; set -o noclobber; python -c 'import secrets; print("APP_ENV=production"); print("SECRET_KEY=" + secrets.token_urlsafe(48))' > .env)
python -m flask --app app db upgrade
python -m flask --app app create-admin
```

In the **Web** tab, create a web app using **Manual configuration** and
**Python 3.13**. Set its virtualenv to `/home/YOUR_USERNAME/.virtualenvs/smart-farming`.
Replace the contents of the WSGI file linked on the Web tab with:

```python
from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / "smart-farming"))
from pythonanywhere_wsgi import application
```

Enable **Force HTTPS**, reload the web app, and visit its public URL.
`/healthz` should return `{"status":"ok"}`. Check the expiry date in the Web tab.
When updating the code, preserve `.env` and the `instance` directory, apply
migrations, and reload the web app. Existing PostgreSQL or MySQL records
require a separate import. Keep a downloadable backup using SQLite's
online backup command:

```bash
sqlite3 instance/smart_farming.sqlite3 ".backup /home/$(whoami)/smart-farming-backup.sqlite3"
```

See the [PythonAnywhere Flask guide](https://help.pythonanywhere.com/pages/Flask/)
and [free account limits](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/).

## Run locally on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set `SECRET_KEY` in `.env` to the generated value. Run:

```powershell
.\.venv\Scripts\python -m flask --app app db upgrade
.\.venv\Scripts\python -m flask --app app run
```

Open http://127.0.0.1:5000. To run the integration suite against a temporary
SQLite file, use `python -m unittest -v` from the virtual environment.

## Maize leaf analysis

Farmers open **Crop health tracking** and choose **Analyse a maize leaf photo**
inside that dashboard.
The browser runs MobileNetV2 with ONNX Runtime Web (1.22.0). No photo is sent
to the server. The first analysis downloads the model and runtime.

The ONNX export uses the Apache 2.0
[PlantVillage MobileNetV2 checkpoint](https://huggingface.co/neghani/plantvillage-mobilenetv2/tree/d33601185b32cf05b3942661b8d84ffb86dc48ec).
The model takes a centre-cropped 224 by 224 RGB tensor scaled to [-1, 1] and
outputs 38 logits. The app reports only the four maize classes and declines
predictions below 0.75 after the source checkpoint's temperature scaling.
This threshold is a screening choice and has not been validated on Kenyan
farms. Management guidance links to university extension references.

## Farmer dashboards

**Farm management** contains farm records and the farm input log.
**AI Recommendations** contains both the water estimate and the
farming question form.

- **Irrigation** records litres or cubic metres by crop and date. The total
  includes all matching records, and the history shows the latest 50 entries.
- **AI Recommendations** uses a saved plot size and application efficiency,
  three days of Open-Meteo reference evapotranspiration and forecast rain,
  the crop and growth stage, and irrigation logged today. Water figures are
  planning estimates, with crop coefficients informed by
  [FAO-56](https://www.fao.org/4/X0490E/x0490e0b.htm).
- **Farm Alerts** shows the selected farm's forecast and crop-check reminders
  every 3, 7, or 14 days, depending on crop stage and health. Reminders are
  displayed in the app.
- **AI Chatbot** answers common questions from the built-in guide. For
  open-ended answers, add `GEMINI_API_KEY` to the private server `.env`
  and reload the web app. Use a
  [Gemini free-tier project](https://ai.google.dev/gemini-api/docs/pricing)
  with billing disabled if the deployment must cost KSh 0. Only the
  submitted question is sent to Gemini, and questions are not stored by
  this app. A local guide remains available if the service returns an error.
