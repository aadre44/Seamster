"""Tests for the most-recent-run debug trace (backend/debug/last_run.json)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.debug_trace as dt
from app.main import app


@pytest.fixture()
def trace_path(tmp_path, monkeypatch):
    path = tmp_path / "last_run.json"
    monkeypatch.setattr(dt, "TRACE_PATH", path)
    dt.begin_generate()  # clear any events left over from other tests
    return path


def _read(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_trace_analyze_starts_a_fresh_run(trace_path):
    dt.trace_analyze(
        {"garment_type": "skirt"}, "SYS", "USER", '{"ok": 1}', {"silhouette": "a_line"},
    )
    data = _read(trace_path)
    assert data["analyze"]["request"] == {"garment_type": "skirt"}
    assert data["analyze"]["system_prompt"] == "SYS"
    assert data["analyze"]["raw_response"] == '{"ok": 1}'
    assert data["analyze"]["features"] == {"silhouette": "a_line"}
    assert data["analyze"]["error"] is None
    assert data["generate"] is None


def test_trace_generate_attaches_events_and_keeps_analyze(trace_path):
    dt.trace_analyze({"garment_type": "skirt"}, "SYS", "USER", "{}", {})
    dt.begin_generate()
    dt.add_event("template_hit", detail="belt", template_id="belt-skirt-v1")
    dt.trace_generate(
        {"shape_mode": "modifiers"},
        {"pieces": [{"name": "Front", "source": "engine", "cutQty": 1}],
         "elements": [], "connections": []},
    )
    data = _read(trace_path)
    assert data["analyze"] is not None  # same run, both halves present
    gen = data["generate"]
    assert gen["request"] == {"shape_mode": "modifiers"}
    assert gen["events"][0]["stage"] == "template_hit"
    assert gen["summary"]["piece_count"] == 1
    assert gen["summary"]["pieces"][0]["source"] == "engine"
    assert gen["output"]["pieces"][0]["name"] == "Front"


def test_new_analyze_clears_previous_generate(trace_path):
    dt.trace_generate({}, {"pieces": [], "elements": []})
    assert _read(trace_path)["generate"] is not None
    dt.trace_analyze({"garment_type": "vest"}, "SYS", "USER", "{}", {})
    data = _read(trace_path)
    assert data["generate"] is None
    assert data["analyze"]["request"]["garment_type"] == "vest"


def test_generate_without_analyze_still_traces(trace_path):
    dt.begin_generate()
    dt.trace_generate({"shape_mode": "warp"}, None, error="boom")
    data = _read(trace_path)
    assert data["analyze"] is None
    assert data["generate"]["error"] == "boom"
    assert data["generate"]["summary"] is None


def test_events_reset_between_generates(trace_path):
    dt.begin_generate()
    dt.add_event("llm_fallback_placeholder", detail="x")
    dt.trace_generate({}, {"pieces": [], "elements": []})
    dt.begin_generate()
    dt.trace_generate({}, {"pieces": [], "elements": []})
    assert _read(trace_path)["generate"]["events"] == []


def test_generate_endpoint_writes_trace(trace_path):
    client = TestClient(app)
    resp = client.post("/api/generate", json={
        "features": {
            "garment_type": "skirt",
            "silhouette": "straight",
            "length_category": "knee",
            "closure": {"type": "center_back_zip", "position": "center_back"},
            "details": [],
            "confidence": 0.9,
        },
        "measurements": {
            "waist_cm": 76, "hip_cm": 94, "waist_to_hip_cm": 21, "length_cm": 65,
        },
    })
    assert resp.status_code == 200
    data = _read(trace_path)
    gen = data["generate"]
    assert gen["error"] is None
    assert gen["request"]["features"]["garment_type"] == "skirt"
    assert gen["summary"]["piece_count"] >= 2
    assert gen["output"]["pieces"]  # the full psnap is stored


def test_trace_refine_attaches_third_half_and_keeps_others(trace_path):
    dt.trace_analyze({"garment_type": "vest"}, "SYS", "USER", "{}", {})
    dt.begin_generate()
    dt.trace_generate({"shape_mode": "modifiers"}, {"pieces": [], "elements": []})
    dt.begin_refine()
    dt.add_event("refine_piece_accepted", name="Overlap Front")
    dt.trace_refine(
        {"garment_type": "vest", "piece_count": 6},
        "REFINE-SYS", ["USER-1", "USER-2"], ["{}", '{"pieces": []}'],
        {"changed": ["Overlap Front"], "rejected": [], "unchanged": ["Back Bodice"]},
    )
    data = _read(trace_path)
    assert data["analyze"] is not None and data["generate"] is not None
    ref = data["refine"]
    assert ref["request"]["piece_count"] == 6
    assert ref["system_prompt"] == "REFINE-SYS"
    assert ref["user_prompts"] == ["USER-1", "USER-2"]
    assert len(ref["raw_responses"]) == 2
    assert ref["events"][0]["stage"] == "refine_piece_accepted"
    assert ref["summary"]["changed"] == ["Overlap Front"]
    assert ref["error"] is None
