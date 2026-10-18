import logging
from sympy import SympifyError, sympify

logger = logging.getLogger("xa.specialists.engineer")


def calculate(expression: str) -> dict:
    try:
        result = sympify(expression)
        return {"result": str(result), "expression": expression}
    except (SympifyError, SyntaxError, ValueError, TypeError) as exc:
        return {"error": f"Invalid expression: {exc}", "expression": expression}
