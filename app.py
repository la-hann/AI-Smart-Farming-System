import os
import click
import requests
import mysql.connector
from mysql.connector import Error
from functools import wraps
from datetime import date
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-this-before-deployment')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true')


def get_db_connection():
    host = os.getenv('MYSQLHOST') or os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('MYSQLPORT') or os.getenv('DB_PORT', '3306'))
    user = os.getenv('MYSQLUSER') or os.getenv('DB_USER', 'root')
    password = os.getenv('MYSQLPASSWORD') or os.getenv('DB_PASSWORD', '')
    database = os.getenv('MYSQLDATABASE') or os.getenv('DB_NAME', 'ai_smart_farming')
    return mysql.connector.connect(host=host, port=port, user=user, password=password, database=database, connection_timeout=10)


def query_db(sql, params=(), one=False, commit=False):
    conn = cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        if commit:
            conn.commit()
            return cur.lastrowid
        return cur.fetchone() if one else cur.fetchall()
    finally:
        if cur:
            cur.close()
        if conn and conn.is_connected():
            conn.close()


def init_db():
    statements = [
        """CREATE TABLE IF NOT EXISTS farmers (
            farmer_id INT AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE, phone VARCHAR(25), password_hash VARCHAR(255) NOT NULL,
            role ENUM('farmer','admin') NOT NULL DEFAULT 'farmer', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS farms (
            farm_id INT AUTO_INCREMENT PRIMARY KEY, farmer_id INT NOT NULL, farm_name VARCHAR(100) NOT NULL,
            location VARCHAR(180) NOT NULL, farm_size DECIMAL(10,2), soil_type VARCHAR(80), irrigation_method VARCHAR(80),
            water_source VARCHAR(80), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS crops (
            crop_id INT AUTO_INCREMENT PRIMARY KEY, farm_id INT NOT NULL, crop_name VARCHAR(100) NOT NULL,
            variety VARCHAR(100), planting_date DATE, expected_harvest DATE, growth_stage VARCHAR(80) DEFAULT 'Seedling',
            health_status VARCHAR(80) DEFAULT 'Healthy', notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farm_id) REFERENCES farms(farm_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS farm_inputs (
            input_id INT AUTO_INCREMENT PRIMARY KEY, farm_id INT NOT NULL, crop_id INT NULL,
            input_type VARCHAR(80) NOT NULL, product_name VARCHAR(120), quantity VARCHAR(80), input_date DATE NOT NULL,
            notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farm_id) REFERENCES farms(farm_id) ON DELETE CASCADE,
            FOREIGN KEY (crop_id) REFERENCES crops(crop_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS disease_cases (
            case_id INT AUTO_INCREMENT PRIMARY KEY, farm_id INT NOT NULL, crop_id INT NULL,
            issue_name VARCHAR(150) NOT NULL, symptoms TEXT, reported_date DATE NOT NULL,
            status ENUM('Reported','Under treatment','Monitoring','Recovered') DEFAULT 'Reported',
            treatment_notes TEXT, resolved_date DATE NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farm_id) REFERENCES farms(farm_id) ON DELETE CASCADE,
            FOREIGN KEY (crop_id) REFERENCES crops(crop_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    ]
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for statement in statements:
            cur.execute(statement)
        # Upgrade the recovered starter database safely if the role column is absent.
        cur.execute("SHOW COLUMNS FROM farmers LIKE 'role'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE farmers ADD COLUMN role ENUM('farmer','admin') NOT NULL DEFAULT 'farmer'")
        for column, definition in [('soil_type', 'VARCHAR(80) NULL'), ('irrigation_method', 'VARCHAR(80) NULL'), ('water_source', 'VARCHAR(80) NULL')]:
            cur.execute(f"SHOW COLUMNS FROM farms LIKE '{column}'")
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE farms ADD COLUMN {column} {definition}")
        conn.commit()
    finally:
        cur.close(); conn.close()


def db_ready():
    try:
        init_db()
        return True
    except Error:
        app.logger.exception('Database initialization failed')
        return False


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please sign in to continue.', 'warning')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get('role') != role:
                flash('You do not have permission to open that page.', 'error')
                return redirect(url_for('home'))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def farmer_farm(farm_id):
    if session.get('role') == 'admin':
        return query_db('SELECT * FROM farms WHERE farm_id=%s', (farm_id,), one=True)
    return query_db('SELECT * FROM farms WHERE farm_id=%s AND farmer_id=%s', (farm_id, session['user_id']), one=True)


@app.context_processor
def inject_template_values():
    return {'now_date': date.today().strftime('%d %B %Y')}


@app.route('/')
def home():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return redirect(url_for('admin_dashboard' if session.get('role') == 'admin' else 'dashboard'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return home()
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        selected_role = request.form.get('role', 'farmer')
        if not email or not password:
            flash('Enter your email and password.', 'error')
        elif not db_ready():
            flash('Database connection is not ready. Check the database setup and environment variables.', 'error')
        else:
            user = query_db('SELECT farmer_id,full_name,email,password_hash,role FROM farmers WHERE email=%s', (email,), one=True)
            if user and user['role'] == selected_role and check_password_hash(user['password_hash'], password):
                session.clear(); session['user_id'] = user['farmer_id']; session['name'] = user['full_name']; session['email'] = user['email']; session['role'] = user['role']
                return home()
            flash('The details do not match an account with the selected role.', 'error')
    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('full_name', '').strip(); email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip(); password = request.form.get('password', '')
        if not name or not email or len(password) < 8 or '@' not in email:
            flash('Enter a name, valid email and password of at least 8 characters.', 'error')
        elif not db_ready():
            flash('Database is not ready. Check your database settings.', 'error')
        else:
            try:
                query_db('INSERT INTO farmers(full_name,email,phone,password_hash,role) VALUES(%s,%s,%s,%s,\'farmer\')', (name,email,phone or None,generate_password_hash(password)), commit=True)
                flash('Farmer account created. You can now sign in.', 'success'); return redirect(url_for('login'))
            except Error as exc:
                flash('That email is already registered.' if exc.errno == 1062 else 'Could not create the account. Check the database connection.', 'error')
    return render_template('signup.html')


@app.route('/dashboard')
@role_required('farmer')
def dashboard():
    farms = query_db('SELECT * FROM farms WHERE farmer_id=%s ORDER BY created_at DESC', (session['user_id'],))
    stats = query_db('SELECT (SELECT COUNT(*) FROM farms WHERE farmer_id=%s) farms, (SELECT COUNT(*) FROM crops c JOIN farms f ON c.farm_id=f.farm_id WHERE f.farmer_id=%s) crops, (SELECT COUNT(*) FROM disease_cases d JOIN farms f ON d.farm_id=f.farm_id WHERE f.farmer_id=%s AND d.status<>\'Recovered\') active_cases', (session['user_id'],session['user_id'],session['user_id']), one=True)
    cases = query_db('SELECT d.*,f.farm_name,c.crop_name FROM disease_cases d JOIN farms f ON d.farm_id=f.farm_id LEFT JOIN crops c ON d.crop_id=c.crop_id WHERE f.farmer_id=%s ORDER BY d.reported_date DESC LIMIT 5', (session['user_id'],))
    return render_template('dashboard.html', farms=farms, stats=stats, cases=cases)


@app.route('/farms', methods=['GET','POST'])
@role_required('farmer')
def farms_page():
    if request.method == 'POST':
        name=request.form.get('farm_name','').strip(); location=request.form.get('location','').strip()
        if not name or not location: flash('Farm name and location are required.','error')
        else:
            query_db('INSERT INTO farms(farmer_id,farm_name,location,farm_size,soil_type,irrigation_method,water_source) VALUES(%s,%s,%s,%s,%s,%s,%s)', (session['user_id'],name,location,request.form.get('farm_size') or None,request.form.get('soil_type') or None,request.form.get('irrigation_method') or None,request.form.get('water_source') or None),commit=True)
            flash('Farm saved.','success'); return redirect(url_for('farms_page'))
    farms=query_db('SELECT * FROM farms WHERE farmer_id=%s ORDER BY created_at DESC',(session['user_id'],))
    return render_template('farms.html',farms=farms)


@app.route('/crops', methods=['GET','POST'])
@role_required('farmer')
def crops_page():
    farms=query_db('SELECT * FROM farms WHERE farmer_id=%s',(session['user_id'],))
    if request.method=='POST':
        farm=farmer_farm(request.form.get('farm_id'))
        if not farm or not request.form.get('crop_name','').strip(): flash('Choose one of your farms and enter a crop name.','error')
        else:
            query_db('INSERT INTO crops(farm_id,crop_name,variety,planting_date,expected_harvest,growth_stage,health_status,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(farm['farm_id'],request.form['crop_name'].strip(),request.form.get('variety') or None,request.form.get('planting_date') or None,request.form.get('expected_harvest') or None,request.form.get('growth_stage') or 'Seedling',request.form.get('health_status') or 'Healthy',request.form.get('notes') or None),commit=True)
            flash('Crop record saved.','success'); return redirect(url_for('crops_page'))
    crops=query_db('SELECT c.*,f.farm_name FROM crops c JOIN farms f ON c.farm_id=f.farm_id WHERE f.farmer_id=%s ORDER BY c.created_at DESC',(session['user_id'],))
    return render_template('crops.html',farms=farms,crops=crops)


@app.route('/inputs', methods=['GET','POST'])
@role_required('farmer')
def inputs_page():
    farms=query_db('SELECT * FROM farms WHERE farmer_id=%s',(session['user_id'],))
    crops=query_db('SELECT c.crop_id,c.crop_name,c.farm_id FROM crops c JOIN farms f ON c.farm_id=f.farm_id WHERE f.farmer_id=%s',(session['user_id'],))
    if request.method=='POST':
        farm=farmer_farm(request.form.get('farm_id')); crop_id=request.form.get('crop_id') or None
        if not farm or not request.form.get('input_type') or not request.form.get('input_date'): flash('Complete the required input details.','error')
        else:
            if crop_id and not query_db('SELECT crop_id FROM crops WHERE crop_id=%s AND farm_id=%s',(crop_id,farm['farm_id']),one=True): crop_id=None
            query_db('INSERT INTO farm_inputs(farm_id,crop_id,input_type,product_name,quantity,input_date,notes) VALUES(%s,%s,%s,%s,%s,%s,%s)',(farm['farm_id'],crop_id,request.form['input_type'],request.form.get('product_name') or None,request.form.get('quantity') or None,request.form['input_date'],request.form.get('notes') or None),commit=True)
            flash('Farm input recorded.','success'); return redirect(url_for('inputs_page'))
    logs=query_db('SELECT i.*,f.farm_name,c.crop_name FROM farm_inputs i JOIN farms f ON i.farm_id=f.farm_id LEFT JOIN crops c ON i.crop_id=c.crop_id WHERE f.farmer_id=%s ORDER BY i.input_date DESC',(session['user_id'],))
    return render_template('inputs.html',farms=farms,crops=crops,logs=logs,today=date.today().isoformat())


@app.route('/diseases', methods=['GET','POST'])
@role_required('farmer')
def diseases_page():
    farms=query_db('SELECT * FROM farms WHERE farmer_id=%s',(session['user_id'],))
    crops=query_db('SELECT c.crop_id,c.crop_name,c.farm_id FROM crops c JOIN farms f ON c.farm_id=f.farm_id WHERE f.farmer_id=%s',(session['user_id'],))
    if request.method=='POST':
        farm=farmer_farm(request.form.get('farm_id')); crop_id=request.form.get('crop_id') or None
        if not farm or not request.form.get('issue_name','').strip() or not request.form.get('reported_date'): flash('Choose your farm and enter the issue and report date.','error')
        else:
            if crop_id and not query_db('SELECT crop_id FROM crops WHERE crop_id=%s AND farm_id=%s',(crop_id,farm['farm_id']),one=True): crop_id=None
            query_db('INSERT INTO disease_cases(farm_id,crop_id,issue_name,symptoms,reported_date) VALUES(%s,%s,%s,%s,%s)',(farm['farm_id'],crop_id,request.form['issue_name'].strip(),request.form.get('symptoms') or None,request.form['reported_date']),commit=True)
            flash('Crop health case recorded. Update its progress as the crop recovers.','success'); return redirect(url_for('diseases_page'))
    cases=query_db('SELECT d.*,f.farm_name,c.crop_name,DATEDIFF(COALESCE(d.resolved_date,CURDATE()),d.reported_date) AS days_open FROM disease_cases d JOIN farms f ON d.farm_id=f.farm_id LEFT JOIN crops c ON d.crop_id=c.crop_id WHERE f.farmer_id=%s ORDER BY d.reported_date DESC',(session['user_id'],))
    return render_template('diseases.html',farms=farms,crops=crops,cases=cases,today=date.today().isoformat())


@app.route('/diseases/<int:case_id>/update', methods=['POST'])
@role_required('farmer')
def update_case(case_id):
    case=query_db('SELECT d.case_id,d.farm_id FROM disease_cases d JOIN farms f ON d.farm_id=f.farm_id WHERE d.case_id=%s AND f.farmer_id=%s',(case_id,session['user_id']),one=True)
    if not case: flash('Case not found.','error')
    else:
        status=request.form.get('status','Reported')
        if status not in ['Reported','Under treatment','Monitoring','Recovered']: status='Reported'
        resolved=date.today().isoformat() if status=='Recovered' else None
        query_db('UPDATE disease_cases SET status=%s,treatment_notes=%s,resolved_date=%s WHERE case_id=%s',(status,request.form.get('treatment_notes') or None,resolved,case_id),commit=True)
        if status=='Recovered': query_db("UPDATE crops SET health_status='Healthy' WHERE crop_id=(SELECT crop_id FROM disease_cases WHERE case_id=%s) AND crop_id IS NOT NULL",(case_id,),commit=True)
        flash('Crop health progress updated.','success')
    return redirect(url_for('diseases_page'))


@app.route('/weather', methods=['GET','POST'])
@role_required('farmer')
def weather_page():
    farms=query_db('SELECT * FROM farms WHERE farmer_id=%s',(session['user_id'],))
    report=None; error_message=None
    selected=request.values.get('farm_id','')
    if request.method=='POST' and selected:
        farm=farmer_farm(selected)
        if farm:
            try:
                geo=requests.get('https://geocoding-api.open-meteo.com/v1/search',params={'name':farm['location'],'count':1,'language':'en','format':'json'},timeout=12).json()
                results=geo.get('results') or []
                if not results: error_message='Could not find that farm location. Try a nearby town or county name in Farm Management.'
                else:
                    place=results[0]
                    weather=requests.get('https://api.open-meteo.com/v1/forecast',params={'latitude':place['latitude'],'longitude':place['longitude'],'current':'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m','daily':'precipitation_probability_max,temperature_2m_max,temperature_2m_min','forecast_days':3,'timezone':'auto'},timeout=12).json()
                    report={'place':', '.join(x for x in [place.get('name'),place.get('admin1'),place.get('country')] if x),'current':weather.get('current',{}),'daily':weather.get('daily',{})}
            except (requests.RequestException,ValueError,KeyError): error_message='Weather service is temporarily unavailable. Please try again.'
    return render_template('weather.html',farms=farms,report=report,error_message=error_message,selected=selected)


@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    stats=query_db('SELECT (SELECT COUNT(*) FROM farmers WHERE role=\'farmer\') farmers,(SELECT COUNT(*) FROM farms) farms,(SELECT COUNT(*) FROM crops) crops,(SELECT COUNT(*) FROM disease_cases WHERE status<>\'Recovered\') active_cases',one=True)
    recent=query_db("SELECT farmer_id,full_name,email,created_at FROM farmers WHERE role='farmer' ORDER BY created_at DESC LIMIT 12")
    cases=query_db('SELECT d.*,f.farm_name,u.full_name,c.crop_name FROM disease_cases d JOIN farms f ON d.farm_id=f.farm_id JOIN farmers u ON f.farmer_id=u.farmer_id LEFT JOIN crops c ON d.crop_id=c.crop_id ORDER BY d.reported_date DESC LIMIT 10')
    return render_template('admin.html',stats=stats,recent=recent,cases=cases)


@app.route('/logout',methods=['POST'])
@login_required
def logout():
    session.clear(); flash('You have signed out.','success'); return redirect(url_for('login'))


@app.cli.command('create-admin')
@click.option('--name', prompt='Administrator full name')
@click.option('--email', prompt='Administrator email')
@click.password_option()
def create_admin(name,email,password):
    """Create an administrator account from the server terminal (never public signup)."""
    init_db()
    query_db("INSERT INTO farmers(full_name,email,password_hash,role) VALUES(%s,%s,%s,'admin')",(name,email.strip().lower(),generate_password_hash(password)),commit=True)
    click.echo('Administrator account created.')


@app.errorhandler(404)
def not_found(_error):
    return render_template('404.html'),404


if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=os.getenv('FLASK_DEBUG','false').lower()=='true')
