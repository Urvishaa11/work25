import base64
import json
import mimetypes
import os
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

# Try to load environment variables from .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_FILE = DATA_DIR / 'work24_data.json'
DB_FILE = DATA_DIR / 'work24.db'
SCHEMA_VERSION = 3

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()
    
    # Create tables
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS configs (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT UNIQUE,
            password_hash TEXT,
            profile_image TEXT,
            category TEXT,
            location TEXT,
            experience TEXT,
            status TEXT,
            created_at TEXT,
            approved_at TEXT,
            work_images TEXT
        );
        CREATE TABLE IF NOT EXISTS sellers (
            id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT UNIQUE,
            password_hash TEXT,
            profile_image TEXT,
            business_name TEXT,
            location TEXT,
            description TEXT,
            status TEXT,
            created_at TEXT,
            approved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY,
            seller_id TEXT,
            title TEXT,
            title_slug TEXT,
            category TEXT,
            description TEXT,
            price TEXT,
            image TEXT,
            created_at TEXT,
            FOREIGN KEY (seller_id) REFERENCES sellers (id)
        );
        CREATE TABLE IF NOT EXISTS architect_requests (
            id TEXT PRIMARY KEY,
            company_name TEXT,
            project_type TEXT,
            location TEXT,
            budget TEXT,
            message TEXT,
            status TEXT,
            created_at TEXT,
            completed_at TEXT,
            design_images TEXT
        );
    ''')
    
    # Check if we need to migrate from JSON
    cursor.execute("SELECT count(*) FROM configs WHERE key = 'schema_version'")
    if cursor.fetchone()[0] == 0:
        migrate_json_to_sqlite()
        cursor.execute("INSERT INTO configs (key, value) VALUES (?, ?)", ('schema_version', str(SCHEMA_VERSION)))
        
    conn.commit()
    conn.close()

def migrate_json_to_sqlite():
    if not DATA_FILE.exists():
        # Inject default data if no JSON exists
        data = default_data()
    else:
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            data = default_data()
            
    conn = get_db()
    cursor = conn.cursor()
    
    # Configs
    cursor.execute("INSERT OR REPLACE INTO configs (key, value) VALUES (?, ?)", ('admin_contact', json.dumps(data.get('admin_contact', {}))))
    cursor.execute("INSERT OR REPLACE INTO configs (key, value) VALUES (?, ?)", ('admin_credentials', json.dumps(data.get('admin_credentials', {}))))
    cursor.execute("INSERT OR REPLACE INTO configs (key, value) VALUES (?, ?)", ('worker_categories', json.dumps(data.get('worker_categories', []))))
    cursor.execute("INSERT OR REPLACE INTO configs (key, value) VALUES (?, ?)", ('material_categories', json.dumps(data.get('material_categories', []))))
    
    # Workers
    for w in data.get('workers', []):
        cursor.execute('''INSERT OR REPLACE INTO workers 
            (id, name, phone, password_hash, profile_image, category, location, experience, status, created_at, approved_at, work_images) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
            (w['id'], w['name'], w['phone'], w['password_hash'], w['profile_image'], w['category'], w['location'], w['experience'], w['status'], w['created_at'], w.get('approved_at', ''), json.dumps(w.get('work_images', []))))
            
    # Sellers
    for s in data.get('sellers', []):
        cursor.execute('''INSERT OR REPLACE INTO sellers 
            (id, name, phone, password_hash, profile_image, business_name, location, description, status, created_at, approved_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
            (s['id'], s['name'], s['phone'], s['password_hash'], s['profile_image'], s['business_name'], s['location'], s['description'], s['status'], s['created_at'], s.get('approved_at', '')))
            
    # Materials
    for m in data.get('materials', []):
        cursor.execute('''INSERT OR REPLACE INTO materials 
            (id, seller_id, title, title_slug, category, description, price, image, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
            (m['id'], m['seller_id'], m['title'], m['title_slug'], m['category'], m['description'], m['price'], m['image'], m['created_at']))
            
    # Architect Requests
    for r in data.get('architect_requests', []):
        cursor.execute('''INSERT OR REPLACE INTO architect_requests 
            (id, company_name, project_type, location, budget, message, status, created_at, completed_at, design_images) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
            (r['id'], r['company_name'], r['project_type'], r['location'], r['budget'], r['message'], r['status'], r['created_at'], r.get('completed_at', ''), json.dumps(r.get('design_images', []))))
            
    conn.commit()
    conn.close()

def create_app() -> Flask:
    app = Flask(__name__)
    # Enable CORS for cross-origin requests
    CORS(app)
    
    # Use environment variable for secret key
    app.secret_key = os.environ.get('SECRET_KEY', 'work24-fresh-app-secret-change-me-in-prod')
    
    app.config['MAX_CONTENT_LENGTH'] = 24 * 1024 * 1024

    # Initialize SQLite Database
    init_db()

    @app.route('/sw.js')
    def service_worker():
        return app.send_static_file('sw.js')

    @app.route('/set-language/<lang>')
    def set_language(lang: str):
        response = redirect(request.referrer or url_for('index'))
        if lang in ['en', 'hi', 'gu']:
            session['lang'] = lang
            response.set_cookie('lang', lang, max_age=30*24*60*60) # 30 days
        return response

    @app.context_processor
    def inject_globals() -> dict[str, Any]:
        lang = request.cookies.get('lang') or session.get('lang', 'en')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Load translations
        translations = {}
        try:
            trans_path = DATA_DIR / 'translations.json'
            if trans_path.exists():
                with trans_path.open('r', encoding='utf-8') as f:
                    translations = json.load(f)
        except Exception:
            pass

        def translate(key: str, default: str | None = None) -> str:
            val = translations.get(lang, {}).get(key)
            if val:
                return val
            if '.' in key:
                parts = key.split('.')
                curr = translations.get(lang, {})
                for p in parts:
                    if isinstance(curr, dict):
                        curr = curr.get(p, {})
                if isinstance(curr, str):
                    return curr
            return default or key

        # Fetch categories from DB
        cursor.execute("SELECT value FROM configs WHERE key = 'worker_categories'")
        raw_worker_cats = json.loads(cursor.fetchone()[0])
        cursor.execute("SELECT value FROM configs WHERE key = 'material_categories'")
        raw_material_cats = json.loads(cursor.fetchone()[0])
        cursor.execute("SELECT value FROM configs WHERE key = 'admin_contact'")
        admin_contact = json.loads(cursor.fetchone()[0])
        
        worker_cats = [translate(f"categories.{cat}", cat) for cat in raw_worker_cats]
        material_cats = [translate(f"categories.{cat}", cat) for cat in raw_material_cats]

        conn.close()

        return {
            'admin_contact': admin_contact,
            'worker_categories': worker_cats,
            'material_categories': material_cats,
            'raw_worker_categories': raw_worker_cats,
            'raw_material_categories': raw_material_cats,
            'current_year': datetime.now().year,
            'is_admin_logged_in': bool(session.get('admin_authenticated')),
            'partner_role': session.get('partner_role'),
            'lang': lang,
            'has_lang': bool(request.cookies.get('lang') or session.get('lang')),
            '_': translate
        }

    @app.route('/')
    def index() -> str:
        return render_template('index.html', 
                             workers=approved_workers_list()[:4], 
                             materials=group_materials_list()[:6], 
                             stats=build_stats())

    @app.route('/workers')
    def workers() -> str:
        category = request.args.get('category', '').strip()
        conn = get_db()
        cursor = conn.cursor()
        query = "SELECT * FROM workers WHERE status = 'approved'"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY rowid DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        visible_workers = []
        for r in rows:
            w = dict(r)
            w['work_images'] = json.loads(w.get('work_images', '[]'))
            visible_workers.append(w)
        conn.close()
        return render_template('workers.html', workers=visible_workers, active_category=category)

    @app.route('/workers/<worker_id>')
    def worker_detail(worker_id: str) -> str:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM workers WHERE id = ? AND status = 'approved'", (worker_id,))
        worker_row = cursor.fetchone()
        
        if not worker_row:
            conn.close()
            flash('Worker profile not found.', 'error')
            return redirect(url_for('workers'))
            
        worker = dict(worker_row)
        worker['work_images'] = json.loads(worker.get('work_images', '[]'))
        
        cursor.execute("SELECT * FROM workers WHERE category = ? AND id != ? AND status = 'approved' LIMIT 3", (worker['category'], worker['id']))
        related_workers = [dict(r) for r in cursor.fetchall()]
        conn.close()
        
        return render_template('worker_detail.html', worker=worker, related_workers=related_workers)

    @app.route('/materials')
    def materials() -> str:
        category = request.args.get('category', '').strip()
        catalog = group_materials_list()
        if category:
            catalog = [item for item in catalog if item['category'] == category]
        return render_template('materials.html', materials=catalog, active_category=category)

    @app.route('/materials/<material_slug>')
    def material_detail(material_slug: str) -> str:
        offers = approved_material_offers_list(material_slug)
        if not offers:
            flash('Material not found.', 'error')
            return redirect(url_for('materials'))
        primary = offers[0]
        return render_template('material_detail.html', 
                             material_slug=material_slug, 
                             material_name=primary['title'], 
                             category=primary['category'], 
                             offers=offers)

    @app.route('/architects', methods=['GET', 'POST'])
    def architects() -> str:
        if request.method == 'POST':
            entry = {
                'id': create_id('arch'),
                'company_name': request.form.get('company_name', '').strip(),
                'project_type': request.form.get('project_type', '').strip(),
                'location': request.form.get('location', '').strip(),
                'budget': request.form.get('budget', '').strip(),
                'message': request.form.get('message', '').strip(),
                'design_images': json.dumps(read_uploaded_images('design_images')),
                'status': 'open',
                'created_at': timestamp(),
                'completed_at': '',
            }
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO architect_requests 
                (id, company_name, project_type, location, budget, message, design_images, status, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (entry['id'], entry['company_name'], entry['project_type'], entry['location'], entry['budget'], entry['message'], entry['design_images'], entry['status'], entry['created_at'], entry['completed_at']))
            conn.commit()
            conn.close()
            flash('Architect request submitted. Work24 admin will respond on the official number.', 'success')
            return redirect(url_for('architects'))
        return render_template('architects.html')

    @app.route('/join-worker', methods=['GET', 'POST'])
    def join_worker() -> str:
        if request.method == 'POST':
            phone = request.form.get('phone', '').strip()
            if find_worker_by_phone(phone):
                flash('A worker account with this phone already exists. Please login instead.', 'error')
                return redirect(url_for('partner_login', role='worker'))
            
            worker = {
                'id': create_id('worker'),
                'name': request.form.get('name', '').strip(),
                'phone': phone,
                'password_hash': generate_password_hash(request.form.get('password', '').strip()),
                'profile_image': read_uploaded_single_image('profile_image') or encode_svg_data_uri('WORKER', '#f59e0b', '#34d399'),
                'category': request.form.get('category', '').strip(),
                'location': request.form.get('location', '').strip(),
                'experience': request.form.get('experience', '').strip(),
                'status': 'pending',
                'created_at': timestamp(),
                'approved_at': '',
                'work_images': json.dumps(read_uploaded_images('work_images')),
            }
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO workers (id, name, phone, password_hash, profile_image, category, location, experience, status, created_at, approved_at, work_images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (worker['id'], worker['name'], worker['phone'], worker['password_hash'], worker['profile_image'], worker['category'], worker['location'], worker['experience'], worker['status'], worker['created_at'], worker['approved_at'], worker['work_images']))
            conn.commit()
            conn.close()
            flash('Worker registration submitted. Your profile will appear after admin approval.', 'success')
            return redirect(url_for('partner_login', panel='login', role='worker'))
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM configs WHERE key = 'worker_categories'")
        worker_categories = json.loads(cursor.fetchone()[0])
        cursor.execute("SELECT value FROM configs WHERE key = 'material_categories'")
        material_categories = json.loads(cursor.fetchone()[0])
        conn.close()
        
        return render_template(
            'partner_login.html',
            role='worker',
            active_panel='join-worker',
            worker_categories=worker_categories,
            material_categories=material_categories,
        )

    @app.route('/join-seller', methods=['GET', 'POST'])
    def join_seller() -> str:
        if request.method == 'POST':
            phone = request.form.get('phone', '').strip()
            if find_seller_by_phone(phone):
                flash('A seller account with this phone already exists. Please login instead.', 'error')
                return redirect(url_for('partner_login', role='seller'))
            
            seller_id = create_id('seller')
            seller = {
                'id': seller_id,
                'name': request.form.get('name', '').strip(),
                'phone': phone,
                'password_hash': generate_password_hash(request.form.get('password', '').strip()),
                'profile_image': read_uploaded_single_image('profile_image') or encode_svg_data_uri('SHOP', '#f59e0b', '#38bdf8'),
                'business_name': request.form.get('business_name', '').strip(),
                'location': request.form.get('location', '').strip(),
                'description': request.form.get('description', '').strip(),
                'status': 'pending',
                'created_at': timestamp(),
                'approved_at': '',
            }
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sellers (id, name, phone, password_hash, profile_image, business_name, location, description, status, created_at, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (seller['id'], seller['name'], seller['phone'], seller['password_hash'], seller['profile_image'], seller['business_name'], seller['location'], seller['description'], seller['status'], seller['created_at'], seller['approved_at']))
            
            initial_material_name = request.form.get('material_title', '').strip()
            if initial_material_name:
                images = read_uploaded_images('material_images')
                for image in images or [encode_svg_data_uri('MATERIAL', '#fb923c', '#38bdf8')]:
                    cursor.execute('''
                        INSERT INTO materials (id, seller_id, title, title_slug, category, description, price, image, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (create_id('mat'), seller_id, initial_material_name, slugify(initial_material_name), request.form.get('material_category', '').strip(), request.form.get('material_description', '').strip(), request.form.get('price', '').strip(), image, timestamp()))
            
            conn.commit()
            conn.close()
            flash('Seller registration submitted. Your shop and materials will go live after admin approval.', 'success')
            return redirect(url_for('partner_login', panel='login', role='seller'))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM configs WHERE key = 'worker_categories'")
        worker_categories = json.loads(cursor.fetchone()[0])
        cursor.execute("SELECT value FROM configs WHERE key = 'material_categories'")
        material_categories = json.loads(cursor.fetchone()[0])
        conn.close()

        return render_template(
            'partner_login.html',
            role='seller',
            active_panel='join-seller',
            worker_categories=worker_categories,
            material_categories=material_categories,
        )

    @app.route('/partner-login', methods=['GET', 'POST'])
    def partner_login() -> str:
        role = request.args.get('role', request.form.get('role', 'worker'))
        if request.method == 'POST':
            phone = request.form.get('phone', '').strip()
            password = request.form.get('password', '').strip()
            partner = find_worker_by_phone(phone) if role == 'worker' else find_seller_by_phone(phone)
            
            if not partner or not check_password_hash(partner['password_hash'], password):
                flash('Invalid phone number or password.', 'error')
                return redirect(url_for('partner_login', role=role))
            
            session['partner_id'] = partner['id']
            session['partner_role'] = role
            flash('Login successful.', 'success')
            return redirect(url_for('dashboard'))
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM configs WHERE key = 'worker_categories'")
        worker_categories = json.loads(cursor.fetchone()[0])
        cursor.execute("SELECT value FROM configs WHERE key = 'material_categories'")
        material_categories = json.loads(cursor.fetchone()[0])
        conn.close()

        return render_template(
            'partner_login.html',
            role=role,
            worker_categories=worker_categories,
            material_categories=material_categories,
        )

    @app.route('/dashboard')
    def dashboard() -> str:
        partner = current_partner()
        if not partner:
            flash('Please login to continue.', 'error')
            return redirect(url_for('partner_login'))
            
        conn = get_db()
        cursor = conn.cursor()
        if session['partner_role'] == 'worker':
            cursor.execute("SELECT value FROM configs WHERE key = 'worker_categories'")
            categories = json.loads(cursor.fetchone()[0])
            conn.close()
            return render_template('dashboard.html', role='worker', partner=partner, items=partner['work_images'], categories=categories)
            
        cursor.execute("SELECT * FROM materials WHERE seller_id = ? ORDER BY rowid DESC", (partner['id'],))
        items = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT value FROM configs WHERE key = 'material_categories'")
        categories = json.loads(cursor.fetchone()[0])
        conn.close()
        return render_template('dashboard.html', role='seller', partner=partner, items=items, categories=categories)

    @app.route('/dashboard/worker', methods=['POST'])
    def update_worker_dashboard() -> str:
        worker = current_partner()
        if not worker or session.get('partner_role') != 'worker':
            flash('Please login as worker.', 'error')
            return redirect(url_for('partner_login', role='worker'))
            
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        category = request.form.get('category', '').strip()
        location = request.form.get('location', '').strip()
        experience = request.form.get('experience', '').strip()
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Profile image update
        profile_image = read_uploaded_single_image('profile_image')
        if profile_image:
            cursor.execute("UPDATE workers SET profile_image = ? WHERE id = ?", (profile_image, worker['id']))
            
        # Add new work images to existing list
        new_images = read_uploaded_images('work_images')
        work_images = worker['work_images'] # This is already a list from current_partner()
        if new_images:
            work_images.extend(new_images)
            cursor.execute("UPDATE workers SET work_images = ? WHERE id = ?", (json.dumps(work_images), worker['id']))
            
        cursor.execute('''
            UPDATE workers 
            SET name = ?, phone = ?, category = ?, location = ?, experience = ?
            WHERE id = ?
        ''', (name, phone, category, location, experience, worker['id']))
        
        conn.commit()
        conn.close()
        flash('Worker profile updated successfully.', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/dashboard/seller', methods=['POST'])
    def update_seller_dashboard() -> str:
        seller = current_partner()
        if not seller or session.get('partner_role') != 'seller':
            flash('Please login as seller.', 'error')
            return redirect(url_for('partner_login', role='seller'))
            
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        business_name = request.form.get('business_name', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        
        conn = get_db()
        cursor = conn.cursor()
        
        profile_image = read_uploaded_single_image('profile_image')
        if profile_image:
            cursor.execute("UPDATE sellers SET profile_image = ? WHERE id = ?", (profile_image, seller['id']))
            
        cursor.execute('''
            UPDATE sellers 
            SET name = ?, phone = ?, business_name = ?, location = ?, description = ?
            WHERE id = ?
        ''', (name, phone, business_name, location, description, seller['id']))
        
        conn.commit()
        conn.close()
        flash('Seller profile updated successfully.', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/dashboard/material', methods=['POST'])
    def add_seller_material() -> str:
        seller = current_partner()
        if not seller or session.get('partner_role') != 'seller':
            flash('Please login as seller.', 'error')
            return redirect(url_for('partner_login', role='seller'))
            
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', '').strip()
        images = read_uploaded_images('images')
        
        if not title:
            flash('Material title is required.', 'error')
            return redirect(url_for('dashboard'))
            
        conn = get_db()
        cursor = conn.cursor()
        for image in images or [encode_svg_data_uri(title[:12], '#fb923c', '#38bdf8')]:
            cursor.execute('''
                INSERT INTO materials (id, seller_id, title, title_slug, category, description, price, image, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (create_id('mat'), seller['id'], title, slugify(title), category, description, price, image, timestamp()))
        
        conn.commit()
        conn.close()
        flash('Material added successfully.', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/logout', methods=['POST'])
    def partner_logout() -> str:
        session.pop('partner_id', None)
        session.pop('partner_role', None)
        flash('Logged out successfully.', 'success')
        return redirect(url_for('index'))

    @app.route('/admin-login', methods=['GET', 'POST'])
    def admin_login() -> str:
        if request.method == 'POST':
            admin_id = request.form.get('admin_id', '').strip()
            password = request.form.get('password', '').strip()
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM configs WHERE key = 'admin_credentials'")
            credentials = json.loads(cursor.fetchone()[0])
            conn.close()
            
            if admin_id == credentials['id'] and check_password_hash(credentials['password_hash'], password):
                session['admin_authenticated'] = True
                flash('Admin login successful.', 'success')
                return redirect(url_for('admin_dashboard'))
            flash('Invalid admin ID or password.', 'error')
            return redirect(url_for('admin_login'))
        return render_template('admin_login.html')

    @app.route('/admin')
    def admin_dashboard() -> str:
        if not session.get('admin_authenticated'):
            flash('Please login as admin.', 'error')
            return redirect(url_for('admin_login'))
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM workers ORDER BY rowid DESC")
        workers = []
        for r in cursor.fetchall():
            w = dict(r)
            w['work_images'] = json.loads(w.get('work_images', '[]'))
            workers.append(w)
            
        cursor.execute("SELECT * FROM sellers ORDER BY rowid DESC")
        sellers = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM architect_requests ORDER BY rowid DESC")
        architects = []
        for r in cursor.fetchall():
            arch = dict(r)
            arch['design_images'] = json.loads(arch.get('design_images', '[]'))
            architects.append(arch)
            
        materials_by_seller = materials_grouped_by_seller_dict()
        stats = build_stats()
        conn.close()
        
        return render_template('admin.html', workers=workers, sellers=sellers, materials_by_seller=materials_by_seller, architects=architects, stats=stats)

    @app.route('/admin/status/<entity>/<item_id>/<action>', methods=['POST'])
    def admin_status(entity: str, item_id: str, action: str) -> str:
        if not session.get('admin_authenticated'):
            flash('Please login as admin.', 'error')
            return redirect(url_for('admin_login'))
            
        action_map = {'approve': 'approved', 'reject': 'rejected', 'suspend': 'suspended', 'activate': 'approved'}
        if action not in action_map:
            flash('Invalid action.', 'error')
            return redirect(url_for('admin_dashboard'))
            
        conn = get_db()
        cursor = conn.cursor()
        table = 'workers' if entity == 'worker' else 'sellers'
        
        status = action_map[action]
        approved_at = timestamp() if status == 'approved' else ''
        
        if status == 'approved':
            cursor.execute(f"UPDATE {table} SET status = ?, approved_at = ? WHERE id = ?", (status, approved_at, item_id))
        else:
            cursor.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (status, item_id))
            
        if cursor.rowcount == 0:
            flash('Profile not found.', 'error')
        else:
            flash(f"{entity.title()} profile updated to {status}.", 'success')
            
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin/inquiry/<inquiry_id>/complete', methods=['POST'])
    def complete_inquiry(inquiry_id: str) -> str:
        if not session.get('admin_authenticated'):
            flash('Please login as admin.', 'error')
            return redirect(url_for('admin_login'))
            
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE architect_requests SET status = 'completed', completed_at = ? WHERE id = ?", (timestamp(), inquiry_id))
        
        if cursor.rowcount == 0:
            flash('Inquiry not found.', 'error')
        else:
            flash('Inquiry marked as completed.', 'success')
            
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard'))

    @app.route('/admin-logout', methods=['POST'])
    def admin_logout() -> str:
        session.pop('admin_authenticated', None)
        flash('Admin logged out successfully.', 'success')
        return redirect(url_for('admin_login'))

    return app


def build_stats() -> dict[str, int]:
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT count(*) FROM workers WHERE status = 'approved'")
    approved_workers_count = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM sellers WHERE status = 'approved'")
    approved_sellers_count = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM architect_requests")
    architect_requests = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM workers WHERE status = 'pending'")
    pending_workers = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM sellers WHERE status = 'pending'")
    pending_sellers = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM workers")
    total_workers = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM sellers")
    total_sellers = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM architect_requests WHERE status != 'completed'")
    open_inquiries = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM architect_requests WHERE status = 'completed'")
    completed_inquiries = cursor.fetchone()[0]
    
    # Live materials (from approved sellers)
    cursor.execute('''
        SELECT count(*) FROM materials 
        JOIN sellers ON materials.seller_id = sellers.id 
        WHERE sellers.status = 'approved'
    ''')
    live_materials = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'approved_workers': approved_workers_count,
        'approved_sellers': approved_sellers_count,
        'live_materials': live_materials,
        'architect_requests': architect_requests,
        'pending_workers': pending_workers,
        'pending_sellers': pending_sellers,
        'total_workers': total_workers,
        'total_sellers': total_sellers,
        'total_inquiries': architect_requests,
        'open_inquiries': open_inquiries,
        'completed_inquiries': completed_inquiries,
    }

def current_partner() -> dict[str, Any] | None:
    partner_id = session.get('partner_id')
    role = session.get('partner_role')
    if not partner_id or not role:
        return None
    
    conn = get_db()
    cursor = conn.cursor()
    table = 'workers' if role == 'worker' else 'sellers'
    cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (partner_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        partner = dict(row)
        if role == 'worker' and 'work_images' in partner:
            partner['work_images'] = json.loads(partner['work_images'])
        return partner
    return None

def approved_workers_list() -> list[dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers WHERE status = 'approved' ORDER BY rowid DESC")
    rows = cursor.fetchall()
    conn.close()
    
    workers = []
    for r in rows:
        w = dict(r)
        w['work_images'] = json.loads(w.get('work_images', '[]'))
        workers.append(w)
    return workers

def approved_materials_list() -> list[dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT materials.* FROM materials 
        JOIN sellers ON materials.seller_id = sellers.id 
        WHERE sellers.status = 'approved'
        ORDER BY materials.rowid DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def group_materials_list() -> list[dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT materials.title, materials.title_slug, materials.category, materials.image, 
               materials.price as starting_price, sellers.business_name, materials.seller_id
        FROM materials 
        JOIN sellers ON materials.seller_id = sellers.id 
        WHERE sellers.status = 'approved'
        ORDER BY materials.rowid DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    grouped: dict[str, dict[str, Any]] = {}
    for r in rows:
        row = dict(r)
        slug = row['title_slug']
        if slug not in grouped:
            grouped[slug] = {
                'slug': slug,
                'title': row['title'],
                'category': row['category'],
                'image': row['image'],
                'starting_price': row['starting_price'],
                'seller_names': [row['business_name']],
                'offer_count': 1
            }
        else:
            if row['business_name'] not in grouped[slug]['seller_names']:
                grouped[slug]['seller_names'].append(row['business_name'])
            grouped[slug]['offer_count'] += 1
            
    return list(grouped.values())

def approved_material_offers_list(material_slug: str) -> list[dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT materials.*, sellers.name as seller_name, sellers.business_name, 
               sellers.location, sellers.profile_image as seller_profile_image
        FROM materials 
        JOIN sellers ON materials.seller_id = sellers.id 
        WHERE materials.title_slug = ? AND sellers.status = 'approved'
    ''', (material_slug,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def materials_grouped_by_seller_dict() -> dict[str, list[dict[str, Any]]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sellers")
    sellers = cursor.fetchall()
    
    result = {}
    for s in sellers:
        cursor.execute("SELECT * FROM materials WHERE seller_id = ?", (s['id'],))
        result[s['id']] = [dict(m) for m in cursor.fetchall()]
    
    conn.close()
    return result

def find_worker_by_phone(phone: str) -> dict[str, Any] | None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def find_seller_by_phone(phone: str) -> dict[str, Any] | None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sellers WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def read_uploaded_single_image(field_name: str) -> str:
    files = request.files.getlist(field_name)
    for file in files:
        if file and file.filename:
            return file_to_data_uri(file)
    return ''


def read_uploaded_images(field_name: str) -> list[str]:
    images = []
    for file in request.files.getlist(field_name):
        if file and file.filename:
            images.append(file_to_data_uri(file))
    return images


def file_to_data_uri(file_storage: Any) -> str:
    data = file_storage.read()
    mime = file_storage.mimetype or mimetypes.guess_type(file_storage.filename)[0] or 'image/png'
    encoded = base64.b64encode(data).decode('utf-8')
    return f'data:{mime};base64,{encoded}'


def slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def create_id(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def timestamp() -> str:
    return datetime.now().strftime('%d %b %Y, %I:%M %p')


def encode_svg_data_uri(text: str, start: str, end: str) -> str:
    safe_text = text[:16]
    svg = f"""
    <svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 900 640'>
      <defs>
        <linearGradient id='g' x1='0%' y1='0%' x2='100%' y2='100%'>
          <stop offset='0%' stop-color='{start}' />
          <stop offset='100%' stop-color='{end}' />
        </linearGradient>
      </defs>
      <rect width='900' height='640' rx='42' fill='url(#g)' />
      <circle cx='160' cy='120' r='110' fill='rgba(255,255,255,0.18)' />
      <circle cx='750' cy='520' r='150' fill='rgba(255,255,255,0.18)' />
      <text x='50%' y='52%' dominant-baseline='middle' text-anchor='middle' fill='white' font-size='54' font-family='Verdana'>{safe_text}</text>
    </svg>
    """.strip()
    encoded = base64.b64encode(svg.encode('utf-8')).decode('utf-8')
    return f'data:image/svg+xml;base64,{encoded}'


def default_data() -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'admin_contact': {
            'phone': '+91 92748 58475',
            'whatsapp': 'https://wa.me/919274858475?text=Hello%20Work24%2C%20I%20want%20to%20book%20a%20worker%20or%20buy%20material.',
        },
        'admin_credentials': {'id': 'work24admin', 'password_hash': generate_password_hash('Work24@Secure')},
        'worker_categories': ['Plumber', 'Electrician', 'Carpenter', 'Painter', 'Fabricator', 'Furniture Expert'],
        'material_categories': ['Building Materials', 'Electrical', 'Plumbing', 'Paints', 'Wood & Boards', 'Hardware'],
        'workers': [
            {'id': 'worker-demo-1', 'name': 'Rahul Carpenter', 'phone': '9876500001', 'password_hash': generate_password_hash('worker123'), 'profile_image': encode_svg_data_uri('RAHUL', '#f59e0b', '#34d399'), 'category': 'Carpenter', 'location': 'Ahmedabad', 'experience': '8 years', 'status': 'approved', 'created_at': timestamp(), 'approved_at': timestamp(), 'work_images': [encode_svg_data_uri('Wardrobe', '#fb923c', '#38bdf8'), encode_svg_data_uri('Kitchen', '#f59e0b', '#34d399'), encode_svg_data_uri('TV Unit', '#fbbf24', '#22c55e')]},
            {'id': 'worker-demo-2', 'name': 'Imran Electrician', 'phone': '9876500002', 'password_hash': generate_password_hash('worker123'), 'profile_image': encode_svg_data_uri('IMRAN', '#f97316', '#38bdf8'), 'category': 'Electrician', 'location': 'Surat', 'experience': '6 years', 'status': 'approved', 'created_at': timestamp(), 'approved_at': timestamp(), 'work_images': [encode_svg_data_uri('Lighting', '#fb923c', '#38bdf8'), encode_svg_data_uri('Panels', '#f59e0b', '#0ea5e9'), encode_svg_data_uri('Wiring', '#fdba74', '#22c55e')]},
        ],
        'sellers': [
            {'id': 'seller-demo-1', 'name': 'Mitesh Patel', 'phone': '9876500010', 'password_hash': generate_password_hash('seller123'), 'profile_image': encode_svg_data_uri('SHREE', '#f59e0b', '#38bdf8'), 'business_name': 'Shree Build Mart', 'location': 'Vadodara', 'description': 'Bulk materials for contractors, interiors, and home upgrades.', 'status': 'approved', 'created_at': timestamp(), 'approved_at': timestamp()},
            {'id': 'seller-demo-2', 'name': 'Krunal Shah', 'phone': '9876500011', 'password_hash': generate_password_hash('seller123'), 'profile_image': encode_svg_data_uri('KRUNAL', '#f97316', '#38bdf8'), 'business_name': 'BlueStone Traders', 'location': 'Rajkot', 'description': 'Tiles, plumbing products, paint, hardware, and finishing materials.', 'status': 'approved', 'created_at': timestamp(), 'approved_at': timestamp()},
        ],
        'materials': [
            {'id': 'mat-demo-1', 'seller_id': 'seller-demo-1', 'title': 'PVC Pipe Set', 'title_slug': 'pvc-pipe-set', 'category': 'Plumbing', 'description': 'Heavy-duty PVC pipe set for residential and commercial fitting work by Shree Build Mart.', 'price': '₹1,450', 'image': encode_svg_data_uri('PVC Pipe', '#fb923c', '#38bdf8'), 'created_at': timestamp()},
            {'id': 'mat-demo-2', 'seller_id': 'seller-demo-2', 'title': 'PVC Pipe Set', 'title_slug': 'pvc-pipe-set', 'category': 'Plumbing', 'description': 'Contractor pack with elbows and reducers from BlueStone Traders.', 'price': '₹1,390', 'image': encode_svg_data_uri('PVC Offer', '#f59e0b', '#34d399'), 'created_at': timestamp()},
            {'id': 'mat-demo-3', 'seller_id': 'seller-demo-1', 'title': 'Modular Switch Board', 'title_slug': 'modular-switch-board', 'category': 'Electrical', 'description': 'White modular switch board with premium plates from Shree Build Mart.', 'price': '₹320', 'image': encode_svg_data_uri('Switch Board', '#fb923c', '#0ea5e9'), 'created_at': timestamp()},
        ],
        'architect_requests': [],
    }


def ensure_data_file() -> None:
    # Deprecated: Using SQLite now. Keeping empty to avoid breakages if called elsewhere.
    pass

def load_data() -> dict[str, Any]:
    # Deprecated: Using SQLite now.
    return {}

def save_data(data: dict[str, Any]) -> None:
    # Deprecated: Using SQLite now.
    pass


app = create_app()


if __name__ == '__main__':
    # Get port from environment variable (Render assigns a dynamic port)
    port = int(os.environ.get('PORT', 5000))
    # Binding to 0.0.0.0 is required for Render/Docker/Production
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true')
