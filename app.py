from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
import sqlite3, os
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import json
from datetime import timedelta, datetime
import traceback
import uuid
from urllib.parse import urlparse  # <-- تمت إضافة هذا السطر الجديد

# محاولة استيراد Supabase (إذا كان مثبتاً)
try:
    from supabase import create_client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("⚠️ مكتبة supabase غير مثبتة. سيتم استخدام التخزين المحلي للصور.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ========== إعداد Supabase Storage ==========
# تم استبدال رابط Supabase القديم بالجديد
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://iiwktxwlorknefbkztvt.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase = None
if SUPABASE_AVAILABLE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Supabase Storage متصل بنجاح")
    except Exception as e:
        print(f"⚠️ فشل الاتصال بـ Supabase Storage: {e}")

# ========== بيانات حساب الأدمن ==========
ADMIN_EMAIL = "admin@turkishstore.com"
ADMIN_PASSWORD = "Turk!sh@dm!n2025#Secure"
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

DATABASE_URL = os.environ.get('DATABASE_URL')
USE_POSTGRES = bool(DATABASE_URL)

print(f"🔍 استخدام PostgreSQL: {USE_POSTGRES}")

# ========== دالة الاتصال بقاعدة البيانات (تم تعديلها) ==========
def get_db():
    try:
        if USE_POSTGRES:
            # تفكيك رابط قاعدة البيانات (DATABASE_URL)
            result = urlparse(DATABASE_URL)
            dbname = result.path[1:]
            user = result.username
            password = result.password
            host = result.hostname
            port = result.port
            
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                sslmode='require'
            )
            conn.cursor_factory = RealDictCursor
            return conn
        else:
            conn = sqlite3.connect(DB_PATH, timeout=30)
            conn.row_factory = lambda cursor, row: {col[0]: row[i] for i, col in enumerate(cursor.description)}
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
        traceback.print_exc()
        raise

def get_placeholder():
    return '%s' if USE_POSTGRES else '?'

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    if USE_POSTGRES:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                old_price REAL DEFAULT 0,
                image TEXT,
                category TEXT DEFAULT 'عام',
                bulk_discounts TEXT DEFAULT '[]'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_images (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                filename TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                items TEXT NOT NULL,
                total REAL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                customer_name TEXT,
                customer_phone TEXT,
                customer_address TEXT,
                customer_notes TEXT
            )
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                old_price REAL DEFAULT 0,
                image TEXT,
                category TEXT DEFAULT 'عام',
                bulk_discounts TEXT DEFAULT '[]'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                filename TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                items TEXT NOT NULL,
                total REAL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                customer_name TEXT,
                customer_phone TEXT,
                customer_address TEXT,
                customer_notes TEXT
            )
        """)
    
    conn.commit()
    conn.close()

def migrate_db():
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        if USE_POSTGRES:
            cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS old_price REAL DEFAULT 0")
            cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS bulk_discounts TEXT DEFAULT '[]'")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_name TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_phone TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_address TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_notes TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS total REAL DEFAULT 0")
        else:
            cursor.execute("PRAGMA table_info(products)")
            columns = cursor.fetchall()
            has_old_price = False
            has_bulk_discounts = False
            for col in columns:
                if col['name'] == 'old_price':
                    has_old_price = True
                if col['name'] == 'bulk_discounts':
                    has_bulk_discounts = True
            if not has_old_price:
                cursor.execute("ALTER TABLE products ADD COLUMN old_price REAL DEFAULT 0")
            if not has_bulk_discounts:
                cursor.execute("ALTER TABLE products ADD COLUMN bulk_discounts TEXT DEFAULT '[]'")
            
            cursor.execute("PRAGMA table_info(orders)")
            order_columns = cursor.fetchall()
            order_col_names = [col['name'] for col in order_columns]
            
            if 'customer_name' not in order_col_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_name TEXT")
            if 'customer_phone' not in order_col_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_phone TEXT")
            if 'customer_address' not in order_col_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_address TEXT")
            if 'customer_notes' not in order_col_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_notes TEXT")
            if 'total' not in order_col_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN total REAL DEFAULT 0")
        
        conn.commit()
    except Exception as e:
        print(f"⚠️ تحذير: {e}")
    finally:
        conn.close()

def create_admin_user():
    conn = get_db()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    
    try:
        cursor.execute(f"SELECT * FROM users WHERE email = {placeholder}", (ADMIN_EMAIL,))
        existing = cursor.fetchone()
        
        if not existing:
            cursor.execute(
                f"INSERT INTO users (name, email, password, phone) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
                ("مدير الموقع", ADMIN_EMAIL, ADMIN_PASSWORD_HASH, "0500000000")
            )
            conn.commit()
            print("✅ تم إضافة حساب الأدمن")
    except Exception as e:
        print(f"⚠️ تحذير: {e}")
    finally:
        conn.close()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("الرجاء تسجيل الدخول أولاً", "warning")
            return redirect(url_for("user_login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            flash("الرجاء تسجيل الدخول كأدمن.", "warning")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/")
def index():
    return redirect(url_for("products"))

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/work")
def work():
    return render_template("work.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/products")
def products():
    cat = request.args.get("cat")
    conn = get_db()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    
    cursor.execute("SELECT DISTINCT COALESCE(category,'عام') AS c FROM products ORDER BY c")
    cats = cursor.fetchall()
    
    if cat:
        cursor.execute(f"SELECT * FROM products WHERE COALESCE(category,'عام') = {placeholder} ORDER BY id DESC", (cat,))
    else:
        cursor.execute("SELECT * FROM products ORDER BY id DESC")
    items = cursor.fetchall()
    
    products_list = []
    for product in items:
        product_dict = dict(product)
        cursor.execute(f"SELECT filename FROM product_images WHERE product_id = {placeholder} ORDER BY id", (product['id'],))
        extra_images = cursor.fetchall()
        product_dict['extra_images'] = [img['filename'] for img in extra_images] if extra_images else []
        product_dict['main_image'] = product_dict.get('image')
        if 'old_price' not in product_dict:
            product_dict['old_price'] = None
        if 'bulk_discounts' not in product_dict or not product_dict['bulk_discounts']:
            product_dict['bulk_discounts'] = []
        else:
            try:
                product_dict['bulk_discounts'] = json.loads(product_dict['bulk_discounts'])
            except:
                product_dict['bulk_discounts'] = []
        products_list.append(product_dict)
    
    conn.close()
    
    categories_list = [r["c"] for r in cats]
    
    return render_template("products.html", products=products_list, categories=categories_list, active_cat=cat)

# ========== صفحة تفاصيل المنتج المنفصلة (للمشاركة) ==========
@app.route("/product/<int:pid>")
def product_detail(pid):
    conn = get_db()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    cursor.execute(f"SELECT * FROM products WHERE id = {placeholder}", (pid,))
    item = cursor.fetchone()
    cursor.execute(f"SELECT id, filename FROM product_images WHERE product_id = {placeholder} ORDER BY id", (pid,))
    imgs = cursor.fetchall()
    conn.close()
    if not item:
        flash("المنتج غير موجود.", "danger")
        return redirect(url_for("products"))
    
    all_images = []
    if item["image"]:
        all_images.append(item["image"])
    for img in imgs:
        if img['filename'] not in all_images:
            all_images.append(img['filename'])
    
    main_image = item["image"] if item["image"] else (imgs[0]["filename"] if imgs else None)
    
    # معالجة خصم الكميات
    bulk_discounts = []
    if item.get('bulk_discounts'):
        try:
            bulk_discounts = json.loads(item['bulk_discounts'])
        except:
            bulk_discounts = []
    
    return render_template("product_detail.html", p=item, images=imgs, main_image=main_image, all_images=all_images, bulk_discounts=bulk_discounts)

# ========== API للسلة ==========
@app.route("/api/add-to-cart", methods=["POST"])
def api_add_to_cart():
    try:
        data = request.json
        product_id = data.get('product_id')
        product_name = data.get('product_name')
        product_price = data.get('product_price')
        quantity = data.get('quantity', 1)
        
        try:
            quantity = int(quantity)
        except:
            quantity = 1
        
        if quantity == 0:
            return jsonify({'success': True, 'cart_count': len(session.get('cart', []))})
        
        if not session.get('cart'):
            session['cart'] = []
        
        cart = session['cart']
        existing = next((item for item in cart if item['id'] == product_id), None)
        
        if existing:
            new_qty = existing['qty'] + quantity
            if new_qty <= 0:
                cart = [item for item in cart if item['id'] != product_id]
            else:
                existing['qty'] = new_qty
        else:
            if quantity > 0:
                cart.append({
                    'id': product_id,
                    'name': product_name,
                    'price': float(product_price),
                    'qty': quantity
                })
        
        session['cart'] = cart
        session.permanent = True
        
        total_items = sum(item['qty'] for item in cart)
        
        return jsonify({'success': True, 'cart_count': total_items})
    except Exception as e:
        print(f"❌ خطأ في إضافة المنتج للسلة: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/get-cart")
def api_get_cart():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['qty'] for item in cart)
    return jsonify({'cart': cart, 'total': total})

@app.route("/api/remove-from-cart", methods=["POST"])
def api_remove_from_cart():
    try:
        data = request.json
        product_id = data.get('product_id')
        
        cart = session.get('cart', [])
        cart = [item for item in cart if item['id'] != product_id]
        session['cart'] = cart
        
        total = sum(item['price'] * item['qty'] for item in cart)
        total_items = sum(item['qty'] for item in cart)
        return jsonify({'success': True, 'cart': cart, 'total': total, 'cart_count': total_items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== دالة إتمام الطلب (موحدة للسلة والحجز المباشر) ==========
@app.route("/checkout", methods=["POST"])
def checkout():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'بيانات غير صالحة'}), 400

        # التحقق من نوع الطلب: من السلة أم حجز مباشر؟
        is_direct_booking = data.get('is_direct_booking', False)
        cart_items = []

        if is_direct_booking:
            # --- حالة الحجز المباشر: إنشاء عنصر واحد من بيانات الحجز ---
            customer_name = data.get('customer_name', '').strip()
            customer_phone = data.get('customer_phone', '').strip()
            customer_address = data.get('customer_address', '').strip()
            customer_notes = data.get('customer_notes', '').strip()
            product_id = data.get('product_id')
            product_name = data.get('product_name', '').strip()
            product_price = data.get('product_price', 0)
            quantity = data.get('quantity', 1)

            if not customer_name or not customer_phone or not customer_address or not product_name:
                return jsonify({'success': False, 'error': 'جميع الحقول مطلوبة للحجز المباشر'}), 400

            # إنشاء عنصر سلة مؤقت من بيانات الحجز
            cart_items = [{
                'id': product_id,
                'name': product_name,
                'price': float(product_price),
                'qty': int(quantity)
            }]
            total = float(product_price) * int(quantity)
            user_id = session.get('user_id', 0)

        else:
            # --- حالة السلة العادية ---
            cart_items = session.get('cart', [])
            if not cart_items:
                return jsonify({'success': False, 'error': 'السلة فارغة'}), 400

            customer_name = data.get('customer_name', '').strip()
            customer_phone = data.get('customer_phone', '').strip()
            customer_address = data.get('customer_address', '').strip()
            customer_notes = data.get('customer_notes', '').strip()
            user_id = session.get('user_id', 0)

            if not customer_name or not customer_phone or not customer_address:
                return jsonify({'success': False, 'error': 'الرجاء تعبئة جميع البيانات المطلوبة'}), 400

            # حساب المجموع الكلي
            total = 0
            for item in cart_items:
                item_total = item['price'] * item['qty']
                total += item_total

        # --- حفظ الطلب في قاعدة البيانات (موحد لكل من السلة والحجز المباشر) ---
        conn = get_db()
        cursor = conn.cursor()
        placeholder = get_placeholder()
        cart_json = json.dumps(cart_items, ensure_ascii=False)

        cursor.execute(
            f"""INSERT INTO orders (user_id, items, total, customer_name, customer_phone, customer_address, customer_notes, status) 
               VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})""",
            (user_id, cart_json, total, customer_name, customer_phone, customer_address, customer_notes, 'pending')
        )

        conn.commit()

        if USE_POSTGRES:
            cursor.execute("SELECT LASTVAL()")
            order_id = cursor.fetchone()['lastval']
        else:
            order_id = cursor.lastrowid

        conn.close()

        # إذا كان الطلب من السلة، نقوم بتفريغها
        if not is_direct_booking:
            session.pop('cart', None)

        return jsonify({'success': True, 'order_id': order_id, 'message': 'تم إرسال الطلب بنجاح'})

    except Exception as e:
        print(f"❌ خطأ في إتمام الطلب: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== API للطلبات ==========
@app.route("/api/orders", methods=["GET"])
@admin_required
def api_get_orders():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT o.*, u.name as user_name, u.email as user_email 
            FROM orders o 
            LEFT JOIN users u ON o.user_id = u.id 
            ORDER BY o.created_at DESC
        """)
        orders = cursor.fetchall()
        conn.close()
        
        for order in orders:
            try:
                order['items'] = json.loads(order['items']) if isinstance(order['items'], str) else order['items']
            except:
                order['items'] = []
        
        return jsonify({'success': True, 'orders': orders})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/orders/update", methods=["POST"])
@admin_required
def api_update_order():
    try:
        data = request.json
        order_id = data.get('order_id')
        status = data.get('status')
        
        if not order_id or not status:
            return jsonify({'success': False, 'error': 'بيانات غير مكتملة'})
        
        if status not in ['pending', 'completed', 'cancelled']:
            return jsonify({'success': False, 'error': 'حالة غير صالحة'})
        
        conn = get_db()
        cursor = conn.cursor()
        placeholder = get_placeholder()
        
        cursor.execute(
            f"UPDATE orders SET status = {placeholder} WHERE id = {placeholder}",
            (status, order_id)
        )
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/api/orders/delete/<int:order_id>", methods=["DELETE"])
@admin_required
def api_delete_order(order_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        placeholder = get_placeholder()
        
        cursor.execute(f"SELECT id FROM orders WHERE id = {placeholder}", (order_id,))
        order = cursor.fetchone()
        
        if not order:
            conn.close()
            return jsonify({'success': False, 'error': 'الطلب غير موجود'}), 404
        
        cursor.execute(f"DELETE FROM orders WHERE id = {placeholder}", (order_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'تم حذف الطلب رقم {order_id} بنجاح'})
    except Exception as e:
        print(f"❌ خطأ في حذف الطلب: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== نظام تسجيل الدخول للعملاء ==========
@app.route("/user/login", methods=["GET", "POST"])
def user_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        
        try:
            conn = get_db()
            cursor = conn.cursor()
            placeholder = get_placeholder()
            
            cursor.execute(f"SELECT * FROM users WHERE email = {placeholder}", (email,))
            user = cursor.fetchone()
            conn.close()
            
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['user_email'] = user['email']
                flash(f"مرحباً {user['name']}، تم تسجيل الدخول بنجاح!", "success")
                return redirect(url_for("products"))
            else:
                flash("البريد الإلكتروني أو كلمة المرور غير صحيحة", "danger")
        except Exception as e:
            flash("حدث خطأ في الخادم، حاول مرة أخرى", "danger")
    
    return render_template("user_login.html")

@app.route("/user/register", methods=["GET", "POST"])
def user_register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        phone = request.form.get("phone")
        
        if password != confirm_password:
            flash("كلمتا المرور غير متطابقتين", "danger")
            return redirect(url_for("user_register"))
        
        hashed_password = generate_password_hash(password)
        
        conn = get_db()
        cursor = conn.cursor()
        placeholder = get_placeholder()
        
        try:
            cursor.execute(
                f"INSERT INTO users (name, email, password, phone) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})",
                (name, email, hashed_password, phone)
            )
            conn.commit()
            flash("تم إنشاء الحساب بنجاح! يمكنك تسجيل الدخول الآن", "success")
            return redirect(url_for("user_login"))
        except Exception as e:
            flash("البريد الإلكتروني مسجل مسبقاً", "danger")
            return redirect(url_for("user_register"))
        finally:
            conn.close()
    
    return render_template("user_register.html")

@app.route("/user/logout")
def user_logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_email', None)
    session.pop('cart', None)
    session.pop('is_admin', None)
    session.pop('admin_email', None)
    flash("تم تسجيل الخروج بنجاح", "info")
    return redirect(url_for("products"))

@app.route("/user/profile")
@login_required
def user_profile():
    return render_template("user_profile.html")

# ========== نظام الأدمن ==========
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            session["admin_email"] = email
            session["user_id"] = 999
            session["user_name"] = "مدير الموقع"
            flash("تم تسجيل الدخول كأدمن بنجاح.", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("البريد الإلكتروني أو كلمة المرور غير صحيحة.", "danger")
    
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("admin_email", None)
    flash("تم تسجيل الخروج من لوحة التحكم.", "info")
    return redirect(url_for("products"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products ORDER BY id DESC")
    items = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    users_count = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as count FROM orders")
    orders_count = cursor.fetchone()
    
    conn.close()
    return render_template("admin_dashboard.html", 
                          products=items, 
                          users_count=users_count['count'], 
                          orders_count=orders_count['count'])

@app.route("/admin/orders")
@admin_required
def admin_orders():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, u.name as user_name, u.email as user_email 
        FROM orders o 
        LEFT JOIN users u ON o.user_id = u.id 
        ORDER BY o.created_at DESC
    """)
    orders = cursor.fetchall()
    
    for order in orders:
        try:
            order['items'] = json.loads(order['items']) if isinstance(order['items'], str) else order['items']
        except:
            order['items'] = []
    
    conn.close()
    return render_template("admin_orders.html", orders=orders)

@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = cursor.fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)

# ========== دالة إضافة المنتج ==========
@app.route("/admin/add", methods=["GET", "POST"])
@admin_required
def admin_add():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT COALESCE(category,'عام') AS c FROM products ORDER BY c")
    cats = cursor.fetchall()
    categories = [r["c"] for r in cats]
    conn.close()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        old_price = request.form.get("old_price", "").strip()
        category = request.form.get("category", "").strip()
        bulk_discounts_json = request.form.get("bulk_discounts", "[]")
        image_filename = None

        files = request.files.getlist("images")
        files = [f for f in files if getattr(f, "filename", "")]
        
        # رفع الصور إلى Supabase
        if files and supabase:
            try:
                ext = files[0].filename.split('.')[-1] if '.' in files[0].filename else 'jpg'
                unique_name = f"{uuid.uuid4()}.{ext}"
                file_content = files[0].read()
                supabase.storage.from_("products").upload(unique_name, file_content)
                image_filename = unique_name
                print(f"✅ تم رفع الصورة الرئيسية {unique_name} إلى Supabase")
                
                if len(files) > 1:
                    for i, f in enumerate(files[1:5]):
                        ext2 = f.filename.split('.')[-1] if '.' in f.filename else 'jpg'
                        unique_name2 = f"{uuid.uuid4()}.{ext2}"
                        f.seek(0)
                        file_content2 = f.read()
                        supabase.storage.from_("products").upload(unique_name2, file_content2)
                        print(f"✅ تم رفع الصورة الإضافية {unique_name2} إلى Supabase")
            except Exception as e:
                print(f"❌ خطأ في رفع الصورة إلى Supabase: {e}")
                image_filename = files[0].filename
                for f in files:
                    try:
                        f.seek(0)
                        f.save(os.path.join(app.config["UPLOAD_FOLDER"], f.filename))
                    except Exception as e2:
                        print(f"❌ خطأ في حفظ الصورة محلياً: {e2}")
        elif files:
            image_filename = files[0].filename
            for f in files:
                try:
                    f.save(os.path.join(app.config["UPLOAD_FOLDER"], f.filename))
                except Exception as e:
                    print(f"❌ خطأ في حفظ الصورة: {e}")

        if not name or not price or not category:
            flash("الاسم والسعر والفئة مطلوبة.", "danger")
            return redirect(url_for("admin_add"))

        try:
            price_val = float(price)
            old_price_val = float(old_price) if old_price else 0
        except ValueError:
            flash("السعر غير صالح.", "danger")
            return redirect(url_for("admin_add"))

        try:
            conn = get_db()
            cursor = conn.cursor()
            placeholder = get_placeholder()
            
            if USE_POSTGRES:
                cursor.execute(
                    f"INSERT INTO products (name, description, price, old_price, image, category, bulk_discounts) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}) RETURNING id",
                    (name, description, price_val, old_price_val, image_filename, category, bulk_discounts_json)
                )
                result = cursor.fetchone()
                pid = result['id']
            else:
                cursor.execute(
                    f"INSERT INTO products (name, description, price, old_price, image, category, bulk_discounts) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})",
                    (name, description, price_val, old_price_val, image_filename, category, bulk_discounts_json)
                )
                pid = cursor.lastrowid
            
            if files and len(files) > 1:
                if supabase:
                    for i, f in enumerate(files[1:5]):
                        ext2 = f.filename.split('.')[-1] if '.' in f.filename else 'jpg'
                        unique_name2 = f"{uuid.uuid4()}.{ext2}"
                        f.seek(0)
                        file_content2 = f.read()
                        try:
                            supabase.storage.from_("products").upload(unique_name2, file_content2)
                            cursor.execute(f"INSERT INTO product_images (product_id, filename) VALUES ({placeholder}, {placeholder})", (pid, unique_name2))
                        except Exception as e:
                            print(f"⚠️ فشل رفع الصورة الإضافية: {e}")
                else:
                    for f in files[1:5]:
                        cursor.execute(f"INSERT INTO product_images (product_id, filename) VALUES ({placeholder}, {placeholder})", (pid, f.filename))
            
            conn.commit()
            conn.close()
            flash("✅ تمت إضافة المنتج بنجاح!", "success")
            return redirect(url_for("admin_dashboard"))
            
        except Exception as e:
            print(f"❌ خطأ في إضافة المنتج: {e}")
            flash(f"❌ حدث خطأ: {str(e)[:100]}", "danger")
            return redirect(url_for("admin_add"))

    return render_template("add_product.html", categories=categories)

# ========== دالة تعديل المنتج ==========
@app.route("/admin/edit/<int:pid>", methods=["GET", "POST"])
@admin_required
def admin_edit(pid):
    conn = get_db()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    cursor.execute(f"SELECT * FROM products WHERE id = {placeholder}", (pid,))
    product = cursor.fetchone()
    if not product:
        conn.close()
        flash("المنتج غير موجود.", "danger")
        return redirect(url_for("admin_dashboard"))

    cursor.execute(f"SELECT id, filename FROM product_images WHERE product_id = {placeholder} ORDER BY id", (pid,))
    images = cursor.fetchall()
    cursor.execute("SELECT DISTINCT COALESCE(category,'عام') AS c FROM products ORDER BY c")
    cats = cursor.fetchall()
    categories = [r["c"] for r in cats]
    conn.close()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        old_price = request.form.get("old_price", "").strip()
        category = request.form.get("category", "").strip()
        bulk_discounts_json = request.form.get("bulk_discounts", "[]")
        remove_image = request.form.get("remove_image", "0") == "1"

        if not name or not price or not category:
            flash("الاسم والسعر والفئة مطلوبة.", "danger")
            return redirect(url_for("admin_edit", pid=pid))

        image_filename = product["image"]
        
        if remove_image and image_filename and supabase:
            try:
                supabase.storage.from_("products").remove([image_filename])
                print(f"✅ تم حذف الصورة القديمة {image_filename} من Supabase")
            except Exception as e:
                print(f"⚠️ لم نتمكن من حذف الصورة من Supabase: {e}")
            image_filename = None

        files = request.files.getlist("images")
        files = [f for f in files if getattr(f, "filename", "")]
        
        if files and supabase:
            try:
                ext = files[0].filename.split('.')[-1] if '.' in files[0].filename else 'jpg'
                unique_name = f"{uuid.uuid4()}.{ext}"
                file_content = files[0].read()
                supabase.storage.from_("products").upload(unique_name, file_content)
                image_filename = unique_name
                print(f"✅ تم رفع الصورة الرئيسية الجديدة {unique_name} إلى Supabase")
            except Exception as e:
                print(f"❌ خطأ في رفع الصورة إلى Supabase: {e}")
                image_filename = files[0].filename
                for f in files:
                    try:
                        f.seek(0)
                        f.save(os.path.join(app.config["UPLOAD_FOLDER"], f.filename))
                    except Exception as e2:
                        print(f"❌ خطأ في حفظ الصورة محلياً: {e2}")
        elif files:
            image_filename = files[0].filename
            for f in files:
                f.save(os.path.join(app.config["UPLOAD_FOLDER"], f.filename))

        try:
            price_val = float(price)
            old_price_val = float(old_price) if old_price else 0
        except ValueError:
            flash("السعر غير صالح.", "danger")
            return redirect(url_for("admin_edit", pid=pid))

        conn2 = get_db()
        cursor2 = conn2.cursor()
        placeholder = get_placeholder()
        cursor2.execute(
            f"UPDATE products SET name={placeholder}, description={placeholder}, price={placeholder}, old_price={placeholder}, image={placeholder}, category={placeholder}, bulk_discounts={placeholder} WHERE id={placeholder}",
            (name, description, price_val, old_price_val, image_filename, category, bulk_discounts_json, pid)
        )
        
        conn2.commit()
        conn2.close()
        flash("تم تعديل المنتج بنجاح.", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("edit_product.html", p=product, images=images, categories=categories)

@app.route("/admin/delete/<int:pid>", methods=["POST"])
@admin_required
def admin_delete(pid):
    conn = get_db()
    cursor = conn.cursor()
    placeholder = get_placeholder()
    cursor.execute(f"SELECT image FROM products WHERE id = {placeholder}", (pid,))
    row = cursor.fetchone()
    
    if row and row["image"] and supabase:
        try:
            supabase.storage.from_("products").remove([row["image"]])
            print(f"✅ تم حذف الصورة {row['image']} من Supabase")
        except Exception as e:
            print(f"⚠️ لم نتمكن من حذف الصورة من Supabase: {e}")
    
    cursor.execute(f"SELECT filename FROM product_images WHERE product_id = {placeholder}", (pid,))
    extra_images = cursor.fetchall()
    for img in extra_images:
        if supabase and img['filename']:
            try:
                supabase.storage.from_("products").remove([img['filename']])
            except:
                pass
    
    cursor.execute(f"DELETE FROM product_images WHERE product_id = {placeholder}", (pid,))
    cursor.execute(f"DELETE FROM products WHERE id = {placeholder}", (pid,))
    conn.commit()
    conn.close()

    flash("✅ تم حذف المنتج بنجاح.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# ========== Routes لإصلاح قاعدة البيانات ==========
@app.route("/fix-db")
def fix_db():
    try:
        migrate_db()
        return """
        <!DOCTYPE html>
        <html dir="rtl">
        <head><meta charset="UTF-8"><title>إصلاح قاعدة البيانات</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h1>✅ تم إصلاح قاعدة البيانات بنجاح!</h1>
            <p>تم إضافة جميع الأعمدة المطلوبة.</p>
            <hr>
            <a href="/">العودة للصفحة الرئيسية</a>
        </body>
        </html>
        """
    except Exception as e:
        return f"❌ خطأ: {e}"

@app.route("/fix-orders")
def fix_orders():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if USE_POSTGRES:
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS total REAL DEFAULT 0")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_name TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_phone TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_address TEXT")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_notes TEXT")
        else:
            cursor.execute("PRAGMA table_info(orders)")
            columns = cursor.fetchall()
            column_names = [col['name'] for col in columns]
            
            if 'total' not in column_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN total REAL DEFAULT 0")
            if 'customer_name' not in column_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_name TEXT")
            if 'customer_phone' not in column_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_phone TEXT")
            if 'customer_address' not in column_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_address TEXT")
            if 'customer_notes' not in column_names:
                cursor.execute("ALTER TABLE orders ADD COLUMN customer_notes TEXT")
        
        conn.commit()
        conn.close()
        
        return """
        <!DOCTYPE html>
        <html dir="rtl">
        <head><meta charset="UTF-8"><title>إصلاح جدول الطلبات</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h1>✅ تم إصلاح جدول الطلبات بنجاح!</h1>
            <hr>
            <a href="/admin">الذهاب إلى لوحة التحكم</a>
        </body>
        </html>
        """
    except Exception as e:
        return f"❌ خطأ: {e}"

if __name__ == "__main__":
    init_db()
    migrate_db()
    create_admin_user()
    app.run(debug=True, host='0.0.0.0', port=5000)