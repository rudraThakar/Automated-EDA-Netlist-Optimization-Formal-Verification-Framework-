from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ir import GateType, NetlistError, NetlistIR


class PythonGraphBackend:
    """Lightweight deterministic graph analysis over NetlistIR."""

    def __init__(self, ir: NetlistIR) -> None:
        self.ir = ir

    def bind(self, ir: NetlistIR) -> None:
        self.ir = ir

    def fanout(self, node_or_net: str) -> Dict[str, object]:
        target = node_or_net.strip()
        if target in self.ir.nets:
            return {
                "kind": "net",
                "name": target,
                "fanout": len(self.ir.nets[target].sinks),
            }
        if target in self.ir.nodes:
            node = self.ir.nodes[target]
            if node.output is None:
                raise NetlistError(f"Node '{target}' has no output net.")
            return {
                "kind": "node",
                "name": target,
                "output_net": node.output,
                "fanout": len(self.ir.nets[node.output].sinks),
            }
        raise NetlistError(f"Unknown node or net: '{target}'")

    def check_max_fanout(self, max_fanout: int) -> Dict[str, object]:
        violations = []
        for net_name, net in self.ir.nets.items():
            fanout = len(net.sinks)
            if fanout > max_fanout:
                violations.append((net_name, fanout))
        return {"valid": not violations, "max_fanout": max_fanout, "violations": violations}

    def longest_path_between_nets(self, source: str, sink: str) -> Tuple[int, List[str]]:
        if source not in self.ir.nets or sink not in self.ir.nets:
            return -1, []
        memo: Dict[str, Tuple[int, List[str]]] = {}
        temp_mark = set()

        def dfs_net(cur_net: str) -> Tuple[int, List[str]]:
            if cur_net == sink:
                return 0, [cur_net]
            if cur_net in memo:
                return memo[cur_net]
            if cur_net in temp_mark:
                return -1, []
            temp_mark.add(cur_net)
            best_depth = -1
            best_path: List[str] = []
            for node_name in self.ir.nets[cur_net].sinks:
                node = self.ir.nodes[node_name]
                if node.gate_type == GateType.DFF:
                    continue
                out_net = node.output
                if out_net is None:
                    continue
                sub_depth, sub_path = dfs_net(out_net)
                if sub_depth >= 0 and 1 + sub_depth > best_depth:
                    best_depth = 1 + sub_depth
                    best_path = [cur_net, node_name] + sub_path
            temp_mark.remove(cur_net)
            memo[cur_net] = (best_depth, best_path)
            return memo[cur_net]

        return dfs_net(source)

    def find_any_path(self, source: str, sink: str, avoid: Optional[str]) -> List[str]:
        if source not in self.ir.nets or sink not in self.ir.nets:
            return []
        avoid_set = {avoid} if avoid else set()
        visited_nets = set()
        visited_nodes = set()

        def dfs_net(cur_net: str, acc: List[str]) -> Optional[List[str]]:
            if cur_net in avoid_set:
                return None
            if cur_net == sink:
                return acc + [cur_net]
            if cur_net in visited_nets:
                return None
            visited_nets.add(cur_net)
            for node_name in self.ir.nets[cur_net].sinks:
                if node_name in avoid_set or node_name in visited_nodes:
                    continue
                visited_nodes.add(node_name)
                out_net = self.ir.nodes[node_name].output
                if out_net is None:
                    continue
                result = dfs_net(out_net, acc + [cur_net, node_name])
                if result is not None:
                    return result
            return None

        result = dfs_net(source, [])
        return result if result is not None else []

    def cone_from_output(self, output_signal: str) -> Tuple[set[str], set[str]]:
        cone_nets = set()
        cone_nodes = set()
        visited_nets = set()
        visited_nodes = set()

        if output_signal not in self.ir.nets:
            return cone_nets, cone_nodes

        def traverse_upstream(net_name: str) -> None:
            if net_name in visited_nets:
                return
            visited_nets.add(net_name)
            cone_nets.add(net_name)
            net = self.ir.nets[net_name]
            if net.driver and net.driver not in visited_nodes:
                visited_nodes.add(net.driver)
                cone_nodes.add(net.driver)
                node = self.ir.nodes[net.driver]
                for input_net in node.inputs:
                    traverse_upstream(input_net)

        traverse_upstream(output_signal)
        return cone_nets, cone_nodes

    def live_cone_from_outputs(self) -> Tuple[set[str], set[str]]:
        live_nets = set(self.ir.outputs)
        live_nodes = set()
        stack = list(self.ir.outputs)
        while stack:
            net_name = stack.pop()
            net = self.ir.nets.get(net_name)
            if net is None or net.driver is None:
                continue
            node_name = net.driver
            if node_name in live_nodes:
                continue
            live_nodes.add(node_name)
            node = self.ir.nodes[node_name]
            for in_net in node.inputs:
                if in_net not in live_nets:
                    live_nets.add(in_net)
                    stack.append(in_net)
        return live_nets, live_nodes
