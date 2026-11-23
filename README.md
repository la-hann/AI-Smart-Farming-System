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
