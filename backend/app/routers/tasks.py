import os
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from ..database import get_db
from ..auth import Me, get_current_user, require_write
from ..utils import apply, get_or_404, notify, save_upload, shrink_image, parse_dt, UPLOAD_DIR
from .. import models as m
from .. import serializers as s

router = APIRouter(prefix="/api", tags=["tasks"])

TASK_FIELDS = ("site_id", "title", "description", "deadline", "priority", "status", "assignee_id", "checklist")


def _sys(db, task: m.Task, user: Me, text: str):
    db.add(m.TaskComment(task_id=task.id, author_id=user.id, text=text, is_system=True))


@router.get("/tasks")
def list_tasks(site_id: int | None = None, status: str | None = None, assignee_id: int | None = None,
               direction_id: int | None = None, overdue: bool = False, mine: bool = False,
               user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(m.Task).filter(m.Task.company_id == user.company_id)
    if site_id:
        q = q.filter(m.Task.site_id == site_id)
    if status:
        q = q.filter(m.Task.status == status)
    if assignee_id:
        q = q.filter(m.Task.assignee_id == assignee_id)
    if mine:
        q = q.filter(m.Task.assignee_id == user.id)
    if direction_id:
        q = q.join(m.Site).filter(m.Site.direction_id == direction_id)
    if overdue:
        q = q.filter(m.Task.status != "done", m.Task.deadline < date.today())
    return [s.task(t) for t in q.order_by(m.Task.deadline.is_(None), m.Task.deadline).all()]


@router.post("/tasks")
def create_task(data: dict, user: Me = Depends(require_write("tasks")), db: Session = Depends(get_db)):
    if not data.get("title") or not data.get("site_id"):
        raise HTTPException(400, "Нужны название и объект")
    get_or_404(db, m.Site, int(data["site_id"]), user.company_id)
    task = apply(m.Task(company_id=user.company_id, author_id=user.id), data, TASK_FIELDS)
    if isinstance(data.get("checklist"), list):
        task.checklist = [{"text": str(c.get("text") if isinstance(c, dict) else c), "done": False}
                          for c in data["checklist"] if c]
    db.add(task); db.commit(); db.refresh(task)
    _sys(db, task, user, "Задача создана")
    if task.assignee_id and task.assignee_id != user.id:
        notify(db, user.company_id, "task", f"Вам поставлена задача «{task.title}»",
               f"/tasks/{task.id}", task.assignee_id)
    db.commit()
    return s.task(task, full=True)


@router.get("/tasks/{tid}")
def get_task(tid: int, user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    return s.task(get_or_404(db, m.Task, tid, user.company_id), full=True)


@router.patch("/tasks/{tid}")
def patch_task(tid: int, data: dict, user: Me = Depends(require_write("tasks")), db: Session = Depends(get_db)):
    task = get_or_404(db, m.Task, tid, user.company_id)
    old = {"status": task.status, "deadline": task.deadline, "assignee_id": task.assignee_id}
    apply(task, data, TASK_FIELDS)
    if task.status != old["status"]:
        _sys(db, task, user, f"Статус: {m.TASK_STATUSES.get(old['status'])} → {m.TASK_STATUSES.get(task.status)}")
        if task.status == "done":
            task.completed_at = datetime.utcnow()
            notify(db, user.company_id, "done", f"Задача «{task.title}» выполнена ({task.site.name})",
                   f"/tasks/{task.id}")
        else:
            task.completed_at = None
    if task.deadline != old["deadline"]:
        _sys(db, task, user, f"Срок: {old['deadline'] or '—'} → {task.deadline or '—'}")
        notify(db, user.company_id, "deadline",
               f"Изменён срок задачи «{task.title}»: {task.deadline or 'без срока'}", f"/tasks/{task.id}")
    if task.assignee_id != old["assignee_id"]:
        _sys(db, task, user, f"Ответственный: {task.assignee.name if task.assignee else '—'}")
        if task.assignee_id:
            notify(db, user.company_id, "task", f"Вам передана задача «{task.title}»",
                   f"/tasks/{task.id}", task.assignee_id)
    db.commit(); db.refresh(task)
    return s.task(task, full=True)


@router.post("/tasks/{tid}/checklist/{idx}")
def toggle_check(tid: int, idx: int, user: Me = Depends(require_write("tasks")), db: Session = Depends(get_db)):
    task = get_or_404(db, m.Task, tid, user.company_id)
    items = list(task.checklist or [])
    if idx < 0 or idx >= len(items):
        raise HTTPException(404, "Пункта нет")
    items[idx] = {**items[idx], "done": not items[idx].get("done")}
    task.checklist = items
    db.commit(); db.refresh(task)
    return s.task(task, full=True)


@router.post("/tasks/{tid}/comments")
def add_comment(tid: int, data: dict, user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    task = get_or_404(db, m.Task, tid, user.company_id)
    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Пустой комментарий")
    db.add(m.TaskComment(task_id=task.id, author_id=user.id, text=text))
    db.commit()
    return s.task(task, full=True)


@router.post("/tasks/{tid}/photos")
async def add_photo(tid: int, file: UploadFile = File(...), caption: str = Form(""),
                    lat: float | None = Form(None), lng: float | None = Form(None),
                    taken_at: str | None = Form(None),
                    user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    """Фото с объекта. Время и координаты приходят с телефона в момент съёмки."""
    task = get_or_404(db, m.Task, tid, user.company_id)
    url, _ = await save_upload(file, "photos")
    shrink_image(os.path.join(UPLOAD_DIR, url.replace("/uploads/", "", 1)))
    p = m.TaskPhoto(task_id=task.id, url=url, caption=caption, lat=lat, lng=lng,
                    author_id=user.id, taken_at=parse_dt(taken_at) or datetime.utcnow())
    db.add(p)
    _sys(db, task, user, "Добавлено фото" + (f": {caption}" if caption else ""))
    db.commit()
    return s.task(task, full=True)


@router.delete("/tasks/{tid}")
def delete_task(tid: int, user: Me = Depends(require_write("tasks")), db: Session = Depends(get_db)):
    task = get_or_404(db, m.Task, tid, user.company_id)
    if user.role not in ("director", "pto") and task.author_id != user.id:
        raise HTTPException(403, "Удалять может автор, ПТО или директор")
    db.delete(task); db.commit()
    return {"ok": True}
