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
