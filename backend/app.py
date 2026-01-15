from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort
from flask_migrate import Migrate
from flask_cors import CORS
from database import db
from models import Employee, Log
from deepface import DeepFace
import base64
import numpy as np
import cv2
from datetime import datetime
import hashlib
import qrcode
from fpdf import FPDF
from io import StringIO
import csv
from flask import Response
import os
from io import BytesIO


PERCENTAGE_THRESHOLD = 10
CAMERA_ENABLED = True
QR_SCANNER_ENABLED = True

def create_app():
    template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../frontend/templates'))
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../frontend'))
    DEF_DIR = os.path.join(os.path.dirname(__file__), "def_qr")
    os.makedirs(DEF_DIR, exist_ok=True)  # tworzy folder jeśli nie istnieje

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    CORS(app)

    # konfiguracja bazy danych (stara baza w backend/instance)
    db_path = os.path.join(os.path.dirname(__file__), "instance", "database.db")  # backend/instance/database.db
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "super-secret-key"

    db.init_app(app)
    Migrate(app, db)

    with app.app_context():
        db.create_all()

        admin_exists = Employee.query.filter_by(is_admin=True).first()

        if not admin_exists:
            default_admin = Employee(
                imie="Admin",
                nazwisko="System",
                stanowisko="Administrator",
                is_admin=True,
                qr_value="1234567890",
                photo_hash=None
            )
            if default_admin:
                db.session.add(default_admin)
                db.session.commit()
                qr = qrcode.make(default_admin.qr_value)

                filename = f"QR_{default_admin.imie}_{default_admin.nazwisko}.png"
                file_path = os.path.join(DEF_DIR, filename)
                qr.save(file_path)


    
                        

    @app.route("/")
    def index():
        return render_template("base.html")

    return app


app = create_app()

fake_database = {
    "12345": { "name": "Jan Kowalski", "authorized": True },
    "ADMIN": { "name": "Anna Nowak", "authorized": True },
    "GUEST": { "name": "Gość", "authorized": False }
}

KNOWN_FACES_DIR = os.path.join(os.path.dirname(__file__), 'known_faces')

LOG_QR_DIR = os.path.join(os.path.dirname(__file__), 'scans', 'qr')
LOG_FACE_DIR = os.path.join(os.path.dirname(__file__), 'scans', 'faces')
os.makedirs(LOG_QR_DIR, exist_ok=True)
os.makedirs(LOG_FACE_DIR, exist_ok=True)

# funkcja generująca hash do kodu qr
def generate_qr_hash(imie, nazwisko, employee_id=None):
    base = f"{imie}|{nazwisko}|{employee_id}|{datetime.now().isoformat()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

# Funkcja pomocnicza do dekodowania i zapisu obrazu
def decode_and_save_image(image_b64, folder, prefix):
    """Dekoduje Base64 i zapisuje plik na dysku. Zwraca ścieżkę do pliku."""
    try:
        if "," in image_b64:
            header, encoded = image_b64.split(",", 1)
        else:
            encoded = image_b64
            
        binary_data = base64.b64decode(encoded)
        
        # Generowanie nazwy pliku
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.jpg"
        file_path = os.path.join(folder, filename)
        
        with open(file_path, "wb") as f:
            f.write(binary_data)
            
        return file_path
    except Exception as e:
        print(f"Błąd zapisu obrazu: {e}")
        return None
    
    from flask import abort

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return Employee.query.get(user_id)


def check_admin():
    user_id = session.get("user_id")
    if not user_id:
        return False
    else:
        user = Employee.query.get(user_id)
        if user:
            return (user.is_admin and user.is_active)
        else: return False
    


# --- KROK 1: Odbiór zdjęcia kodu QR i weryfikacja danych ---
@app.route('/api/check-qr', methods=['POST'])
def check_qr():
    data = request.get_json()
    qr_code = data.get('qr_code')
    image_qr_b64 = data.get('image_qr') # Oczekujemy zdjęcia QR

    if not qr_code:
        return jsonify({"status": "error", "message": "Brak kodu QR"}), 400

    # 1. Zapisujemy zdjęcie QR na dysku (dowód, że zrobiono osobne zdjęcie)
    if image_qr_b64:
        decode_and_save_image(image_qr_b64, LOG_QR_DIR, f"QR_{qr_code}")

    # 2. Logika biznesowa
   # user = fake_database.get(qr_code)
    user = Employee.query.filter_by(qr_value=qr_code).first()
    
    if not user:
        return jsonify({"status": "denied", "message": "Nieznany kod QR"})
    
    #if not user['authorized']:
     #   return jsonify({"status": "denied", "message": "Pracownik zablokowany"})
    if not user.is_active:
        new_log = Log(
            employee_id = user.id,
            date = datetime.now(),
            verification_result = "Odmowa",
            qr_status = False
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"status": "denied", "message": "Pracownik zablokowany"})
        

    known_image_path = os.path.join(KNOWN_FACES_DIR, f"{qr_code}.jpg")
    if not os.path.exists(known_image_path):
        new_log = Log(
            employee_id = user.id,
            date = datetime.now(),
            verification_result = "Odmowa - brak zdjęcia",
            qr_status = True
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"status": "denied", "message": "Brak zdjęcia wzorcowego w bazie"})

    
    return jsonify({
        "status": "valid", 
        "message": "Kod OK. Przygotuj się do zdjęcia twarzy...",
        "user_name": user.imie
    })


# KROK 2: Weryfikacja twarzy (DeepFace)
@app.route('/api/verify-face', methods=['POST'])
def verify_face():
    try:
        data = request.get_json()
        qr_code = data.get('qr_code')
        image_face_b64 = data.get('image_face')

        if not qr_code or not image_face_b64:
            return jsonify({"status": "error", "message": "Brak danych"}), 400

        # 1. Zapisujemy zdjęcie z kamery do pliku tymczasowego
        # DeepFace najlepiej działa na ścieżkach do plików
        target_path = decode_and_save_image(image_face_b64, LOG_FACE_DIR, f"FACE_{qr_code}")

        if not target_path:
            return jsonify({"status": "error", "message": "Błąd zapisu zdjęcia"}), 500

        # 2. Ścieżka do zdjęcia wzorcowego
        source_path = os.path.join(KNOWN_FACES_DIR, f"{qr_code}.jpg")

        # 3. Uruchomienie DeepFace
        # Przy pierwszym uruchomieniu pobierze wagi modelu (ok. 500MB) - może chwilę potrwać!
        try:
            result = DeepFace.verify(
                img1_path = target_path,
                img2_path = source_path,
                model_name = "VGG-Face", # Bardzo dokładny model
                detector_backend = "opencv", # Szybki detektor twarzy
                enforce_detection = False, # Nie wyrzucaj błędu jak nie znajdzie twarzy (zwróci verified: False)
                align = True
            )
        except Exception as e:
            print(f"DeepFace Exception: {e}")
            # Czasem DeepFace rzuca błąd jak zdjęcie jest bardzo niewyraźne
            return jsonify({"status": "denied", "message": "Nie udało się przetworzyć twarzy"}), 200

        # 4. Interpretacja wyniku
        distance = result["distance"]
        similarity_threshold = 1 - PERCENTAGE_THRESHOLD/100
        if distance <= similarity_threshold:

            #user = fake_database.get(qr_code)
            user = Employee.query.filter_by(qr_value=qr_code).first()

            print(f"Sukces! Dystans: {result['distance']}")
            new_log = Log(
                employee_id = user.id,
                date = datetime.now(),
                verification_result = "Dostęp przyznany",
                attempt_photo_path = target_path,
                qr_status = True,
                similarity=1-result.get('distance')  # <-- zapisujemy similarity
            )
            db.session.add(new_log)
            db.session.commit()
            #if user.get('is_admin') == True:
            #    session["is_admin"] == True
            #else:
            #    session["is_admin"] == False
            if user.is_admin:
                session.clear()
                session["user_id"] = user.id   # ← zapisujemy KONKRETNEGO usera
            return jsonify({"status": "granted", "user_name": user.imie, "is_admin":user.is_admin})


        else:
            session.clear()
            print(f"Odmowa. Dystans: {result['distance']}")
            try:
                user = Employee.query.filter_by(qr_value=qr_code).first()
                new_log = Log(
                    employee_id = user.id,
                    date = datetime.now(),
                    verification_result = "Odmowa - twarz",
                    attempt_photo_path = target_path,
                    qr_status = True,
                    similarity=1-result.get('distance')  # <-- zapisujemy similarity
                )
                db.session.add(new_log)
                db.session.commit()
            except Exception as e:
                print("dupa zbita")



            return jsonify({"status": "denied", "message": "Twarz niezgodna z wzorcem."})

    except Exception as e:
        print(f"Błąd serwera: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # ---- POST ----

    data = request.get_json(silent=True)

    if data:
        # LOGIN PRZEZ FETCH (JSON)
        username = data.get("username")
        password = data.get("password")
    else:
        # LOGIN PRZEZ FORMULARZ HTML
        username = request.form.get("username")
        password = request.form.get("password")

    if not username or not password:
        return jsonify({"status": "error", "message": "Brak danych"}), 400

    admin = Employee.query.filter_by(imie=username, is_admin=True).first()

    if not admin:
        return jsonify({"status": "error", "message": "Brak użytkownika"}), 401
    
    if password != "secret":
        return jsonify({"status": "error", "message": "Błędne hasło"}), 401

    if not admin.is_active:
        return jsonify({"status": "error", "message": "Konto nieaktywne"}), 403

    session.clear()
    session["user_id"] = admin.id

    return jsonify({"status": "ok"})






@app.route("/admin")
def admin():
    if check_admin():
        return render_template("admin.html")
    else:
        return redirect(url_for("index"))
    

@app.route("/admin/reject", methods=["POST"])
def reject_admin():
    session.clear()
    return jsonify({"status": "revoked"})

@app.route("/admin/users")
def admin_users():
    if not check_admin():
        return redirect(url_for("index"))
    # przykładowe dane użytkowników
    users_list = Employee.query.all()
    
    return render_template("users.html", users=users_list)


@app.route("/admin/users/toggle-admin", methods=["POST"])
def toggle_admin():
    if not check_admin():
        return jsonify({"message": "Brak uprawnień"}), 403

    data = request.get_json()
    user = Employee.query.get(data["user_id"])

    if not user:
        return jsonify({"message": "Użytkownik nie istnieje"}), 404

    user.is_admin = not user.is_admin
    db.session.commit()

    return jsonify({
        "message": f"Zmieniono uprawnienia admina dla {user.imie} {user.nazwisko}",
        "is_admin": user.is_admin
    })

@app.route("/admin/users/add", methods=["POST"])
def add_user():
    if not check_admin():
        return jsonify({"status": "error", "message": "Brak uprawnień"}), 403

    data = request.get_json()

    new_employee = Employee(
        imie=data["imie"],
        nazwisko=data["nazwisko"],
        stanowisko=data["stanowisko"],
        is_admin=data["is_admin"],
        photo_hash=None,
        qr_value=None
    )

    db.session.add(new_employee)
    db.session.commit()  # potrzebne, żeby dostać ID

    # generujemy hash QR (z ID)
    new_qr = generate_qr_hash(
        new_employee.imie,
        new_employee.nazwisko,
        new_employee.id
    )

    new_employee.qr_value = new_qr
    db.session.commit()

    return jsonify({"status": "ok"})

@app.route("/admin/users/delete", methods=["POST"])
def delete_user():
    if not check_admin():
        return jsonify({"status": "error", "message": "Brak uprawnień"}), 403

    data = request.get_json()
    user = Employee.query.get(data["user_id"])

    if not user:
        return jsonify({"message": "Użytkownik nie istnieje"}), 404
    db.session.delete(user)
    db.session.commit()
    print("usunięto:", user.id)


    return jsonify({
        "status": "ok",
        "message": f"usunieto {user.imie} {user.nazwisko}",
    })

@app.route("/admin/users/qr/<int:user_id>")
def download_qr(user_id):
    if not check_admin():
        return redirect(url_for("index"))

    user = Employee.query.get_or_404(user_id)

    qr = qrcode.make(user.qr_value)
    buf = BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)

    filename = f"QR_{user.imie}_{user.nazwisko}.png"

    return send_file(
        buf,
        mimetype="image/png",
        as_attachment=True,
        download_name=filename
    )

@app.route("/admin/users/regenerate-qr/", methods=["POST"])
def regenerate_qr():
    if not check_admin():
            return jsonify({"status": "error", "message": "Brak uprawnień"}), 403


    data = request.get_json()
    user = Employee.query.get(data["user_id"])
    A = user.qr_value+".jpg"
    B = KNOWN_FACES_DIR
    
    new_qr = generate_qr_hash(
        user.imie,
        user.nazwisko,
        user.id
    )

    user.qr_value = new_qr
    C = new_qr+".jpg"
    old_path = os.path.join(B, A)
    new_path = os.path.join(B, C)

    if os.path.exists(old_path):
        os.rename(old_path, new_path)
    
    db.session.commit()
    return jsonify({
        "status": "ok"
    })

@app.route("/admin/users/upload-face", methods=["POST"])
def upload_face():
    if not check_admin():
        return jsonify({"status": "error", "message": "Brak uprawnień"}), 403

    file = request.files.get("photo")
    user_id = request.form.get("user_id")

    if not file or not user_id:
        return jsonify({"status": "error", "message": "Brak danych"}), 400

    # Pobierz użytkownika
    employee = Employee.query.get(user_id)
    if not employee:
        return jsonify({"status": "error", "message": "Użytkownik nie istnieje"}), 404

    # Wczytaj obraz do OpenCV
    npimg = np.frombuffer(file.read(), np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

    # Próba wykrycia twarzy przez DeepFace
    try:
        # enforce_detection=True wymusza, żeby DeepFace znalazł twarz
        _ = DeepFace.extract_faces(img, detector_backend="opencv", enforce_detection=True)
    except Exception as e:
        return jsonify({"status": "error", "message": "Nie wykryto twarzy na zdjęciu"}), 400

    # Zapis pliku w folderze known_faces z nazwą <qr_value>.jpg
    save_path = os.path.join(KNOWN_FACES_DIR, f"{employee.qr_value}.jpg")
    cv2.imwrite(save_path, img)
    employee.last_photo_update = datetime.now()
    db.session.commit()
    return jsonify({"status": "ok", "message": "Zdjęcie zapisane i twarz wykryta"})

@app.route("/admin/users/deactivate-employee", methods=["POST"])
def deactivate_employee():
    if not check_admin():
        return jsonify({"message": "Brak uprawnień"}), 403

    data = request.get_json()
    user = Employee.query.get(data["user_id"])

    if not user:
        return jsonify({"message": "Użytkownik nie istnieje"}), 404

    user.is_active = not user.is_active
    db.session.commit()

    return jsonify({
        "is_active":user.is_active,
        "status":"ok"
    })

@app.route("/uploads/faces/<filename>")
def uploaded_face(filename):
    face_path = os.path.join(LOG_FACE_DIR, filename)
    if os.path.exists(face_path):
        return send_file(face_path, mimetype="image/jpeg")
    else:
        abort(404)

@app.route("/uploads/known_faces/<filename>")
def known_face(filename):
    face_path = os.path.join(KNOWN_FACES_DIR, filename)
    if os.path.exists(face_path):
        return send_file(face_path, mimetype="image/jpeg")
    else:
        abort(404)


@app.route("/admin/statistics")
def admin_statistics():
    if not check_admin():
        return redirect(url_for("index"))

    logs = Log.query.order_by(Log.date.desc()).all()
    # dodajemy photo_url do każdego logu

    for log in logs:
        # Miniatura zdjęcia logu
        if log.attempt_photo_path and os.path.exists(log.attempt_photo_path):
            filename = os.path.basename(log.attempt_photo_path)
            log.photo_url = url_for("uploaded_face", filename=filename)
        else:
            log.photo_url = None

        # Zdjęcie wzorcowe
        known_path = os.path.join(KNOWN_FACES_DIR, f"{log.employee.qr_value}.jpg")
        if os.path.exists(known_path):
            log.template_photo_url = url_for("known_face", filename=f"{log.employee.qr_value}.jpg")
        else:
            log.template_photo_url = None

    return render_template("statistics.html", logs=logs)


@app.route("/admin/logs/export/csv")
def export_logs_csv():
    if not check_admin():
        return redirect(url_for("index"))

    logs = Log.query.all()

    # Dodajemy tymczasowe pola photo_url i template_photo_url
    for log in logs:
        log.photo_url = log.attempt_photo_path if log.attempt_photo_path and os.path.exists(log.attempt_photo_path) else "Brak"
        known_path = os.path.join(KNOWN_FACES_DIR, f"{log.employee.qr_value}.jpg")
        log.template_photo_url = known_path if os.path.exists(known_path) else "Brak"

    # StringIO z UTF-8
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow([
        "ID pracownika",
        "Data/Czas",
        "Status QR",
        "Wynik weryfikacji",
        "Podobieństwo",
    ])

    for log in logs:
        similarity_text = f"{log.similarity * 100:.2f}%" if log.similarity is not None else "-"
        cw.writerow([
            log.employee_id,
            log.date.strftime("%Y-%m-%d %H:%M:%S"),
            "Zgodne" if log.qr_status else "Niezgodne",
            log.verification_result,
            similarity_text,
        ])

    si.seek(0)
    csv_data = si.getvalue()

    # Dodaj BOM dla Excela
    bom = "\ufeff"
    csv_data = bom + csv_data

    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment;filename=statystyki_logow.csv"}
    )





@app.route("/admin/logs/export/pdf")
def export_logs_pdf():
    if not check_admin():
        return redirect(url_for("index"))

    logs = Log.query.all()

    # --- Dodanie tymczasowych pól ---
    for log in logs:
        log.photo_url = log.attempt_photo_path if log.attempt_photo_path and os.path.exists(log.attempt_photo_path) else None
        log.template_photo_url = os.path.join(KNOWN_FACES_DIR, f"{log.employee.qr_value}.jpg")
        if not os.path.exists(log.template_photo_url):
            log.template_photo_url = None

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()

    # Czcionka Unicode
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.add_font("DejaVu", "B", font_path, uni=True)

    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, "Statystyki logów wejścia", ln=True, align="C")
    pdf.ln(5)

    # Nagłówki tabeli
    pdf.set_font("DejaVu", "B", 10)
    widths = [30, 45, 30, 55, 25, 45, 45]
    headers = ["ID pracownika","Data/Czas","Status QR","Wynik weryfikacji","Podobieństwo","Zdjęcie logu","Zdjęcie wzorcowe"]
    for w, h in zip(widths, headers):
        pdf.cell(w, 10, h, 1, 0, "C")
    pdf.ln()

    # Dane
    pdf.set_font("DejaVu", "", 9)
    row_height = 35
    img_size = 30

    for log in logs:
        pdf.cell(widths[0], row_height, str(log.employee_id), 1, 0, "C")
        pdf.cell(widths[1], row_height, log.date.strftime("%Y-%m-%d %H:%M:%S"), 1, 0, "C")
        pdf.cell(widths[2], row_height, "Zgodne" if log.qr_status else "Niezgodne", 1, 0, "C")
        pdf.cell(widths[3], row_height, log.verification_result, 1, 0, "C")
        similarity_text = f"{log.similarity * 100:.2f}%" if log.similarity is not None else "-"
        pdf.cell(widths[4], row_height, similarity_text, 1, 0, "C")

        # Zdjęcie logu
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.cell(widths[5], row_height, "", 1)
        if log.photo_url:
            pdf.image(log.photo_url, x + 2, y + 2, w=img_size, h=img_size)

        # Zdjęcie wzorcowe
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.cell(widths[6], row_height, "", 1)
        if log.template_photo_url:
            pdf.image(log.template_photo_url, x + 2, y + 2, w=img_size, h=img_size)

        pdf.ln(row_height)

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="statystyki_logow.pdf"
    )






@app.route("/admin/logs/reset", methods=["POST"])
def reset_logs():
    logs = Log.query.all()
    print("Logów przed usunięciem:", len(logs))

    for log in logs:
        if log.attempt_photo_path and os.path.exists(log.attempt_photo_path):
            os.remove(log.attempt_photo_path)
            print("Usunięto zdjęcie:", log.attempt_photo_path)

    Log.query.delete()
    db.session.commit()
    print("Wszystkie logi zostały usunięte.")
    return jsonify({"status": "ok", "message": "Wszystkie logi zostały usunięte."})

@app.route("/admin/settings", methods=["POST"])
def save_admin_settings():
    global PERCENTAGE_THRESHOLD, CAMERA_ENABLED, QR_SCANNER_ENABLED

    data = request.json

    PERCENTAGE_THRESHOLD = float(data["threshold"])
    CAMERA_ENABLED = bool(data["camera_enabled"])
    QR_SCANNER_ENABLED = bool(data["qr_scanner_enabled"])

    return jsonify({"status": "ok"})

@app.route("/admin/settings", methods=["GET"])
def admin_settings():
    settings = {
        "threshold": PERCENTAGE_THRESHOLD,
        "camera_enabled": CAMERA_ENABLED,
        "qr_scanner_enabled": QR_SCANNER_ENABLED
    }
    return render_template("settings.html", settings=settings)


@app.route("/admin/settings/threshold", methods=["GET", "POST"])
def threshold_settings():
    global PERCENTAGE_THRESHOLD

    if request.method == "POST":
        data = request.json
        PERCENTAGE_THRESHOLD = float(data["threshold"])
        return jsonify({"status": "ok", "threshold": PERCENTAGE_THRESHOLD})

    return jsonify({"threshold": PERCENTAGE_THRESHOLD})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    global PERCENTAGE_THRESHOLD, CAMERA_ENABLED, QR_SCANNER_ENABLED
    return jsonify({
        "threshold": PERCENTAGE_THRESHOLD,
        "camera_enabled": CAMERA_ENABLED,
        "qr_scanner_enabled": QR_SCANNER_ENABLED
    })

@app.route("/admin/settings/export")
def export_database_pdf():
    if not check_admin():
        return redirect(url_for("index"))

    # --- Pobranie danych ---
    employees = Employee.query.order_by(Employee.id).all()
    logs = Log.query.order_by(Log.date.desc()).all()

    # --- Dodanie tymczasowych pól dla logów ---
    for log in logs:
        log.photo_url = log.attempt_photo_path if log.attempt_photo_path and os.path.exists(log.attempt_photo_path) else None
        known_path = os.path.join(KNOWN_FACES_DIR, f"{log.employee.qr_value}.jpg")
        log.template_photo_url = known_path if os.path.exists(known_path) else None

    # --- Tworzenie PDF ---
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()

    # Czcionka Unicode
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.add_font("DejaVu", "B", font_path, uni=True)

    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, "Raport pełnej bazy danych", ln=True, align="C")
    pdf.ln(5)

    # --- Sekcja Employees ---
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(0, 10, "Tabela Employees", ln=True)
    pdf.set_font("DejaVu", "B", 8)

    # Nagłówki tabeli
    emp_widths = [7, 20, 25, 25, 20, 120, 17, 15, 35]  # dopasowane do kolumn
    emp_headers = ["ID","Imię","Nazwisko","Stanowisko","Photo Hash","QR Value","Admin","Aktywny","Ostatni Update"]
    for w, h in zip(emp_widths, emp_headers):
        pdf.cell(w, 10, h, 1, 0, "C")
    pdf.ln()

    pdf.set_font("DejaVu", "", 8)
    row_height = 8

    for emp in employees:
        pdf.cell(emp_widths[0], row_height, str(emp.id), 1, 0, "C")
        pdf.cell(emp_widths[1], row_height, emp.imie, 1, 0, "C")
        pdf.cell(emp_widths[2], row_height, emp.nazwisko, 1, 0, "C")
        pdf.cell(emp_widths[3], row_height, emp.stanowisko, 1, 0, "C")
        pdf.cell(emp_widths[4], row_height, emp.photo_hash if emp.photo_hash else "-", 1, 0, "C")
        pdf.cell(emp_widths[5], row_height, emp.qr_value if emp.qr_value else "-", 1, 0, "C")
        pdf.cell(emp_widths[6], row_height, "Tak" if emp.is_admin else "Nie", 1, 0, "C")
        pdf.cell(emp_widths[7], row_height, "Tak" if emp.is_active else "Nie", 1, 0, "C")
        pdf.cell(emp_widths[8], row_height, emp.last_photo_update.strftime("%Y-%m-%d %H:%M:%S") if emp.last_photo_update else "-", 1, 0, "C")
        pdf.ln()

    pdf.ln(5)

    # --- Sekcja Logs ---
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 10, "Tabela Logs", ln=True)
    pdf.set_font("DejaVu", "B", 10)

    log_widths = [30, 45, 30, 55, 25, 45, 45]
    log_headers = ["ID pracownika","Data/Czas","Status QR","Wynik weryfikacji","Podobieństwo","Zdjęcie logu","Zdjęcie wzorcowe"]
    for w, h in zip(log_widths, log_headers):
        pdf.cell(w, 10, h, 1, 0, "C")
    pdf.ln()

    pdf.set_font("DejaVu", "", 9)
    row_height = 35
    img_size = 30

    for log in logs:
        pdf.cell(log_widths[0], row_height, str(log.employee_id), 1, 0, "C")
        pdf.cell(log_widths[1], row_height, log.date.strftime("%Y-%m-%d %H:%M:%S"), 1, 0, "C")
        pdf.cell(log_widths[2], row_height, "Zgodne" if log.qr_status else "Niezgodne", 1, 0, "C")
        pdf.cell(log_widths[3], row_height, log.verification_result, 1, 0, "C")
        similarity_text = f"{log.similarity * 100:.2f}%" if log.similarity is not None else "-"
        pdf.cell(log_widths[4], row_height, similarity_text, 1, 0, "C")

        x = pdf.get_x()
        y = pdf.get_y()
        pdf.cell(log_widths[5], row_height, "", 1)
        if log.photo_url:
            pdf.image(log.photo_url, x + 2, y + 2, w=img_size, h=img_size)

        x = pdf.get_x()
        y = pdf.get_y()
        pdf.cell(log_widths[6], row_height, "", 1)
        if log.template_photo_url:
            pdf.image(log.template_photo_url, x + 2, y + 2, w=img_size, h=img_size)

        pdf.ln(row_height)

    # --- Zwrócenie PDF ---
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="full_database_report.pdf"
    )




if __name__ == "__main__":
    app.run(debug=True)
