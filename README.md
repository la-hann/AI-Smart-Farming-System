# Smart Farming

A Flask and Jinja app for farmer accounts, farm and crop records, input logs,
manual crop health tracking, and forecasts for registered farm locations.
Administrators have a separate summary dashboard. PostgreSQL stores shared data.

## Local setup

Create an empty PostgreSQL database named `smart_farming`. From the repository
on Windows, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `SECRET_KEY` inside `.env` and set `DATABASE_URL`
to your database connection string. Then run:

```powershell
.\.venv\Scripts\python -m flask --app app db upgrade
.\.venv\Scripts\python -m flask --app app run
```

Open http://127.0.0.1:5000. Register a farmer account in the browser. To create
a separate administrator, run `python -m flask --app app create-admin` from
the same virtual environment.

The migration creates a PostgreSQL schema for the rewrite. Existing MySQL data
would need a separate import before switching an installation with live records.

## Railway deployment

1. Deploy the repo as a web service using the Dockerfile and add a PostgreSQL service.
2. Set the web service's `DATABASE_URL` to reference the PostgreSQL service. Set
   `APP_ENV=production` and supply a unique, randomly generated `SECRET_KEY`.
3. Set the pre-deploy command to `flask --app app db upgrade` and the healthcheck
   path to `/healthz`.
4. Generate an HTTPS domain. Set `TRUSTED_PROXY_HOPS=1` when the app receives
   forwarded headers from a single trusted edge proxy and cannot be reached by
   untrusted clients that bypass it. Adjust the value to your deployment's
   verified proxy topology.
5. Create the admin through the web service's shell with
   `flask --app app create-admin`. Enable PostgreSQL backups before onboarding users.

The Gunicorn command reads the platform-provided `PORT`. Configure
`WEB_CONCURRENCY` to adjust the number of worker processes. Login limits are
stored in PostgreSQL so they apply across workers.

## Verification

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database URL with permission
to create schemas, then run `python -m unittest -v`. The suite uses its own
temporary schema and applies the checked-in migration.
