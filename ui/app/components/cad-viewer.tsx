"use client"

import { useEffect, useRef, useState } from 'react'
import * as THREE from "three"
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js"
import { createOpenSCAD, OpenSCADInstance } from "openscad-wasm"

export interface CadViewerProps {
    scadScript: string
}


export default function CadViewer({ scadScript }: CadViewerProps) {
    const ref = useRef<HTMLDivElement>(null)
    const [status, setStatus] = useState("Idle")

    useEffect(() => {
        if (!ref.current) return
        let active = true
        let renderer: THREE.WebGLRenderer | null = null
        let openScad: OpenSCADInstance | null = null

        const run = async () => {
            if (!scadScript?.trim()) {
                setStatus("No model yet")
                return
            }
            setStatus("Compiling OpenSCAD (WASM)...")
            openScad = await createOpenSCAD()
            const stlText = await openScad.renderToStl(scadScript)
            if (!active || !ref.current) return

            const loader = new STLLoader()
            const geometry = loader.parse(new TextEncoder().encode(stlText).buffer)
            geometry.computeVertexNormals()

            const scene = new THREE.Scene()
            scene.background = new THREE.Color(0xf8f8f8)
            const camera = new THREE.PerspectiveCamera(55, ref.current.clientWidth / Math.max(ref.current.clientHeight, 1), 0.1, 5000)
            camera.position.set(140, 120, 140)
            camera.lookAt(0, 0, 0)

            renderer = new THREE.WebGLRenderer({ antialias: true })
            renderer.setSize(ref.current.clientWidth || 1024, ref.current.clientHeight || 640)
            ref.current.innerHTML = ""
            ref.current.appendChild(renderer.domElement)

            const material = new THREE.MeshStandardMaterial({ color: 0x7d93b2, metalness: 0.15, roughness: 0.65 })
            const mesh = new THREE.Mesh(geometry, material)
            scene.add(mesh)

            scene.add(new THREE.AmbientLight(0xffffff, 1.0))
            const key = new THREE.DirectionalLight(0xffffff, 1.0)
            key.position.set(100, 100, 120)
            scene.add(key)
            scene.add(new THREE.GridHelper(240, 24))
            scene.add(new THREE.AxesHelper(80))

            const box = new THREE.Box3().setFromObject(mesh)
            const size = box.getSize(new THREE.Vector3()).length() || 1
            const center = box.getCenter(new THREE.Vector3())
            mesh.position.sub(center)
            camera.near = size / 100
            camera.far = size * 20
            camera.updateProjectionMatrix()

            const animate = () => {
                if (!active || !renderer) return
                mesh.rotation.z += 0.005
                renderer.render(scene, camera)
                requestAnimationFrame(animate)
            }
            animate()
            setStatus("Preview ready")
        }

        run().catch((e) => setStatus(`Preview failed: ${e?.message || e}`))
        return () => {
            active = false
            if (renderer) renderer.dispose()
        }
    }, [scadScript])

    return (
        <div>
            <div style={{ marginBottom: 8, fontSize: 12, color: "#666" }}>{status}</div>
            <div ref={ref} style={{ width: "100%", height: "70vh", border: "1px solid #efefef" }} />
        </div>
    )
}