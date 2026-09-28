# 3D Body & Garment Fit

The 3D view shows a measurement-driven body (a mannequin) that the user can resize and reshape. It is the base for putting the drafted pattern on that body. The work ships in three phases, each its own entry in `harness/FEATURES.json`:

| Phase | Feature id | Status |
|-------|-----------|--------|
| 1. Parametric body avatar + customization UI | `body-avatar-3d` | Done (procedural body; realism upgrade in progress, see below) |
| 2. Static fit preview: pattern pieces wrapped onto the body using `SeamConnection` topology | `garment-3d-fit-preview` | Planned |
| 3. Physics drape: position-based dynamics cloth, seams as stitching constraints, body collision | `garment-3d-drape-simulation` | Planned |

Everything runs in the browser, and no backend endpoint is involved.

> **Realism.** The current body is generated procedurally from measured cross-sections. It is accurate to the tape, but it still reads as a stylized dress form. Real anatomy (collarbones, deltoids, knees, how breasts sit on the ribcage) needs a sculpted base mesh. The chosen next step is a base body modelled in **Fusion 360**, deformed at runtime to the user's measurements; see *Next: sculpted base mesh* below. The measurement, tape-fitting, worker and rendering code here carries over unchanged.

---

## Libraries

| Package | License | Why |
|---------|---------|-----|
| `three` | MIT | WebGL scene graph, plus `OrbitControls` and `RoomEnvironment` from its examples |
| `@react-three/fiber` **v8** | MIT | Lets the scene be written as React components. v9 needs React 19; the app is on React 18. |
| `earcut` (phase 3) | ISC | Triangulates concave pattern pieces |

`@react-three/drei` is deliberately not used, because of its large dependency tree. `BodyModelView` is loaded with `React.lazy()`, so three.js sits in its own chunk (about 230 KB gzipped) and is fetched only when the view is first opened. Meshing runs in a separate Web Worker chunk (about 13 KB).

---

## Files

```
frontend/src/three/
  types.ts            BodyProfile, ResolvedBody, LoftRing (profiled cross-section), Lobe, MeshData
  bodyRegions.ts      Body fields + defaults, profile resolution, shape presets, landmark sections for
                      torso / legs / arms, arm A-pose frame, head + foot ellipsoids
  rings.ts            Section outline R(θ), tape length (convex hull), monotone-cubic interpolation
  bodySdf.ts          Signed distance field: swept section tubes + ellipsoids joined by smooth minimum
  surfaceNets.ts      Narrow-band surface-nets mesher with a Newton projection onto the surface
  avatarBuilder.ts    buildAvatar(body, cell) → mesh + landmarks
  avatarWorker.ts     Web Worker entry: builds the mesh off the UI thread
  useAvatarMesh.ts    Scheduler: coarse preview while dragging, then full resolution; one job in flight
  avatarBuilder.test.ts
frontend/src/components/
  BodyModelView.tsx           Lazy 3D view: studio lighting, soft shadow, orbit camera, on-demand frames
  BodyCustomizationPanel.tsx  Body sliders + shape preset + reset (right sidebar, 3D view only)
```

---

## Body profile & measurement resolution

`EditorState.bodyProfile = { overrides, shape }` stores **only the values the user has set** on the Body panel. Each field resolves as:

```
override  ??  state.measurements[measurementKey]  ??  default     → clamped to [min, max]
```

Only true body measurements are mapped from the Measurements panel: `bust`, `waist`, `hip`, `waistToHip`, `inseam`, `shoulder`. `sleeveLength` is not treated as arm length. The panel tags each field `custom` (an override) or `measured` (from the Measurements panel). **Reset to measurements** clears the overrides and keeps the shape preset.

The profile belongs to the user, not the pattern:
- `LOAD_STATE` (open a `.psnap`, AI generate, refine) keeps it.
- It is not part of undo/redo.
- It is not saved in `.psnap` yet.

The 16 fields and their ranges are listed in `BODY_FIELDS` in `bodyRegions.ts`. Defaults describe a 168 cm body with bust 92, underbust 76, waist 74 and hip 98. Underbust is clamped to be no larger than bust.

---

## How the procedural body is built

### Cross-sections
Each landmark is a **profiled section**, not an ellipse. Its outline in the section plane (u = lateral, w = front) is:

```
R(θ) = superellipse(half-width a, front depth b, back depth `back`, exponent n)  +  Σ lobes
```

- **Superellipse:** `n` is above 2 on the torso, which gives the flatter, boxier sections of a real torso. The separate front and back depths make the sections asymmetric front to back.
- **Lobes:** rounded domes `amp·(1 − k²)^1.5` placed at fixed angles: breasts, shoulder blades, belly and buttocks on the torso; quadriceps and calf on the legs. The mirrored pairs keep the body symmetric.
- **Sizing:** a section is scaled so its **tape length**, the perimeter of its convex hull (what a tape measure reads, since it bridges hollows), equals the measurement.
- **Bust:** the chest wall is sized from the underbust (× 1.06). The breast projection is then solved by bisection so the tape over the apexes equals the bust measurement. The bust–underbust difference therefore becomes the cup.
- **Breast profile:** extra upper- and lower-bust sections give the breast its side-on shape.
- **Posture:** section centre z offsets give the spine its S-curve (upper back, chest forward, lumbar hollow, seat back). Shape presets (hourglass, rectangle, pear, apple) change the waist and hip depths, the belly and buttock projection, and the posture offsets.

### Levels
Levels are fractions of height, from adult proportions. Two are measured instead: the crotch sits at the **inseam**, and the hip at waist − **waist-to-hip**. The neck section continues up inside the head.
- **Legs** start at hip level, with the outer thigh just inside the hip line.
- **Arms** hang in an A-pose. The angle opens just enough (up to 55°) to keep a 3.5 cm gap from every torso section from the bust down.

### Interpolation
Between landmarks, every scalar (size, depths, exponent, centre, each lobe amplitude) follows its own **monotone cubic** (Fritsch–Carlson) over distance along the body. As a result, sections never bulge past their landmarks and never fold.

### Surface
The body is the zero set of a **signed distance field**:
- **Tubes:** the torso, each leg and each arm is a tube swept through densely sampled sections, with each section's outline tabulated at 128 angles.
- **Ellipsoids:** the head is a cranium plus a jaw; each foot is an ellipsoid, cut flat at the floor.
- **Blending:** parts are joined with a polynomial smooth minimum, with blend radii head 2.5, legs 4, feet 3 and arms 2.5 cm. This is what makes shoulders flow into arms and hips into legs. The arm blend radius is smaller than the arm clearance, so no measured section is fattened.
- **Symmetric order:** the smooth minimum isn't associative, so each left/right pair is blended together first.

### Mesh
The mesh is built with **surface nets**:
- It samples only a narrow band: 4³ blocks are probed at their centre and skipped when far from the surface.
- The x grid is symmetric about the centre line.
- Each vertex gets one Newton step onto the exact surface.
- The fine mesh (0.8 cm cells, about 37k vertices) takes about 1 s, so it runs in a **Web Worker**. While a slider is being dragged, a 2 cm preview is shown; the fine mesh follows once the body stops changing. Only one build is ever in flight.

---

## Rendering

The view uses a matte white material (`MeshStandardMaterial`, roughness 0.58). Lighting:
- soft reflections from three's procedural `RoomEnvironment`, via PMREM;
- a key light casting a soft (PCF) shadow onto an invisible shadow-only floor;
- a fill light and a rim light;
- a radial-gradient backdrop behind a transparent canvas.

Frames render on demand, when the camera moves or the mesh changes. React context doesn't cross into the r3f `<Canvas>` in fiber v8, so the body is resolved outside it and the geometry is passed in as props.

---

## Tests

`src/three/avatarBuilder.test.ts`:
- **Sizing:** the ellipse inverse; profile resolution; each measured section tapes to its measurement within 0.5%.
- **Shape:** the bust–underbust difference becomes breast projection, with a cleavage set back from the apexes; shape presets change the silhouette but not the measurements; changing the bust doesn't change the waist.
- **Robustness:** sections are strictly ordered at every slider extreme; smoothing never folds or overshoots; the arms clear the torso for extreme bodies.
- **Final surface:** tape measurements taken on the **final blended surface** match bust, waist and hip within 2%; the mesh has no holes and faces outward; it is mirror-symmetric, stands on the floor, and reaches its height; the neck and crotch are continuous; the build time is logged.

`src/context/EditorContext.test.ts` covers the profile actions, keeping the profile through `LOAD_STATE`, and the profile staying out of undo history.

---

## Next: sculpted base mesh (Fusion 360)

A body modelled in Fusion 360 is exported as a mesh (OBJ, FBX or STL, converted to `.glb`) and loaded in place of the procedural surface. Fusion gives a single fixed body. To fit it to the user's measurements, the mesh will be **deformed at runtime rather than morphed**:
1. **Segment** the vertices into torso, arms and legs.
2. **Measure** the mesh with the same tape code (convex hull of horizontal slices) at each landmark level.
3. **Scale** each vertex radially about its section centre. The scale factor is interpolated between landmark levels so each slice's tape matches the target. Height scales the levels.

This keeps the sculpted anatomy and makes the tape accurate. Shape presets become section-shape targets rather than generated lobes.
