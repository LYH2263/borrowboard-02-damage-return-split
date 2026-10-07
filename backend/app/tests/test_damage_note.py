import pytest
from app import main, seed
from app.db import connect
from app.modules import damage_note


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    return tmp_path


def rows(c, sql, args=()):
    return [dict(r) for r in c.execute(sql, args)]


def test_preview_does_not_touch_items(db):
    c = connect()
    before = rows(c, "SELECT * FROM items")
    c.close()
    plan = main.return_preview(1, main.ReturnIn(note="角裂了"))
    assert plan["damage"] and plan["next_status"] == damage_note.DAMAGED_HOLD
    assert main.return_preview(1, main.ReturnIn(note=""))["next_status"] == "available"
    c = connect()
    assert rows(c, "SELECT * FROM items") == before
    assert rows(c, "SELECT * FROM damage_notes") == []
    assert c.execute("SELECT status FROM loans WHERE id=1").fetchone()["status"] == "active"
    c.close()


def test_confirm_with_damage_holds_item_out_of_available(db):
    r = main.return_loan(1, main.ReturnIn(note="角裂了"))
    assert r["damage"] and r["next_status"] == damage_note.DAMAGED_HOLD
    c = connect()
    assert c.execute("SELECT status FROM items WHERE id=4").fetchone()["status"] == damage_note.DAMAGED_HOLD
    loan = c.execute("SELECT * FROM loans WHERE id=1").fetchone()
    assert loan["status"] == "returned" and loan["returned_at"]
    notes = rows(c, "SELECT * FROM damage_notes")
    assert len(notes) == 1 and notes[0]["loan_id"] == 1 and notes[0]["item_id"] == 4
    assert notes[0]["note"] == "角裂了"
    c.close()
    # 资格链：可借栏、顶细条可借数都不含待解锁物
    b = main.board()
    assert all(i["id"] != 4 for i in b["available"])
    assert b["counts"]["available"] == len(b["available"])
    assert [i["id"] for i in b["held"]] == [4] and b["counts"]["held"] == 1


def test_confirm_clean_returns_to_available(db):
    r = main.return_loan(1, main.ReturnIn(note="  "))
    assert not r["damage"] and r["next_status"] == "available"
    c = connect()
    assert c.execute("SELECT status FROM items WHERE id=4").fetchone()["status"] == "available"
    assert rows(c, "SELECT * FROM damage_notes") == []
    c.close()


def test_held_item_cannot_be_lent_until_unlocked(db):
    main.return_loan(1, main.ReturnIn(note="裂"))
    with pytest.raises(main.HTTPException) as e:
        main.lend(4, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))
    assert e.value.status_code == 409
    main.unlock_item(4)
    assert main.lend(4, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))["loan_id"]
    c = connect()
    assert c.execute("SELECT status FROM items WHERE id=4").fetchone()["status"] == "on_loan"
    c.close()


def test_unlock_rejects_non_held(db):
    with pytest.raises(main.HTTPException) as e:
        main.unlock_item(1)
    assert e.value.status_code == 409


def test_returned_overdue_leaves_topbar_and_stacks_returned(db):
    assert main.board()["counts"]["overdue"] == 1
    main.return_loan(1, main.ReturnIn(note=""))
    b = main.board()
    assert b["counts"]["overdue"] == 0 and b["overdue"] == []
    data = main.loans()
    assert data["overdue"] == [] and data["active"] == []
    assert len(data["returned"]) == 1 and data["returned"][0]["id"] == 1


def test_loans_listing_carries_damage_note(db):
    main.return_loan(1, main.ReturnIn(note="掉漆"))
    data = main.loans()
    assert data["returned"][0]["damage_note"] == "掉漆"


def test_failed_return_rolls_back_and_dirty_seed_stays_dirty(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(damage_note, "apply_return", boom)
    with pytest.raises(RuntimeError):
        main.return_loan(1, main.ReturnIn(note="裂"))
    c = connect()
    assert c.execute("SELECT status FROM loans WHERE id=1").fetchone()["status"] == "active"
    assert c.execute("SELECT status FROM items WHERE id=4").fetchone()["status"] == "on_loan"
    dirty = c.execute("SELECT * FROM items WHERE id=3").fetchone()
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty" and dirty["status"] == "available"
    assert rows(c, "SELECT * FROM damage_notes") == []
    c.close()
    assert main.board()["counts"]["overdue"] == 1


def test_double_return_rejected_without_side_effects(db):
    main.return_loan(1, main.ReturnIn(note="裂"))
    with pytest.raises(main.HTTPException) as e:
        main.return_loan(1, main.ReturnIn(note="再写一条"))
    assert e.value.status_code == 400
    c = connect()
    assert len(rows(c, "SELECT * FROM damage_notes")) == 1
    dirty = c.execute("SELECT * FROM items WHERE id=3").fetchone()
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty"
    c.close()


def test_relend_after_clean_return_lands_on_available_id(db):
    main.return_loan(1, main.ReturnIn(note=""))
    r = main.lend(4, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))
    c = connect()
    loan = c.execute("SELECT * FROM loans WHERE id=?", (r["loan_id"],)).fetchone()
    assert loan["status"] == "active" and loan["item_id"] == 4
    assert c.execute("SELECT status FROM items WHERE id=4").fetchone()["status"] == "on_loan"
    c.close()
    with pytest.raises(main.HTTPException) as e:
        main.lend(4, main.LendIn(borrower="邻居丙", due_date="2026-12-31"))
    assert e.value.status_code == 409
