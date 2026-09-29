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
