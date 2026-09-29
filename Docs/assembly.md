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
Trim attachments and pocket placements are inferred next (planned).
