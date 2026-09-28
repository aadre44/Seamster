import { useEffect, useMemo, useState } from 'react'
import { Canvas as ThreeCanvas, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { useEditor } from '../context/EditorContext'
import { resolveBody } from '../three/bodyRegions'
import { useAvatarMesh } from '../three/useAvatarMesh'

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

export default function BodyModelView() {
  const { state } = useEditor()
  const body = useMemo(
    () => resolveBody(state.bodyProfile, state.measurements),
    [state.bodyProfile, state.measurements],
  )
  const mesh = useAvatarMesh(body)

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
    </div>
  )
}
