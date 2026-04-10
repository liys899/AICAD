"use client"

import { useEffect, useMemo, useRef, useState } from 'react'
import "../../dist/three-cad-viewer/three-cad-viewer.css"
import { Viewer } from "../../dist/three-cad-viewer/three-cad-viewer.esm.js"

function nc(_change: unknown) {}

export interface CadViewerProps {
    cadShapes: any
}


export default function CadViewer({ cadShapes }: CadViewerProps) {
    const ref = useRef(null)
    const [viewport, setViewport] = useState({ width: 1024, height: 768 })

    useEffect(() => {
        const update = () => setViewport({ width: window.innerWidth, height: window.innerHeight })
        update()
        window.addEventListener("resize", update)
        return () => window.removeEventListener("resize", update)
    }, [])

    const viewerOptions = useMemo(() => ({
        theme: "light",
        ortho: true,
        control: "trackball", // "orbit",
        normalLen: 0,
        cadWidth: viewport.width,
        height: viewport.height * 0.85,
        ticks: 10,
        ambientIntensity: 0.9,
        directIntensity: 0.12,
        transparent: false,
        blackEdges: false,
        axes: true,
        grid: [false, false, false],
        timeit: false,
        rotateSpeed: 1,
        tools: false,
        glass: false
    }), [viewport.height, viewport.width])

    const renderOptions = useMemo(() => ({
        ambientIntensity: 1.0,
        directIntensity: 1.1,
        metalness: 0.30,
        roughness: 0.65,
        edgeColor: 0x707070,
        defaultOpacity: 0.5,
        normalLen: 0,
        up: "Z"
    }), [])


    useEffect(() => {
        const container = ref.current //document.getElementById("cad_view")

        // 2) Create the CAD display in this container
        // const display = new Display(container, options)

        // 3) Create the CAD viewer

        // var shapesStates = viewer.renderTessellatedShapes(shapes, states, options)
        if (cadShapes && cadShapes.length > 0) {
            const viewer = new Viewer(container, viewerOptions, nc)

            const [shapes, states] = cadShapes as unknown as [any, any]
            const render = (_name: string, shapes: any, states: any) => {
                viewer?.clear()
                const [unselected, selected] = viewer.renderTessellatedShapes(shapes, states, renderOptions)
                console.log(unselected)
                console.log(selected)

                viewer.render(
                    unselected,
                    selected,
                    states,
                    renderOptions,
                )
            }
            render("input", shapes, states)
        }


    }, [cadShapes, viewerOptions, renderOptions])

    return (
        <div ref={ref}></div>
    )
}