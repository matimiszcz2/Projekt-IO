from database import db
from datetime import datetime


class Log(db.Model):
    __tablename__ = "logs"

    id = db.Column(db.Integer, primary_key=True)

    # powiązanie z pracownikiem
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)

    # data + czas
    date = db.Column(db.Date, default=datetime.utcnow)
    time = db.Column(db.Time, default=datetime.utcnow)

    # wynik weryfikacji (np. matched / rejected)
    verification_result = db.Column(db.String(50), nullable=False)

    # zdjęcie z próby (hash lub ścieżka)
    attempt_photo_hash = db.Column(db.String(255), nullable=True)

    # status kodu QR (True = poprawny, False = błędny)
    qr_status = db.Column(db.Boolean, default=False)

    # relacja zwrotna
    employee = db.relationship("Employee", back_populates="logs")

    def __repr__(self):
        return f"<Log employee={self.employee_id} result={self.verification_result}>"
