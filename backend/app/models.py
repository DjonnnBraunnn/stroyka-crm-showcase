"""Модель данных системы управления стройкой.

Каркас повторяет структуру компании заказчика:

    Направление (СМР, Городок-склад, Добыча, Содержание и эксплуатация, Офис)
    └── Объект
        ├── Задачи (чек-листы, фотоотчёты, история)
        ├── Персонал на вахте
        ├── Техника и путевые листы (ГСМ, выработка)
        ├── Финансы (бюджет, затраты, акты, оплаты)
        ├── Документы (версии, согласование)
        ├── Геодезия
        └── Добыча (объёмы)

    Сотрудник ── Проживание в вахтовом городке (блок → комната → койко-место)

Каждая рабочая таблица несёт company_id: система с первого дня готова
обслуживать несколько компаний, хотя в демо компания одна.
"""
from datetime import datetime, date
from sqlalchemy import (Column, Integer, String, Text, Float, Boolean, Date,
                        DateTime, ForeignKey, JSON)
from sqlalchemy.orm import relationship
from .database import Base


def now():
    return datetime.utcnow()


# ── Компания и пользователи ──────────────────────────────────────────────

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    short_name = Column(String(60), default="")
    city = Column(String(100), default="Павлодар")
    created_at = Column(DateTime, default=now)


# Роли. Директор видит всё; остальные — свои разделы.
ROLES = {
    "director":     "Директор",
    "pto":          "ПТО / инженер",
    "foreman":      "Прораб",
    "hr":           "Кадры",
    "camp":         "Комендант городка",
    "mechanic":     "Механик",
    "accountant":   "Бухгалтер",
    "surveyor":     "Геодезист",
}


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    login = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    name = Column(String(160), nullable=False)
    role = Column(String(30), nullable=False, default="foreman")
    phone = Column(String(30), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


# ── Направления и объекты ────────────────────────────────────────────────

class Direction(Base):
    """Пять направлений компании — рукописная пометка руководителя на ТЗ."""
    __tablename__ = "directions"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    code = Column(String(30), nullable=False)      # smr, camp, mining, maintenance, office
    name = Column(String(120), nullable=False)
    short = Column(String(40), default="")
    color = Column(String(20), default="#f59e0b")
    icon = Column(String(40), default="building")
    order = Column(Integer, default=0)


SITE_STATUSES = {
    "planned":   "Подготовка",
    "active":    "В работе",
    "suspended": "Приостановлен",
    "done":      "Завершён",
}


class Site(Base):
    """Объект: стройплощадка, участок дороги, карьер, городок, офис."""
    __tablename__ = "sites"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    direction_id = Column(Integer, ForeignKey("directions.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    address = Column(String(300), default="")
    lat = Column(Float)
    lng = Column(Float)
    customer = Column(String(200), default="")
    contract_no = Column(String(80), default="")
    contract_sum = Column(Float, default=0)
    budget = Column(Float, default=0)
    start_plan = Column(Date)
    end_plan = Column(Date)
    end_fact = Column(Date)
    status = Column(String(20), default="active")
    progress = Column(Integer, default=0)          # % готовности, ставит ПТО
    responsible_id = Column(Integer, ForeignKey("users.id"))
    description = Column(Text, default="")
    created_at = Column(DateTime, default=now)

    direction = relationship("Direction")
    responsible = relationship("User")


# ── Задачи ───────────────────────────────────────────────────────────────

TASK_STATUSES = {
    "new":         "Новая",
    "in_progress": "В работе",
    "review":      "На проверке",
    "done":        "Выполнена",
}
TASK_PRIORITIES = {"low": "Низкий", "normal": "Обычный", "high": "Высокий", "critical": "Критичный"}


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    title = Column(String(250), nullable=False)
    description = Column(Text, default="")
    deadline = Column(Date)
    priority = Column(String(12), default="normal")
    status = Column(String(15), default="new")
    assignee_id = Column(Integer, ForeignKey("users.id"))
    author_id = Column(Integer, ForeignKey("users.id"))
    checklist = Column(JSON, default=list)       # [{"text": "...", "done": false}]
    created_at = Column(DateTime, default=now)
    completed_at = Column(DateTime)

    site = relationship("Site")
    assignee = relationship("User", foreign_keys=[assignee_id])
    author = relationship("User", foreign_keys=[author_id])
    photos = relationship("TaskPhoto", cascade="all, delete-orphan", order_by="TaskPhoto.taken_at")
    comments = relationship("TaskComment", cascade="all, delete-orphan", order_by="TaskComment.created_at")


class TaskPhoto(Base):
    """Фото с объекта: время и координаты фиксируются в момент съёмки."""
    __tablename__ = "task_photos"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    url = Column(String(300), nullable=False)
    caption = Column(String(250), default="")
    taken_at = Column(DateTime, default=now)
    lat = Column(Float)
    lng = Column(Float)
    author_id = Column(Integer, ForeignKey("users.id"))
    author = relationship("User")


class TaskComment(Base):
    """Комментарии и системная история: смена статуса, срока, исполнителя."""
    __tablename__ = "task_comments"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    text = Column(Text, nullable=False)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
    author = relationship("User")


# ── Персонал и вахта ─────────────────────────────────────────────────────

EMPLOYEE_STATUSES = {"active": "Работает", "vacation": "Межвахтовый отдых",
                     "sick": "Больничный", "dismissed": "Уволен"}
EMPLOYEE_CATEGORIES = {"itr": "ИТР", "worker": "Рабочий", "driver": "Машинист / водитель", "office": "Офис"}


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    full_name = Column(String(160), nullable=False)
    position = Column(String(120), default="")
    category = Column(String(12), default="worker")
    phone = Column(String(30), default="")
    direction_id = Column(Integer, ForeignKey("directions.id"))
    status = Column(String(12), default="active")
    hired_at = Column(Date)
    is_rotational = Column(Boolean, default=True)   # вахтовик
    note = Column(Text, default="")

    direction = relationship("Direction")


class Rotation(Base):
    """Вахта: сотрудник на объекте с … по …. Между вахтами — отдых."""
    __tablename__ = "rotations"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    note = Column(String(200), default="")

    employee = relationship("Employee")
    site = relationship("Site")


class Vacancy(Base):
    __tablename__ = "vacancies"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"))
    title = Column(String(150), nullable=False)
    count = Column(Integer, default=1)
    closed = Column(Integer, default=0)
    opened_at = Column(Date, default=date.today)
    status = Column(String(12), default="open")     # open / closed
    note = Column(String(250), default="")

    site = relationship("Site")


# ── Вахтовый городок ─────────────────────────────────────────────────────

RESIDENCE_STATUSES = {
    "expected":    "Ожидается заезд",
    "living":      "Проживает",
    "left":        "Выехал",
    "transferred": "Переведён",
    "absent":      "Отсутствует",
}


class CampBlock(Base):
    __tablename__ = "camp_blocks"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"))
    name = Column(String(80), nullable=False)
    kind = Column(String(40), default="Жилой")      # Жилой / ИТР / Столовая / Склад
    order = Column(Integer, default=0)

    rooms = relationship("CampRoom", cascade="all, delete-orphan", order_by="CampRoom.number")


class CampRoom(Base):
    __tablename__ = "camp_rooms"
    id = Column(Integer, primary_key=True)
    block_id = Column(Integer, ForeignKey("camp_blocks.id"), nullable=False, index=True)
    number = Column(String(20), nullable=False)
    capacity = Column(Integer, default=4)

    beds = relationship("CampBed", cascade="all, delete-orphan", order_by="CampBed.number")


class CampBed(Base):
    __tablename__ = "camp_beds"
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("camp_rooms.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)


class Residence(Base):
    """Проживание сотрудника на койко-месте. История переселений — это
    цепочка записей: старая получает статус «Переведён», новая — «Проживает»."""
    __tablename__ = "residences"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    bed_id = Column(Integer, ForeignKey("camp_beds.id"), nullable=False, index=True)
    planned_in = Column(Date)
    planned_out = Column(Date)
    checked_in = Column(DateTime)
    checked_out = Column(DateTime)
    status = Column(String(15), default="expected")
    note = Column(String(250), default="")
    created_at = Column(DateTime, default=now)

    employee = relationship("Employee")
    bed = relationship("CampBed")


# ── Спецтехника ──────────────────────────────────────────────────────────

EQUIPMENT_STATUSES = {"working": "В работе", "idle": "Простой", "repair": "Ремонт", "transit": "Перебазировка"}


class Equipment(Base):
    __tablename__ = "equipment"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(150), nullable=False)          # Экскаватор Hitachi ZX330
    kind = Column(String(60), default="")               # Экскаватор
    plate = Column(String(30), default="")
    year = Column(Integer)
    status = Column(String(12), default="working")
    site_id = Column(Integer, ForeignKey("sites.id"))
    operator_id = Column(Integer, ForeignKey("employees.id"))
    gps_id = Column(String(60), default="")
    fuel_norm = Column(Float, default=0)                # л/моточас по норме
    hours_total = Column(Float, default=0)
    next_service_hours = Column(Float, default=0)
    note = Column(Text, default="")

    site = relationship("Site")
    operator = relationship("Employee")


class WorkLog(Base):
    """Путевой лист / смена: часы, ГСМ, выработка."""
    __tablename__ = "work_logs"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("employees.id"))
    date = Column(Date, nullable=False, index=True)
    hours = Column(Float, default=0)
    fuel_issued = Column(Float, default=0)
    fuel_used = Column(Float, default=0)
    output = Column(Float, default=0)                   # выработка
    output_unit = Column(String(20), default="м³")
    note = Column(String(250), default="")

    equipment = relationship("Equipment")
    site = relationship("Site")
    operator = relationship("Employee")


# ── Добыча и геодезия ────────────────────────────────────────────────────

class Production(Base):
    """Добыча: объём за смену по материалу."""
    __tablename__ = "production"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    material = Column(String(80), default="ПГС")
    volume = Column(Float, default=0)                   # м³
    trips = Column(Integer, default=0)                  # рейсов
    shipped = Column(Float, default=0)                  # отгружено, м³
    note = Column(String(250), default="")

    site = relationship("Site")


GEODESY_KINDS = {"survey": "Съёмка", "layout": "Разбивка", "asbuilt": "Исполнительная",
                 "volume": "Подсчёт объёмов", "control": "Контроль"}


class GeodesyEntry(Base):
    __tablename__ = "geodesy"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    kind = Column(String(12), default="survey")
    surveyor_id = Column(Integer, ForeignKey("employees.id"))
    description = Column(String(300), default="")
    result = Column(String(300), default="")            # «Объём выемки 12 340 м³»
    status = Column(String(12), default="done")         # planned / done / deviation

    site = relationship("Site")
    surveyor = relationship("Employee")


# ── Финансы ──────────────────────────────────────────────────────────────

EXPENSE_CATEGORIES = {"materials": "Материалы", "fuel": "ГСМ", "salary": "Зарплата",
                      "contractor": "Подрядчики", "rent": "Аренда техники",
                      "logistics": "Логистика", "other": "Прочее"}


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    category = Column(String(15), default="other")
    contractor = Column(String(150), default="")
    amount = Column(Float, default=0)
    description = Column(String(250), default="")
    is_purchase = Column(Boolean, default=False)        # закупка (материалы, запчасти)

    site = relationship("Site")


class Act(Base):
    """Акт выполненных работ. Подписанный акт — выручка по объекту."""
    __tablename__ = "acts"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    number = Column(String(40), default="")
    date = Column(Date, nullable=False)
    counterparty = Column(String(150), default="")
    amount = Column(Float, default=0)
    status = Column(String(12), default="draft")        # draft / signed / paid
    description = Column(String(250), default="")

    site = relationship("Site")


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    act_id = Column(Integer, ForeignKey("acts.id"))
    date = Column(Date, nullable=False)
    counterparty = Column(String(150), default="")
    amount = Column(Float, default=0)
    direction = Column(String(5), default="in")         # in — поступление, out — оплата
    description = Column(String(250), default="")

    site = relationship("Site")


# ── Документооборот ──────────────────────────────────────────────────────

DOC_TYPES = {"contract": "Договор", "order": "Приказ", "act": "Акт",
             "executive": "Исполнительная документация", "project": "Проектная документация",
             "other": "Прочее"}
DOC_STATUSES = {"draft": "Черновик", "review": "На согласовании",
                "approved": "Согласован", "signed": "Подписан", "rejected": "Отклонён"}


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"))
    type = Column(String(12), default="other")
    title = Column(String(250), nullable=False)
    status = Column(String(12), default="draft")
    author_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=now)

    site = relationship("Site")
    author = relationship("User")
    versions = relationship("DocumentVersion", cascade="all, delete-orphan", order_by="DocumentVersion.version")
    approvals = relationship("Approval", cascade="all, delete-orphan", order_by="Approval.id")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    version = Column(Integer, default=1)
    filename = Column(String(250), default="")
    url = Column(String(300), default="")
    comment = Column(String(250), default="")
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=now)
    uploader = relationship("User")


class Approval(Base):
    """Лист согласования: кто и когда одобрил или отклонил."""
    __tablename__ = "approvals"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(12), default="pending")      # pending / approved / rejected
    comment = Column(String(250), default="")
    decided_at = Column(DateTime)
    approver = relationship("User")


# ── Уведомления ──────────────────────────────────────────────────────────

class Notification(Base):
    """Одна лента событий. Каналы (WhatsApp, Telegram, почта) читают её же."""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))   # None — всем
    kind = Column(String(30), default="info")           # overdue / deadline / done / camp / finance / doc
    text = Column(String(300), nullable=False)
    link = Column(String(200), default="")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
