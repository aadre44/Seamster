"""Tiles a pattern across printable PDF pages using reportlab."""
import io
import math

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import cm

# ── Constants ─────────────────────────────────────────────────────────────────

OVERLAP_CM = 1.5          # overlap between adjacent pages
MARGIN_CM  = 0.8          # page margin
CROSSHAIR  = 0.5          # crosshair arm length in cm

PAPER_SIZES = {
    "a4":     A4,
    "letter": LETTER,
}


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _sample_bezier(sx, sy, cx1, cy1, cx2, cy2, ex, ey, t):
    u = 1 - t
    return (
        u**3*sx + 3*u**2*t*cx1 + 3*u*t**2*cx2 + t**3*ex,
        u**3*sy + 3*u**2*t*cy1 + 3*u*t**2*cy2 + t**3*ey,
    )


def _bounding_box(elements):
    xs, ys = [], []
    for el in elements:
        t = el.get("type", "")
        if t == "line":
            xs += [el["start"]["x"], el["end"]["x"]]
            ys += [el["start"]["y"], el["end"]["y"]]
        elif t == "curve":
            for pt in ("start", "end", "cp1", "cp2"):
                xs.append(el[pt]["x"]); ys.append(el[pt]["y"])
        elif t == "grain-line":
            xs += [el["start"]["x"], el["end"]["x"]]
            ys += [el["start"]["y"], el["end"]["y"]]
        elif t == "notch":
            xs.append(el["position"]["x"]); ys.append(el["position"]["y"])
    if not xs:
        return 0, 0, 10, 10
    return min(xs), min(ys), max(xs), max(ys)


def _flatten_piece(element_ids, el_map):
    pts = []
    for eid in element_ids:
        el = el_map.get(eid)
        if not el:
            continue
        if el["type"] == "line":
            pts.append((el["start"]["x"], el["start"]["y"]))
        elif el["type"] == "curve":
            s = el["start"]; c1 = el["cp1"]; c2 = el["cp2"]
            for i in range(16):
                x, y = _sample_bezier(s["x"], s["y"], c1["x"], c1["y"],
                                      c2["x"], c2["y"], el["end"]["x"], el["end"]["y"], i / 16)
                pts.append((x, y))
    return pts


def _offset_polygon(pts, d):
    n = len(pts)
    if n < 3:
        return pts
    area = sum(pts[i][0]*pts[(i+1)%n][1] - pts[(i+1)%n][0]*pts[i][1] for i in range(n))
    sign = 1 if area > 0 else -1
    off_edges = []
    for i in range(n):
        j = (i + 1) % n
        dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
        length = math.hypot(dx, dy)
        if length < 1e-10:
            off_edges.append((pts[i], pts[j]))
            continue
        nx, ny = sign * dy / length, sign * (-dx) / length
        off_edges.append((
            (pts[i][0] + nx * d, pts[i][1] + ny * d),
            (pts[j][0] + nx * d, pts[j][1] + ny * d),
        ))
    result = []
    for i in range(n):
        prev = (i - 1 + n) % n
        a1, a2 = off_edges[prev]
        b1, b2 = off_edges[i]
        dx1, dy1 = a2[0]-a1[0], a2[1]-a1[1]
        dx2, dy2 = b2[0]-b1[0], b2[1]-b1[1]
        denom = dx1*dy2 - dy1*dx2
        if abs(denom) < 1e-10:
            result.append(b1)
        else:
            t = ((b1[0]-a1[0])*dy2 - (b1[1]-a1[1])*dx2) / denom
            result.append((a1[0] + t*dx1, a1[1] + t*dy1))
    return result


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _pt(x_cm, y_cm, origin_x, origin_y, page_h_cm):
    """Convert pattern cm coords to reportlab pts (Y-axis flipped)."""
    return (x_cm - origin_x) * cm, (page_h_cm - (y_cm - origin_y)) * cm


def _draw_pattern(c, elements, pieces, origin_x, origin_y, page_h_cm,
                  page_w_pts, page_h_pts):
    def pt(x, y):
        return _pt(x, y, origin_x, origin_y, page_h_cm)

    el_map = {el["id"]: el for el in elements}

    # Piece fills + seam allowances
    for piece in pieces:
        pts = _flatten_piece(piece["elementIds"], el_map)
        if len(pts) < 3:
            continue
        poly_pts = [pt(x, y) for x, y in pts]
        c.setFillColorRGB(0.73, 0.9, 0.98, alpha=0.4)
        c.setStrokeColorRGB(0.1, 0.1, 0.1)
        c.setLineWidth(0.5)
        path = c.beginPath()
        path.moveTo(*poly_pts[0])
        for px, py in poly_pts[1:]:
            path.lineTo(px, py)
        path.close()
        c.drawPath(path, fill=1, stroke=1)

        sa = piece.get("seamAllowance", 0)
        if sa > 0:
            off = _offset_polygon(pts, sa)
            if len(off) >= 3:
                off_pts = [pt(x, y) for x, y in off]
                c.setFillColorRGB(0, 0, 0, alpha=0)
                c.setStrokeColorRGB(0.94, 0.27, 0.27)
                c.setLineWidth(0.5)
                c.setDash(4, 3)
                path2 = c.beginPath()
                path2.moveTo(*off_pts[0])
                for px, py in off_pts[1:]:
                    path2.lineTo(px, py)
                path2.close()
                c.drawPath(path2, fill=0, stroke=1)
                c.setDash()

        if pts:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            lx, ly = pt(cx, cy)
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setFont("Helvetica", 7)
            c.drawCentredString(lx, ly + 4, piece.get("name", ""))
            c.setFont("Helvetica", 5)
            c.drawCentredString(lx, ly - 4, f"Cut x {piece.get('cutQty', 2)}")

    # Drawing elements
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(0.5)
    c.setDash()

    for el in elements:
        t = el.get("type", "")
        if t == "line":
            s, e = el["start"], el["end"]
            if el.get("isFold"):
                c.setDash(4, 3)
            sx, sy = pt(s["x"], s["y"])
            ex, ey = pt(e["x"], e["y"])
            c.line(sx, sy, ex, ey)
            c.setDash()

        elif t == "curve":
            s = el["start"]; cp1 = el["cp1"]; cp2 = el["cp2"]; e = el["end"]
            path = c.beginPath()
            path.moveTo(*pt(s["x"], s["y"]))
            path.curveTo(*pt(cp1["x"], cp1["y"]), *pt(cp2["x"], cp2["y"]), *pt(e["x"], e["y"]))
            c.drawPath(path, fill=0, stroke=1)

        elif t == "grain-line":
            s, e = el["start"], el["end"]
            dx, dy = e["x"] - s["x"], e["y"] - s["y"]
            length = math.hypot(dx, dy)
            if length < 0.01:
                continue
            nx, ny = dx / length, dy / length
            AW, AF = 0.4, 0.18
            c.setStrokeColorRGB(0.15, 0.39, 0.92)
            c.line(*pt(s["x"], s["y"]), *pt(e["x"], e["y"]))
            for px_cm, py_cm, dir_x, dir_y in [
                (e["x"], e["y"], -nx, -ny),
                (s["x"], s["y"], nx, ny),
            ]:
                ax1, ay1 = pt(px_cm + dir_x*AW + ny*AF, py_cm + dir_y*AW - nx*AF)
                ax2, ay2 = pt(px_cm + dir_x*AW - ny*AF, py_cm + dir_y*AW + nx*AF)
                px_p, py_p = pt(px_cm, py_cm)
                c.line(ax1, ay1, px_p, py_p)
                c.line(ax2, ay2, px_p, py_p)
            mid_x = (s["x"] + e["x"]) / 2
            mid_y = (s["y"] + e["y"]) / 2
            lx, ly = pt(mid_x, mid_y)
            c.setFont("Helvetica", 5)
            c.setFillColorRGB(0.15, 0.39, 0.92)
            c.drawCentredString(lx, ly + 5, "Grain")
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setStrokeColorRGB(0.1, 0.1, 0.1)

        elif t == "notch":
            pos = el["position"]
            angle_rad = el.get("angle", 0) * math.pi / 180
            half = 0.25
            x1c = pos["x"] - math.cos(angle_rad) * half
            y1c = pos["y"] - math.sin(angle_rad) * half
            x2c = pos["x"] + math.cos(angle_rad) * half
            y2c = pos["y"] + math.sin(angle_rad) * half
            c.setLineWidth(1.0)
            c.line(*pt(x1c, y1c), *pt(x2c, y2c))
            c.setLineWidth(0.5)


def _draw_crosshair(c, x_pts, y_pts, arm_pts):
    c.setStrokeColorRGB(0.5, 0.5, 0.5)
    c.setLineWidth(0.3)
    c.line(x_pts - arm_pts, y_pts, x_pts + arm_pts, y_pts)
    c.line(x_pts, y_pts - arm_pts, x_pts, y_pts + arm_pts)
    c.circle(x_pts, y_pts, arm_pts * 0.3, stroke=1, fill=0)
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)


def _draw_test_square(c, x_pts, y_pts):
    side = 5 * cm
    c.setStrokeColorRGB(0.5, 0.5, 0.5)
    c.setFillColorRGB(1, 1, 1)
    c.setDash(3, 2)
    c.setLineWidth(0.5)
    c.rect(x_pts, y_pts, side, side, stroke=1, fill=1)
    c.setDash()
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.setFont("Helvetica", 6)
    c.drawCentredString(x_pts + side/2, y_pts + side/2, "5 cm test square")
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)


# ── Public API ────────────────────────────────────────────────────────────────

def tile_pdf(svg_content: str = "", paper_size: str = "a4", single_page: bool = False,
             elements=None, pieces=None) -> bytes:
    """Return PDF bytes. elements/pieces are lists of dicts from the frontend."""
    if elements is None:
        elements = []
    if pieces is None:
        pieces = []

    page_size = PAPER_SIZES.get(paper_size.lower(), A4)
    page_w_pts, page_h_pts = page_size
    page_w_cm = page_w_pts / cm
    page_h_cm = page_h_pts / cm

    usable_w = page_w_cm - 2 * MARGIN_CM
    usable_h = page_h_cm - 2 * MARGIN_CM

    bbx0, bby0, bbx1, bby1 = _bounding_box(elements)
    pat_w = max(bbx1 - bbx0, 0.1)
    pat_h = max(bby1 - bby0, 0.1)

    if single_page:
        buf = io.BytesIO()
        pw = (pat_w + 4) * cm
        ph = (pat_h + 4) * cm
        c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
        page_h_local = pat_h + 4
        _draw_pattern(c, elements, pieces, bbx0 - 2, bby0 - 2, page_h_local, pw, ph)
        _draw_test_square(c, 0.5*cm, 0.5*cm)
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(0.5*cm, 0.5*cm - 10, "5 cm test square — print at 100%")
        c.save()
        return buf.getvalue()

    # Tiled
    net_w = usable_w - OVERLAP_CM
    net_h = usable_h - OVERLAP_CM
    cols = max(1, math.ceil(pat_w / net_w))
    rows = max(1, math.ceil(pat_h / net_h))

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=page_size)

    # ── Assembly diagram page ────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(page_w_pts/2, page_h_pts - 1.5*cm, "PatternSnap — Assembly Guide")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN_CM*cm, page_h_pts - 2.5*cm,
                 f"Paper: {paper_size.upper()}  |  Grid: {cols} cols x {rows} rows  |  Overlap: {OVERLAP_CM} cm")

    cell_w = min(3.5*cm, (page_w_pts - 2*MARGIN_CM*cm) / max(cols, 1))
    cell_h = min(2.5*cm, (page_h_pts - 6*cm) / max(rows, 1))
    grid_x0 = (page_w_pts - cols * cell_w) / 2
    grid_y0 = page_h_pts - 5.5*cm - rows * cell_h

    for row in range(rows):
        for col in range(cols):
            x = grid_x0 + col * cell_w
            y = grid_y0 + (rows - 1 - row) * cell_h
            label = f"{chr(65+row)}{col+1}"
            c.setStrokeColorRGB(0.5, 0.5, 0.5)
            c.setFillColorRGB(0.95, 0.97, 1.0)
            c.rect(x, y, cell_w, cell_h, stroke=1, fill=1)
            c.setFillColorRGB(0.2, 0.2, 0.2)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(x + cell_w/2, y + cell_h/2 - 4, label)

    _draw_test_square(c, MARGIN_CM*cm, MARGIN_CM*cm)
    c.setFont("Helvetica", 7)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawString(MARGIN_CM*cm, MARGIN_CM*cm - 10, "Print at 100% — measure to verify scale")
    c.showPage()

    # ── Pattern tiles ────────────────────────────────────────────────────────
    for row in range(rows):
        for col in range(cols):
            label = f"{chr(65+row)}{col+1}"
            tile_x0 = bbx0 + col * net_w - OVERLAP_CM / 2
            tile_y0 = bby0 + row * net_h - OVERLAP_CM / 2

            origin_x = tile_x0 - MARGIN_CM
            origin_y = tile_y0 - MARGIN_CM

            _draw_pattern(c, elements, pieces, origin_x, origin_y, page_h_cm,
                          page_w_pts, page_h_pts)

            # Page border
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.setLineWidth(0.3)
            c.rect(MARGIN_CM*cm, MARGIN_CM*cm, usable_w*cm, usable_h*cm, stroke=1, fill=0)

            # Crosshairs at overlap corners
            arm_pts = CROSSHAIR * cm
            for cx_pts, cy_pts in [
                (MARGIN_CM*cm + OVERLAP_CM/2*cm, MARGIN_CM*cm + OVERLAP_CM/2*cm),
                (MARGIN_CM*cm + usable_w*cm - OVERLAP_CM/2*cm, MARGIN_CM*cm + OVERLAP_CM/2*cm),
                (MARGIN_CM*cm + OVERLAP_CM/2*cm, MARGIN_CM*cm + usable_h*cm - OVERLAP_CM/2*cm),
                (MARGIN_CM*cm + usable_w*cm - OVERLAP_CM/2*cm, MARGIN_CM*cm + usable_h*cm - OVERLAP_CM/2*cm),
            ]:
                _draw_crosshair(c, cx_pts, cy_pts, arm_pts)

            # Page label
            c.setFillColorRGB(0.3, 0.3, 0.3)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(MARGIN_CM*cm + 4, page_h_pts - MARGIN_CM*cm - 12, label)
            c.setFont("Helvetica", 7)
            c.drawString(MARGIN_CM*cm + 4, page_h_pts - MARGIN_CM*cm - 22,
                         f"Overlap: {OVERLAP_CM} cm  |  PatternSnap")

            c.showPage()

    c.save()
    return buf.getvalue()
