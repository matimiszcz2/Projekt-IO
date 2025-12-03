from backend.database import db
from datetime import datetime


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    imie = db.Column(db.String(100), nullable=False)
    nazwisko = db.Column(db.String(100), nullable=False)
    stanowisko = db.Column(db.String(100), nullable=False)

    # hash zdjęcia pracownika
    photo_hash = db.Column(db.String(255), nullable=False)

    # wartość zakodowanego QR (np. UUID)
    qr_value = db.Column(db.String(255), unique=True, nullable=False)

    # uprawnienia admina (True = admin)
    is_admin = db.Column(db.Boolean, default=False)

    # relacja do logów
    logs = db.relationship("Log", back_populates="employee", cascade="all, delete")

    def __repr__(self):
        return f"<Employee {self.id} {self.imie} {self.nazwisko}>"
