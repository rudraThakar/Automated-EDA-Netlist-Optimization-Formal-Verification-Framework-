from backends.python_graph import PythonGraphBackend
from backends.router import BackendRouter
from ir import NetlistIR


def make_ir():
    ir = NetlistIR()
    ir.module_name = "top"
    ir.add_input("a")
    ir.add_input("b")
    ir.add_output("y")
    ir.add_gate("and", "u0", "n1", ["a", "b"])
    ir.add_gate("buf", "u1", "y", ["n1"])
    return ir


def test_python_graph_backend_queries():
    backend = PythonGraphBackend(make_ir())

    assert backend.fanout("n1")["fanout"] == 1
    assert backend.longest_path_between_nets("a", "y")[0] == 2
    assert backend.find_any_path("a", "y", avoid=None)
    assert backend.check_max_fanout(1)["valid"] is True


def test_backend_router_describes_operation_ownership():
    routes = BackendRouter().describe()

    assert routes["get_fanout"]["backend"] == "python_graph"
    assert "yosys" in routes["normalize_design"]["backend"]
    assert routes["clean_dangling_and_write"]["backend"] == "workflow"
