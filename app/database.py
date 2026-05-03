from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/feuerwehr.db")

# Sicherstellen, dass das Datenbankverzeichnis existiert
if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

# Für SQLite müssen wir check_same_thread=False setzen
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# --- Modelle ---

class Mitglied(Base):
    __tablename__ = "mitglieder"
    
    id = Column(Integer, primary_key=True, index=True)
    dienstnummer = Column(String, unique=True, index=True)
    vorname = Column(String, nullable=False)
    nachname = Column(String, nullable=False)
    geburtsdatum = Column(String)
    eintrittsdatum = Column(String)
    funktion = Column(String)  # z.B. "Kommandant", "Maschinist", "Mannschaft"
    status = Column(String, default="aktiv")  # aktiv, inaktiv, ehrenmitglied
    telefon = Column(String)
    email = Column(String)
    adresse = Column(Text)
    notizen = Column(Text)
    erstellt_am = Column(DateTime, default=datetime.utcnow)
    
    einsaetze = relationship("EinsatzMitglied", back_populates="mitglied")

class Fahrzeug(Base):
    __tablename__ = "fahrzeuge"
    
    id = Column(Integer, primary_key=True, index=True)
    kennzeichen = Column(String, unique=True, index=True)
    bezeichnung = Column(String, nullable=False)  # z.B. "RLF-A 2000", "TLF 3000"
    marke = Column(String)
    typ = Column(String)
    baujahr = Column(Integer)
    sitzplaetze = Column(Integer)
    status = Column(String, default="einsatzbereit")  # einsatzbereit, werkstatt, außer dienst
    letzte_inspektion = Column(String)
    naechste_inspektion = Column(String)
    notizen = Column(Text)
    erstellt_am = Column(DateTime, default=datetime.utcnow)
    
    einsaetze = relationship("EinsatzFahrzeug", back_populates="fahrzeug")

class Einsatz(Base):
    __tablename__ = "einsaetze"
    
    id = Column(Integer, primary_key=True, index=True)
    einsatznummer = Column(String, unique=True, index=True)
    alarmierung = Column(DateTime, default=datetime.utcnow)
    einsatzende = Column(DateTime)
    stichwort = Column(String, nullable=False)  # z.B. "B1", "B2", "TH1"
    beschreibung = Column(Text)
    adresse = Column(Text, nullable=False)
    ort = Column(String)
    melder = Column(String)
    bericht = Column(Text)
    status = Column(String, default="offen")  # offen, abgeschlossen
    erstellt_am = Column(DateTime, default=datetime.utcnow)
    
    mitglieder = relationship("EinsatzMitglied", back_populates="einsatz")
    fahrzeuge = relationship("EinsatzFahrzeug", back_populates="einsatz")

class EinsatzMitglied(Base):
    __tablename__ = "einsatz_mitglieder"
    
    id = Column(Integer, primary_key=True, index=True)
    einsatz_id = Column(Integer, ForeignKey("einsaetze.id"))
    mitglied_id = Column(Integer, ForeignKey("mitglieder.id"))
    rolle = Column(String)  # z.B. "Fahrzeugführer", "Angriffstrupp", "Wassertrupp"
    
    einsatz = relationship("Einsatz", back_populates="mitglieder")
    mitglied = relationship("Mitglied", back_populates="einsaetze")

class EinsatzFahrzeug(Base):
    __tablename__ = "einsatz_fahrzeuge"
    
    id = Column(Integer, primary_key=True, index=True)
    einsatz_id = Column(Integer, ForeignKey("einsaetze.id"))
    fahrzeug_id = Column(Integer, ForeignKey("fahrzeuge.id"))
    
    einsatz = relationship("Einsatz", back_populates="fahrzeuge")
    fahrzeug = relationship("Fahrzeug", back_populates="einsaetze")

# Datenbanktabellen erstellen
Base.metadata.create_all(bind=engine)

# Dependency für DB-Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
