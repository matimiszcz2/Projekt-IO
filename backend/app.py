from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort
from flask_migrate import Migrate
from flask_cors import CORS
from database import db
from models import Employee, Log
from deepface import DeepFace
import base64
import numpy as np
import cv2
import uuid
from datetime import datetime
import hashlib
import qrcode
from fpdf import FPDF
from io import StringIO
import csv
from flask import Response
import os
from io import BytesIO







def create_app():
    template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../frontend/templates'))
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../frontend'))
    DEF_DIR = os.path.join(os.path.dirname(__file__), "def_qr")
    os.makedirs(DEF_DIR, exist_ok=True)  # tworzy folder jeśli nie istnieje

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    CORS(app)

    # konfiguracja bazy danych (SQLite dla łatwości)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
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
        if result['verified']:
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

    # StringIO zamiast BytesIO
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["ID pracownika", "Data/Czas", "Wynik", "QR status", "Ścieżka zdjęcia"])

    for log in logs:
        cw.writerow([log.employee_id, log.date, log.verification_result, log.qr_status, log.attempt_photo_path])

    # Przesuń wskaźnik na początek
    si.seek(0)

    # Flask potrzebuje bajtów, więc zakoduj na utf-8
    return Response(
        si.getvalue(),  # <-- to jest str
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=logs.csv"}
    )



@app.route("/admin/logs/export/pdf")
def export_logs_pdf():
    if not check_admin():
        return redirect(url_for("index"))

    logs = Log.query.all()
    pdf = FPDF()
    pdf.add_page()

    # Dodajemy czcionkę Unicode
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
    pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.add_font("DejaVu", "B", font_path, uni=True)

    pdf.set_font("DejaVu", 'B', 16)
    pdf.cell(0, 10, txt="Raport logów", ln=True, align='C')
    pdf.ln(5)

    # --- Ustawienia tabeli ---
    widths = [20, 55, 46, 25, 50]  # ID, Data/Czas, Wynik, QR, Zdjęcie (zdjęcie większe)
    row_height = 50  # wysokość wiersza danych (mniejsza niż poprzednie 25)
    image_size = 49  # szerokość i wysokość obrazka w mm

    # --- Nagłówki tabeli ---
    headers = ["ID", "Data/Czas", "Wynik", "QR", "Zdjęcie"]
    for i in range(len(headers)):
        pdf.cell(widths[i], 10, headers[i], 1, 0, 'C')
    pdf.ln()  # przejście do wiersza danych

    # --- Dane w tabeli ---
    pdf.set_font("DejaVu", '', 12)
    for log in logs:
        # ID, Data, Wynik, QR
        pdf.cell(widths[0], row_height, str(log.employee_id), 1, 0, 'C')
        pdf.cell(widths[1], row_height, log.date.strftime("%Y-%m-%d %H:%M:%S"), 1, 0, 'C')
        pdf.cell(widths[2], row_height, log.verification_result, 1, 0, 'C')
        pdf.cell(widths[3], row_height, str(log.qr_status), 1, 0, 'C')

        # Zdjęcie
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.cell(widths[4], row_height, "", 1, 0, 'C')  # pusta komórka z ramką

        if log.attempt_photo_path and os.path.exists(log.attempt_photo_path):
            pdf.image(
                os.path.abspath(log.attempt_photo_path).replace("\\", "/"),
                x=x + (widths[4] - image_size) / 2,  # centrowanie obrazka w komórce
                y=y + (row_height - image_size) / 2,
                w=image_size,
                h=image_size
            )

        pdf.ln(row_height)  # przejście do kolejnego wiersza

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name="logs.pdf")


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

@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    if not check_admin():
        return redirect(url_for("index"))

    # Pobieramy aktualne ustawienia z bazy lub pliku (na razie użyjemy prostego słownika)
    SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

    import json
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
    else:
        settings = {
            "threshold": 0.4,          # threshold dla DeepFace
            "camera_enabled": True,
            "qr_scanner_enabled": True
        }

    if request.method == "POST":
        data = request.get_json()
        settings["threshold"] = float(data.get("threshold", settings["threshold"]))
        settings["camera_enabled"] = bool(data.get("camera_enabled", settings["camera_enabled"]))
        settings["qr_scanner_enabled"] = bool(data.get("qr_scanner_enabled", settings["qr_scanner_enabled"]))

        # zapisujemy do pliku
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)

        return jsonify({"status": "ok", "settings": settings})

    return render_template("settings.html", settings=settings)


if __name__ == "__main__":
    app.run(debug=True)
