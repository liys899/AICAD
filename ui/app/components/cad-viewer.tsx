"use client"

import { useEffect, useRef, useState } from "react"
import * as THREE from "three"
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js"
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js"
import { createOpenSCAD } from "openscad-wasm"

export interface CadViewerProps {
  scadScript: string
}

export default function CadViewer({ scadScript }: CadViewerProps) {
  const ref = useRef<HTMLDivElement>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const overlaySceneRef = useRef<THREE.Scene | null>(null)
  const overlayCameraRef = useRef<THREE.OrthographicCamera | null>(null)
  const [status, setStatus] = useState("Idle")

  useEffect(() => {
    if (!ref.current) return
    let active = true
    let renderer: THREE.WebGLRenderer | null = null
    let controls: OrbitControls | null = null
    let winResizeAttached = false

    const fitCameraToSize = () => {
      const el = ref.current
      const cam = cameraRef.current
      const ren = rendererRef.current
      if (!el || !cam || !ren) return
      const w = el.clientWidth
      const h = Math.max(el.clientHeight, 1)
      ren.setSize(w, h)
      cam.aspect = w / h
      cam.updateProjectionMatrix()
    }

    const onWinResize = () => fitCameraToSize()

    const run = async () => {
      if (!scadScript?.trim()) {
        setStatus("No model yet")
        if (ref.current) ref.current.innerHTML = ""
        rendererRef.current = null
        cameraRef.current = null
        overlaySceneRef.current = null
        overlayCameraRef.current = null
        return
      }
      setStatus("Compiling OpenSCAD (WASM)...")
      const openScad = await createOpenSCAD()
      const stlText = await openScad.renderToStl(scadScript)
      if (!active || !ref.current) return

      const loader = new STLLoader()
      const geometry = loader.parse(new TextEncoder().encode(stlText).buffer)
      geometry.computeVertexNormals()

      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0xf8f8f8)
      const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 5000)
      cameraRef.current = camera
      camera.position.set(140, 120, 140)
      camera.lookAt(0, 0, 0)

      renderer = new THREE.WebGLRenderer({ antialias: true })
      rendererRef.current = renderer
      ref.current.innerHTML = ""
      ref.current.appendChild(renderer.domElement)
      fitCameraToSize()
      window.addEventListener("resize", onWinResize)
      winResizeAttached = true

      controls = new OrbitControls(camera, renderer.domElement)
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      controls.target.set(0, 0, 0)
      controls.update()

      const material = new THREE.MeshStandardMaterial({ color: 0x7d93b2, metalness: 0.15, roughness: 0.65 })
      const mesh = new THREE.Mesh(geometry, material)
      scene.add(mesh)

      scene.add(new THREE.AmbientLight(0xffffff, 1.0))
      const key = new THREE.DirectionalLight(0xffffff, 1.0)
      key.position.set(100, 100, 120)
      scene.add(key)

      const overlayScene = new THREE.Scene()
      const overlayCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10)
      overlayCamera.position.set(0, 0, 2)
      overlayCamera.lookAt(0, 0, 0)
      overlaySceneRef.current = overlayScene
      overlayCameraRef.current = overlayCamera
      overlayScene.add(new THREE.AxesHelper(0.85))

      const box = new THREE.Box3().setFromObject(mesh)
      const size = box.getSize(new THREE.Vector3()).length() || 1
      const center = box.getCenter(new THREE.Vector3())
      mesh.position.sub(center)
      camera.near = size / 100
      camera.far = size * 20
      camera.updateProjectionMatrix()

      const animate = () => {
        if (!active || !renderer) return
        controls?.update()

        const el = ref.current
        const w = el?.clientWidth || 0
        const h = el?.clientHeight || 0
        if (w > 0 && h > 0) {
          renderer.setViewport(0, 0, w, h)
          renderer.setScissorTest(false)
        }
        renderer.render(scene, camera)

        if (w > 0 && h > 0 && overlaySceneRef.current && overlayCameraRef.current) {
          const s = Math.round(Math.min(w, h) * 0.18)
          const pad = 10
          const x = w - s - pad
          const y = h - s - pad
          renderer.clearDepth()
          renderer.setScissorTest(true)
          renderer.setScissor(x, y, s, s)
          renderer.setViewport(x, y, s, s)
          renderer.render(overlaySceneRef.current, overlayCameraRef.current)
          renderer.setScissorTest(false)
        }

        requestAnimationFrame(animate)
      }
      animate()
      setStatus("Preview ready")
    }

    run().catch((e) => setStatus(`Preview failed: ${e?.message || e}`))
    return () => {
      active = false
      if (winResizeAttached) window.removeEventListener("resize", onWinResize)
      controls?.dispose()
      if (renderer) renderer.dispose()
      rendererRef.current = null
      cameraRef.current = null
      overlaySceneRef.current = null
      overlayCameraRef.current = null
    }
  }, [scadScript])

  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(() => {
      const ren = rendererRef.current
      const cam = cameraRef.current
      if (!ren || !cam) return
      const w = el.clientWidth
      const h = Math.max(el.clientHeight, 1)
      ren.setSize(w, h)
      cam.aspect = w / h
      cam.updateProjectionMatrix()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [scadScript])

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, minWidth: 0, width: "100%" }}>
      <div style={{ flexShrink: 0, marginBottom: 8, fontSize: 12, color: "#666" }}>{status}</div>
      <div ref={ref} style={{ flex: 1, minHeight: 0, width: "100%", border: "1px solid #efefef", position: "relative" }} />
    </div>
  )
}
