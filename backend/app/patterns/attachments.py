"""Where trims attach: seams for collars, cuffs, waistbands, facings, flies and
pocket bags, and placements for patch pockets and welts.

The label-based stitch map (engine._compute_connections) joins the garment
shell. Trims are mostly plain rectangles with unlabelled edges, and where they
do carry a label (a collar's ``neckline``) one trim edge runs along SEVERAL
host edges — a collar along the back then the front neckline — which a
whole-edge pairing gets wrong. This module works from piece names and
geometry, so it applies to engine patterns, AI pieces and hand-drawn ones alike
(``POST /api/infer-attachments``).

A trim edge is sewn along a *path* of host edges: each step is one host element
walked forwards or backwards, optionally on one side of the body (``side``,
the wearer's left/right) or one half of an on-fold sleeve (``half``). Where the
path crosses from one element to the next, the trim edge's range is split, so
every connection pairs a stretch of one trim element with a stretch of one host
element. Ranges are fractions of each element's length in its own start→end
direction, as the frontend expects (types/index.ts SeamEnd).

Everything produced here is marked ``source: "inferred"``; the Assembly view
keeps the user's own edits (``source: "user"``) when re-inferring.
"""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field

# Kept in step with frontend three/pieceClassifier.ts TRIM (yoke is shell here:
# it joins by yoke_seam labels).
_TRIM_RE = re.compile(
    r"\b(facing|facings|binding|pocket|pockets|welt|flap|collar|cuff|cuffs|loop|loops|strap|straps|tie|ties|"
    r"fly|shield|gusset|placket|belt|bag|lining|interfacing|casing|epaulet|epaulette|hood|waistband|band|"
    r"ruffle|frill|bow|tab|strip|sash)\b",
    re.IGNORECASE,
)
# Pieces that end up inside the garment once sewn.
_INSIDE_RE = re.compile(r"\b(facing|facings|bag|lining|interfacing|fly|shield)\b", re.IGNORECASE)
_CENTER = ("center_front", "center_back", "center_sleeve")
_EPS = 1e-6


def is_trim(name: str) -> bool:
    return bool(_TRIM_RE.search(name))


def layer_of(name: str) -> str:
    return "inside" if _INSIDE_RE.search(name) else "outer"


# ── Geometry ──────────────────────────────────────────────────────────────────

def _length(e: dict) -> float:
    from app.patterns.engine import _edge_length
    return _edge_length(e)


def _pt(p: dict) -> tuple[float, float]:
    return (p["x"], p["y"])


def _mid(e: dict) -> tuple[float, float]:
    return ((e["start"]["x"] + e["end"]["x"]) / 2, (e["start"]["y"] + e["end"]["y"]) / 2)


def _near(p: tuple[float, float], q: tuple[float, float], tol: float = 0.05) -> bool:
    return math.hypot(p[0] - q[0], p[1] - q[1]) < tol


@dataclass
class _Piece:
    raw: dict
    edges: list[dict]

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def name(self) -> str:
        return self.raw.get("name", "")

    @property
    def cut(self) -> int:
        return int(self.raw.get("cutQty", 1))

    @property
    def on_fold(self) -> bool:
        return bool(self.raw.get("onFold"))

    def labelled(self, label: str) -> list[dict]:
        return [e for e in self.edges if e.get("seamLabel") == label and not e.get("isFold")]

    @property
    def labels(self) -> set[str]:
        return {e.get("seamLabel", "") for e in self.edges} - {""}

    @property
    def fold(self) -> list[dict]:
        return [e for e in self.edges if e.get("isFold")]

    @property
    def side(self) -> str | None:
        labels = self.labels
        if labels & {"center_front", "overlap_edge", "underlap_edge"}:
            return "front"
        if "center_back" in labels:
            return "back"
        n = self.name.lower()
        return "front" if re.search(r"\bfront\b", n) else "back" if re.search(r"\bback\b", n) else None

    def center_x(self) -> float | None:
        """x of the piece's centre line (CF / CB / fold edge)."""
        pts = [p for e in self.edges if e.get("isFold") or e.get("seamLabel") in _CENTER for p in (_pt(e["start"]), _pt(e["end"]))]
        return sum(p[0] for p in pts) / len(pts) if pts else None

    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for e in self.edges for p in (_pt(e["start"]), _pt(e["end"]))]
        ys = [p[1] for e in self.edges for p in (_pt(e["start"]), _pt(e["end"]))]
        return min(xs), min(ys), max(xs), max(ys)


def _pieces(elements: list[dict], pieces: list[dict]) -> list[_Piece]:
    by_id = {e["id"]: e for e in elements}
    out = []
    for p in pieces:
        edges = [by_id[i] for i in p.get("elementIds", []) if i in by_id and by_id[i].get("type") in ("line", "curve")]
        if edges:
            out.append(_Piece(p, edges))
    return out


# ── Sewing a trim edge along a path of host edges ─────────────────────────────

@dataclass
class _Step:
    piece: _Piece
    edge: dict
    forward: bool  # walk the element start→end
    side: str | None = None
    half: str | None = None
    length: float = field(init=False)

    def __post_init__(self) -> None:
        self.length = _length(self.edge)


def _end(piece_id: str, edge_id: str, lo: float, hi: float, side: str | None = None, half: str | None = None) -> dict:
    end: dict = {"pieceId": piece_id, "edgeId": edge_id}
    lo, hi = min(lo, hi), max(lo, hi)
    if lo > 1e-4 or hi < 1 - 1e-4:
        end["range"] = [round(lo, 4), round(hi, 4)]
    if side:
        end["side"] = side
    if half:
        end["half"] = half
    return end


def _sew(
    label: str,
    trim: _Piece,
    trim_edge: dict,
    path: list[_Step],
    *,
    trim_span: tuple[float, float] = (0.0, 1.0),
    trim_forward: bool = True,
    start_cm: float = 0.0,
    length_cm: float | None = None,
    trim_side: str | None = None,
) -> list[dict]:
    """Sew trim_span of trim_edge (walked forwards or backwards) along the path
    from start_cm for length_cm (default: to the end of the path)."""
    total = sum(s.length for s in path)
    if total <= _EPS:
        return []
    s0 = max(0.0, start_cm)
    s1 = min(total, s0 + length_cm) if length_cm is not None else total
    if s1 - s0 <= _EPS:
        return []
    t_lo, t_hi = trim_span
    out: list[dict] = []
    c0 = 0.0
    for step in path:
        c1 = c0 + step.length
        a, b = max(s0, c0), min(s1, c1)
        if b - a > 0.05:
            # host element fractions (element direction)
            u0, u1 = (a - c0) / step.length, (b - c0) / step.length
            h_lo, h_hi = (u0, u1) if step.forward else (1 - u1, 1 - u0)
            # trim fractions: path position → trim span, in the trim's walking direction
            f0 = t_lo + (t_hi - t_lo) * (a - s0) / (s1 - s0)
            f1 = t_lo + (t_hi - t_lo) * (b - s0) / (s1 - s0)
            g_lo, g_hi = (f0, f1) if trim_forward else (1 - f1, 1 - f0)
            out.append({
                "label": label,
                "from": _end(trim.id, trim_edge["id"], g_lo, g_hi, side=trim_side),
                "to": _end(step.piece.id, step.edge["id"], h_lo, h_hi, side=step.side, half=step.half),
                # element start meets element start unless exactly one of them is walked backwards
                "reversed": step.forward != trim_forward,
                "source": "inferred",
            })
        c0 = c1
    return out


# ── Host paths ────────────────────────────────────────────────────────────────

def _from_center(piece: _Piece, edges: list[dict], outward: bool) -> list[_Step]:
    """A piece's edges ordered and oriented away from (or toward) its centre line."""
    cx = piece.center_x()
    if cx is None:
        cx = piece.bbox()[0]
    dist = lambda p: abs(p[0] - cx)  # noqa: E731
    ordered = sorted(edges, key=lambda e: dist(_mid(e)), reverse=not outward)
    steps = []
    for e in ordered:
        away = dist(_pt(e["end"])) >= dist(_pt(e["start"]))
        steps.append(_Step(piece, e, forward=away if outward else not away))
    return steps


def _reverse(steps: list[_Step], side: str | None = None, half: str | None = None) -> list[_Step]:
    return [_Step(s.piece, s.edge, not s.forward, side=side or s.side, half=half or s.half) for s in reversed(steps)]


def _with(steps: list[_Step], side: str | None = None, half: str | None = None) -> list[_Step]:
    return [_Step(s.piece, s.edge, s.forward, side=side or s.side, half=half or s.half) for s in steps]


def _shell_by_side(shell: list[_Piece], label: str) -> tuple[_Piece | None, _Piece | None]:
    front = next((p for p in shell if p.side == "front" and p.labelled(label)), None)
    back = next((p for p in shell if p.side == "back" and p.labelled(label)), None)
    return front, back


def _around(shell: list[_Piece], label: str, start: str) -> tuple[list[_Step], list[_Step]] | None:
    """Half and full paths around the body along `label` edges (neckline, waist,
    hem). A half path covers one side from the centre `start` ('back' or
    'front') to the other centre; the full path starts at the wearer's right
    front centre and goes all the way round."""
    front, back = _shell_by_side(shell, label)
    if not front and not back:
        return None
    f_out = _from_center(front, front.labelled(label), outward=True) if front else []  # CF → side
    b_out = _from_center(back, back.labelled(label), outward=True) if back else []     # CB → side
    if start == "back":
        half = b_out + _reverse(f_out)          # CB → side → CF
    else:
        half = f_out + _reverse(b_out)          # CF → side → CB
    full = (_with(f_out, side="right") + _reverse(b_out, side="right")
            + _with(b_out, side="left") + _reverse(f_out, side="left"))   # CF(R) → CB → CF(L)
    return half, full


# ── Rules ─────────────────────────────────────────────────────────────────────

def _attach_edge(trim: _Piece, label: str | None = None) -> dict:
    """The trim edge that is sewn: the one carrying the host's label, else the
    longest edge that is not a fold (the first of equals, i.e. the top edge of
    a drafted rectangle)."""
    if label:
        for e in trim.edges:
            if e.get("seamLabel") == label and not e.get("isFold"):
                return e
    cands = [e for e in trim.edges if not e.get("isFold")]
    best = max(_length(e) for e in cands)
    return next(e for e in cands if _length(e) >= best - 0.05)


def _walk_from(trim: _Piece, edge: dict) -> bool:
    """Walk a trim edge from its fold end (a collar cut on the CB fold starts at CB)."""
    for f in trim.fold:
        if any(_near(_pt(edge["start"]), _pt(p)) for p in (f["start"], f["end"])):
            return True
        if any(_near(_pt(edge["end"]), _pt(p)) for p in (f["start"], f["end"])):
            return False
    return True


def _around_rule(trim: _Piece, shell: list[_Piece], label: str, start: str) -> list[dict]:
    paths = _around(shell, label, start)
    if not paths:
        return []
    half, full = paths
    edge = _attach_edge(trim, label)
    L = _length(edge)
    H = sum(s.length for s in half)
    if trim.fold or L < 1.5 * H:
        # One side (a collar cut on the fold, or one of a pair): copies pair by side.
        return _sew(label, trim, edge, half, trim_forward=_walk_from(trim, edge), trim_span=_true_span(L, H, label, trim.name))
    return _sew(label, trim, edge, full, trim_span=_true_span(L, 2 * H, label, trim.name))


def _true_span(trim_len: float, path_len: float, label: str, name: str = "") -> tuple[float, float]:
    """A band longer than the opening is sewn length for length; a shorter one is
    eased along it. A waistband keeps its extra length as the overlap at its end;
    a collar or neck band has a seam allowance at each end, so its extra is
    shared between the two ends. An elastic / drawstring casing is gathered evenly."""
    if trim_len <= path_len * 1.02 or re.search(r"elastic|drawstring|gather", name, re.IGNORECASE):
        return (0.0, 1.0)
    used = path_len / trim_len
    if label == "neckline":
        return ((1 - used) / 2, (1 + used) / 2)
    return (0.0, used)


def _wrist_rule(trim: _Piece, shell: list[_Piece]) -> list[dict]:
    sleeves = [p for p in shell if p.labelled("wrist")]
    if not sleeves:
        return []
    edge = _attach_edge(trim, "wrist")
    L = _length(edge)
    steps: list[_Step] = []
    for s in sleeves:  # one sleeve, or upper + under sleeve
        for e in s.labelled("wrist"):
            steps.append(_Step(s, e, forward=True))
    W = sum(s.length for s in steps)
    if len(sleeves) == 1 and sleeves[0].on_fold and L > 1.5 * W:
        # A cuff all round an on-fold sleeve: its front half, then its back half.
        steps = _with(steps, half="front") + _reverse(steps, half="back")
    return _sew("wrist", trim, edge, steps)


def _armhole_rule(trim: _Piece, shell: list[_Piece]) -> list[dict]:
    front, back = _shell_by_side(shell, "armhole")
    steps = ([_Step(front, e, True) for e in front.labelled("armhole")] if front else []) + \
            ([_Step(back, e, True) for e in back.labelled("armhole")] if back else [])
    if not steps:
        return []
    return _sew("armhole", trim, _attach_edge(trim, "armhole"), steps)


def _center_path(host: _Piece, label: str, from_label: str) -> list[_Step]:
    """A piece's centre edges (CF / CB) walked from the end at `from_label`
    (the waist or neckline) downwards."""
    edges = host.labelled(label)
    anchors = [p for e in host.labelled(from_label) for p in (_pt(e["start"]), _pt(e["end"]))]
    if not edges:
        return []
    if anchors:
        top = min(anchors, key=lambda a: min(math.hypot(a[0] - p[0], a[1] - p[1]) for e in edges for p in (_pt(e["start"]), _pt(e["end"]))))
    else:
        top = min((p for e in edges for p in (_pt(e["start"]), _pt(e["end"]))), key=lambda p: p[1])
    d = lambda p: math.hypot(p[0] - top[0], p[1] - top[1])  # noqa: E731
    ordered = sorted(edges, key=lambda e: min(d(_pt(e["start"])), d(_pt(e["end"]))))
    return [_Step(host, e, forward=d(_pt(e["start"])) <= d(_pt(e["end"]))) for e in ordered]


def _fly_rule(trim: _Piece, shell: list[_Piece], side: str) -> list[dict]:
    host = next((p for p in shell if p.side == "front" and p.labelled("center_front") and p.labelled("waist")), None)
    if not host:
        return []
    path = _with(_center_path(host, "center_front", "waist"), side=side)
    cf = sum(s.length for s in path)
    # The fly edge is the trim's straight edge closest to the CF length.
    lines = [e for e in trim.edges if e.get("type") == "line"] or trim.edges
    edge = min(lines, key=lambda e: abs(_length(e) - cf))
    walk_down = _pt(edge["start"])[1] <= _pt(edge["end"])[1]
    return _sew("fly", trim, edge, path, trim_forward=walk_down, length_cm=min(_length(edge), cf))


def _placket_rule(trim: _Piece, shell: list[_Piece]) -> list[dict]:
    host = next((p for p in shell if p.side == "front" and p.labelled("center_front") and p.labelled("neckline")), None)
    if not host:
        return []
    path = _center_path(host, "center_front", "neckline")
    edge = _attach_edge(trim)
    walk_down = _pt(edge["start"])[1] <= _pt(edge["end"])[1]
    return _sew("placket", trim, edge, path, trim_forward=walk_down, length_cm=_length(edge))


def _front_facing_rule(trim: _Piece, shell: list[_Piece]) -> list[dict]:
    host = next((p for p in shell if p.side == "front" and p.labelled("center_front")), None)
    if not host:
        return []
    top = "neckline" if host.labelled("neckline") else "waist"
    path = _center_path(host, "center_front", top)
    edge = _attach_edge(trim)
    walk_down = _pt(edge["start"])[1] <= _pt(edge["end"])[1]
    return _sew("facing", trim, edge, path, trim_forward=walk_down, length_cm=_length(edge))


def _pocket_bag_rule(trim: _Piece, shell: list[_Piece]) -> list[dict]:
    """An in-seam / side pocket bag, sewn into the front side seam just below the waist."""
    fronts = [p for p in shell if p.side == "front" and p.labelled("side_seam")]
    # The skirt / leg below the waist, not a bodice.
    host = next((p for p in fronts if (p.labelled("waist") or p.labelled("waist_seam")) and not p.labelled("armhole")), None) \
        or next(iter(fronts), None)
    if not host:
        return []
    top_label = "waist" if host.labelled("waist") else "waist_seam" if host.labelled("waist_seam") else "armhole"
    path = _center_path(host, "side_seam", top_label)
    edge = _attach_edge(trim)
    walk_down = _pt(edge["start"])[1] <= _pt(edge["end"])[1]
    below_waist = 0.0 if host.labelled("inseam") else 3.0  # trousers: slant pocket from the waist
    return _sew("pocket_opening", trim, edge, path, trim_forward=walk_down, start_cm=below_waist, length_cm=_length(edge))


# ── Placements (patch pockets, welts) ─────────────────────────────────────────

def _side_x(host: _Piece, y: float) -> float | None:
    """x of the host's side seam at height y (clamped into its extent)."""
    segs = [(_pt(e["start"]), _pt(e["end"])) for e in host.labelled("side_seam")]
    if not segs:
        return None
    ys = [p[1] for s in segs for p in s]
    y = min(max(y, min(ys)), max(ys))
    for a, b in segs:
        if min(a[1], b[1]) - _EPS <= y <= max(a[1], b[1]) + _EPS:
            return a[0] if abs(b[1] - a[1]) < _EPS else a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1])
    return segs[0][0][0]


def _top_y(host: _Piece, label: str) -> float:
    pts = [p for e in host.labelled(label) for p in (_pt(e["start"]), _pt(e["end"]))]
    return max(p[1] for p in pts) if pts else host.bbox()[1]


def _placement(pocket: _Piece, host: _Piece, cx: float, top: float, side: str | None) -> dict:
    x0, y0, x1, y1 = pocket.bbox()
    mouth = min(pocket.edges, key=lambda e: _mid(e)[1])  # the top-most edge
    if re.search(r"\bbag\b", pocket.name, re.IGNORECASE):
        # A welt pocket bag hangs inside from the welt opening.
        stitched = [mouth["id"]]
    else:
        # A patch pocket / welt is stitched on every edge but its mouth.
        stitched = [e["id"] for e in pocket.edges if e is not mouth and e.get("seamLabel") != "pocket_opening"]
    out = {
        "id": str(uuid.uuid4()),
        "pieceId": pocket.id,
        "hostId": host.id,
        "transform": {"dx": round(cx - (x0 + x1) / 2, 3), "dy": round(top + (y1 - y0) / 2 - (y0 + y1) / 2, 3), "rotation": 0},
        "stitched": stitched,
        "source": "inferred",
    }
    if side:
        out["side"] = side
    return out


def _between(host: _Piece, y: float, f: float) -> float:
    """x at fraction f of the way from the host's centre line to its side seam."""
    c = host.center_x()
    s = _side_x(host, y)
    x0, _, x1, _ = host.bbox()
    c = c if c is not None else x0
    s = s if s is not None else x1
    return c + (s - c) * f


def _pocket_placement(pocket: _Piece, shell: list[_Piece]) -> dict | None:
    n = pocket.name.lower()
    h = pocket.bbox()[3] - pocket.bbox()[1]
    side = None if pocket.cut >= 2 else "left"
    fronts = [p for p in shell if p.side == "front"]
    backs = [p for p in shell if p.side == "back"]
    legs = lambda ps: [p for p in ps if p.labelled("inseam")]  # noqa: E731
    lower = lambda ps: [p for p in ps if (p.labelled("waist") or p.labelled("waist_seam")) and not p.labelled("neckline")]  # noqa: E731
    uppers = [p for p in fronts if p.labelled("neckline") or p.labelled("armhole")]

    if re.search(r"\b(chest|breast)\b", n) and uppers:
        host = uppers[0]
        # Pocket top a few cm above the bust line (the bottom of the armhole).
        top = _top_y(host, "armhole") - 4.0
        return _placement(pocket, host, _between(host, top + h / 2, 0.5), top, "left")
    if "cargo" in n and legs(fronts):
        host = legs(fronts)[0]
        crotch = _top_y(host, "crotch")
        return _placement(pocket, host, _between(host, crotch + 5 + h / 2, 0.85), crotch + 5, side)
    if re.search(r"\bback\b", n) and backs:
        host = (legs(backs) or lower(backs) or backs)[0]
        top = _top_y(host, "waist") + 6.0
        return _placement(pocket, host, _between(host, top + h / 2, 0.45), top, side)
    host = next(iter(lower([p for p in fronts if not p.labelled("neckline")]) or legs(fronts) or fronts), None)
    if not host:
        return None
    if host.labelled("neckline"):
        # A jacket / shirt front: hip pocket a hand's width above the hem.
        hem = host.bbox()[3]
        top = hem - h - 6.0
        return _placement(pocket, host, _between(host, top + h / 2, 0.5), top, side)
    top = _top_y(host, "waist" if host.labelled("waist") else "waist_seam") + (6.0 if host.labelled("inseam") else 8.0)
    return _placement(pocket, host, _between(host, top + h / 2, 0.5), top, side)


def _same_pocket(welt_name: str, bag_name: str) -> bool:
    """'welt strip' ↔ 'welt pocket bag', 'breast pocket welt' ↔ 'breast pocket bag'."""
    words = lambda s: set(re.findall(r"[a-z]+", s)) - {"pocket", "bag", "strip", "welt", "piece"}  # noqa: E731
    return "welt" in welt_name and words(welt_name) == words(bag_name)


def _under(bag: _Piece, welt: dict, ps: list[_Piece]) -> dict | None:
    """A bag placed with its mouth centred under the welt it hangs from."""
    w = next((p for p in ps if p.id == welt["pieceId"]), None)
    host = next((p for p in ps if p.id == welt["hostId"]), None)
    if not w or not host:
        return None
    x0, y0, x1, _ = w.bbox()
    cx = (x0 + x1) / 2 + welt["transform"]["dx"]
    top = y0 + welt["transform"]["dy"]
    return _placement(bag, host, cx, top, welt.get("side"))


# ── Entry point ───────────────────────────────────────────────────────────────

def infer_attachments(elements: list[dict], pieces: list[dict], connections: list[dict]) -> dict:
    """Seams and placements for the pattern's trims.

    Returns {"connections", "placements", "layers"}: the shell connections that
    don't involve a handled trim (marked inferred), plus trim seams; pocket and
    welt placements; and each trim's layer ('inside' / 'outer') by piece id.
    """
    ps = _pieces(elements, pieces)
    shell = [p for p in ps if not is_trim(p.name)]
    trims = [p for p in ps if is_trim(p.name)]
    seams: list[dict] = []
    placements: list[dict] = []
    handled: set[str] = set()
    # Welt pocket bags hang under their welt: place the welts first.
    trims.sort(key=lambda t: bool(re.search(r"\bbag\b", t.name, re.IGNORECASE)))
    placed_at: dict[str, dict] = {}
    for t in trims:
        n = t.name.lower()
        new: list[dict] = []
        placement = None
        if re.search(r"\bfly\b", n) and "facing" in n:
            new = _fly_rule(t, shell, "left")
        elif "shield" in n:
            new = _fly_rule(t, shell, "right")
        elif re.search(r"\b(collar|hood)\b", n) or re.search(r"\b(neck|collar|turtleneck)\b.*\b(band|binding|facing)\b", n):
            new = _around_rule(t, shell, "neckline", "back")
        elif re.search(r"\bwaistband\b", n) or ("band" in n and "waist" in n):
            new = _around_rule(t, shell, "waist", "front")
        elif re.search(r"\bcuff", n) or ("band" in n and re.search(r"\b(wrist|sleeve)\b", n)):
            new = _wrist_rule(t, shell)
        elif "armhole" in n:
            new = _armhole_rule(t, shell)
        elif re.search(r"\bhem\b", n) or re.search(r"\b(ruffle|frill|flounce)\b", n):
            new = _around_rule(t, shell, "hem", "front")
        elif "placket" in n:
            new = _placket_rule(t, shell)
        elif re.search(r"\bfront\b", n) and "facing" in n:
            new = _front_facing_rule(t, shell)
        elif re.search(r"\b(neck|neckline)\b", n) and "facing" in n:
            new = _around_rule(t, shell, "neckline", "back")
        elif "bag" in n and not re.search(r"\b(welt|breast)\b", n):
            new = _pocket_bag_rule(t, shell)
        elif "pocket" in n or re.search(r"\bwelt\b", n):
            welt = next((pl for name, pl in placed_at.items() if "bag" in n and _same_pocket(name, n)), None)
            placement = _under(t, welt, ps) if welt else _pocket_placement(t, shell)
            if placement:
                placed_at[n] = placement
        if new:
            seams += new
            handled.add(t.id)
        if placement:
            placements.append(placement)
            handled.add(t.id)

    kept = [{**c, "source": c.get("source", "inferred")} for c in connections
            if c["from"]["pieceId"] not in handled and c["to"]["pieceId"] not in handled]
    layers = {t.id: layer_of(t.name) for t in trims}
    return {"connections": kept + seams, "placements": placements, "layers": layers}


def apply_attachments(psnap: dict) -> dict:
    """Adds trim seams, placements and inside layers to a generated .psnap."""
    result = infer_attachments(psnap.get("elements", []), psnap.get("pieces", []), psnap.get("connections", []))
    pieces = [{**p, "layer": result["layers"][p["id"]]} if p["id"] in result["layers"] else p for p in psnap.get("pieces", [])]
    return {**psnap, "pieces": pieces, "connections": result["connections"], "placements": result["placements"]}
