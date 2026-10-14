"""Open charger sources: parsing each feed and loading it beside the pilot data."""

import pytest
from sqlalchemy import create_engine

from backend.charger_import import ID_BASE, import_source, region_counts
from backend.charger_sources import (REGIONS, output_kw, plausible, parse_bfe, parse_bnetza, parse_digitraffic, parse_irve,
                                     parse_ndw, parse_osm)

NDW = [{
    "id": "loc-1", "publish": True, "name": "Ark van Norg", "address": "Tussenlaan 18", "city": "Norg",
    "postal_code": "9331ZB", "country_code": "NL", "coordinates": {"latitude": "53.079105", "longitude": "6.476502"},
    "operator": {"name": "E-Flux by Road"},
    "evses": [
        {"uid": "e1", "evse_id": "NL*EFL*E1", "status": "AVAILABLE",
         "connectors": [{"power_type": "AC_3_PHASE", "max_electric_power": 11040}]},
        {"uid": "e2", "evse_id": "NL*EFL*E2", "status": "CHARGING",
         "connectors": [{"power_type": "DC", "max_voltage": 400, "max_amperage": 125}]},
        {"uid": "e3", "status": "REMOVED", "connectors": []},
    ],
}, {"id": "hidden", "publish": False, "coordinates": {"latitude": "52", "longitude": "5"}, "evses": [{"uid": "x"}]}]

BNETZA = "\n".join([
    "Ladesäulenregister Bundesnetzagentur;;;",
    "Letzte Aktualisierung vom: 01.09.2026;;;",
    "Ladeeinrichtungs-ID;Betreiber;Anzeigename (Karte);Status;Art der Ladeeinrichtung;Anzahl Ladepunkte;"
    "Nennleistung Ladeeinrichtung [kW];Straße;Hausnummer;Postleitzahl;Ort;Breitengrad;Längengrad;"
    "Steckertypen1;Nennleistung Stecker1;EVSE-ID1;Steckertypen2;Nennleistung Stecker2;EVSE-ID2",
    "1010338;Albwerk;Albwerk;In Betrieb;Normalladeeinrichtung;2;22;Am Berg;1;72535;Heroldstatt;48,446067;9,668408;"
    "AC Typ 2 Steckdose;22;DEAEWE1;AC Typ 2 Steckdose;11;",
    "1010339;Albwerk;Albwerk;In Betrieb;Schnellladeeinrichtung;1;150;Am Berg;1;72535;Heroldstatt;48,446067;9,668408;"
    "DC Kupplung Combo, CCS;150;DEAEWE2;;;",
    "1010340;Bad;Bad;In Betrieb;Normalladeeinrichtung;1;11;;;;;0;0;;;;;;",
])

OSM = [
    {"type": "node", "id": 1, "lat": 38.72, "lon": -9.14, "tags": {
        "amenity": "charging_station", "operator": "EDP", "capacity": "2",
        "socket:type2_combo": "1", "socket:type2_combo:output": "50 kW", "socket:type2": "1"}},
    {"type": "way", "id": 2, "center": {"lat": 38.73, "lon": -9.15}, "tags": {"amenity": "charging_station"}},
    {"type": "node", "id": 3, "lat": 38.74, "lon": -9.16, "tags": {"access": "private"}},
]
LISBON = next(region for region in REGIONS if region.id == "lisbon")


def test_ndw_keeps_live_evses_and_derives_power_and_kind():
    [site] = parse_ndw(NDW)
    assert (site.key, site.operator, site.city, site.country) == ("NL**loc-1", "E-Flux by Road", "Norg", "NL")
    assert [(p.key, p.power_kw, p.kind) for p in site.points] == [
        ("NL*EFL*E1", 11.04, "regular"), ("NL*EFL*E2", 50.0, "fast")]


def test_bnetza_reads_decimal_commas_and_groups_devices_by_location():
    sites = list(parse_bnetza(BNETZA))
    assert len(sites) == 2  # the 0,0 row is dropped
    normal, fast = sites
    assert normal.lat == pytest.approx(48.446067) and normal.group == fast.group
    assert [(p.key, p.power_kw, p.kind) for p in normal.points] == [("DEAEWE1", 22, "regular"), ("1010338#2", 11, "regular")]
    assert [(p.power_kw, p.kind) for p in fast.points] == [(150, "fast")]
    assert normal.street == "Am Berg 1"


def test_osm_uses_capacity_dc_sockets_and_skips_private_sites():
    first, second = parse_osm(OSM, LISBON)
    assert (first.key, first.operator, first.country, len(first.points)) == ("node/1", "EDP", "PT", 2)
    assert {p.kind for p in first.points} == {"fast"} and first.points[0].power_kw == 50
    assert (second.lat, len(second.points), second.points[0].power_kw, second.city) == (38.73, 1, None, "Lisbon")


def test_bfe_groups_an_operators_evses_by_position_and_reads_single_names():
    def record(evse, power, kind, names):
        return {"EvseID": evse, "ChargingStationId": evse, "GeoCoordinates": {"Google": "46.23432 6.055602"},
                "Address": {"City": "Meyrin", "Street": "Esplanade des Particules", "HouseNum": "1"},
                "ChargingFacilities": [{"power": power, "powertype": kind}], "ChargingStationNames": names}
    data = {"EVSEData": [{"OperatorID": "CH*CCI", "OperatorName": "SIG", "EVSEDataRecord": [
        record("CH*CCI*E1", "22.0", "AC_3_PHASE", [{"lang": "de", "value": "CERN"}, {"lang": "en", "value": "CERN Site"}]),
        record("CH*CCI*E2", "150", "DC", {"lang": "en", "value": "CERN Site"}),
        dict(record("CH*CCI*E3", "11", "AC_3_PHASE", []), GeoCoordinates={"Google": "not a position"}),
    ]}]}
    [site] = parse_bfe(data)
    assert (site.operator, site.name, site.street, site.country) == ("SIG", "CERN Site", "Esplanade des Particules 1", "CH")
    assert [(p.key, p.power_kw, p.kind) for p in site.points] == [("CH*CCI*E1", 22, "regular"), ("CH*CCI*E2", 150, "fast")]


def test_irve_prefers_checked_coordinates_converts_watts_and_keeps_the_latest_row():
    base = {"id_station_itinerance": "FRXXXP1", "nom_operateur": "Op", "nom_station": "Gare", "adresse_station": "1 rue",
            "consolidated_commune": "Lyon", "consolidated_code_postal": "69001", "consolidated_latitude": "45.76",
            "consolidated_longitude": "4.83", "coordonneesXY": "garbage", "prise_type_combo_ccs": "false",
            "prise_type_chademo": "FALSE", "date_maj": "2025-01-01"}
    rows = [dict(base, id_pdc_itinerance="FRXXXE1", puissance_nominale="22"),
            dict(base, id_pdc_itinerance="FRXXXE1", puissance_nominale="7.4", date_maj="2026-05-01"),
            dict(base, id_pdc_itinerance="FRXXXE2", puissance_nominale="150000", prise_type_combo_ccs="True"),
            dict(base, id_station_itinerance="ESXXXP9", id_pdc_itinerance="ESXXXE9", puissance_nominale="50",
                 consolidated_latitude="", consolidated_longitude="", coordonneesXY="[-3.59, 40.52]")]
    lyon, spain = parse_irve(rows)
    assert (lyon.lat, lyon.lon, lyon.city, lyon.country) == (45.76, 4.83, "Lyon", "FR")
    assert [(p.key, p.power_kw, p.kind) for p in lyon.points] == [("FRXXXE1", 7.4, "regular"), ("FRXXXE2", 150, "fast")]
    # Labelled France: the ID prefix names the operator's country; positions.py relabels it
    assert (spain.lat, spain.lon, spain.country) == (40.52, -3.59, "FR")


def test_digitraffic_reads_geojson_evses_in_kilowatts():
    collection = {"features": [{"geometry": {"coordinates": [24.875, 60.1911]}, "properties": {
        "id": "loc-1", "name": "Tennis club", "address": {"street": "Kärkitie 4", "city": "Helsinki", "postalCode": "00330"},
        "operator": {"id": "FI*911", "details": {"name": "Porsche"}},
        "evses": [{"id": "FI*911*E1", "connectors": [{"powerType": "AC_3_PHASE", "maxElectricPower": 12800}]},
                  {"id": "FI*911*E2", "connectors": [{"powerType": "DC", "maxElectricPower": 150000}]}]}},
        {"geometry": {"coordinates": [25.0, 60.2]}, "properties": {"id": "empty", "evses": []}}]}
    [site] = parse_digitraffic(collection)
    assert (site.key, site.operator, site.city, site.country) == ("loc-1", "Porsche", "Helsinki", "FI")
    assert [(p.power_kw, p.kind) for p in site.points] == [(12.8, "regular"), (150, "fast")]


def test_positions_outside_the_sites_country_are_rejected():
    assert plausible("CH", 46.2, 6.1) and not plausible("CH", 50.0, -15.0)  # BFE placeholder
    assert not plausible("NL", 40.36, -79.74)  # NDW site with US coordinates
    assert plausible("FR", -20.88, 55.47) and plausible("FR", 48.85, 2.35)  # Reunion, Paris
    assert plausible("ES", 40.5, -3.6) and not plausible("ES", 45.0, 70.0)  # other countries: Europe


@pytest.mark.parametrize("value, expected", [("22 kW", 22), ("7.4kW", 7.4), ("50", 50), ("3700 W", 3.7),
                                             ("22 kW;11 kW", 22), ("", None)])
def test_output_kw(value, expected):
    assert output_kw(value) == expected


@pytest.fixture
def connection(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'chargers.sqlite').as_posix()}")
    tagged = "source VARCHAR, external_id VARCHAR"
    with engine.begin() as connection:
        for statement in [
            f"CREATE TABLE locations (id INTEGER PRIMARY KEY, street VARCHAR, locator_designator VARCHAR, "
            f"supplement VARCHAR, postal_name VARCHAR, zip_code VARCHAR, state VARCHAR, country VARCHAR, "
            f"latitude FLOAT, longitude FLOAT, geom BLOB, {tagged})",
            "CREATE TABLE operators (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL)",
            f"CREATE TABLE columns (id INTEGER PRIMARY KEY, operator_id INTEGER NOT NULL, location_id INTEGER NOT NULL, "
            f"comissioning_date DATETIME, net_capacity FLOAT, elaadnl_id VARCHAR, {tagged})",
            f"CREATE TABLE charging_points (id INTEGER PRIMARY KEY, column_id INTEGER NOT NULL, type VARCHAR, "
            f"power FLOAT, {tagged})",
            "CREATE TABLE grid_connections (id INTEGER PRIMARY KEY, transformer_id INTEGER, column_id INTEGER)",
            # One Amsterdam pilot charger, untagged as in the existing database
            "INSERT INTO operators VALUES (1, 'Vattenfall')",
            "INSERT INTO locations (id, latitude, longitude) VALUES (9022, 52.303958, 4.751661)",
            "INSERT INTO columns (id, operator_id, location_id) VALUES (9125, 1, 9022)",
            "INSERT INTO charging_points (id, column_id, type, power) VALUES (6801, 9125, 'regular', 11)",
        ]:
            connection.exec_driver_sql(statement)
    with engine.begin() as connection:
        yield connection
    engine.dispose()


def ndw_site(key, lat, lon, operator="Vattenfall"):
    return {"id": key, "coordinates": {"latitude": str(lat), "longitude": str(lon)}, "operator": {"name": operator},
            "evses": [{"uid": f"{key}-1", "connectors": [{"power_type": "AC_3_PHASE", "max_electric_power": 11000}]}]}


def test_import_skips_pilot_duplicates_reuses_operators_and_keeps_ids(connection):
    feed = [ndw_site("near-pilot", 52.30397, 4.75167), ndw_site("rotterdam", 51.92, 4.48, "Shell Recharge")]
    stats = import_source(connection, "ndw", parse_ndw(feed), with_geometry=False)
    assert (stats["sites"], stats["points"], stats["skipped_pilot_duplicates"], stats["operators_added"]) == (1, 1, 1, 1)
    point_id = connection.exec_driver_sql("SELECT id FROM charging_points WHERE source = 'ndw'").scalar_one()
    assert point_id == ID_BASE["ndw"] + 1

    # Re-importing with a new site keeps the existing ID and never touches the pilot rows
    feed.append(ndw_site("utrecht", 52.09, 5.12))
    import_source(connection, "ndw", parse_ndw(feed), with_geometry=False)
    rows = dict(connection.exec_driver_sql("SELECT external_id, id FROM charging_points WHERE source = 'ndw'").all())
    assert rows == {"rotterdam-1": ID_BASE["ndw"] + 1, "utrecht-1": ID_BASE["ndw"] + 2}
    assert connection.exec_driver_sql("SELECT COUNT(*) FROM charging_points WHERE source IS NULL").scalar_one() == 1
    counts = region_counts(connection)
    assert counts["amsterdam"] == dict(sites=1, points=1) and counts["rotterdam"] == dict(sites=1, points=1)


def test_import_skips_sites_inside_an_excluded_area(connection):
    feed = [ndw_site("amsterdam", 52.37, 4.89), ndw_site("haarlem", 52.38, 4.64)]
    stats = import_source(connection, "ndw", parse_ndw(feed), with_geometry=False,
                          exclude=lambda lat, lon: lon > 4.7)
    assert (stats["sites"], stats["skipped_pilot_area"]) == (1, 1)
    assert connection.exec_driver_sql("SELECT external_id FROM columns WHERE source = 'ndw'").scalar_one() == "NL**haarlem"


def test_density_cells_aggregate_points_per_zoom_grid(connection):
    from backend.charger_import import density_cells
    feed = [ndw_site("rotterdam-a", 51.92, 4.48), ndw_site("rotterdam-b", 51.93, 4.47), ndw_site("utrecht", 52.09, 5.12)]
    import_source(connection, "ndw", parse_ndw(feed), with_geometry=False)
    # Zoom 4 cells are 5.6 degrees: every charger, pilot included, shares one cell
    [(lat, lon, points, fast, sites)] = density_cells(connection, 4)
    assert (points, fast, sites) == (4, 0, 4) and 51.9 < lat < 52.4
    # Zoom 11 cells are 0.04 degrees: Amsterdam, Rotterdam and Utrecht separate
    assert sorted(cell[2] for cell in density_cells(connection, 11)) == [1, 1, 2]
    # Sites without any known power still count, just not as fast
    connection.exec_driver_sql("UPDATE charging_points SET power = NULL")
    assert density_cells(connection, 4)[0][2:4] == [4, 0]
    # The bubble sits on a real charger (the Rotterdam one nearest the mean), not between them
    assert density_cells(connection, 4)[0][:2] == [51.93, 4.47]



class FakeGeocoder:
    """Addresses -> positions without network; records what was asked."""
    def __init__(self, local=None, anywhere=None):
        self.local, self.anywhere, self.asked, self.requests = local or {}, anywhere or {}, [], 0

    def locate(self, site):
        self.asked.append(("local", site.street))
        return self.local.get(site.street)

    def locate_anywhere(self, site):
        self.asked.append(("anywhere", site.street))
        return self.anywhere.get(site.street)

    def save(self):
        pass


def site(key, lat, lon, country="DE", street=None, city=None, group=None):
    from backend.charger_sources import Point, Site
    return Site("test", key, lat, lon, country, street=street, city=city, postcode="1000",
                group=group, points=[Point(f"{key}#1", 11, "regular")])


def test_repair_swaps_relabels_stations_abroad_and_geocodes_typos():
    import math
    from backend.charger_positions import repair_positions
    swapped = site("swap", 9.44874, 47.04627, "CH", "Langgrabenstrasse 20", "Sargans")
    abroad = site("abroad", 47.71277, 10.81981, "CH", "Via Claudia 6", "Lechbruck", group="47.71277,10.81981")
    typo = site("typo", 55.12278, 6.21601, "DE", "Friedrich-List-Allee 22", "Wegberg", group="55.12278,6.21601")
    lost = site("lost", 50.0, -15.0, "CH", None, None)
    geocoder = FakeGeocoder(anywhere={"Via Claudia 6": (47.7129, 10.8199, "DE"),
                                      "Friedrich-List-Allee 22": (51.12254, 6.21621, "DE")})
    sites, stats = repair_positions([swapped, abroad, typo, lost], geocoder, mask=False, shapes=False)
    assert (swapped.lat, swapped.lon) == (47.04627, 9.44874)
    # Right place, wrong label: position kept, country from the address
    assert (abroad.lat, abroad.country) == (47.71277, "DE")
    assert (typo.lat, typo.lon, typo.group) == (51.12254, 6.21621, "51.12254,6.21621")
    assert math.isnan(lost.lat)  # no address to go on: dropped by the importer
    assert stats["swapped"] == 1 and stats["relabelled_abroad"] == 1 and stats["geocoded"] == 1 and stats["unresolved"] == 1


def test_pile_ups_are_geocoded_confirmed_or_dropped():
    from backend.charger_positions import repair_positions
    import math
    sea = (54.32459, 7.36405)  # BNetzA point shared by devices from all over Germany
    pile = [site(f"p{i}", *sea, street=f"Strasse {i}", city=city) for i, city in enumerate(["Ulm", "Bonn", "Kiel", "Jena"])]
    town = (51.27603, 6.76836)  # one town's chargers on its centroid
    centroid = [site(f"d{i}", *town, street=f"Weg {i}", city="Duesseldorf") for i in range(3)]
    hub = [site(f"h{i}", 52.5, 13.4, street=f"Platz {i}", city="Berlin") for i in range(3)]
    geocoder = FakeGeocoder(local={"Strasse 0": (48.40, 9.99), "Strasse 1": (50.73, 7.10),
                                   "Weg 0": (51.2201, 6.7802),
                                   **{f"Platz {i}": (52.5001, 13.4001) for i in range(3)}})
    sites, stats = repair_positions(pile+centroid+hub, geocoder, mask=False, shapes=False)
    assert (pile[0].lat, pile[1].lat) == (48.40, 50.73)
    assert all(math.isnan(s.lat) for s in pile[2:])  # placeholder from several towns, no address match
    assert centroid[0].lat == 51.2201 and centroid[1].lat == town[0]  # one town: kept near the right place
    assert all(s.lat == 52.5 for s in hub)  # addresses confirm a genuine shared position
    assert stats["pile_up_points"] == 3 and stats["confirmed"] == 3 and stats["unresolved_placeholder"] == 2


def test_bfe_takes_the_country_from_the_address():
    data = {"EVSEData": [{"OperatorID": "CH*X", "OperatorName": "X", "EVSEDataRecord": [
        {"EvseID": "CH*X*E1", "GeoCoordinates": {"Google": "47.71277 10.81981"},
         "Address": {"City": "Lechbruck", "Country": "DEU", "Street": "Via Claudia"},
         "ChargingFacilities": [{"power": "22", "powertype": "AC_3_PHASE"}]}]}]}
    [site_] = parse_bfe(data)
    assert site_.country == "DE"



def test_sites_far_out_at_sea_are_geocoded_or_dropped():
    import math
    from shapely.geometry import box
    from backend.charger_positions import repair_positions
    land = box(4.6, 51.0, 7.3, 53.6).buffer(.02)  # stand-in for the Natural Earth land mask
    coast = site("coast", 52.6227, 4.6216, "NL", "Boulevard 64", "Egmond aan Zee")  # on the buffered coast
    lost = site("lost", 52.83605, 4.38591, "NL", "Wegastraat 44", "Alphen aan den Rijn")
    nowhere = site("nowhere", 52.9, 4.2, "NL", "Nergens 1", "Nergens")
    # Reclaimed land the coarse coastline misses: the address confirms it
    maasvlakte = site("maasvlakte", 51.9409, 4.52, "NL", "Amoerweg 50", "Maasvlakte")
    # Close to the coast, no address match: kept, the coastline is too coarse to judge
    quay = site("quay", 52.0, 4.53, "NL", "Kade 1", "Haven")
    geocoder = FakeGeocoder(anywhere={"Wegastraat 44": (52.1347, 4.6702, "NL"),
                                      "Amoerweg 50": (51.9410, 4.5201, "NL")})
    sites, stats = repair_positions([coast, lost, nowhere, maasvlakte, quay], geocoder, mask=land, shapes=False)
    assert (coast.lat, lost.lat, lost.lon) == (52.6227, 52.1347, 4.6702)
    assert math.isnan(nowhere.lat)  # 0.4 degrees out, no address match
    assert (maasvlakte.lat, quay.lat) == (51.9409, 52.0)
    assert stats["at_sea"] == 4 and stats["geocoded"] == 1 and stats["unresolved"] == 1
    assert stats["confirmed_by_address"] == 1 and stats["kept_near_coast"] == 1


def test_import_leaves_out_stations_outside_the_sources_countries(connection):
    feed = [ndw_site("rotterdam", 51.92, 4.48), dict(ndw_site("antwerp", 51.22, 4.40), country="BEL")]
    stats = import_source(connection, "ndw", parse_ndw(feed), countries=("NL",), with_geometry=False)
    assert (stats["sites"], stats["skipped_outside_coverage"]) == (1, 1)



def test_sites_clearly_inside_another_country_take_its_label():
    import geopandas as gpd
    from shapely.geometry import box
    from backend.charger_positions import CountryShapes, repair_positions
    borders = CountryShapes(gpd.GeoDataFrame({"ISO_A2_EH": ["NL", "BE", "FI", "AX"]},
                                             geometry=[box(3.3, 51.3, 7.2, 53.5), box(2.5, 49.5, 6.4, 51.3),
                                                       box(21.0, 59.8, 31.5, 70.0), box(19.3, 59.7, 21.0, 60.5)]))
    antwerp = site("antwerp", 51.22, 4.40, "NL", "Meir 1", "Antwerpen")
    border = site("border", 51.295, 4.40, "NL", "Grensweg 1", "Putte")  # within ~1 km of the NL border
    offshore_ = site("sea", 52.0, 3.0, "NL", "Kade 1", "Haven")  # in no country: keeps its label
    mariehamn = site("mariehamn", 60.10, 19.94, "FI", "Torggatan 1", "Mariehamn")  # Aland is Finland
    sites, stats = repair_positions([antwerp, border, offshore_, mariehamn], None, mask=False, shapes=borders)
    assert (antwerp.country, border.country, offshore_.country, mariehamn.country) == ("BE", "NL", "NL", "FI")
    assert stats["relabelled_by_border"] == 1
