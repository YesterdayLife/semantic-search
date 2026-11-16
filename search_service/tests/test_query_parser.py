"""Query parser checks. These tests do not load the embedding model."""

from __future__ import annotations

from app.query_parser import parse_query
from app.records import SourceHint

SOURCES = (
    SourceHint("SRC-01", "FAO", "FAOSTAT QCL"),
    SourceHint("SRC-05", "OAE", "OAE maize total"),
    SourceHint("SRC-06", "OAE", "OAE cassava"),
)


def test_thai_cassava_north_converts_buddhist_era():
    parsed = parse_query("มันสำปะหลังภาคเหนือปี 2566")
    assert parsed.crop_id == "CAS"
    assert parsed.region_code == "NOR"
    assert parsed.spatial_level == "region"
    assert parsed.year_ce == 2023
    assert parsed.season is None
    assert any("2566" in warning and "2023" in warning for warning in parsed.warnings)


def test_english_maize_central_thailand():
    parsed = parse_query("maize production in central Thailand 2022")
    assert parsed.crop_id == "MAI"
    assert parsed.region_code == "CEN"
    assert parsed.spatial_level == "region"
    assert parsed.year_ce == 2022
    assert parsed.unavailable_measures == ()


def test_dry_season_rice_and_crop_aliases():
    parsed = parse_query("ข้าวนาปรังปี 2565")
    assert parsed.crop_id == "RIC"
    assert parsed.season == "dry"
    assert parsed.year_ce == 2022
    assert parse_query("ข้าวโพด").crop_id == "MAI"
    assert parse_query("cassava").crop_id == "CAS"
    assert parse_query("sugarcane").crop_id == "SUG"


def test_region_aliases_do_not_confuse_northeast_with_north():
    assert parse_query("ตะวันออกเฉียงเหนือ").region_code == "NEA"
    assert parse_query("ภาคเหนือ").region_code == "NOR"
    assert parse_query("ภาคใต้").region_code == "SOU"
    assert parse_query("ภาคกลาง").region_code == "CEN"


def test_ambiguous_crop_season_and_year_stay_unfiltered():
    crops = parse_query("มันสำปะหลังและข้าวโพด")
    assert crops.crop_id is None
    assert any("crop" in warning for warning in crops.warnings)
    seasons = parse_query("ข้าวนาปรังกับข้าวนาปี")
    assert seasons.season is None
    assert any("season" in warning for warning in seasons.warnings)
    years = parse_query("rice 2020 and 2022")
    assert years.year_ce is None
    assert any("year" in warning for warning in years.warnings)


def test_source_matches_a_unique_title_and_reports_shared_agencies():
    assert parse_query("FAOSTAT QCL rice", SOURCES).source_id == "SRC-01"
    ambiguous = parse_query("OAE production", SOURCES)
    assert ambiguous.source_id is None
    assert any("source" in warning for warning in ambiguous.warnings)


def test_unsupported_measures_are_identified():
    fertilizer = parse_query("ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง")
    assert fertilizer.crop_id == "CAS"
    assert fertilizer.unavailable_measures == ("fertilizer",)
    carbon = parse_query("carbon footprint of rice production")
    assert carbon.crop_id == "RIC"
    assert carbon.unavailable_measures == ("carbon_footprint",)
