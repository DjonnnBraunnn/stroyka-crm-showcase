from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from ..database import get_db
from ..auth import Me, get_current_user, require_write
from ..utils import get_or_404, notify, save_upload
from .. import models as m
from .. import serializers as s

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents(site_id: int | None = None, type: str | None = None, status: str | None = None,
                   user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(m.Document).filter(m.Document.company_id == user.company_id)
    if site_id:
        q = q.filter(m.Document.site_id == site_id)
    if type:
        q = q.filter(m.Document.type == type)
    if status:
        q = q.filter(m.Document.status == status)
    return [s.document(d) for d in q.order_by(m.Document.created_at.desc())]


@router.get("/inbox")
def inbox(user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    """Документы, которые ждут решения текущего пользователя."""
    rows = (db.query(m.Document).join(m.Approval)
            .filter(m.Document.company_id == user.company_id, m.Approval.approver_id == user.id,
                    m.Approval.status == "pending", m.Document.status == "review").all())
    return [s.document(d) for d in rows]


@router.post("")
async def create_document(title: str = Form(...), type: str = Form("other"), site_id: int | None = Form(None),
                          comment: str = Form(""), approvers: str = Form(""),
                          file: UploadFile | None = File(None),
                          user: Me = Depends(require_write("documents")), db: Session = Depends(get_db)):
    if type not in m.DOC_TYPES:
        raise HTTPException(400, "Неизвестный тип документа")
    d = m.Document(company_id=user.company_id, site_id=site_id or None, type=type, title=title.strip(),
                   author_id=user.id)
    db.add(d); db.flush()
    if file and file.filename:
        url, name = await save_upload(file, "docs")
        db.add(m.DocumentVersion(document_id=d.id, version=1, filename=name, url=url,
                                 comment=comment, uploaded_by=user.id))
    for a in [x for x in approvers.split(",") if x.strip().isdigit()]:
        db.add(m.Approval(document_id=d.id, approver_id=int(a)))
    db.commit(); db.refresh(d)
    return s.document(d, full=True)


@router.get("/{did}")
def get_document(did: int, user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    return s.document(get_or_404(db, m.Document, did, user.company_id), full=True)


@router.post("/{did}/versions")
async def add_version(did: int, file: UploadFile = File(...), comment: str = Form(""),
                      user: Me = Depends(require_write("documents")), db: Session = Depends(get_db)):
    d = get_or_404(db, m.Document, did, user.company_id)
    url, name = await save_upload(file, "docs")
    v = (d.versions[-1].version + 1) if d.versions else 1
    db.add(m.DocumentVersion(document_id=d.id, version=v, filename=name, url=url, comment=comment,
                             uploaded_by=user.id))
    # новая версия сбрасывает согласование: подписывали-то прежний текст
    for a in d.approvals:
        a.status = "pending"; a.decided_at = None; a.comment = ""
    if d.status in ("approved", "rejected"):
        d.status = "draft"
    db.commit(); db.refresh(d)
    return s.document(d, full=True)


@router.post("/{did}/submit")
def submit(did: int, data: dict, user: Me = Depends(require_write("documents")), db: Session = Depends(get_db)):
    """Отправить на согласование указанным пользователям."""
    d = get_or_404(db, m.Document, did, user.company_id)
    ids = [int(x) for x in data.get("approvers", []) if str(x).isdigit()]
    existing = {a.approver_id for a in d.approvals}
    for uid in ids:
        if uid not in existing:
            db.add(m.Approval(document_id=d.id, approver_id=uid))
    if not ids and not d.approvals:
        raise HTTPException(400, "Укажите, кто согласует")
    d.status = "review"
    for uid in ids or existing:
        notify(db, user.company_id, "doc", f"На согласование: «{d.title}»", f"/documents/{d.id}", uid)
    db.commit(); db.refresh(d)
    return s.document(d, full=True)


@router.post("/{did}/decide")
def decide(did: int, data: dict, user: Me = Depends(get_current_user), db: Session = Depends(get_db)):
    d = get_or_404(db, m.Document, did, user.company_id)
    a = next((x for x in d.approvals if x.approver_id == user.id), None)
    if not a:
        raise HTTPException(403, "Вы не в листе согласования")
    decision = data.get("decision")
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "Решение: approved или rejected")
    a.status = decision
    a.comment = data.get("comment", "")
    a.decided_at = datetime.utcnow()
    if decision == "rejected":
        d.status = "rejected"
        notify(db, user.company_id, "doc", f"«{d.title}» отклонён: {a.comment or 'без комментария'}",
               f"/documents/{d.id}", d.author_id)
    elif all(x.status == "approved" for x in d.approvals):
        d.status = "approved"
        notify(db, user.company_id, "doc", f"«{d.title}» согласован всеми", f"/documents/{d.id}", d.author_id)
    db.commit(); db.refresh(d)
    return s.document(d, full=True)


@router.post("/{did}/sign")
def sign(did: int, user: Me = Depends(require_write("documents")), db: Session = Depends(get_db)):
    """Отметка о подписании. Юридически значимая ЭЦП подключается к оператору ЭДО отдельным этапом."""
    d = get_or_404(db, m.Document, did, user.company_id)
    if d.status != "approved":
        raise HTTPException(400, "Подписать можно только согласованный документ")
    d.status = "signed"
    db.commit(); db.refresh(d)
    return s.document(d, full=True)


@router.patch("/{did}")
def patch_document(did: int, data: dict, user: Me = Depends(require_write("documents")), db: Session = Depends(get_db)):
    d = get_or_404(db, m.Document, did, user.company_id)
    for f in ("title", "type", "site_id"):
        if f in data:
            setattr(d, f, data[f])
    db.commit(); db.refresh(d)
    return s.document(d, full=True)
