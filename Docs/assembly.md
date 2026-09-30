# Assembly: seams and placed pieces

How the pieces of a pattern go together. The same data drives the flat
**Assembly** view and the 3D drape (see [3d-body.md](3d-body.md)).

## Views

The header tabs **Pattern | Assembly | 3D Body** (`App.tsx` `ViewTabs`) pick the
main view. Assembly is disabled while the canvas has no pattern pieces.

## Data model (`frontend/src/types/index.ts`)

```ts
interface SeamEnd {
  pieceId: string; edgeId: string
  range?: [number, number]   // part of the edge sewn, as fractions of its length (default whole edge)
  side?: 'left' | 'right'    // one copy of a cut-2 / on-fold piece (default: both, each on its own side)
  half?: 'front' | 'back'    // one half of an on-fold sleeve (a cuff wraps both)
}
interface SeamConnection {
  label: string; from: SeamEnd; to: SeamEnd
  reversed?: boolean         // user override of the sewing direction (default: taken from the 3D geometry)
  source?: 'inferred' | 'user'
}
interface Placement {        // a piece applied onto another: patch pocket, flap, appliqué
  id: string; pieceId: string; hostId: string
  transform: { dx; dy; rotation; flip? } // piece canvas coords -> host canvas coords
  side?: 'left' | 'right'    // default: both copies of the host
  stitched: string[]         // edge ids sewn down; the others stay open (pocket mouth)
  source?: 'inferred' | 'user'
}
PatternPiece.layer?: 'outer' | 'inside' // facings, fly facings, pocket bags sit inside
```

All the new fields are optional, so older `.psnap` files load unchanged.

- **Ranges** are fractions of the element's arc length measured in the element's
  own start→end direction (the direction it was drawn), whichever way the
  outline runs.
- **Sides** are the wearer's: `left` is +x on the 3D body (the body faces +z).
- **`reversed`**: `undefined` = pair the two edges the way the 3D wrap puts them
  (default, right for engine patterns); `false` = element start to start;
  `true` = start to end.

## Garment view (`components/assembly/garmentLayout.ts`)

The default Assembly view shows the whole garment the way it is worn: every
cut copy of every piece (a left and a right front leg, a left and a right back
leg…), unrolled around the body as if cut down the centre back:

```
 CB        side       CF        side        CB
 | R back ||  R front || L front ||  L back |     (Back centred: the backs in the middle)
```

- **Copies**: a piece cut 2 or on the fold has an L and an R copy (on the fold:
  its two mirrored halves); a sleeve on the fold also has front / back halves.
  Keys `pieceId#side[-half]`, sides the wearer's (in 3D, the un-mirrored copy
  is on +x = the wearer's left).
- **Rows**: upper torso (bodice) above lower torso / legs (skirt, trousers).
- **Ring**: from the centre piece (CF, or CB when back-centred) outward, each
  piece aligned to the previous along the seam between them — the side seam,
  never the inseam — by `alignToNeighbour` (whole seam, mirror-aware), pushed
  `LAYOUT_GAP` (1.2 cm) away, then eased further until the two outlines don't
  cross (front and back hip curves both bulge outward, so they touch near the
  hip and part toward waist and hem). The other side is the mirror image; a
  piece reaching past the centre line (a trouser front's crotch extension)
  moves that side out just clear, so the legs' inseams meet in the middle.
- **Sleeves** (both halves, cap down) above their side; **trims** and
  unattached pieces in a tray row underneath.
- `copyAt(point)` finds the copy under a layout point (or the nearest within
  the gap). The layout is pure geometry, shared with the 3D side.
- Seam arcs join the copies each connection applies to (paired by side; a
  sleeve half by the other piece's front/back), and are omitted between
  neighbours that visibly touch. Clicking edges on two copies of the same side
  makes a symmetric seam; across sides (L ↔ R) it sets `side` on both ends.
- **Symmetric and one-sided placements.** A placement with no `side` is a
  mirrored pair (🔗, e.g. inferred back pockets): drawn on both copies; moving
  either moves both. **Unlink sides** (`UNLINK_PLACEMENT`) splits it into an R
  and an L placement that move independently — asymmetric designs; **Mirror to
  other side** (`MIRROR_PLACEMENT`) turns a one-sided placement back into a
  pair, replacing its twin. A piece may therefore have several placements; in
  3D they become one placed piece with a copy each (`trimPlacement.mergePlaced`).
- **Placing precisely** (`components/assembly/placementAids.ts`, host pattern
  coordinates, so it is the same on every copy): while a placed piece is
  dragged, a readout gives its centre's distance from the centre line, its top
  below the waist (measured above the pocket — the waist may slope) and its
  nearest edge to the side seam ("across the side seam" when it straddles it);
  it snaps (within 0.8 cm; Alt = free) its centre onto the side seam, midway
  between centre line and side seam, or level with its twin on the other side,
  with dashed guides. The placement editor has exact **Centre from centre
  line** / **Top below the waist** fields (changing one keeps the other) and
  **Align with other side** for an unlinked twin.
- **Buttons per side** (`components/assembly/closures.ts`): markings may carry
  a `side`, so they sit on one copy of a cut-2 piece. **Buttons…** (Placed
  pieces header) adds a row: N buttons evenly down a front's front edge (in
  from it by an inset, from a gap below the top to a gap above the bottom), on
  the wearer's right (menswear) or left, with vertical / horizontal / no
  buttonholes on the other front — one undo step. Assembly and the 3D body draw
  each marking only on its side. (The fronts are joined at their extension
  edges in 3D, so buttons and holes sit either side of the centre line rather
  than over each other — the button-front overlap limit in 3d-body.md.)
- **Across a seam.** A placement may hang over the edge of its host onto the
  neighbouring panel (a cargo pocket on the side seam): it is anchored to the
  host under its centre, and in 3D the part past a sewn edge continues onto the
  panel sewn there (see 3d-body.md, "Across seams").
- Placements are drawn on every host copy they apply to — both sides for a
  pair (🔗), one side when `side` is set; a piece dropped on a copy of a cut-2 /
  on-fold host is placed on that side only.

**3D beside** (Assembly toolbar) splits the view: Assembly on the left, the
live 3D body on the right (`App.tsx`), with the body panel in the sidebar. The
3D view follows the editor state, so moving a pocket or editing a seam
re-drapes beside it.

## Editing seams (`components/AssemblyView.tsx`, `components/assembly/`)

- **Add**: click an edge, then the edge on another piece it is sewn to. The new
  seam takes the first edge's seam label and is marked `source: 'user'`.
  Clicking a second edge on the same piece switches the first pick; Esc cancels.
- **Select** a seam by its arc or its row in the **Seams** panel. Both sewn
  stretches are highlighted, with round handles at their ends: drag a handle
  to sew only part of an edge (one undo step per drag).
- The seam editor sets the label, the sewn range of each end (as %), the side
  (only for cut-2 / on-fold pieces), the direction, or deletes the seam
  (also Delete/Backspace). Ctrl+Z / Ctrl+Y undo and redo in this view too.
- Each seam shows whether its two sewn lengths **match** (≤ 0.3 cm), are
  **eased** (up to max(1 cm, 5 %) of fullness worked in) or **mismatch**.
- Layout (`assembly/geometry.ts`): **Pieces** (default) shelf-packs the pieces
  at one common scale, so they stay put while you edit; **Laid flat** lays
  them edge to edge along their seams (breadth first). A piece is aligned along
  the whole seam to its neighbour — the two farthest-apart endpoints of all the
  edges sewn between them — and may be mirrored (sewn pieces lie right sides
  together); of the four rotate/mirror options the one that puts every seam
  element next to its partner without overlap wins.
- Reducer actions: `ADD_CONNECTION` (ignores an existing pair either way round),
  `UPDATE_CONNECTION` (optional `tag` coalesces a gesture into one undo step),
  `DELETE_CONNECTION`, `SET_CONNECTIONS`.

## Placing pieces (pockets, flaps, appliqués)

- **Drag** any piece (by its body) onto another piece to place it there; the
  drop point is where its centre goes. A piece is placed on one host at a time
  (`ADD_PLACEMENT` replaces an earlier placement of the same piece).
- Placed pieces leave the layout and are drawn on their host (amber = outside,
  grey = inside): stitched edges dashed brown, open edges dotted grey.
- Select a placed piece (click it, or its row under **Placed pieces**): drag it
  to move, drag the round handle above it to turn it (5° steps). The placement
  editor sets the rotation, the side of the body (hosts cut 2 / on the fold;
  default both), whether it sits outside or inside (`PatternPiece.layer`), and
  which edges are stitched — also by clicking the piece's edges. **Remove**
  (or Delete) puts it back in the layout. Every edit marks it `source: 'user'`.
- A new placement stitches every edge but the top-most one (the mouth).
- `utils/placement.ts` (`placementMatrix`) is the one transform both the
  Assembly view and the 3D drape use: mirror in x (optional), rotate about the
  piece's bbox centre (canvas axes, y down), translate.
- Unlabelled edges are named by where they lie ("top edge", "left edge").
- Reducer actions: `ADD_PLACEMENT`, `UPDATE_PLACEMENT` (optional `tag`: one undo
  step per drag / rotate), `DELETE_PLACEMENT`.

## Bands across several pieces (`components/assembly/bands.ts`)

A waistband, collar, neck or hem band is ONE edge sewn to several edges in
turn (front waist, back waist, on both sides). Sewing its whole edge to each
of them — what clicking edge to edge produces — sews every host edge to the
same stretch of band, and in 3D welds the front and back waists together.
So a band's seams are consecutive stretches of its edge, in order round the body:

- one piece going all the way round (cut once, longer than 1.5 × the half
  opening): R front (CF → side) → R back (side → CB) → L back → L front, each
  end with its `side`; a half (on the fold / cut 2): CF → side → CB (a collar
  cut on the CB fold starts at the fold); a cuff round an on-fold sleeve: its
  front half, then its back half;
- each stretch as long as the edge it meets (`reversed` set from which way
  each edge runs round the body); a longer band keeps the rest as the overlap
  at its end (a collar: its seam allowances, half at each end); a shorter one
  is eased along the opening.

**Automatically:** when a band (a trim) edge is sewn whole to two or more
garment edges — by clicking in Assembly, or in an older file on opening —
`normalizeBands` (in `ADD_CONNECTION` and `LOAD_STATE`) re-makes those seams
as a band, whatever the click order. **Band…** (Seams panel) sews a chosen
band's longest edge round the waist / neckline / hem / wrist in one step,
showing first how its length compares with the opening (e.g. "14.7 cm left
over, as the overlap at its end — a waistband overlap is usually 3–4 cm").
The backend's `_around_rule` follows the same length rules (`_true_span`).

## Auto-placing a fly (`components/assembly/autoFly.ts`)

A fly is sewn, not placed: dragging a fly facing onto the front leg makes a
pocket-style placement, and a hand-drawn seam doesn't know the side, the start
at the waist or the direction. **Fly…** (Seams panel header, shown when a piece
has a centre front and a waist) opens a form prefilled from piece names — front
piece, fly facing, fly shield, and the facing side (wearer's left for
menswear, right for womenswear). **Attach fly** sews the facing's straight edge
closest in length to the CF along the CF from the waist down (split across CF
elements, ranges and `reversed` set exactly), the shield the same on the other
side, marks both inside, and replaces any seams or placements they had
(`REPLACE_ATTACHMENTS`, one undo step). A placed piece named fly/shield shows a
button to do this instead. The result equals the generator's
(`attachments.py _fly_rule`; tested). The seams are `source: 'user'`, and
Re-infer never adds an inferred seam on an edge the user has sewn, nor places a
piece the user has sewn on.

## How seams reach the 3D drape

- `pieceGeometry.ts` outline edges carry `base` (the element id), `span` (the
  stretch of the element they cover) and `flipped` (the loop runs the element
  end→start).
- `splitAtRanges` cuts elements where any seam's range ends (ids
  `<id>#range-k`), before darts are cut, so every seam end is a run of whole
  edges; `seamParts(edges, end)` finds them (and the `#after-dart-` parts).
- `garmentWrap.conformSeamCounts` gives both ends of each seam one vertex count,
  and `clothSim` welds them vertex to vertex, as for whole-edge seams.
- `side` restricts a seam to the copies on that side of the body
  (`clothSim` checks where each copy was placed); `reversed` overrides the
  geometric pairing direction.

## State and persistence

- `EditorState.connections` / `placements` are versioned together with elements
  and pieces in every undo entry (`EditorSnapshot`).
- Deleting a piece removes the seams and placements that involve it; deleting an
  edge removes its seams and un-stitches it from any placement.
- `.psnap` read/write lives in one module, `utils/psnap.ts` (`toPsnap`,
  `loadPsnapAction`), used by the header Save/Open, Ctrl+S and drag-and-drop.
  (Before this, Save silently dropped `connections`.)

## Inference

Generated patterns arrive with seams from the backend's `_compute_connections`
(`backend/app/patterns/engine.py`), keyed on edge `seamLabel`s and the kind of
seam (construction / join / opening — see the README file-format section).

Trims are then handled by `backend/app/patterns/attachments.py`
(`apply_attachments`, the last step of `generate_pattern`). Trims are mostly
plain rectangles with unlabelled edges, and one trim edge often runs along
several host edges, so the rules work from piece **names and geometry**:

| Trim (name) | Sewn to | Notes |
|---|---|---|
| Collar, hood, neck band / binding / facing | neckline | half trim (cut on the CB fold, or shorter than 1.5× the half neckline): CB → shoulder → CF, copies pair by side; full trim: CF(right) → CB → CF(left) with host `side`s |
| Waistband | waist | same scheme, starting at CF |
| Cuff, wrist / sleeve band | wrist | all round an on-fold sleeve: its front `half`, then its back `half` |
| Armhole facing / binding | armhole | front then back |
| Hem facing, ruffle, frill, flounce | hem | from CF |
| Fly facing / fly shield | front CF from the waist | `side` left / right (wearer's); inside |
| Placket | front CF from the neckline | |
| Front facing | front CF from the neckline | inside |
| Pocket bag (in-seam) | front side seam just below the waist (the skirt / leg, not a bodice) | inside |
| Patch pocket, welt | **placement** on a host | chest/breast → left front at bust line; back → back leg / skirt below the waist; cargo → front leg outer thigh; otherwise front skirt / leg below the waist, or a jacket/shirt front above the hem |
| Welt pocket bag | **placement** under its welt | inside, stitched along its mouth only |

- The core helper `_sew` walks a *path* of host edges (each step one element,
  walked forwards or backwards, optionally with a side / half); where the path
  crosses to the next element the trim's range is split. So every connection
  pairs a stretch of one trim element with a stretch of one host element, and a
  trim edge's stretches tile it without overlapping. `reversed` is set exactly
  (element starts meet unless one of them is walked backwards).
- Placements stitch every edge except the mouth (the top-most edge); bags only
  the mouth. `transform` is a translation (rotation 0).
- Each trim gets a `layer`: inside for facings, bags, lining, fly pieces.
- Belt loops, ties and straps are not attached yet.
- Everything is `source: "inferred"`.

**Re-infer** (Seams panel) sends the current elements and pieces to
`POST /api/infer-attachments` (`backend/app/api/attachments.py`: shell seams +
the rules above; malformed pieces → 422). `APPLY_INFERRED` keeps the user's
seams and placements (`source: 'user'`), replaces the rest, skips inferred
seams that duplicate a user seam, and sets layers only where the user has not.

## In 3D

Trims attached by a seam and pieces placed on a host are shown on the body and
draped with it — see [3d-body.md](3d-body.md#trims-and-placed-pieces-trimplacementts).
