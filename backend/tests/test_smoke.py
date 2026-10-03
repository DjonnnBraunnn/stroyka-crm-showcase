"""Дымовой тест: пустая база → демо-данные → все основные разделы отвечают.

Запуск:  python tests/test_smoke.py   (из папки backend, в venv)
Ничего кроме зависимостей проекта не нужно: база — временный SQLite.
"""
import os
import sys
import tempfile
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_tmp = tempfile.mkdtemp(prefix="stroyka-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = os.path.join(_tmp, "uploads")
os.environ["SEED_DEMO"] = "1"
os.environ["SCHEDULER"] = "0"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print("  ok  ", msg)
    else:
        print("  FAIL", msg)
        FAILS.append(msg)


def run():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"login": "director", "password": os.environ["DEMO_PASSWORD"]})
        check(r.status_code == 200, "вход директора")
        token = r.json()["token"]
        H = {"Authorization": f"Bearer {token}"}
        check(c.post("/api/auth/login", json={"login": "director", "password": "x"}).status_code == 401, "неверный пароль → 401")
        check(c.get("/api/sites").status_code == 401, "без токена → 401")

        meta = c.get("/api/meta", headers=H).json()
        check(len(meta["directions"]) == 5, "пять направлений")

        sites = c.get("/api/sites", headers=H).json()
        check(len(sites) == 8, f"объекты: {len(sites)}")
        water = next(s for s in sites if "Водопровод" in s["name"])
        check(water["over_budget"], "водопровод показывает перерасход бюджета")
        card = c.get(f"/api/sites/{water['id']}", headers=H).json()
        check(len(card["tasks"]) >= 4 and "expenses_by_category" in card, "карточка объекта полная")

        tasks = c.get("/api/tasks", headers=H).json()
        overdue = c.get("/api/tasks?overdue=true", headers=H).json()
        check(len(tasks) > 25 and len(overdue) >= 4, f"задачи {len(tasks)}, просрочено {len(overdue)}")
        t = c.post("/api/tasks", json={"site_id": water["id"], "title": "Тестовая задача", "deadline": "2030-01-01",
                                       "checklist": ["Пункт 1", "Пункт 2"]}, headers=H).json()
        check(t["checklist_total"] == 2, "создание задачи с чек-листом")
        t = c.post(f"/api/tasks/{t['id']}/checklist/0", headers=H).json()
        check(t["checklist_done"] == 1, "отметка пункта чек-листа")
        t = c.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=H).json()
        check(t["status"] == "done" and any(x["is_system"] for x in t["comments"]), "смена статуса пишет историю")
        # фото
        from PIL import Image
        buf = io.BytesIO(); Image.new("RGB", (2400, 1800), (120, 100, 80)).save(buf, "JPEG"); buf.seek(0)
        r = c.post(f"/api/tasks/{t['id']}/photos", files={"file": ("a.jpg", buf, "image/jpeg")},
                   data={"caption": "тест", "lat": "52.1", "lng": "76.9"}, headers=H)
        check(r.status_code == 200 and r.json()["photos_count"] == 1, "загрузка фото с координатами")
        check(c.get(r.json()["photos"][0]["url"]).status_code == 200, "фото отдаётся по ссылке")

        emps = c.get("/api/employees", headers=H).json()
        check(len(emps) >= 50 and any(e["on_site"] for e in emps), "сотрудники с вахтой")
        rot = c.get("/api/rotations", headers=H).json()
        check(len(rot["rotations"]) > 30, "вахтовый график месяца")
        e0 = next(e for e in emps if e["on_site"])
        r = c.post("/api/rotations", json={"employee_id": e0["id"], "site_id": e0["on_site"]["site_id"],
                                            "date_from": e0["on_site"]["date_from"], "date_to": e0["on_site"]["date_to"]}, headers=H)
        check(r.status_code == 400, "пересечение вахт запрещено")

        st = c.get("/api/camp/structure", headers=H).json()
        check(st["beds_total"] == 56 and st["occupied"] > 30, f"городок: {st['occupied']}/{st['beds_total']}")
        stats = c.get("/api/camp/stats", headers=H).json()
        check(len(stats["arrivals_week"]) >= 3, "ожидаемые заезды на неделе")
        free_bed = next(b for blk in st["blocks"] for rm in blk["rooms"] for b in rm["beds"] if not b["residence"])
        free_emp = next(e for e in emps if not e["residence"] and e["status"] == "active")
        r = c.post("/api/camp/residences", json={"employee_id": free_emp["id"], "bed_id": free_bed["id"], "check_in_now": True}, headers=H)
        check(r.status_code == 200 and r.json()["status"] == "living", "заселение")
        rid = r.json()["id"]
        r2 = c.post("/api/camp/residences", json={"employee_id": free_emp["id"], "bed_id": free_bed["id"]}, headers=H)
        check(r2.status_code == 400, "занятое место не даёт заселить")
        st2 = c.get("/api/camp/structure", headers=H).json()
        free2 = next(b for blk in st2["blocks"] for rm in blk["rooms"] for b in rm["beds"] if not b["residence"])
        r = c.post(f"/api/camp/residences/{rid}/transfer", json={"bed_id": free2["id"]}, headers=H)
        check(r.status_code == 200 and r.json()["status"] == "living", "переселение")
        hist = c.get(f"/api/camp/residences?employee_id={free_emp['id']}", headers=H).json()
        check(any(h["status"] == "transferred" for h in hist), "история переселения сохранена")
        r = c.post(f"/api/camp/residences/{r.json()['id']}/checkout", headers=H)
        check(r.json()["status"] == "left", "выезд")

        eq = c.get("/api/equipment", headers=H).json()
        check(len(eq) == 19 and any(e["fuel_over_pct"] > 20 for e in eq), "техника и перерасход ГСМ")
        r = c.post("/api/worklogs", json={"equipment_id": eq[0]["id"], "site_id": eq[0]["site_id"], "date": "2026-09-25",
                                           "hours": 10, "fuel_used": 500, "fuel_issued": 500, "output": 200}, headers=H)
        check(r.status_code == 200, "путевой лист")
        prod = c.get("/api/production", headers=H).json()
        check(prod["total_volume"] > 10000, "добыча за 60 дней")

        fin = c.get("/api/finance/summary", headers=H).json()
        check(fin["totals"]["over_budget_count"] >= 1, "финансы: план/факт по объектам")
        rep = c.get("/api/finance/report?by=contractor&period=all", headers=H).json()
        check(len(rep["rows"]) > 5, "отчёт по подрядчикам")

        docs = c.get("/api/documents", headers=H).json()
        check(len(docs) >= 10, "документы")
        inbox = c.get("/api/documents/inbox", headers=H).json()
        check(len(inbox) >= 3, f"директору на согласование: {len(inbox)}")
        d = c.post(f"/api/documents/{inbox[0]['id']}/decide", json={"decision": "approved"}, headers=H).json()
        check(d["approvals_done"] >= 1, "согласование документа")
        check(c.get(docs[0]["id"] and f"/api/documents/{docs[0]['id']}", headers=H).json()["versions"], "версии документа")

        for name in ("sites", "plan", "equipment", "fuel", "staff", "vacancies", "overdue", "finance"):
            r = c.get(f"/api/reports/{name}?period=month", headers=H)
            check(r.status_code == 200, f"отчёт {name}")
            x = c.get(f"/api/reports/{name}/excel?period=month", headers=H)
            check(x.status_code == 200 and len(x.content) > 3000, f"excel {name}")
        dash = c.get("/api/reports/dashboard", headers=H).json()
        check(dash["tasks"]["overdue"] >= 4 and dash["camp"]["beds_total"] == 56 and len(dash["by_direction"]) == 5, "панель директора")

        # ежедневные уведомления: второй прогон за день дублей не даёт
        from app.database import SessionLocal
        from app.scheduler import run_daily
        db = SessionLocal()
        first = run_daily(db); second = run_daily(db)
        db.close()
        check(second == 0, f"ежедневные уведомления без дублей ({first} → {second})")
        n = c.get("/api/notifications", headers=H).json()
        check(n["unread"] > 5, "уведомления")

        # права: прораб не может править финансы
        r = c.post("/api/auth/login", json={"login": "prorab", "password": os.environ["DEMO_PASSWORD"]}).json()
        HP = {"Authorization": f"Bearer {r['token']}"}
        check(c.post("/api/finance/expenses", json={"site_id": 1, "date": "2026-09-01", "amount": 5}, headers=HP).status_code == 403, "прораб не пишет в финансы")
        check(c.get("/api/finance/summary", headers=HP).status_code == 200, "но видит сводку")

    print()
    if FAILS:
        print(f"ПРОВАЛЕНО: {len(FAILS)}")
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print("ВСЕ ПРОВЕРКИ ПРОШЛИ")


if __name__ == "__main__":
    run()
