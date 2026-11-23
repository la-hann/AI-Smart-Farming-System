AI-DRIVEN SMART FARMING SYSTEM — RAILWAY-READY FLASK + MYSQL PROJECT
====================================================================

WHAT THIS RECOVERED PROJECT NOW CONTAINS
----------------------------------------
- Flask application with farmer sign-up and sign-in.
- Separate farmer and administrator login selection.
- Admin accounts are created only from the server command line; public
  registration cannot create an administrator.
- Farmer dashboard with farm, crop and active crop-health case totals.
- Farm registration (location, size, soil type, irrigation and water source).
- Crop records (variety, planting date, expected harvest, growth stage and
  health status).
- Farm input log (fertiliser, seeds, pesticides, irrigation, labour, etc.).
- Crop health case register with report date, symptoms, treatment notes,
  status progression and recovery date.
- Weather lookup by saved farm location using Open-Meteo geocoding and forecast.
- MySQL database tables are created automatically at app startup. Existing
  recovered farmers/farms tables are upgraded with the missing role/farm fields.
- Responsive emerald-green and burgundy interface.
- Railway deployment configuration (Procfile and railway.json).
- Root index.html redirect for the hosted app's /login route.

IMPORTANT FEATURE LIMITATIONS
-----------------------------
The ZIP available in the previous conversation did not contain the original
trained crop-disease model, model.py, class_names.json, or the complete original
AI/chatbot/irrigation modules. This rebuilt version therefore records crop
health cases and their recovery progress, but it does NOT perform automatic
image-based disease diagnosis. Weather is live external data; there is no
trained AI model in this recovered archive. Do not describe the manual health
register as AI diagnosis in a project demonstration.

RUN LOCALLY ON WINDOWS
----------------------
1. Extract the ZIP and open the extracted folder in VS Code.
2. Open the VS Code terminal in that folder.
3. Install dependencies:
      py -m pip install -r requirements.txt
   If py is unavailable, use python instead.
4. Start your local MySQL Server and execute database.sql in MySQL Workbench.
   (The app also creates/upgrades its tables when it starts.)
5. Copy .env.example to a new file named .env and enter your local MySQL
   password in DB_PASSWORD. Replace SECRET_KEY with a long random value.
6. Run:
      py app.py
7. Open http://127.0.0.1:5000/login in Chrome or Edge.
8. Register a farmer account, then sign in as Farmer.
9. To create the first administrator, run this in another terminal in the
   same folder (with the database configured and reachable):
      py -m flask --app app create-admin
   Follow the prompts. Then sign out and choose Administrator on the login
   page. Never share the admin password or commit the .env file.

RAILWAY HOSTING — WEB APP + MYSQL DATABASE
------------------------------------------
This ZIP is prepared for Railway, but it has NOT been connected to a Railway
account or database. You must create the Railway project in your own account;
we cannot create a hosted database without your account authorization and
service credentials.

A. Put the project in a GitHub repository
   - Extract this ZIP.
   - Create a private GitHub repository for the project.
   - Upload the project files, excluding .env, __pycache__ and local secrets.

B. Create the Railway project and MySQL service
   - In Railway, create a new project and deploy the repository as a service.
   - Add a MySQL database service to the same Railway project.
   - Open the web service's Variables settings.
   - Add SECRET_KEY with a long unique random value.
   - Add COOKIE_SECURE=true.
   - Add the MySQL service's reference variables to the web service:
       MYSQLHOST
       MYSQLPORT
       MYSQLUSER
       MYSQLPASSWORD
       MYSQLDATABASE
     Use Railway's variable-reference picker to reference the matching values
     from the MySQL service. Do not paste database passwords into source code.
   - The Flask app reads those MYSQL* variables automatically. It also
     supports DB_HOST, DB_PORT, DB_USER, DB_PASSWORD and DB_NAME for local use.
   - Deploy/redeploy the web service. The app creates its required tables on
     first successful database connection.
   - Generate a public domain for the web service in Railway's networking
     settings. Open that HTTPS URL; the app will send you to /login.

C. Create the administrator after the first deployment
   - Open the Railway web service shell/command console.
   - Run:
       flask --app app create-admin
   - Follow the prompts to set the administrator's name, email and password.
   - Sign in at your public app URL and choose Administrator.

DATABASE HOSTING NOTES
----------------------
- The MySQL service is the persistent hosted database; do not use SQLite or a
  local database for the public deployment.
- Keep the web service and MySQL service in the same Railway project and use
  private service-reference variables where offered.
- Never commit .env or publish database credentials.
- Configure backups in the database provider and keep a separate export before
  major schema changes.
- If the app reports a database connection error, verify the five MYSQL*
  variables are set on the WEB SERVICE and redeploy it.

ABOUT index.html AND VS CODE LIVE SERVER
----------------------------------------
The included root index.html redirects to /login on the same host. It does not
make Flask run by itself. Do not open the file with Live Server to test the
backend. Run `py app.py` and open http://127.0.0.1:5000 locally, or use the
public Railway HTTPS URL after deployment. The Flask app serves the templates,
login sessions and database routes.

WEATHER
-------
The weather page uses Open-Meteo's public geocoding and forecast endpoints.
Enter a town, county or recognised place in the farm's location field. Weather
lookups require an internet connection. Forecast values are planning guidance,
not a substitute for local observation.

SECURITY
--------
- Passwords are stored as Werkzeug password hashes.
- Admin access is assigned through a server-side CLI command, never a public
  role selector at registration.
- Farmer queries are restricted to farms belonging to the signed-in farmer.
- Use HTTPS in production and set COOKIE_SECURE=true.
- Change SECRET_KEY before deployment and keep credentials out of GitHub.
