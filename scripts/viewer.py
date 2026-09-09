"""
ForgeAgent 3D CAD Viewer (OpenCascade / VTK & Web).
Visualizes generated parts, assemblies, STEP, STL, and CadQuery scripts.

Usage:
    # View the latest run automatically:
    uv run python scripts/viewer.py

    # View a specific STEP, STL, or script:
    uv run python scripts/viewer.py artifacts/test_live_graph_assy/mounting_plate_assembly.step
    uv run python scripts/viewer.py artifacts/test_live_graph_assy/mounting_plate_assembly.stl

    # View an entire run directory (multi-part assembly with distinct part colors):
    uv run python scripts/viewer.py artifacts/test_live_graph_assy/

    # Save a high-res PNG snapshot:
    uv run python scripts/viewer.py <path> --snapshot preview.png

    # Open in Web Browser (Three.js):
    uv run python scripts/viewer.py <path> --web
"""

import os
import sys
import argparse
import webbrowser
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional

import cadquery as cq
import vtk


PART_PALETTE: List[Tuple[float, float, float]] = [
    (0.25, 0.55, 0.90),  # Royal Blue
    (0.95, 0.50, 0.20),  # Orange
    (0.20, 0.80, 0.50),  # Emerald Green
    (0.85, 0.30, 0.60),  # Magenta / Berry
    (0.95, 0.80, 0.20),  # Golden Amber
    (0.30, 0.80, 0.85),  # Cyan / Teal
    (0.65, 0.65, 0.70),  # Satin Metal / Grey
    (0.85, 0.35, 0.35),  # Crimson Coral
]


def find_latest_run_dir(base_dir: str = "artifacts/runs") -> Optional[Path]:
    p = Path(base_dir)
    if not p.exists():
        artifacts_dir = Path("artifacts")
        if not artifacts_dir.exists():
            return None
        subdirs = [d for d in artifacts_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if subdirs:
            return max(subdirs, key=lambda d: d.stat().st_mtime)
        return None
    runs = [d for d in p.iterdir() if d.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda d: d.stat().st_mtime)


def build_assembly_from_path(target_path: Path) -> Tuple[Optional[cq.Assembly], str]:
    """Inspects path and returns a populated cq.Assembly with styled components."""
    assy = cq.Assembly()
    label = target_path.name

    if target_path.is_file():
        suffix = target_path.suffix.lower()
        if suffix in (".step", ".stp"):
            shape = cq.importers.importStep(str(target_path))
            color = cq.Color(*PART_PALETTE[0])
            assy.add(shape, name=target_path.stem, color=color)
        elif suffix == ".stl":
            step_match = target_path.with_suffix(".step")
            if step_match.exists():
                shape = cq.importers.importStep(str(step_match))
                assy.add(shape, name=target_path.stem, color=cq.Color(*PART_PALETTE[0]))
            else:
                return None, f"stl:{target_path}"
        elif suffix == ".py":
            local_vars = {}
            with open(target_path, "r") as f:
                code = f.read()
            exec(code, {"cq": cq, "cadquery": cq}, local_vars)
            obj = local_vars.get("assembly") or local_vars.get("result") or local_vars.get("assy")
            if isinstance(obj, cq.Assembly):
                return obj, target_path.stem
            elif isinstance(obj, (cq.Workplane, cq.Shape)):
                assy.add(obj, name=target_path.stem, color=cq.Color(*PART_PALETTE[0]))
            else:
                raise ValueError(f"Script {target_path} did not produce a cq.Workplane or cq.Assembly in 'result'/'assembly'.")
        else:
            raise ValueError(f"Unsupported CAD file format: {suffix}")

    elif target_path.is_dir():
        top_step = list(target_path.glob("*.step")) + list(target_path.glob("*.stp"))
        assy_step = next((s for s in top_step if "assembly" in s.name.lower() or s.stem == target_path.name), None)
        if assy_step:
            shape = cq.importers.importStep(str(assy_step))
            assy.add(shape, name=assy_step.stem, color=cq.Color(*PART_PALETTE[0]))
            return assy, assy_step.stem

        part_step_files = sorted(list(target_path.glob("**/*.step")) + list(target_path.glob("**/*.stp")))
        if not part_step_files:
            stl_files = sorted(list(target_path.glob("**/*.stl")))
            if stl_files:
                return None, f"dir_stl:{target_path}"
            raise FileNotFoundError(f"No .step or .stl files found in {target_path}")

        for i, sfile in enumerate(part_step_files):
            try:
                shape = cq.importers.importStep(str(sfile))
                color = cq.Color(*PART_PALETTE[i % len(PART_PALETTE)])
                assy.add(shape, name=sfile.stem, color=color)
            except Exception as e:
                print(f"  ⚠️ Warning: Could not import {sfile.name}: {e}")

    return assy, label


def render_native_vtk(assy: Optional[cq.Assembly], raw_stl_path: Optional[str] = None, title: str = "ForgeAgent CAD Viewer", snapshot_path: Optional[str] = None):
    """Launches an interactive native desktop OpenCascade/VTK 3D window."""
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.12, 0.14, 0.18)   # Dark graphite top
    renderer.SetBackground2(0.20, 0.23, 0.30)  # Slate bottom
    renderer.SetGradientBackground(True)

    if assy is not None:
        cq_renderer = cq.exporters.assembly.toVTK(assy, tolerance=1e-3, angularTolerance=0.1)
        actors = cq_renderer.GetActors()
        actors.InitTraversal()
        actor = actors.GetNextItem()
        while actor:
            renderer.AddActor(actor)
            actor = actors.GetNextItem()
    elif raw_stl_path:
        p = Path(raw_stl_path)
        stl_files = [p] if p.is_file() else sorted(list(p.glob("**/*.stl")))
        for i, sf in enumerate(stl_files):
            reader = vtk.vtkSTLReader()
            reader.SetFileName(str(sf))
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(reader.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            rgb = PART_PALETTE[i % len(PART_PALETTE)]
            actor.GetProperty().SetColor(rgb[0], rgb[1], rgb[2])
            actor.GetProperty().SetSpecular(0.3)
            actor.GetProperty().SetSpecularPower(20)
            renderer.AddActor(actor)

    renderer.ResetCamera()

    rw = vtk.vtkRenderWindow()
    rw.AddRenderer(renderer)
    rw.SetWindowName(f"ForgeAgent 3D Viewer — {title}")
    rw.SetSize(1100, 800)

    if snapshot_path:
        rw.SetOffScreenRendering(1)
        rw.Render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(rw)
        w2i.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(snapshot_path)
        writer.SetInputConnection(w2i.GetOutputPort())
        writer.Write()
        print(f"📸 Snapshot saved to: {snapshot_path}")
        return

    iren = vtk.vtkRenderWindowInteractor()
    iren.SetRenderWindow(rw)

    style = vtk.vtkInteractorStyleTrackballCamera()
    iren.SetInteractorStyle(style)

    axes = vtk.vtkAxesActor()
    widget = vtk.vtkOrientationMarkerWidget()
    widget.SetOrientationMarker(axes)
    widget.SetInteractor(iren)
    widget.SetViewport(0.0, 0.0, 0.22, 0.22)
    widget.SetEnabled(1)
    widget.InteractiveOff()

    print("\n" + "=" * 60)
    print(f" 🖥️  ForgeAgent Native 3D CAD Viewer: {title}")
    print("=" * 60)
    print("  • Left Mouse Drag:      360° Free Orbit / Rotate")
    print("  • Right Mouse / Scroll: Smooth Zoom In / Out")
    print("  • Middle Mouse Drag:    Pan Model")
    print("  • 'r' Key:              Reset Camera View")
    print("  • 'q' or 'e' Key:       Close Viewer Window")
    print("=" * 60 + "\n")

    rw.Render()
    iren.Start()


def render_web_threejs(assy: Optional[cq.Assembly], raw_stl_path: Optional[str], title: str):
    """Exports to GLTF and serves an interactive Three.js 3D viewer in browser."""
    temp_dir = Path(tempfile.mkdtemp(prefix="forgeagent_3d_"))
    gltf_file = temp_dir / "model.gltf"

    if assy:
        cq.exporters.assembly.exportAssembly(assy, str(gltf_file), exportType="GLTF")
    else:
        print("  ⚠️ Web mode requires an assembly or STEP model for GLTF export.")
        return

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ForgeAgent 3D: {title}</title>
    <style>
        body {{ margin: 0; background-color: #12141a; overflow: hidden; font-family: sans-serif; }}
        #info {{ position: absolute; top: 12px; left: 16px; color: #fff; z-index: 100; }}
        h1 {{ font-size: 16px; margin: 0 0 4px 0; color: #60a5fa; }}
        p {{ font-size: 12px; margin: 0; color: #94a3b8; }}
        #canvas-container {{ width: 100vw; height: 100vh; }}
    </style>
    <script type="importmap">
    {{
        "imports": {{
            "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
            "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
        }}
    }}
    </script>
</head>
<body>
    <div id="info">
        <h1>🛠️ ForgeAgent 3D CAD Viewer</h1>
        <p>{title} | Left Drag: Orbit | Right Drag: Pan | Scroll: Zoom</p>
    </div>
    <div id="canvas-container"></div>
    <script type="module">
        import * as THREE from 'three';
        import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
        import {{ GLTFLoader }} from 'three/addons/loaders/GLTFLoader.js';

        const container = document.getElementById('canvas-container');
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x12141a);

        const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 2000);
        camera.position.set(100, 100, 100);

        const renderer = new THREE.WebGLRenderer({{ antialias: true }});
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.shadowMap.enabled = true;
        container.appendChild(renderer.domElement);

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;

        const ambientLight = new THREE.AmbientLight(0xffffff, 1.2);
        scene.add(ambientLight);

        const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.5);
        dirLight1.position.set(100, 200, 100);
        scene.add(dirLight1);

        const dirLight2 = new THREE.DirectionalLight(0x60a5fa, 0.8);
        dirLight2.position.set(-100, -100, -100);
        scene.add(dirLight2);

        const grid = new THREE.GridHelper(200, 20, 0x334155, 0x1e293b);
        grid.position.y = -0.1;
        scene.add(grid);

        const loader = new GLTFLoader();
        loader.load('model.gltf', (gltf) => {{
            const model = gltf.scene;
            const box = new THREE.Box3().setFromObject(model);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            model.position.sub(center);
            scene.add(model);

            const maxDim = Math.max(size.x, size.y, size.z);
            camera.position.set(maxDim * 1.5, maxDim * 1.5, maxDim * 1.8);
            controls.target.set(0, 0, 0);
            controls.update();
        }});

        window.addEventListener('resize', () => {{
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        }});

        function animate() {{
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }}
        animate();
    </script>
</body>
</html>
"""
    html_file = temp_dir / "index.html"
    with open(html_file, "w") as f:
        f.write(html_content)

    import http.server
    import socketserver
    import threading

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(temp_dir), **kwargs)
        def log_message(self, format, *args):
            pass

    port = 8765
    while True:
        try:
            httpd = socketserver.TCPServer(("", port), Handler)
            break
        except OSError:
            port += 1

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}/index.html"
    print(f"🌐 Serving interactive 3D Web Viewer at: {url}")
    webbrowser.open(url)
    print("Press Ctrl+C to stop web viewer server...")
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nStopping viewer server.")


def main():
    parser = argparse.ArgumentParser(description="ForgeAgent 3D CAD Viewer")
    parser.add_argument(
        "path",
        type=str,
        nargs="?",
        default=None,
        help="Path to .step, .stl, .py file, or run directory (default: latest in artifacts/runs/)"
    )
    parser.add_argument(
        "--snapshot",
        type=str,
        default=None,
        help="Save offscreen PNG snapshot to specified file path"
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Open in Web Browser (Three.js WebGL)"
    )

    args = parser.parse_args()

    target_path = Path(args.path) if args.path else find_latest_run_dir()
    if not target_path or not target_path.exists():
        print(f"❌ Error: Path '{target_path}' not found.")
        sys.exit(1)

    print(f"📂 Loading CAD Model: {target_path}")

    raw_stl = None
    assy = None
    title = target_path.name

    try:
        assy, title = build_assembly_from_path(target_path)
        if assy is None and isinstance(title, str) and title.startswith(("stl:", "dir_stl:")):
            raw_stl = title.split(":", 1)[1]
            title = Path(raw_stl).name
    except Exception as e:
        print(f"❌ Failed to load CAD geometry: {e}")
        sys.exit(2)

    if args.web:
        render_web_threejs(assy, raw_stl, title)
    else:
        render_native_vtk(assy, raw_stl, title, snapshot_path=args.snapshot)


if __name__ == "__main__":
    main()
