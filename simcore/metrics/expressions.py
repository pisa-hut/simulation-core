from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

COMPARISON_OPS: dict[type[ast.cmpop], Callable[[float, float], bool]] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}

FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": round,
}


def evaluate_numeric_expression(expression: str, variables: dict[str, Any]) -> float | bool:
    tree = ast.parse(expression, mode="eval")
    value = _eval_node(tree.body, variables)
    if isinstance(value, bool):
        return value
    return float(value)


def _eval_node(node: ast.AST, variables: dict[str, Any]):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return node.value
        if isinstance(node.value, int | float):
            return float(node.value)
        raise ValueError(f"Unsupported expression constant: {node.value!r}")

    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ValueError(f"Unknown expression variable: {node.id}")
        try:
            return float(variables[node.id])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Expression variable {node.id!r} must be numeric") from exc

    if isinstance(node, ast.BinOp):
        op = BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported expression operator: {type(node.op).__name__}")
        return op(
            _as_float(_eval_node(node.left, variables)),
            _as_float(_eval_node(node.right, variables)),
        )

    if isinstance(node, ast.UnaryOp):
        op = UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported expression unary operator: {type(node.op).__name__}")
        return op(_as_float(_eval_node(node.operand, variables)))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ValueError("Only abs(), min(), max(), and round() are allowed in expressions")
        args = [_as_float(_eval_node(arg, variables)) for arg in node.args]
        if node.keywords:
            raise ValueError("Expression function keyword arguments are not supported")
        return FUNCTIONS[node.func.id](*args)

    if isinstance(node, ast.Compare):
        left = _as_float(_eval_node(node.left, variables))
        for op_node, comparator in zip(node.ops, node.comparators, strict=True):
            op = COMPARISON_OPS.get(type(op_node))
            if op is None:
                raise ValueError(f"Unsupported expression comparison: {type(op_node).__name__}")
            right = _as_float(_eval_node(comparator, variables))
            if not op(left, right):
                return False
            left = right
        return True

    raise ValueError(f"Unsupported expression syntax: {type(node).__name__}")


def _as_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean values cannot be used as numeric operands")
    return float(value)
