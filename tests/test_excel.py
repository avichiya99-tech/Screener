"""The live-formula Excel workbook must give the same value as the engine."""
import io
import re

import openpyxl
import pytest
from openpyxl.utils import column_index_from_string, get_column_letter

from conftest import make_bank_bundle, make_bundle
from valuation_engine import compute_valuation, export_formula_excel

_REF = re.compile(r"\$?([A-Z]{1,2})\$?(\d+)")


def _evaluator(ws):
    """Evaluate the formulas this workbook uses: + - * / ^, SUM(range), MIN, IF, comparisons."""
    cache = {}

    def cell(ref):
        if ref not in cache:
            v = ws[ref].value
            cache[ref] = expr(v[1:]) if isinstance(v, str) and v.startswith("=") else v
        return cache[ref]

    def rng(a, b):
        (c1, r1), (c2, r2) = _REF.match(a).groups(), _REF.match(b).groups()
        cols = range(column_index_from_string(c1), column_index_from_string(c2) + 1)
        return [cell(f"{get_column_letter(c)}{r}") for c in cols for r in range(int(r1), int(r2) + 1)]

    def expr(f):
        f = re.sub(r"SUM\((\$?[A-Z]+\$?\d+):(\$?[A-Z]+\$?\d+)\)", r"sum(rng('\1','\2'))", f)
        f = f.replace("MIN(", "min(").replace("IF(", "_if(").replace("^", "**").replace("<>", "!=")
        f = re.sub(r"(?<![<>!=])=(?!=)", "==", f)
        # cell refs outside the quoted rng('A1','B2') arguments become cell('A1') lookups
        f = re.sub(r"(?<!')\$?([A-Z]{1,2})\$?(\d+)(?!')", lambda m: f"cell('{m.group(1)}{m.group(2)}')", f)
        return eval(f, {"cell": cell, "rng": rng, "sum": sum, "min": min,
                        "_if": lambda c, a, b: a if c else b})

    return cell


@pytest.mark.parametrize("make,price_cell_label", [
    (make_bundle, "DCF Intrinsic Share Price"),
    (make_bank_bundle, "Intrinsic Share Price"),
])
def test_workbook_matches_engine(make, price_cell_label):
    val = compute_valuation(make())
    wb = openpyxl.load_workbook(io.BytesIO(export_formula_excel(None, val, None, "TEST.NS")))
    ws = wb.active
    row = next(r for r in range(1, ws.max_row + 1) if ws[f"A{r}"].value == price_cell_label)
    assert _evaluator(ws)(f"B{row}") == pytest.approx(val["intrinsic_price"], rel=1e-9)


def test_workbook_has_10_forecast_years():
    for make in (make_bundle, make_bank_bundle):
        ws = openpyxl.load_workbook(io.BytesIO(export_formula_excel(None, compute_valuation(make()), None, "T"))).active
        headers = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
        assert "Year 10" in headers
