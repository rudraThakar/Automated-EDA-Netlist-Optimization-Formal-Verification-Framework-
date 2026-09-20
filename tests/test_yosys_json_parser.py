from parser import YosysJsonNetlistParser


def test_yosys_json_parser_builds_ir_from_single_bit_cells():
    data = {
        "modules": {
            "top": {
                "attributes": {"top": "1"},
                "ports": {
                    "a": {"direction": "input", "bits": [2]},
                    "b": {"direction": "input", "bits": [3]},
                    "y": {"direction": "output", "bits": [4]},
                },
                "netnames": {
                    "a": {"hide_name": 0, "bits": [2]},
                    "b": {"hide_name": 0, "bits": [3]},
                    "y": {"hide_name": 0, "bits": [4]},
                },
                "cells": {
                    "$and$top.v:1$1": {
                        "type": "$and",
                        "connections": {"A": [2], "B": [3], "Y": [4]},
                    }
                },
            }
        }
    }

    ir = YosysJsonNetlistParser().parse_data(data, loaded_path="top.v")

    assert ir.module_name == "top"
    assert ir.inputs == ["a", "b"]
    assert ir.outputs == ["y"]
    assert len(ir.nodes) == 1

    node = next(iter(ir.nodes.values()))
    assert node.gate_type.value == "and"
    assert node.inputs == ["a", "b"]
    assert node.output == "y"
