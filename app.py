import streamlit as st
import pandas as pd
import json
import re
from copy import deepcopy

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


# Shared by both parcel and building because they describe the zoning/function context.
COMMON_FIELDS = {
    "Zone",
    "ZoneMinArea",
    "Function",
    "FunctionMinArea",
    "Type",
    "FunctionColor",
}



def target_output_key(field_name):
    """
    Avoid overwriting existing GeoJSON keys like Type and Function.
    Still enforce letters/digits/underscore output names.
    """
    reserved_map = {
        "Zone": "CsvZone",
        "Function": "CsvFunction",
        "Type": "CsvType",
    }
    if field_name in reserved_map:
        return reserved_map[field_name]
    return sanitize_attribute_name(field_name)


# Parcel / land fields.
PARCEL_FIELDS = {
    "MaxFootprint (%)",
    "TaxationRevenue_Land($/m2)",
    "MinGreenArea (%)",
    "OffsetInnerPlot",
}

# Building fields.
BUILDING_FIELDS = {
    "TaxationRevenue_Building($/m2)",
    "MaxHeight",
    "MaxFAR",
    "ParkingDensity (Slot/Unit)",
    "MaxOccupancyRatio (People/Unit)",
    "UndergroundParking(Y/N)",
    "AverageUnitDimension",
}



def classify_csv_field(field_name):
    if field_name in COMMON_FIELDS:
        return "common"
    if field_name in PARCEL_FIELDS:
        return "parcelle"
    if field_name in BUILDING_FIELDS:
        return "batiment"

    # Fallback heuristics for future/unknown CSV columns.
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

    # Pattern used in the current workflow: Zone1Function2
    match = re.match(r"^(Zone\d+)(Function\d+)$", raw_function, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)

    # Fallback if Zone and Function are already stored separately.
    separate_zone = raw_zone if re.match(r"^Zone\d+$", raw_zone, re.IGNORECASE) else None
    separate_function = raw_function if re.match(r"^Function\d+$", raw_function, re.IGNORECASE) else None

    return separate_zone, separate_function



def add_csv_attributes_to_feature(props, row_data, feature_kind):
    """
    Add only relevant attributes from the CSV.
    Original feature properties are preserved; only new/enriched fields are added.
    """
    for field, value in row_data.items():
        value = clean_value(value)
        if value is None:
            continue

        field_scope = classify_csv_field(field)
        if field_scope not in ("common", feature_kind):
            continue

        output_key = target_output_key(field)
        props[output_key] = value

    # Optional generic taxation field for downstream compatibility
    if feature_kind == "parcelle" and clean_value(row_data.get("TaxationRevenue_Land($/m2)")) is not None:
        props["TaxationRevenue"] = row_data["TaxationRevenue_Land($/m2)"]
    elif feature_kind == "batiment" and clean_value(row_data.get("TaxationRevenue_Building($/m2)")) is not None:
        props["TaxationRevenue"] = row_data["TaxationRevenue_Building($/m2)"]



def build_output_geojson(source_geojson, output_name, features, crs_data):
    """
    Preserve any extra top-level attributes from the input GeoJSON
    (for example metadata fields), while replacing the feature list and name.
    """
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


if st.button("Start Processing"):

    if csv_file is None or geojson_file is None:
        st.warning("Please upload both files.")
        st.stop()

    with st.spinner("Processing..."):

        df = pd.read_csv(csv_file)

        # Remove junk unnamed columns
        df = df.loc[:, ~df.columns.astype(str).str.contains(r"^Unnamed", case=False, regex=True)]

        # Robust mapping from uploaded CSV headers
        column_mapping = build_column_mapping(df.columns)

        required = ["Zone", "Function", "Type"]
        missing = [col for col in required if col not in column_mapping]

        if missing:
            st.error(f"Missing required CSV columns: {missing}")
            st.stop()

        rename_map = {original: clean_name for clean_name, original in column_mapping.items()}
        df = df.rename(columns=rename_map)

        # Build row dictionaries using all recognized CSV columns
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

            # Keep all original feature attributes, geometry and any other keys,
            # then route the complete feature to the proper output.
            if feature_type == "parcelle":
                parcelle_features.append(feature)
            elif feature_type == "batiment":
                batiment_features.append(feature)

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