"""CRUD tests for /api/patterns.

Uses an in-memory SQLite database — no file left on disk after the test run.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# ---- test database setup ---------------------------------------------------
# StaticPool ensures all sessions share the same in-memory connection so that
# data written in one request is visible in the next.

import app.db_models as _db_models  # noqa: F401 — register ORM models before create_all

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=test_engine)

TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# ---- fixtures --------------------------------------------------------------

MINIMAL_GEOMETRY = {
    "version": 1,
    "measurements": {"waist": 72.0, "hip": 96.0},
    "pieces": [],
}

GEOMETRY_WITH_PIECES = {
    "version": 1,
    "measurements": {"waist": 70.0, "hip": 90.0, "length": 60.0},
    "pieces": [
        {
            "id": "front-skirt",
            "name": "Front Skirt",
            "cut_qty": 1,
            "on_fold": True,
            "seam_allowance": 1.5,
            "elements": [
                {"from": [0.0, 0.0], "to": [0.0, 60.0], "type": "line"},
                {"from": [0.0, 0.0], "to": [24.0, 0.0], "type": "line", "formula": "waist / 2"},
            ],
            "grain_lines": [{"x1": 12.0, "y1": 5.0, "x2": 12.0, "y2": 55.0}],
            "notches": [],
        }
    ],
}

# ---- tests -----------------------------------------------------------------


def test_create_pattern_minimal():
    resp = client.post("/api/patterns", json={"name": "Test Skirt", "geometry": MINIMAL_GEOMETRY})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Skirt"
    assert data["piece_count"] == 0
    assert data["waist_cm"] == 72.0
    assert data["hip_cm"] == 96.0
    assert "id" in data
    assert "created_at" in data


def test_create_pattern_with_pieces():
    resp = client.post(
        "/api/patterns",
        json={"name": "Pencil Skirt", "garment_type": "skirt", "geometry": GEOMETRY_WITH_PIECES},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["piece_count"] == 1
    assert data["waist_cm"] == 70.0
    assert data["garment_type"] == "skirt"
    # geometry blob returned intact
    assert data["geometry"]["pieces"][0]["name"] == "Front Skirt"


def test_list_patterns():
    # create two patterns
    client.post("/api/patterns", json={"name": "A", "geometry": MINIMAL_GEOMETRY})
    client.post("/api/patterns", json={"name": "B", "garment_type": "skirt", "geometry": MINIMAL_GEOMETRY})

    resp = client.get("/api/patterns")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_list_patterns_filter_garment_type():
    client.post("/api/patterns", json={"name": "Filtered", "garment_type": "bodice", "geometry": MINIMAL_GEOMETRY})
    resp = client.get("/api/patterns?garment_type=bodice")
    assert resp.status_code == 200
    assert all(p["garment_type"] == "bodice" for p in resp.json())


def test_get_pattern():
    create = client.post("/api/patterns", json={"name": "Get Me", "geometry": MINIMAL_GEOMETRY})
    pid = create.json()["id"]

    resp = client.get(f"/api/patterns/{pid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid
    assert "geometry" in resp.json()


def test_get_pattern_not_found():
    resp = client.get("/api/patterns/nonexistent-id")
    assert resp.status_code == 404


def test_update_pattern_name():
    create = client.post("/api/patterns", json={"name": "Old Name", "geometry": MINIMAL_GEOMETRY})
    pid = create.json()["id"]

    resp = client.put(f"/api/patterns/{pid}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_update_pattern_geometry_syncs_metadata():
    create = client.post("/api/patterns", json={"name": "Sync Test", "geometry": MINIMAL_GEOMETRY})
    pid = create.json()["id"]

    new_geo = {
        "version": 1,
        "measurements": {"waist": 80.0, "hip": 100.0},
        "pieces": [
            {
                "id": "p1",
                "name": "Back",
                "cut_qty": 2,
                "on_fold": False,
                "seam_allowance": 1.5,
                "elements": [],
                "grain_lines": [],
                "notches": [],
            }
        ],
    }
    resp = client.put(f"/api/patterns/{pid}", json={"geometry": new_geo})
    assert resp.status_code == 200
    data = resp.json()
    assert data["waist_cm"] == 80.0
    assert data["hip_cm"] == 100.0
    assert data["piece_count"] == 1


def test_delete_pattern():
    create = client.post("/api/patterns", json={"name": "Delete Me", "geometry": MINIMAL_GEOMETRY})
    pid = create.json()["id"]

    resp = client.delete(f"/api/patterns/{pid}")
    assert resp.status_code == 204

    resp = client.get(f"/api/patterns/{pid}")
    assert resp.status_code == 404


def test_delete_pattern_not_found():
    resp = client.delete("/api/patterns/ghost-id")
    assert resp.status_code == 404


def test_curve_element_requires_control_points():
    geo = {
        "version": 1,
        "measurements": {},
        "pieces": [
            {
                "id": "p1",
                "name": "Bad Piece",
                "cut_qty": 1,
                "on_fold": False,
                "seam_allowance": 1.5,
                "elements": [
                    # curve without cp1/cp2 — should fail validation
                    {"from": [0.0, 0.0], "to": [10.0, 5.0], "type": "curve"}
                ],
                "grain_lines": [],
                "notches": [],
            }
        ],
    }
    resp = client.post("/api/patterns", json={"name": "Bad Curve", "geometry": geo})
    assert resp.status_code == 422
