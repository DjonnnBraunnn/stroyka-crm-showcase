"""Ежедневные уведомления: просроченные задачи и заезды/выезды в городке.

Раз в час проверяет, не пора ли. На одну задачу или одно проживание за
день создаётся не больше одного уведомления: ключ дня хранится прямо в
тексте ссылки (link + дата), поэтому повторный запуск и второй воркер
дублей не плодят. Каналы WhatsApp/Telegram читают ту же ленту.
"""
import threading
import time
from datetime import date, datetime, timedelta
from .database import SessionLocal
from . import models as m


def _exists(db, company_id: int, kind: str, link: str, day: date) -> bool:
    # Окно считаем от «сейчас» в UTC: created_at пишется в UTC, а местная
    # полночь (UTC+5) с ним не совпадает — сравнение с ней плодило дубли
    # в первые пять часов суток. Поймано тестом test_smoke.
    start = datetime.utcnow() - timedelta(hours=20)
    return db.query(m.Notification).filter(
        m.Notification.company_id == company_id, m.Notification.kind == kind,
        m.Notification.link == link, m.Notification.created_at >= start).first() is not None


def run_daily(db, today: date | None = None) -> int:
    today = today or date.today()
    created = 0
    for t in db.query(m.Task).filter(m.Task.status != "done", m.Task.deadline < today).all():
        link = f"/tasks/{t.id}"
        if _exists(db, t.company_id, "overdue", link, today):
            continue
        days = (today - t.deadline).days
        db.add(m.Notification(company_id=t.company_id, kind="overdue", link=link, user_id=t.assignee_id,
                              text=f"Просрочена на {days} дн.: «{t.title}» ({t.site.name})"))
        created += 1
    tomorrow = today + timedelta(days=1)
    for r in db.query(m.Residence).filter(m.Residence.status == "expected", m.Residence.planned_in <= tomorrow).all():
        link = f"/camp#r{r.id}"
        if not _exists(db, r.company_id, "camp", link, today):
            when = "сегодня" if r.planned_in <= today else "завтра"
            db.add(m.Notification(company_id=r.company_id, kind="camp", link=link,
                                  text=f"Заезд {when}: {r.employee.full_name}"))
            created += 1
    for r in db.query(m.Residence).filter(m.Residence.status.in_(["living", "absent"]), m.Residence.planned_out <= tomorrow).all():
        link = f"/camp#o{r.id}"
        if not _exists(db, r.company_id, "camp", link, today):
            when = "срок выезда прошёл" if r.planned_out < today else ("выезд сегодня" if r.planned_out == today else "выезд завтра")
            db.add(m.Notification(company_id=r.company_id, kind="camp", link=link,
                                  text=f"{r.employee.full_name}: {when}"))
            created += 1
    db.commit()
    return created


def _loop():
    while True:
        try:
            db = SessionLocal()
            try:
                run_daily(db)
            finally:
                db.close()
        except Exception as e:  # не роняем приложение из-за фоновой задачи
            print("scheduler error:", e)
        time.sleep(3600)


def start():
    threading.Thread(target=_loop, daemon=True, name="daily-notifications").start()
