"""Вахтовый городок: блок → комната → койко-место → проживание.

Правила, которые держат учёт честным:
- на одном койко-месте одновременно один живущий или ожидаемый;
- у сотрудника одно активное проживание; переселение закрывает старое
  статусом «Переведён» и открывает новое, история сохраняется;
- предупреждения о заезде/выезде строятся по плановым датам.
"""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..auth import Me, get_current_user, require_write
from ..utils import apply, get_or_404, notify, parse_date
from .. import models as m
from .. import serializers as s

router = APIRouter(prefix="/api/camp", tags=["camp"])

ACTIVE = ("living", "expected", "absent")


def _active_on_bed(db, bed_id: int):
    return db.query(m.Residence).filter(m.Residence.bed_id == bed_id, m.Residence.status.in_(ACTIVE)).first()


def _active_of(db, emp_id: int):
    return db.query(m.Residence).filter(m.Residence.employee_id == emp_id, m.Residence.status.in_(ACTIVE)).first()


def _beds_of_company(db, company_id: int):
    return (db.query(m.CampBed).join(m.CampRoom).join(m.CampBlock)
            .filter(m.CampBlock.company_id == company_id))


@router.get("/structure")
def structure(user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    """Вся карта городка одним ответом: блоки, комнаты, койки и кто на них."""
    blocks = db.query(m.CampBlock).filter(m.CampBlock.company_id == user.company_id).order_by(m.CampBlock.order).all()
    active = {r.bed_id: r for r in db.query(m.Residence).filter(
        m.Residence.company_id == user.company_id, m.Residence.status.in_(ACTIVE)).all()}
    out = []
    total = occupied = expected = 0
    for b in blocks:
        rooms = []
        for r in b.rooms:
            beds = []
            for bed in r.beds:
                total += 1
                res = active.get(bed.id)
                if res and res.status in ("living", "absent"):
                    occupied += 1
                elif res and res.status == "expected":
                    expected += 1
                beds.append({"id": bed.id, "number": bed.number,
                             "residence": s.residence(res, with_place=False) if res else None})
            rooms.append({"id": r.id, "number": r.number, "capacity": r.capacity, "beds": beds,
                          "free": sum(1 for x in beds if not x["residence"])})
        out.append({"id": b.id, "name": b.name, "kind": b.kind, "rooms": rooms,
                    "beds_total": sum(len(r["beds"]) for r in rooms),
                    "beds_free": sum(r["free"] for r in rooms)})
    return {"blocks": out, "beds_total": total, "occupied": occupied, "expected": expected,
            "free": total - occupied - expected,
            "load_pct": round(occupied / total * 100) if total else 0}


@router.get("/stats")
def stats(user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    week = today + timedelta(days=7)
    q = db.query(m.Residence).filter(m.Residence.company_id == user.company_id)
    arrivals = q.filter(m.Residence.status == "expected", m.Residence.planned_in <= week)\
        .order_by(m.Residence.planned_in).all()
    departures = q.filter(m.Residence.status.in_(["living", "absent"]), m.Residence.planned_out <= week)\
        .order_by(m.Residence.planned_out).all()
    overdue_out = [r for r in departures if r.planned_out and r.planned_out < today]
    late_in = [r for r in arrivals if r.planned_in and r.planned_in < today]
    st = structure(user, db)
    # движение за 30 дней
    month_ago = datetime.utcnow() - timedelta(days=30)
    moved_in = q.filter(m.Residence.checked_in >= month_ago).count()
    moved_out = q.filter(m.Residence.checked_out >= month_ago).count()
    transfers = q.filter(m.Residence.status == "transferred", m.Residence.checked_out >= month_ago).count()
    return {
        "beds_total": st["beds_total"], "occupied": st["occupied"], "expected": st["expected"],
        "free": st["free"], "load_pct": st["load_pct"],
        "over_limit": st["occupied"] + st["expected"] > st["beds_total"],
        "arrivals_week": [s.residence(r) for r in arrivals],
        "departures_week": [s.residence(r) for r in departures],
        "overdue_out": len(overdue_out), "late_in": len(late_in),
        "moved_in_30": moved_in, "moved_out_30": moved_out, "transfers_30": transfers,
        "blocks": [{"name": b["name"], "kind": b["kind"], "total": b["beds_total"],
                    "free": b["beds_free"]} for b in st["blocks"]],
    }


@router.get("/residences")
def residences(status: str | None = None, employee_id: int | None = None,
               user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(m.Residence).filter(m.Residence.company_id == user.company_id)
    if status:
        q = q.filter(m.Residence.status == status)
    if employee_id:
        q = q.filter(m.Residence.employee_id == employee_id)
    rows = q.order_by(m.Residence.created_at.desc()).limit(300).all()
    return [_with_place(db, r) for r in rows]


def _with_place(db, r: m.Residence) -> dict:
    out = s.residence(r)
    bed = r.bed
    room = db.query(m.CampRoom).get(bed.room_id) if bed else None
    block = db.query(m.CampBlock).get(room.block_id) if room else None
    out["room_number"] = room.number if room else None
    out["block_name"] = block.name if block else None
    out["place"] = f"{block.name}, к. {room.number}, место {bed.number}" if block else None
    return out


@router.post("/residences")
def book(data: dict, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    """Поставить сотрудника на койко-место: «ожидается заезд» или сразу «проживает»."""
    emp = get_or_404(db, m.Employee, int(data.get("employee_id") or 0), user.company_id)
    bed = get_or_404(db, m.CampBed, int(data.get("bed_id") or 0))
    if _active_on_bed(db, bed.id):
        raise HTTPException(400, "Место занято")
    if _active_of(db, emp.id):
        raise HTTPException(400, "Сотрудник уже размещён. Используйте переселение")
    r = m.Residence(company_id=user.company_id, employee_id=emp.id, bed_id=bed.id,
                    planned_in=parse_date(data.get("planned_in")) or date.today(),
                    planned_out=parse_date(data.get("planned_out")), note=data.get("note", ""))
    if data.get("check_in_now"):
        r.status = "living"
        r.checked_in = datetime.utcnow()
    db.add(r); db.commit(); db.refresh(r)
    notify(db, user.company_id, "camp", f"{emp.full_name}: {'заселён' if r.status == 'living' else 'ожидается заезд ' + r.planned_in.strftime('%d.%m')}", "/camp")
    db.commit()
    return _with_place(db, r)


@router.post("/residences/{rid}/checkin")
def checkin(rid: int, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    r = get_or_404(db, m.Residence, rid, user.company_id)
    if r.status not in ("expected", "absent"):
        raise HTTPException(400, "Заселить можно только ожидаемого или отсутствующего")
    r.status = "living"
    r.checked_in = r.checked_in or datetime.utcnow()
    notify(db, user.company_id, "camp", f"{r.employee.full_name} заселён", "/camp")
    db.commit()
    return _with_place(db, r)


@router.post("/residences/{rid}/checkout")
def checkout(rid: int, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    r = get_or_404(db, m.Residence, rid, user.company_id)
    if r.status not in ACTIVE:
        raise HTTPException(400, "Проживание уже закрыто")
    r.status = "left"
    r.checked_out = datetime.utcnow()
    notify(db, user.company_id, "camp", f"{r.employee.full_name} выехал", "/camp")
    db.commit()
    return _with_place(db, r)


@router.post("/residences/{rid}/absent")
def absent(rid: int, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    r = get_or_404(db, m.Residence, rid, user.company_id)
    if r.status != "living":
        raise HTTPException(400, "Отметить отсутствие можно только проживающему")
    r.status = "absent"
    db.commit()
    return _with_place(db, r)


@router.post("/residences/{rid}/transfer")
def transfer(rid: int, data: dict, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    """Переселение: старая запись закрывается как «Переведён», новая — «Проживает»."""
    r = get_or_404(db, m.Residence, rid, user.company_id)
    if r.status not in ACTIVE:
        raise HTTPException(400, "Проживание уже закрыто")
    bed = get_or_404(db, m.CampBed, int(data.get("bed_id") or 0))
    if bed.id == r.bed_id:
        raise HTTPException(400, "Это то же самое место")
    if _active_on_bed(db, bed.id):
        raise HTTPException(400, "Место занято")
    r.status = "transferred"
    r.checked_out = datetime.utcnow()
    n = m.Residence(company_id=user.company_id, employee_id=r.employee_id, bed_id=bed.id,
                    planned_in=date.today(), planned_out=r.planned_out, status="living",
                    checked_in=datetime.utcnow(), note=data.get("note", "Переселение"))
    db.add(n)
    notify(db, user.company_id, "camp", f"{r.employee.full_name} переселён", "/camp")
    db.commit(); db.refresh(n)
    return _with_place(db, n)


@router.patch("/residences/{rid}")
def patch_residence(rid: int, data: dict, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    r = get_or_404(db, m.Residence, rid, user.company_id)
    apply(r, data, ("planned_in", "planned_out", "note"))
    db.commit()
    return _with_place(db, r)


# ── Структура: блоки и комнаты ───────────────────────────────────────────

@router.post("/blocks")
def create_block(data: dict, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    b = m.CampBlock(company_id=user.company_id, name=data.get("name", "Блок"), kind=data.get("kind", "Жилой"),
                    site_id=data.get("site_id"))
    db.add(b); db.flush()
    rooms = int(data.get("rooms", 0) or 0)
    cap = int(data.get("capacity", 4) or 4)
    for i in range(1, rooms + 1):
        room = m.CampRoom(block_id=b.id, number=str(i), capacity=cap)
        db.add(room); db.flush()
        for n in range(1, cap + 1):
            db.add(m.CampBed(room_id=room.id, number=n))
    db.commit()
    return {"id": b.id}


@router.post("/blocks/{bid}/rooms")
def create_room(bid: int, data: dict, user: Me = Depends(require_write("camp")), db: Session = Depends(get_db)):
    b = get_or_404(db, m.CampBlock, bid, user.company_id)
    cap = int(data.get("capacity", 4) or 4)
    room = m.CampRoom(block_id=b.id, number=str(data.get("number", len(b.rooms) + 1)), capacity=cap)
    db.add(room); db.flush()
    for n in range(1, cap + 1):
        db.add(m.CampBed(room_id=room.id, number=n))
    db.commit()
    return {"id": room.id}
