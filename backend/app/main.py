from datetime import date, datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect
from app.engines.borrow_rules import can_lend, can_unlock, classify_loans
from app.modules import damage_note

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows

@app.get("/api/board")
def board():
    c = connect()
    available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
    held = [dict(r) for r in c.execute("SELECT * FROM items WHERE status=?", (damage_note.DAMAGED_HOLD,))]
    loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    c.close()
    cls = classify_loans(loans, date.today().isoformat())
    return {
        "available": available,
        "held": held,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {
            "available": len(available),
            "held": len(held),
            "active": len(cls["active"]),
            "overdue": len(cls["overdue"]),
        },
    }

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.owner, "available", "clean"))
    c.commit(); iid = cur.lastrowid; c.close(); return {"id": iid}

class LendIn(BaseModel):
    borrower: str
    due_date: str

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    c = connect()
    try:
        # 写锁先行：与归还确认互斥，回包不会打在仍标 on_loan 的 id 上
        c.execute("BEGIN IMMEDIATE")
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item: raise HTTPException(404, "item")
        active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
        check = can_lend(item["status"], active)
        if not check["ok"]: raise HTTPException(409, check["reason"])
        cur = c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (iid, body.borrower, "active", body.due_date, datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
        c.commit()
        return {"loan_id": cur.lastrowid}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

class ReturnIn(BaseModel):
    note: str = ""

def _load_active_loan(c, lid: int):
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: raise HTTPException(404, "loan")
    if loan["status"] != "active": raise HTTPException(400, "not_active")
    item = c.execute("SELECT * FROM items WHERE id=?", (loan["item_id"],)).fetchone()
    if not item: raise HTTPException(409, "item_missing")
    return loan, item

@app.post("/api/loans/{lid}/return/preview")
def return_preview(lid: int, body: ReturnIn):
    # 预览只算不写：不改 items.status、不落破损条
    c = connect()
    try:
        loan, _ = _load_active_loan(c, lid)
        return {"loan_id": lid, "item_id": loan["item_id"], **damage_note.plan_return(body.note)}
    finally:
        c.close()

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int, body: ReturnIn):
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        loan, _ = _load_active_loan(c, lid)
        plan = damage_note.apply_return(c, loan, body.note, datetime.now(timezone.utc).isoformat())
        c.commit()
        return {"ok": True, "loan_id": lid, "item_id": loan["item_id"], **plan}
    except Exception:
        # 归还失败整单回滚：不动其它行，脏数据-无主不会被洗白
        c.rollback()
        raise
    finally:
        c.close()

@app.post("/api/items/{iid}/unlock")
def unlock_item(iid: int):
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item: raise HTTPException(404, "item")
        check = can_unlock(item["status"])
        if not check["ok"]: raise HTTPException(409, check["reason"])
        c.execute("UPDATE items SET status='available' WHERE id=?", (iid,))
        c.commit()
        return {"ok": True}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title, damage_notes.note AS damage_note
           FROM loans JOIN items ON items.id=loans.item_id
           LEFT JOIN damage_notes ON damage_notes.loan_id=loans.id
           ORDER BY loans.id DESC""")]
    c.close()
    return classify_loans(rows, date.today().isoformat())

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows
