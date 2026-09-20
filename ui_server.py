from __future__ import annotations

import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app import ICCADApp  # noqa: E402
from config import load_config, make_planner_from_config  # noqa: E402


app = FastAPI(title="ICCAD 2026 UI", version="0.1.0")


class ConfigureRequest(BaseModel):
    config_path: str = "config.yaml"
    no_llm: bool = False
    require_llm: bool = False
    debug: bool = True
    verification_policy: str = "permissive"


class RequestBody(BaseModel):
    text: str


@dataclass
class TimelineItem:
    request_index: int
    request_text: str
    stdout: str
    planner_meta: Dict[str, Any] = field(default_factory=dict)
    planner_raw: str = ""
    validated_tool: Dict[str, Any] = field(default_factory=dict)
    tool_output_summary: str = ""
    tool_output_data: Dict[str, Any] = field(default_factory=dict)
    validation_error: Dict[str, Any] = field(default_factory=dict)
    execution_error: Dict[str, Any] = field(default_factory=dict)
    response: str = ""
    files: Dict[str, str] = field(default_factory=dict)


class UISession:
    def __init__(self) -> None:
        self.iccad_app: Optional[ICCADApp] = None
        self.timeline: List[TimelineItem] = []
        self.config: Dict[str, Any] = {}
        self.config_path: str = "config.yaml"
        self.no_llm: bool = False
        self.require_llm: bool = False
        self.debug: bool = True
        self.verification_policy: str = "permissive"
        self.run_root: Path = ROOT

    def configure(
        self,
        config_path: str,
        no_llm: bool,
        require_llm: bool,
        debug: bool,
        verification_policy: str = "permissive",
    ) -> Dict[str, Any]:
        cfg = load_config(config_path)
        planner = make_planner_from_config(cfg, no_llm=no_llm, require_llm=require_llm)
        policy = verification_policy or str(cfg.get("verification_policy", "permissive"))
        self.iccad_app = ICCADApp(planner=planner, debug=debug, verification_policy=policy)
        self.timeline = []
        self.config = cfg
        self.config_path = config_path
        self.no_llm = no_llm
        self.require_llm = require_llm
        self.debug = debug
        self.verification_policy = policy
        self.run_root = Path.cwd()
        return {
            "ok": True,
            "planner_class": planner.__class__.__name__,
            "config_path": config_path,
            "no_llm": no_llm,
            "require_llm": require_llm,
            "debug": debug,
            "verification_policy": policy,
        }

    def reset(self) -> None:
        self.iccad_app = None
        self.timeline = []
        self.config = {}

    def run_request(self, text: str) -> TimelineItem:
        if self.iccad_app is None:
            # auto-configure with defaults
            self.configure("config.yaml", no_llm=False, require_llm=False, debug=True, verification_policy="permissive")

        assert self.iccad_app is not None

        buffer = io.StringIO()
        old_stdout = self.iccad_app.protocol.stdout
        self.iccad_app.protocol.stdout = buffer
        try:
            if self.iccad_app.case_name is None:
                init_line = (
                    "This is the beginning of testcase ui_session. "
                    "Please output a copy of the log into ui_session.log.\n"
                )
                self.iccad_app.handle_line(init_line)
            self.iccad_app.handle_line(text if text.endswith("\n") else text + "\n")
        finally:
            self.iccad_app.protocol.stdout = old_stdout

        stdout_text = buffer.getvalue()
        artifacts = self._read_results_dir()

        item = TimelineItem(
            request_index=len(self.timeline) + 1,
            request_text=text,
            stdout=stdout_text,
            planner_meta=artifacts.get("latest_planner_meta.json", {}),
            planner_raw=artifacts.get("latest_planner_raw.txt", ""),
            validated_tool=artifacts.get("latest_validated_tool.json", {}),
            tool_output_summary=artifacts.get("latest_tool_output_summary.txt", ""),
            tool_output_data=artifacts.get("latest_tool_output_data.json", {}),
            validation_error=artifacts.get("latest_validation_error.json", {}),
            execution_error=artifacts.get("latest_execution_error.json", {}),
            response=artifacts.get("latest_response.txt", ""),
            files=self._list_known_files(),
        )
        self.timeline.append(item)
        return item

    def _read_results_dir(self) -> Dict[str, Any]:
        results_dir = self.run_root / "results"
        payload: Dict[str, Any] = {}
        if not results_dir.exists():
            return payload

        for path in results_dir.iterdir():
            if not path.is_file():
                continue
            try:
                if path.suffix == ".json":
                    payload[path.name] = json.loads(path.read_text(encoding="utf-8"))
                else:
                    payload[path.name] = path.read_text(encoding="utf-8")
            except Exception as exc:
                payload[path.name] = f"<<failed to read: {type(exc).__name__}: {exc}>>"
        return payload

    def _list_known_files(self) -> Dict[str, str]:
        files: Dict[str, str] = {}
        candidates = [
            self.run_root / "results" / "latest_user_request.txt",
            self.run_root / "results" / "latest_planner_raw.txt",
            self.run_root / "results" / "latest_planner_meta.json",
            self.run_root / "results" / "latest_validated_tool.json",
            self.run_root / "results" / "latest_tool_output_summary.txt",
            self.run_root / "results" / "latest_tool_output_data.json",
            self.run_root / "results" / "latest_validation_error.json",
            self.run_root / "results" / "latest_execution_error.json",
            self.run_root / "results" / "latest_response.txt",
        ]
        for path in candidates:
            if path.exists():
                files[path.name] = str(path)
        return files

    def get_state(self) -> Dict[str, Any]:
        if self.iccad_app is None and (ROOT / self.config_path).exists():
            self.configure(
                self.config_path,
                no_llm=self.no_llm,
                require_llm=self.require_llm,
                debug=self.debug,
                verification_policy=self.verification_policy,
            )

        planner_name = None
        case_name = None
        design_loaded = None
        verilog_text = ""
        verification_policy = self.verification_policy
        metrics = self._empty_metrics()
        graph = {"status": "empty", "message": "No design loaded.", "nodes": [], "edges": []}
        if self.iccad_app is not None:
            planner_name = self.iccad_app.planner.__class__.__name__
            case_name = self.iccad_app.case_name
            design_loaded = self.iccad_app.engine.ir.loaded_path
            verification_policy = self.iccad_app.engine.verification_policy
            try:
                if self.iccad_app.engine.ir.module_name is not None:
                    verilog_text = self.iccad_app.engine.writer.render(self.iccad_app.engine.ir)
                    metrics = self._design_metrics()
                    graph = self._design_graph()
            except Exception:
                verilog_text = ""

        return {
            "planner_class": planner_name,
            "case_name": case_name,
            "design_loaded": design_loaded,
            "verification_policy": verification_policy,
            "metrics": metrics,
            "timeline": [item.__dict__ for item in self.timeline],
            "verilog": verilog_text,
            "graph": graph,
        }

    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            "module": None,
            "inputs": 0,
            "outputs": 0,
            "instances": 0,
            "nets": 0,
            "max_depth": None,
            "max_fanout": 0,
            "max_fanout_net": None,
            "last_tool": None,
            "last_equivalent": None,
            "last_frontend": None,
        }

    def _design_metrics(self) -> Dict[str, Any]:
        assert self.iccad_app is not None
        engine = self.iccad_app.engine
        ir = engine.ir
        max_depth = None
        for output in ir.outputs:
            for source in ir.inputs:
                try:
                    depth = engine.get_max_depth(source, output).data.get("depth")
                except Exception:
                    depth = None
                if depth is not None:
                    max_depth = depth if max_depth is None else max(max_depth, depth)

        max_fanout = 0
        max_fanout_net = None
        for net_name, net in ir.nets.items():
            fanout = len(net.sinks)
            if fanout > max_fanout:
                max_fanout = fanout
                max_fanout_net = net_name

        last = self.timeline[-1] if self.timeline else None
        tool_data = last.tool_output_data if last else {}
        return {
            "module": ir.module_name,
            "inputs": len(ir.inputs),
            "outputs": len(ir.outputs),
            "instances": len(ir.nodes),
            "nets": len(ir.nets),
            "max_depth": max_depth,
            "max_fanout": max_fanout,
            "max_fanout_net": max_fanout_net,
            "last_tool": last.validated_tool.get("tool") if last and last.validated_tool else None,
            "last_equivalent": tool_data.get("equivalent"),
            "last_frontend": tool_data.get("frontend"),
        }

    def _design_graph(self) -> Dict[str, Any]:
        assert self.iccad_app is not None
        ir = self.iccad_app.engine.ir
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, str]] = []

        for name in ir.inputs:
            nodes.append({"id": name, "label": name, "kind": "input"})
        for name in ir.outputs:
            nodes.append({"id": name, "label": name, "kind": "output"})
        for name, node in ir.nodes.items():
            nodes.append({
                "id": name,
                "label": f"{name}\\n{node.gate_type.value if node.gate_type else 'node'}",
                "kind": "gate",
            })
            for input_net in node.inputs:
                edges.append({"source": input_net, "target": name, "label": input_net})
            if node.output:
                edges.append({"source": name, "target": node.output, "label": node.output})

        seen = {node["id"] for node in nodes}
        for net_name in ir.nets:
            if net_name not in seen:
                nodes.append({"id": net_name, "label": net_name, "kind": "net"})

        return {
            "status": "ok",
            "message": f"{len(nodes)} graph nodes, {len(edges)} edges",
            "nodes": nodes,
            "edges": edges,
        }


SESSION = UISession()

UI_DIR = ROOT / "ui"
app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(UI_DIR / "app.js", media_type="application/javascript")


@app.get("/styles.css")
def styles_css() -> FileResponse:
    return FileResponse(UI_DIR / "styles.css", media_type="text/css")


@app.post("/api/configure")
def configure(req: ConfigureRequest) -> JSONResponse:
    return JSONResponse(
        SESSION.configure(
            config_path=req.config_path,
            no_llm=req.no_llm,
            require_llm=req.require_llm,
            debug=req.debug,
            verification_policy=req.verification_policy,
        )
    )


@app.post("/api/reset")
def reset() -> JSONResponse:
    SESSION.reset()
    return JSONResponse({"ok": True})


@app.post("/api/request")
def run_request(req: RequestBody) -> JSONResponse:
    item = SESSION.run_request(req.text)
    return JSONResponse(item.__dict__)


@app.get("/api/state")
def get_state() -> JSONResponse:
    return JSONResponse(SESSION.get_state())


@app.get("/api/file/{filename}")
def get_file(filename: str):
    allowed = {
        "latest_user_request.txt",
        "latest_planner_raw.txt",
        "latest_planner_meta.json",
        "latest_validated_tool.json",
        "latest_tool_output_summary.txt",
        "latest_tool_output_data.json",
        "latest_validation_error.json",
        "latest_execution_error.json",
        "latest_response.txt",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="File not allowed")

    path = ROOT / "results" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "application/json" if path.suffix == ".json" else "text/plain"
    return FileResponse(path, media_type=media_type)


@app.get("/api/design/verilog")
def design_verilog() -> JSONResponse:
    state = SESSION.get_state()
    return JSONResponse({"verilog": state["verilog"]})


@app.get("/api/design/graph")
def design_graph() -> JSONResponse:
    return JSONResponse(SESSION.get_state()["graph"])
