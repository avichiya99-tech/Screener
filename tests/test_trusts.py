"""REITs/InvITs in the NIFTY 500 and the official NSE listing data (name, industry, series)."""
from conftest import make_bundle
from test_official_sources import _zip
from pipeline.build import build_record
from pipeline.run import parse_nifty500_listing
from pipeline.sources.nse_bhavcopy import parse_bhavcopy

MACRO = {"rf": 0.068, "erp": 0.055, "terminal_g": 0.05, "mos_pct": 0.25, "updated_on": "2026-11-19"}
REIT = {"name": "Brookfield India Real Estate Trust", "industry": "Realty", "series": "RR"}

NIFTY500_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\n"
    "Brookfield India Real Estate Trust,Realty,BIRET,RR,INE0FDU25010\n"
    "Dummy Ltd.,Unknown,DUMMY1,EQ,INE000000000\n"
)


def test_reit_is_not_rated():
    rec = build_record("BIRET.NS", make_bundle(), MACRO, as_of="2026-11-20", listing=REIT)
    assert rec["verdict"] == "Not rated"
    assert rec["meaningful"] is False
    assert rec["scenarios"] == {"bear": None, "base": None, "bull": None}
    assert rec["upside_pct"] is None
    assert "REIT" in rec["not_meaningful_reason"]


def test_official_nse_name_replaces_yahoo_name():
    bundle = make_bundle()
    bundle["info"]["shortName"] = "BIRET.NS,0P0001LR17,171521"
    rec = build_record("BIRET.NS", bundle, MACRO, as_of="2026-11-20", listing=REIT)
    assert rec["name"] == "Brookfield India Real Estate Trust"


def test_sector_falls_back_to_nse_industry():
    rec = build_record("BIRET.NS", make_bundle(drop=("sector",)), MACRO, as_of="2026-11-20", listing=REIT)
    assert rec["sector"] == "Realty"


def test_ordinary_stock_unaffected_by_listing():
    listing = {"name": "ABC Ltd.", "industry": "Capital Goods", "series": "EQ"}
    with_listing = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-20", listing=listing)
    without = build_record("ABC.NS", make_bundle(), MACRO, as_of="2026-11-20")
    assert with_listing["verdict"] == without["verdict"] and with_listing["meaningful"] is True


def test_parse_nifty500_listing():
    symbols, listing = parse_nifty500_listing(NIFTY500_CSV)
    assert symbols == ["RELIANCE.NS", "BIRET.NS"]
    assert listing["BIRET.NS"] == REIT


def test_bhavcopy_includes_reit_prices():
    csv = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,ClsPric\n"
           "2026-11-19,2026-11-19,CM,NSE,STK,1,INE0FDU25010,BIRET,RR,312.10\n"
           "2026-11-19,2026-11-19,CM,NSE,STK,2,INE0000I0000,PGINVIT,IV,95.20\n")
    closes = parse_bhavcopy(_zip(csv))
    assert closes["BIRET"]["close"] == 312.10 and closes["PGINVIT"]["close"] == 95.20
