import streamlit as st
import pandas as pd
import json
import re
from copy import deepcopy
from shapely.geometry import shape
from shapely.strtree import STRtree
from shapely.validation import make_valid

st.title("GeoJSON Processeur")

csv_file = st.file_uploader("Upload CSV file", type=["csv"])
geojson_file = st.file_uploader("Upload GeoJSON file", type=["geojson", "json"])

if "parcelle_json" not in st.session_state:
    st.session_state.parcelle_json = None

if "batiment_json" not in st.session_state:
    st.session_state.batiment_json = None


def normalize_column_name(name):
    name = str(name).strip()
    name = re.sub(r"\s+", " ", name)
    return name


def sanitize_attribute_name(name):
    """
    Keep only letters, digits and underscores in output attribute names.
    Example:
    'TaxationRevenue_Building($/m2)' -> 'TaxationRevenue_Buildingm2'
    """
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "", str(name))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "Attribute"


def clean_value(value):
    if pd.isna(value):
        return None
    return value


def build_column_mapping(columns):
    normalized = {col: normalize_column_name(col) for col in columns}

    alias_map = {}
    for original, clean in normalized.items():
        lower = clean.lower()

        if lower == "zone":
            alias_map["Zone"] = original
        elif lower == "zoneminarea":
            alias_map["ZoneMinArea"] = original
        elif lower == "function":
            alias_map["Function"] = original
        elif lower == "functionminarea":
            alias_map["FunctionMinArea"] = original
        elif lower == "type":
            alias_map["Type"] = original
        elif lower == "maxfootprint (%)":
            alias_map["MaxFootprint (%)"] = original
        elif lower == "taxationrevenue_building($/m2)":
            alias_map["TaxationRevenue_Building($/m2)"] = original
        elif lower == "taxationrevenue_land($/m2)":
            alias_map["TaxationRevenue_Land($/m2)"] = original
        elif lower == "maxheight":
            alias_map["MaxHeight"] = original
        elif lower == "maxfar":
            alias_map["MaxFAR"] = original
        elif lower == "parkingdensity (slot/unit)":
            alias_map["ParkingDensity (Slot/Unit)"] = original
        elif lower == "maxoccupancyratio (people/unit)":
            alias_map["MaxOccupancyRatio (People/Unit)"] = original
        elif lower == "mingreenarea (%)":
            alias_map["MinGreenArea (%)"] = original
        elif lower == "offsetinnerplot":
            alias_map["OffsetInnerPlot"] = original
        elif lower == "undergroundparking(y/n)":
            alias_map["UndergroundParking(Y/N)"] = original
        elif lower == "averageunitdimension":
            alias_map["AverageUnitDimension"] = original
        elif lower == "functioncolor":
            alias_map["FunctionColor"] = original

    return alias_map


COMMON_FIELDS = {
    "Zone",
    "ZoneMinArea",
    "Function",
    "FunctionMinArea",
    "Type",
    "FunctionColor",
}

PARCEL_FIELDS = {
    "MaxFootprint (%)",
    "TaxationRevenue_Land($/m2)",
    "MinGreenArea (%)",
    "OffsetInnerPlot",
}

BUILDING_FIELDS = {
    "TaxationRevenue_Building($/m2)",
    "MaxHeight",
    "MaxFAR",
    "ParkingDensity (Slot/Unit)",
    "MaxOccupancyRatio (People/Unit)",
    "UndergroundParking(Y/N)",
    "AverageUnitDimension",
}


def target_output_key(field_name):
    reserved_map = {
        "Zone": "CsvZone",
        "Function": "CsvFunction",
        "Type": "CsvType",
    }
    if field_name in reserved_map:
        return reserved_map[field_name]
    return sanitize_attribute_name(field_name)


def classify_csv_field(field_name):
    if field_name in COMMON_FIELDS:
        return "common"
    if field_name in PARCEL_FIELDS:
        return "parcelle"
    if field_name in BUILDING_FIELDS:
        return "batiment"

    lower = field_name.lower()

    parcel_keywords = [
        "land", "lot", "plot", "parcel", "green", "setback", "offset", "footprint", "site"
    ]
    building_keywords = [
        "building", "height", "far", "floor", "parking", "occupancy", "unit", "storey"
    ]

    if any(keyword in lower for keyword in building_keywords):
        return "batiment"
    if any(keyword in lower for keyword in parcel_keywords):
        return "parcelle"

    return "common"


def get_zone_and_function_from_feature(props):
    raw_function = str(props.get("Function", "")).strip()
    raw_zone = str(props.get("Zone", "")).strip()

    match = re.match(r"^(Zone\d+)(Function\d+)$", raw_function, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)

    separate_zone = raw_zone if re.match(r"^Zone\d+$", raw_zone, re.IGNORECASE) else None
    separate_function = raw_function if re.match(r"^Function\d+$", raw_function, re.IGNORECASE) else None

    return separate_zone, separate_function


def add_csv_attributes_to_feature(props, row_data, feature_kind):
    for field, value in row_data.items():
        value = clean_value(value)
        if value is None:
            continue

        field_scope = classify_csv_field(field)
        if field_scope not in ("common", feature_kind):
            continue

        output_key = target_output_key(field)
        props[output_key] = value

    if feature_kind == "parcelle" and clean_value(row_data.get("TaxationRevenue_Land($/m2)")) is not None:
        props["TaxationRevenue"] = row_data["TaxationRevenue_Land($/m2)"]
    elif feature_kind == "batiment" and clean_value(row_data.get("TaxationRevenue_Building($/m2)")) is not None:
        props["TaxationRevenue"] = row_data["TaxationRevenue_Building($/m2)"]


def build_output_geojson(source_geojson, output_name, features, crs_data):
    output_geojson = {}
    for key, value in source_geojson.items():
        if key == "features":
            continue
        output_geojson[key] = deepcopy(value)

    output_geojson["type"] = "FeatureCollection"
    output_geojson["name"] = output_name
    output_geojson["crs"] = crs_data
    output_geojson["features"] = features
    return output_geojson

def build_zone_code(zone_value):
    """
    Expected examples:
    Zone1 -> Z1
    zone12 -> Z12
    """
    zone_str = str(zone_value or "").strip()

    # Strict match for strings like Zone1, zone 2, ZONE-3
    match = re.search(r"\bZone\D*(\d+)\b", zone_str, flags=re.IGNORECASE)
    if match:
        return f"Z{match.group(1)}"

    # Fallback: if already something like Z1
    match = re.search(r"\bZ\D*(\d+)\b", zone_str, flags=re.IGNORECASE)
    if match:
        return f"Z{match.group(1)}"

    # Last-resort fallback
    digits_match = re.search(r"(\d+)", zone_str)
    if digits_match:
        return f"Z{digits_match.group(1)}"

    return "Z0"


def build_type_code(type_value):
    """
    Examples:
    Residential A -> RA
    Commercial B -> CB
    Mixed Use C -> MC   (first word initial + trailing single-letter token)
    Residential -> R    (fallback if no trailing letter)
    """
    type_str = str(type_value or "").strip()
    if not type_str:
        return "XX"

    # Keep only alphanumeric word tokens
    tokens = re.findall(r"[A-Za-z0-9]+", type_str)
    if not tokens:
        return "XX"

    first_token = tokens[0]
    first_letter_match = re.search(r"[A-Za-z]", first_token)
    first_letter = first_letter_match.group(0).upper() if first_letter_match else "X"

    # Prefer a trailing single-letter token, e.g. "A" in "Residential A"
    trailing_letter = None
    for token in reversed(tokens[1:]):
        if re.fullmatch(r"[A-Za-z]", token):
            trailing_letter = token.upper()
            break

    if trailing_letter:
        return f"{first_letter}{trailing_letter}"

    # Fallback: use initials of up to 2 words
    initials = []
    for token in tokens:
        m = re.search(r"[A-Za-z]", token)
        if m:
            initials.append(m.group(0).upper())

    if not initials:
        return "XX"

    if len(initials) >= 2:
        return "".join(initials[:2])

    return initials[0]


def build_feature_id_prefix(props):
    csv_zone = props.get("CsvZone")
    csv_type = props.get("CsvType")

    zone_value = csv_zone if csv_zone not in [None, ""] else props.get("Zone", "")
    type_value = csv_type if csv_type not in [None, ""] else props.get("Type", "")

    zone_code = build_zone_code(zone_value)
    type_code = build_type_code(type_value)

    return f"{zone_code}_{type_code}"


def assign_parcel_pids(parcelle_features):
    counters = {}

    for feature in parcelle_features:
        props = feature.setdefault("properties", {})
        prefix = build_feature_id_prefix(props)

        counters[prefix] = counters.get(prefix, 0) + 1
        props["PID"] = f"{prefix}_P_{counters[prefix]}"


def assign_building_bids(batiment_features):
    counters = {}

    for feature in batiment_features:
        props = feature.setdefault("properties", {})
        prefix = build_feature_id_prefix(props)

        counters[prefix] = counters.get(prefix, 0) + 1
        props["BID"] = f"{prefix}_B_{counters[prefix]}"


def build_parcel_spatial_index(parcelle_features):
    parcel_geoms = []
    parcel_pids = []

    for feature in parcelle_features:
        props = feature.get("properties", {})
        geom_json = feature.get("geometry")
        if not geom_json:
            continue

        try:
            geom = shape(geom_json)
            if geom.is_empty:
                continue
            if not geom.is_valid:
                geom = make_valid(geom)

            parcel_geoms.append(geom)
            parcel_pids.append(props.get("PID"))
        except Exception:
            continue

    if not parcel_geoms:
        return None, [], []

    tree = STRtree(parcel_geoms)
    return tree, parcel_geoms, parcel_pids


def find_matching_parcel_pid(building_feature, parcel_tree, parcel_geoms, parcel_pids):
    geom_json = building_feature.get("geometry")
    if not geom_json or parcel_tree is None:
        return None

    try:
        building_geom = shape(geom_json)
        if building_geom.is_empty:
            return None
        if not building_geom.is_valid:
            building_geom = make_valid(building_geom)
    except Exception:
        return None

    best_pid = None
    best_area = 0.0

    try:
        candidate_indices = parcel_tree.query(building_geom)
    except Exception:
        candidate_indices = []

    for idx in candidate_indices:
        try:
            parcel_geom = parcel_geoms[int(idx)]

            if not parcel_geom.intersects(building_geom):
                continue

            intersection = parcel_geom.intersection(building_geom)
            if intersection.is_empty:
                continue

            area = intersection.area
            if area > best_area:
                best_area = area
                best_pid = parcel_pids[int(idx)]
        except Exception:
            continue

    if best_pid is not None and best_area > 0:
        return best_pid

    try:
        rep_point = building_geom.representative_point()
        for idx in candidate_indices:
            parcel_geom = parcel_geoms[int(idx)]
            if parcel_geom.contains(rep_point):
                return parcel_pids[int(idx)]
    except Exception:
        pass

    for idx in candidate_indices:
        try:
            parcel_geom = parcel_geoms[int(idx)]
            if parcel_geom.intersects(building_geom):
                return parcel_pids[int(idx)]
        except Exception:
            continue

    return None


def assign_buildings_to_parcels(batiment_features, parcelle_features):
    parcel_tree, parcel_geoms, parcel_pids = build_parcel_spatial_index(parcelle_features)

    for feature in batiment_features:
        props = feature.setdefault("properties", {})
        matched_pid = find_matching_parcel_pid(feature, parcel_tree, parcel_geoms, parcel_pids)
        props["parcel_PID"] = matched_pid
        if matched_pid is None:
            props["ParcelMatchStatus"] = "unmatched"


if st.button("Start Processing"):

    if csv_file is None or geojson_file is None:
        st.warning("Please upload both files.")
        st.stop()

    with st.spinner("Processing..."):

        df = pd.read_csv(csv_file)
        df = df.loc[:, ~df.columns.astype(str).str.contains(r"^Unnamed", case=False, regex=True)]

        column_mapping = build_column_mapping(df.columns)

        required = ["Zone", "Function", "Type"]
        missing = [col for col in required if col not in column_mapping]

        if missing:
            st.error(f"Missing required CSV columns: {missing}")
            st.stop()

        rename_map = {original: clean_name for clean_name, original in column_mapping.items()}
        df = df.rename(columns=rename_map)

        recognized_columns = list(column_mapping.keys())
        lookup = {}

        for _, row in df.iterrows():
            zone = str(row["Zone"]).strip()
            function = str(row["Function"]).strip()

            row_data = {}
            for field in recognized_columns:
                if field in df.columns:
                    row_data[field] = row[field]

            lookup[(zone, function)] = row_data

        geojson = json.load(geojson_file)

        crs_data = geojson.get("crs")
        if crs_data is None:
            crs_data = {
                "type": "name",
                "properties": {
                    "name": "urn:ogc:def:crs:EPSG::2950"
                }
            }

        parcelle_features = []
        batiment_features = []

        for source_feature in geojson.get("features", []):
            feature = deepcopy(source_feature)
            props = feature.setdefault("properties", {})
            feature_type = str(props.get("Type", "")).strip().lower()

            zone, function_type = get_zone_and_function_from_feature(props)

            if zone:
                props["Zone"] = zone
            if function_type:
                props["FunctionType"] = function_type

            key = (zone, function_type)

            if key in lookup:
                row_data = lookup[key]

                if feature_type == "parcelle":
                    add_csv_attributes_to_feature(props, row_data, "parcelle")
                elif feature_type == "batiment":
                    add_csv_attributes_to_feature(props, row_data, "batiment")
            else:
                props["CsvMatchStatus"] = "unmatched"

            if feature_type == "parcelle":
                parcelle_features.append(feature)
            elif feature_type == "batiment":
                batiment_features.append(feature)

        assign_parcel_pids(parcelle_features)
        assign_building_bids(batiment_features)
        assign_buildings_to_parcels(batiment_features, parcelle_features)

        parcelle_geojson = build_output_geojson(
            source_geojson=geojson,
            output_name="parcelle",
            features=parcelle_features,
            crs_data=crs_data,
        )

        batiment_geojson = build_output_geojson(
            source_geojson=geojson,
            output_name="batiment",
            features=batiment_features,
            crs_data=crs_data,
        )

        st.session_state.parcelle_json = json.dumps(parcelle_geojson, indent=2)
        st.session_state.batiment_json = json.dumps(batiment_geojson, indent=2)

        st.success("Processing complete!")

if st.session_state.parcelle_json and st.session_state.batiment_json:
    col1, col2 = st.columns(2)

    with col1:
        st.download_button(
            "Download Parcelle GeoJSON",
            st.session_state.parcelle_json,
            "parcelle.geojson",
            "application/geo+json"
        )

    with col2:
        st.download_button(
            "Download Batiment GeoJSON",
            st.session_state.batiment_json,
            "batiment.geojson",
            "application/geo+json"
        )