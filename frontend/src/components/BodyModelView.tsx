import { useEffect, useMemo, useState } from 'react'
import { Canvas as ThreeCanvas, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { useEditor } from '../context/EditorContext'
import { resolveBody } from '../three/bodyRegions'
import { buildAvatar } from '../three/avatarBuilder'
import type { MeshData } from '../three/types'

function toGeometry(part: MeshData): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(part.positions, 3))
  g.setIndex(new THREE.BufferAttribute(part.indices, 1))
  g.computeVertexNormals()
  return g
}

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

export default function BodyModelView() {
  const { state } = useEditor()
  const body = useMemo(
    () => resolveBody(state.bodyProfile, state.measurements),
    [state.bodyProfile, state.measurements],
  )
  const geometries = useMemo(() => buildAvatar(body).parts.map(toGeometry), [body])
  useEffect(() => () => geometries.forEach(g => g.dispose()), [geometries])

  const material = useMemo(
    () => new THREE.MeshStandardMaterial({ color: '#d9c2ad', roughness: 0.75, metalness: 0 }),
    [],
  )
  useEffect(() => () => material.dispose(), [material])

  // Camera is placed once from the initial height; later height changes only
  // re-aim the orbit target so the user's view isn't yanked around.
  const [initialCamera] = useState<[number, number, number]>(
    () => [body.height * 0.35, body.height * 0.6, body.height * 1.9],
  )

  return (
    <div className="flex-1 relative overflow-hidden bg-gray-100">
      <ThreeCanvas
        frameloop="demand"
        camera={{ position: initialCamera, fov: 35, near: 1, far: 5000 }}
      >
        <color attach="background" args={['#f3f4f6']} />
        <hemisphereLight args={['#ffffff', '#8d7b68', 1.4]} />
        <directionalLight position={[150, 300, 250]} intensity={2.2} />
        <directionalLight position={[-200, 150, -150]} intensity={0.7} />
        <group>
          {geometries.map((g, i) => (
            <mesh key={i} geometry={g} material={material} />
          ))}
        </group>
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.1, 0]}>
          <circleGeometry args={[70, 48]} />
          <meshStandardMaterial color="#e5e7eb" roughness={1} />
        </mesh>
        <Controls targetY={body.height * 0.55} />
      </ThreeCanvas>
      <div className="absolute top-2 left-3 text-[10px] text-gray-500 pointer-events-none select-none">
        Drag to rotate · scroll to zoom · right-drag to pan
      </div>
    </div>
  )
}
