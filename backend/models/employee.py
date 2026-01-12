from database import db
from datetime import datetime


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    imie = db.Column(db.String(100), nullable=False)
    nazwisko = db.Column(db.String(100), nullable=False)
    stanowisko = db.Column(db.String(100), nullable=False)

    # hash zdjęcia pracownika
    photo_hash = db.Column(db.String(255), nullable=True)

    # wartość zakodowanego QR (np. UUID)
    qr_value = db.Column(db.String(255), unique=True, nullable=True)

    # uprawnienia admina (True = admin)
    is_admin = db.Column(db.Boolean, default=False)

    # czy aktywny
    is_active = db.Column(db.Boolean, default = True)
    # data ostatniego update zdjecia
    last_photo_update = db.Column(db.DateTime, nullable = True)
    # relacja do logów
    logs = db.relationship("Log", back_populates="employee", cascade="all, delete")

    def __repr__(self):
        return f"<Employee {self.id} {self.imie} {self.nazwisko}>"
