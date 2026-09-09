"""
Event-Driven CAD Planner for ForgeAgent Live Graph Engine.
Implements the S13-style (GraphSnapshot, Event) -> GraphPatch protocol.
Grows the execution graph dynamically from physical CAD outcomes and OpenCascade verification events.
"""

from typing import Dict, Any, Set
from orchestrator.models import AssemblyGraph, PartSpec
from orchestrator.live_graph.models import TaskSpec, Event, GraphPatch, GraphSnapshot


class LiveCADPlanner:
    """
    Event-driven CAD planner.
    Uses the Kinematic Blueprint as physical grounding, but emits tasks
    organically as prior geometry is verified and interface ports are proven.
    """

    def __init__(self, blueprint: AssemblyGraph):
        self.blueprint = blueprint
        self.part_map: Dict[str, PartSpec] = {p.id: p for p in blueprint.parts}
        self.verified_interfaces: Dict[str, Dict[str, Any]] = {}
        self.verified_solids: Dict[str, Any] = {}
        self.repair_counts: Dict[str, int] = {p.id: 0 for p in blueprint.parts}
        self.assembly_repairs: int = 0
        self.max_retries: int = 3

        # Compute part dependencies based on mating relationships
        self.deps: Dict[str, Set[str]] = {p.id: set() for p in blueprint.parts}
        envelope_keywords = {"housing", "casing", "frame", "enclosure", "base", "plate", "bracket", "ring", "circular_spline"}
        envelope_ids = {
            p.id for p in blueprint.parts
            if any(kw in (p.id + " " + p.name).lower() for kw in envelope_keywords)
        }
        if not envelope_ids and blueprint.parts:
            # Fallback: part with most mates is datum
            envelope_ids.add(max(blueprint.parts, key=lambda p: len(p.mates)).id)

        for p in blueprint.parts:
            if p.id in envelope_ids:
                continue
            for m in p.mates:
                if m.partner_id in self.part_map and m.partner_id in envelope_ids:
                    self.deps[p.id].add(m.partner_id)
            for j in blueprint.joints:
                if j.part_a == p.id and j.part_b in envelope_ids:
                    self.deps[p.id].add(j.part_b)
                elif j.part_b == p.id and j.part_a in envelope_ids:
                    self.deps[p.id].add(j.part_a)

    async def plan(self, graph: GraphSnapshot, event: Event) -> GraphPatch:
        """Evaluates an outcome Event against GraphSnapshot and returns a GraphPatch mutation."""
        
        # 1. Initial frontier on run start: emit datum/envelope parts
        if event.kind == "run_started":
            root_parts = [p for p in self.blueprint.parts if not self.deps[p.id]]
            if not root_parts:
                root_parts = [self.blueprint.parts[0]]

            add_tasks = []
            connections = []
            for rp in root_parts:
                d_id = f"design_{rp.id}"
                v_id = f"verify_{rp.id}"
                add_tasks.append(TaskSpec(
                    id=d_id,
                    role="code_generator_agent",
                    input={"spec": rp, "master_skeleton": self.blueprint.shared_parameters}
                ))
                add_tasks.append(TaskSpec(
                    id=v_id,
                    role="part_verifier_agent",
                    input={"spec": rp}
                ))
                connections.append((d_id, v_id))

            return GraphPatch(
                add=add_tasks,
                connect=connections,
                reason=f"Emitted root datum parts: {[p.id for p in root_parts]}"
            )

        # 2. Design task finished -> sandbox executed -> pass solid to verifier
        if event.node_id and event.node_id.startswith("design_") and event.kind == "task_succeeded":
            pid = event.node_id.replace("design_", "")
            v_id = f"verify_{pid}"
            # Capture interfaces exported by designer
            if "interfaces" in event.payload:
                self.verified_interfaces[pid] = event.payload["interfaces"]
            return GraphPatch(reason=f"Design {pid} completed in sandbox; verified by {v_id}")

        # 3. Part Verification SUCCEEDED -> capture proven ports, spawn dependent parts
        if event.node_id and event.node_id.startswith("verify_") and event.kind == "task_succeeded":
            pid = event.node_id.replace("verify_", "")
            if "solid" in event.payload:
                self.verified_solids[pid] = event.payload["solid"]

            # Check if any remaining parts now have all their dependencies verified
            new_tasks = []
            new_conns = []
            for child_id, parent_deps in self.deps.items():
                d_id = f"design_{child_id}"
                v_id = f"verify_{child_id}"
                if d_id in graph.nodes or child_id in self.verified_solids:
                    continue  # Already scheduled or completed

                if all(p in self.verified_solids for p in parent_deps):
                    child_spec = self.part_map[child_id]
                    # Gather verified partner interface ports
                    dep_ports = {
                        p: self.verified_interfaces.get(p, {})
                        for p in parent_deps
                    }
                    new_tasks.append(TaskSpec(
                        id=d_id,
                        role="code_generator_agent",
                        input={
                            "spec": child_spec,
                            "master_skeleton": self.blueprint.shared_parameters,
                            "partner_interfaces": dep_ports
                        }
                    ))
                    new_tasks.append(TaskSpec(
                        id=v_id,
                        role="part_verifier_agent",
                        input={"spec": child_spec}
                    ))
                    new_conns.append((d_id, v_id))
                    for p in parent_deps:
                        new_conns.append((f"verify_{p}", d_id))

            if new_tasks:
                return GraphPatch(
                    add=new_tasks,
                    connect=new_conns,
                    reason=f"Verified ports on {pid} unlocked frontier: {[t.id for t in new_tasks if t.id.startswith('design_')]}"
                )

            # If all parts in blueprint are now verified, emit assembly tasks
            if len(self.verified_solids) == len(self.blueprint.parts):
                if "assemble" not in graph.nodes:
                    assy_task = TaskSpec(
                        id="assemble",
                        role="assembly_agent",
                        input={
                            "graph": self.blueprint,
                            "verified_solids": self.verified_solids,
                            "interfaces": self.verified_interfaces
                        }
                    )
                    ver_assy_task = TaskSpec(
                        id="verify_assembly",
                        role="assembly_verifier_agent",
                        input={
                            "graph": self.blueprint,
                            "interfaces": self.verified_interfaces
                        }
                    )
                    conns = [(f"verify_{p.id}", "assemble") for p in self.blueprint.parts]
                    conns.append(("assemble", "verify_assembly"))
                    return GraphPatch(
                        add=[assy_task, ver_assy_task],
                        connect=conns,
                        reason="All single parts verified; emitted assembly and collision check"
                    )

        # 4. Part Verification FAILED -> spawn targeted repair branch
        if event.node_id and event.node_id.startswith("verify_") and event.kind == "task_failed":
            pid = event.node_id.replace("verify_", "")
            self.repair_counts[pid] += 1
            if self.repair_counts[pid] > self.max_retries:
                return GraphPatch(finish=True, reason=f"Part {pid} exceeded maximum repair retries ({self.max_retries})")

            rep_id = f"repair_{pid}_iter_{self.repair_counts[pid]}"
            ver_retry_id = f"verify_{pid}_retry_{self.repair_counts[pid]}"
            rep_task = TaskSpec(
                id=rep_id,
                role="part_repair_agent",
                input={
                    "verdict": event.payload.get("verdict"),
                    "code": event.payload.get("code", ""),
                    "spec": self.part_map[pid]
                }
            )
            v_retry = TaskSpec(
                id=ver_retry_id,
                role="part_verifier_agent",
                input={"spec": self.part_map[pid]}
            )
            return GraphPatch(
                add=[rep_task, v_retry],
                connect=[(event.node_id, rep_id), (rep_id, ver_retry_id)],
                reason=f"Sprouted targeted repair branch for {pid} after verification failure"
            )

        # 5. Assembly Verifier FAILED (Interference / Clash) -> sprout positioning/tolerance patch
        if event.node_id == "verify_assembly" and event.kind == "task_failed":
            self.assembly_repairs += 1
            if self.assembly_repairs > self.max_retries:
                return GraphPatch(finish=True, reason="Assembly exceeded maximum collision repair retries")

            clash_rep_id = f"assembly_repair_iter_{self.assembly_repairs}"
            assy_retry_id = f"assemble_retry_{self.assembly_repairs}"
            ver_retry_id = f"verify_assembly_retry_{self.assembly_repairs}"

            # Create targeted assembly repair tasks
            return GraphPatch(
                add=[
                    TaskSpec(
                        id=clash_rep_id,
                        role="assembly_agent",
                        input={
                            "graph": self.blueprint,
                            "positioning_repair_prompt": f"Shift colliding pair to resolve {event.payload.get('interference_volume', 0.1)}mm3 interference."
                        }
                    ),
                    TaskSpec(
                        id=ver_retry_id,
                        role="assembly_verifier_agent",
                        input={"graph": self.blueprint, "interfaces": self.verified_interfaces}
                    )
                ],
                connect=[(event.node_id, clash_rep_id), (clash_rep_id, ver_retry_id)],
                reason="Sprouted assembly collision repair task"
            )

        # 6. Assembly Verifier SUCCEEDED -> finished!
        if event.node_id and "verify_assembly" in event.node_id and event.kind == "task_succeeded":
            return GraphPatch(
                finish=True,
                reason="Assembly verified collision-free (0.0mm3 interference) and kinematic constraints satisfied."
            )

        return GraphPatch()
