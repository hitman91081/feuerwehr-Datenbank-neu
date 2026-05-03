from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import os

from app.database import get_db, engine
from app.database import Mitglied, Fahrzeug, Einsatz, EinsatzMitglied, EinsatzFahrzeug

app = FastAPI(title="Feuerwehr Datenbank", version="1.0.0")

# Statische Dateien (Frontend)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- Pydantic Schemas ---

class MitgliedCreate(BaseModel):
    dienstnummer: str
    vorname: str
    nachname: str
    geburtsdatum: Optional[str] = None
    eintrittsdatum: Optional[str] = None
    funktion: Optional[str] = None
    status: Optional[str] = "aktiv"
    telefon: Optional[str] = None
    email: Optional[str] = None
    adresse: Optional[str] = None
    notizen: Optional[str] = None

class MitgliedResponse(MitgliedCreate):
    id: int
    class Config:
        from_attributes = True

class FahrzeugCreate(BaseModel):
    kennzeichen: str
    bezeichnung: str
    marke: Optional[str] = None
    typ: Optional[str] = None
    baujahr: Optional[int] = None
    sitzplaetze: Optional[int] = None
    status: Optional[str] = "einsatzbereit"
    letzte_inspektion: Optional[str] = None
    naechste_inspektion: Optional[str] = None
    notizen: Optional[str] = None

class FahrzeugResponse(FahrzeugCreate):
    id: int
    class Config:
        from_attributes = True

class EinsatzCreate(BaseModel):
    einsatznummer: str
    stichwort: str
    beschreibung: Optional[str] = None
    adresse: str
    ort: Optional[str] = None
    melder: Optional[str] = None
    status: Optional[str] = "offen"

class EinsatzResponse(EinsatzCreate):
    id: int
    alarmierung: Optional[str] = None
    class Config:
        from_attributes = True

# --- Frontend Route ---

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
async def health():
    return {"status": "ok"}

# --- API Endpoints: Mitglieder ---

@app.get("/api/mitglieder", response_model=List[MitgliedResponse])
def get_mitglieder(db: Session = Depends(get_db)):
    return db.query(Mitglied).all()

@app.post("/api/mitglieder", response_model=MitgliedResponse)
def create_mitglied(mitglied: MitgliedCreate, db: Session = Depends(get_db)):
    db_mitglied = Mitglied(**mitglied.model_dump())
    db.add(db_mitglied)
    db.commit()
    db.refresh(db_mitglied)
    return db_mitglied

@app.get("/api/mitglieder/{mitglied_id}", response_model=MitgliedResponse)
def get_mitglied(mitglied_id: int, db: Session = Depends(get_db)):
    m = db.query(Mitglied).filter(Mitglied.id == mitglied_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    return m

@app.put("/api/mitglieder/{mitglied_id}", response_model=MitgliedResponse)
def update_mitglied(mitglied_id: int, mitglied: MitgliedCreate, db: Session = Depends(get_db)):
    m = db.query(Mitglied).filter(Mitglied.id == mitglied_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    for key, value in mitglied.model_dump().items():
        setattr(m, key, value)
    db.commit()
    db.refresh(m)
    return m

@app.delete("/api/mitglieder/{mitglied_id}")
def delete_mitglied(mitglied_id: int, db: Session = Depends(get_db)):
    m = db.query(Mitglied).filter(Mitglied.id == mitglied_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    db.delete(m)
    db.commit()
    return {"ok": True}

# --- API Endpoints: Fahrzeuge ---

@app.get("/api/fahrzeuge", response_model=List[FahrzeugResponse])
def get_fahrzeuge(db: Session = Depends(get_db)):
    return db.query(Fahrzeug).all()

@app.post("/api/fahrzeuge", response_model=FahrzeugResponse)
def create_fahrzeug(fahrzeug: FahrzeugCreate, db: Session = Depends(get_db)):
    db_fahrzeug = Fahrzeug(**fahrzeug.model_dump())
    db.add(db_fahrzeug)
    db.commit()
    db.refresh(db_fahrzeug)
    return db_fahrzeug

@app.get("/api/fahrzeuge/{fahrzeug_id}", response_model=FahrzeugResponse)
def get_fahrzeug(fahrzeug_id: int, db: Session = Depends(get_db)):
    f = db.query(Fahrzeug).filter(Fahrzeug.id == fahrzeug_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
    return f

@app.put("/api/fahrzeuge/{fahrzeug_id}", response_model=FahrzeugResponse)
def update_fahrzeug(fahrzeug_id: int, fahrzeug: FahrzeugCreate, db: Session = Depends(get_db)):
    f = db.query(Fahrzeug).filter(Fahrzeug.id == fahrzeug_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
    for key, value in fahrzeug.model_dump().items():
        setattr(f, key, value)
    db.commit()
    db.refresh(f)
    return f

@app.delete("/api/fahrzeuge/{fahrzeug_id}")
def delete_fahrzeug(fahrzeug_id: int, db: Session = Depends(get_db)):
    f = db.query(Fahrzeug).filter(Fahrzeug.id == fahrzeug_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Fahrzeug nicht gefunden")
    db.delete(f)
    db.commit()
    return {"ok": True}

# --- API Endpoints: Einsätze ---

@app.get("/api/einsaetze", response_model=List[EinsatzResponse])
def get_einsaetze(db: Session = Depends(get_db)):
    return db.query(Einsatz).order_by(Einsatz.alarmierung.desc()).all()

@app.post("/api/einsaetze", response_model=EinsatzResponse)
def create_einsatz(einsatz: EinsatzCreate, db: Session = Depends(get_db)):
    db_einsatz = Einsatz(**einsatz.model_dump())
    db.add(db_einsatz)
    db.commit()
    db.refresh(db_einsatz)
    return db_einsatz

@app.get("/api/einsaetze/{einsatz_id}", response_model=EinsatzResponse)
def get_einsatz(einsatz_id: int, db: Session = Depends(get_db)):
    e = db.query(Einsatz).filter(Einsatz.id == einsatz_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")
    return e

@app.put("/api/einsaetze/{einsatz_id}", response_model=EinsatzResponse)
def update_einsatz(einsatz_id: int, einsatz: EinsatzCreate, db: Session = Depends(get_db)):
    e = db.query(Einsatz).filter(Einsatz.id == einsatz_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")
    for key, value in einsatz.model_dump().items():
        setattr(e, key, value)
    db.commit()
    db.refresh(e)
    return e

@app.delete("/api/einsaetze/{einsatz_id}")
def delete_einsatz(einsatz_id: int, db: Session = Depends(get_db)):
    e = db.query(Einsatz).filter(Einsatz.id == einsatz_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Einsatz nicht gefunden")
    db.delete(e)
    db.commit()
    return {"ok": True}
