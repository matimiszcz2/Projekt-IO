from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_migrate import Migrate
from flask_cors import CORS
from database import db
from models import Employee, Log
from deepface import DeepFace
import os
import base64
import numpy as np
import cv2
import uuid
from datetime import datetime



def create_app():
    template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../frontend/templates'))
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../frontend'))

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
    user = fake_database.get(qr_code)
    #user = Employee.query.filter_by(qr_value = qr_code).first()
    
    if not user:
        return jsonify({"status": "denied", "message": "Nieznany kod QR"})
    
    if not user['authorized']:
        return jsonify({"status": "denied", "message": "Pracownik zablokowany"})

    known_image_path = os.path.join(KNOWN_FACES_DIR, f"{qr_code}.jpg")
    if not os.path.exists(known_image_path):
        return jsonify({"status": "denied", "message": "Brak zdjęcia wzorcowego w bazie"})

    return jsonify({
        "status": "valid", 
        "message": "Kod OK. Przygotuj się do zdjęcia twarzy...",
        "user_name": user['name']
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
            user = fake_database.get(qr_code)
            print(f"Sukces! Dystans: {result['distance']}")
            #if user.get('is_admin') == True:
            #    session["is_admin"] == True
            #else:
            #    session["is_admin"] == False
            if user['name'] == 'Anna Nowak':
                session["is_admin"] = True
            return jsonify({"status": "granted", "user_name": user['name'], "is_admin":session.get("is_admin")})
            
            
        else:
            print(f"Odmowa. Dystans: {result['distance']}")
            return jsonify({"status": "denied", "message": "Twarz niezgodna z wzorcem."})

    except Exception as e:
        print(f"Błąd serwera: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/admin/reject", methods=["POST"])
def reject_admin():
    session.pop("is_admin", None)
    return jsonify({"status": "revoked"})


@app.route("/admin")
def admin():
    if session.get("is_admin"):
        return render_template("admin.html")
    else:
        return redirect(url_for("index"))

@app.route("/admin/users")
def admin_users():
    if not session.get("is_admin"):
        return redirect(url_for("index"))
    # przykładowe dane użytkowników
    users_list = Employee.query.all()
    
    return render_template("users.html", users=users_list)


@app.route("/admin/users/toggle-admin", methods=["POST"])
def toggle_admin():
    if not session.get("is_admin"):
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
    print("SESSION is_admin =", session.get("is_admin"))

    if not session.get("is_admin"):
        return jsonify({"status": "error", "message": "Brak uprawnień"}), 403

    data = request.get_json()

    new_employee = Employee(
        imie=data["imie"],
        nazwisko=data["nazwisko"],
        stanowisko=data["stanowisko"],
        is_admin=data["is_admin"],
        photo_hash="TEMP",
        qr_value=str(uuid.uuid4())
    )

    db.session.add(new_employee)
    db.session.commit()
    print("ZAPISANO DO BAZY:", new_employee.id)

    return jsonify({"status": "ok"})

@app.route("/admin/users/delete", methods=["POST"])
def delete_user():

    if not session.get("is_admin"):
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




if __name__ == "__main__":
    app.run(debug=True)
