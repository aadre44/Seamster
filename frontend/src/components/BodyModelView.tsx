import { useEffect, useMemo, useState } from 'react'
import { Canvas as ThreeCanvas, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { useEditor } from '../context/EditorContext'
import { resolveBody } from '../three/bodyRegions'
import { useAvatarMesh } from '../three/useAvatarMesh'
import { useGarmentPlacement } from '../three/useGarmentPlacement'
import { EASE_SNUG, EASE_TIGHT } from '../three/garmentWrap'
import type { GarmentState } from '../three/useGarmentPlacement'

// three's own OrbitControls; the canvas renders on demand, so every camera
// change requests a frame.
function Controls({ targetY }: { targetY: number }) {
  const { camera, gl, invalidate } = useThree()
  const controls = useMemo(() => new OrbitControls(camera, gl.domElement), [camera, gl])
  useEffect(() => {
    controls.minDistance = 40
    controls.maxDistance = 900
    const onChange = () => invalidate()
    controls.addEventListener('change', onChange)
    return () => {
      controls.removeEventListener('change', onChange)
      controls.dispose()
    }
  }, [controls, invalidate])
  useEffect(() => {
    controls.target.set(0, targetY, 0)
    controls.update()
  }, [controls, targetY])
  return null
}

// Soft studio reflections from three's procedural room environment.
function StudioEnvironment() {
  const { gl, scene, invalidate } = useThree()
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl)
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
    scene.environment = env
    invalidate()
    return () => {
      scene.environment = null
      env.dispose()
      pmrem.dispose()
    }
  }, [gl, scene, invalidate])
  return null
}

function KeyLight({ height }: { height: number }) {
  const light = useMemo(() => {
    const l = new THREE.DirectionalLight('#ffffff', 1.6)
    l.position.set(90, 280, 170)
    l.castShadow = true
    l.shadow.mapSize.set(2048, 2048)
    l.shadow.radius = 6
    l.shadow.bias = -0.0004
    l.shadow.normalBias = 0.6
    const cam = l.shadow.camera
    cam.left = -110
    cam.right = 110
    cam.top = 110
    cam.bottom = -110
    cam.near = 50
    cam.far = 700
    return l
  }, [])
  useEffect(() => {
    light.target.position.set(0, height * 0.45, 0)
    light.target.updateMatrixWorld()
  }, [light, height])
  useEffect(() => () => light.dispose(), [light])
  return (
    <>
      <primitive object={light} />
      <primitive object={light.target} />
    </>
  )
}

// One fabric colour for the whole garment, like real cloth; optional distinct
// colours per piece for inspecting how the pattern is assembled.
const FABRIC = '#7f9cc9'
// The wrong side of the garment: facings, fly, pocket bags.
const INSIDE = '#5b739b'
const PIECE_COLORS = ['#7c9cc9', '#c98f7c', '#86b59a', '#b59ac9', '#c9b87c', '#7cb8c9', '#c97ca4', '#9aa0b5']
const SNUG = new THREE.Color('#f5a524')
const TIGHT = new THREE.Color('#e5484d')
// Stitch lines sit this far (cm) off the fabric so they are not hidden by it.
const SEAM_LIFT = 0.12

function GarmentMeshes({ result, fitMap, colorByPiece, xray }: { result: GarmentState; fitMap: boolean; colorByPiece: boolean; xray: boolean }) {
  const { invalidate } = useThree()
  // Geometry is rebuilt only when the placement (topology) or colouring
  // changes; drape frames just move the vertices.
  const meshes = useMemo(() => result.pieces.flatMap((piece, i) => {
    const base = new THREE.Color(colorByPiece ? PIECE_COLORS[i % PIECE_COLORS.length] : piece.layer === 'inside' ? INSIDE : FABRIC)
    return piece.copies.map((copy, ci) => {
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(copy.positions), 3))
      g.setIndex(new THREE.BufferAttribute(copy.indices, 1))
      g.computeVertexNormals()
      const colors = new Float32Array(copy.ease.length * 3)
      copy.ease.forEach((e, v) => {
        const c = !fitMap || e >= EASE_SNUG ? base : e >= EASE_TIGHT ? SNUG : TIGHT
        colors.set([c.r, c.g, c.b], v * 3)
      })
      g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      // Seam stitch lines: consecutive vertex pairs along each sewn edge.
      const pairs: number[] = []
      for (const edge of piece.seams) for (let k = 0; k < edge.length - 1; k++) pairs.push(edge[k], edge[k + 1])
      const seam = new THREE.BufferGeometry()
      seam.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pairs.length * 3), 3))
      return { key: `${piece.id}:${ci}`, piece: i, copy: ci, inside: piece.layer === 'inside', geometry: g, seam, pairs }
    })
  }), [result.placementId, fitMap, colorByPiece])
  useEffect(() => () => meshes.forEach(m => { m.geometry.dispose(); m.seam.dispose() }), [meshes])

  useEffect(() => {
    for (const m of meshes) {
      const src = result.pieces[m.piece]?.copies[m.copy]?.positions
      const attr = m.geometry.getAttribute('position') as THREE.BufferAttribute
      if (!src || src.length !== attr.array.length) continue
      ;(attr.array as Float32Array).set(src)
      attr.needsUpdate = true
      m.geometry.computeVertexNormals()
      const normals = m.geometry.getAttribute('normal').array as Float32Array
      const line = m.seam.getAttribute('position') as THREE.BufferAttribute
      const out = line.array as Float32Array
      m.pairs.forEach((v, k) => {
        for (let d = 0; d < 3; d++) out[k * 3 + d] = src[v * 3 + d] + normals[v * 3 + d] * SEAM_LIFT
      })
      line.needsUpdate = true
      m.seam.computeBoundingSphere()
    }
    invalidate()
  }, [result, meshes, invalidate])

  const seamMaterial = useMemo(() => new THREE.LineBasicMaterial({ color: '#2f3e5c', transparent: true, opacity: 0.55 }), [])
  useEffect(() => () => seamMaterial.dispose(), [seamMaterial])

  const material = useMemo(
    () => new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.85, metalness: 0, side: THREE.DoubleSide, envMapIntensity: 0.4,
      polygonOffset: true, polygonOffsetFactor: -1,
    }),
    [],
  )
  useEffect(() => () => material.dispose(), [material])
  // X-ray: the outer fabric turns see-through so the inside pieces show.
  const glass = useMemo(
    () => new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: 0.85, metalness: 0, side: THREE.DoubleSide, envMapIntensity: 0.4,
      transparent: true, opacity: 0.28, depthWrite: false,
    }),
    [],
  )
  useEffect(() => () => glass.dispose(), [glass])
  useEffect(() => { invalidate() }, [xray, invalidate])

  return (
    <>
      {meshes.map(m => (
        <group key={m.key}>
          <mesh geometry={m.geometry} material={xray && !m.inside ? glass : material} castShadow={!xray || m.inside} receiveShadow
            renderOrder={xray && !m.inside ? 1 : 0} />
          {m.pairs.length > 0 && <lineSegments geometry={m.seam} material={seamMaterial} />}
        </group>
      ))}
    </>
  )
}

export default function BodyModelView() {
  const { state } = useEditor()
  const body = useMemo(
    () => resolveBody(state.bodyProfile, state.measurements),
    [state.bodyProfile, state.measurements],
  )
  const mesh = useAvatarMesh(body)
  const hasPattern = state.pieces.length > 0
  const [showGarment, setShowGarment] = useState(true)
  const [fitMap, setFitMap] = useState(true)
  const [drape, setDrape] = useState(true)
  const [colorByPiece, setColorByPiece] = useState(false)
  const [xray, setXray] = useState(false)
  const garment = useGarmentPlacement(body, state.pieces, state.elements, state.connections, state.placements, hasPattern && showGarment, drape)
  const hasInside = !!garment.result?.pieces.some(p => p.layer === 'inside')
  const placed = garment.result

  const geometry = useMemo(() => {
    if (!mesh) return null
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(mesh.positions, 3))
    g.setIndex(new THREE.BufferAttribute(mesh.indices, 1))
    g.computeVertexNormals()
    return g
  }, [mesh])
  useEffect(() => () => geometry?.dispose(), [geometry])

  const material = useMemo(
    () => new THREE.MeshStandardMaterial({ color: '#f3f3f1', roughness: 0.58, metalness: 0, envMapIntensity: 0.55 }),
    [],
  )
  useEffect(() => () => material.dispose(), [material])

  // Camera is placed once from the initial height; later height changes only
  // re-aim the orbit target so the user's view isn't yanked around.
  const [initialCamera] = useState<[number, number, number]>(
    () => [body.height * 0.3, body.height * 0.58, body.height * 1.95],
  )

  return (
    <div
      className="flex-1 relative overflow-hidden"
      style={{ background: 'radial-gradient(ellipse at 50% 38%, #ffffff 0%, #eef0f3 45%, #d9dde3 100%)' }}
    >
      <ThreeCanvas
        frameloop="demand"
        shadows="soft"
        gl={{ alpha: true, antialias: true }}
        camera={{ position: initialCamera, fov: 32, near: 1, far: 5000 }}
      >
        <StudioEnvironment />
        <hemisphereLight args={['#ffffff', '#c9ced6', 0.55]} />
        <KeyLight height={body.height} />
        <directionalLight position={[-160, 140, 120]} intensity={0.45} />
        <directionalLight position={[0, 180, -220]} intensity={0.5} />
        {geometry && (
          <mesh geometry={geometry} material={material} castShadow receiveShadow />
        )}
        {placed && showGarment && <GarmentMeshes result={placed} fitMap={fitMap} colorByPiece={colorByPiece} xray={xray} />}
        <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[800, 800]} />
          <shadowMaterial transparent opacity={0.16} />
        </mesh>
        <Controls targetY={body.height * 0.52} />
      </ThreeCanvas>
      {!mesh && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400 pointer-events-none">
          Building body…
        </div>
      )}
      <div className="absolute top-2 left-3 text-[10px] text-gray-500 pointer-events-none select-none">
        Drag to rotate · scroll to zoom · right-drag to pan
      </div>
      {hasPattern && (
        <div className="absolute top-2 right-3 w-52 rounded-lg bg-white/85 backdrop-blur border border-gray-200 shadow-sm p-2.5 text-[11px] text-gray-700 space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={showGarment} onChange={e => setShowGarment(e.target.checked)} />
            <span className="font-medium">Show garment</span>
            {garment.busy && <span className="ml-auto w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />}
          </label>
          {showGarment && (
            <>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={drape} onChange={e => setDrape(e.target.checked)} />
                <span>Drape with gravity</span>
                {placed?.draping && <span className="ml-auto text-[10px] text-gray-400">settling…</span>}
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={colorByPiece} onChange={e => setColorByPiece(e.target.checked)} />
                <span>Color by piece</span>
              </label>
              {hasInside && (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={xray} onChange={e => setXray(e.target.checked)} />
                  <span>X-ray (see inside pieces)</span>
                </label>
              )}
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={fitMap} onChange={e => setFitMap(e.target.checked)} />
                <span>Fit map</span>
              </label>
              {fitMap && (
                <div className="space-y-0.5 pl-5 text-[10px] text-gray-500">
                  <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: '#e5484d' }} /> Tight: fabric smaller than body</div>
                  <div className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: '#f5a524' }} /> Snug: no ease</div>
                </div>
              )}
              {placed?.error && <p className="text-red-600">Could not place the pattern: {placed.error}</p>}
              {placed && placed.skipped.length > 0 && (
                <p className="text-[10px] text-gray-500">
                  Not shown in 3D: {placed.skipped.map(s => s.name).join(', ')}
                </p>
              )}
              <p className="text-[10px] text-gray-400">{drape ? 'Draped: seams sewn, gravity and body collision.' : 'Static preview: wrapped onto the body, not draped.'}</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
