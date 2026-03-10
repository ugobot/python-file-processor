import streamlit as st
import pandas as pd
import json
import re

st.title("GeoJSON Processeur")

csv_file = st.file_uploader("Upload CSV file", type=["csv"])
geojson_file = st.file_uploader("Upload GeoJSON file", type=["geojson","json"])

# Initialize session state
if "parcelle_json" not in st.session_state:
    st.session_state.parcelle_json = None

if "batiment_json" not in st.session_state:
    st.session_state.batiment_json = None


if st.button("Start Processing"):

    if csv_file is None or geojson_file is None:
        st.warning("Please upload both files.")
        st.stop()

    with st.spinner("Processing..."):

        # Read CSV
        df = pd.read_csv(csv_file)

        # Clean column names (removes accidental spaces)
        df.columns = df.columns.str.strip()

        # Create lookup table
        lookup = {
            (row["Zone"], row["Function"]): {
                "Type": row["Type"],
                "TaxationRevenue": row["TaxationRevenue_Land($/m2)"]
            }
            for _, row in df.iterrows()
        }

        # Load GeoJSON
        geojson = json.load(geojson_file)

        # Extract CRS if present
        crs_data = geojson.get("crs")

        # If CRS missing, create default EPSG:2950
        if crs_data is None:
            crs_data = {
                "type": "name",
                "properties": {
                    "name": "urn:ogc:def:crs:EPSG::2950"
                }
            }

        parcelle_features = []
        batiment_features = []

        for feature in geojson.get("features", []):

            props = feature.get("properties", {})

            func_value = props.get("Function", "")

            match = re.match(r"(Zone\d+)(Function\d+)", func_value)

            if match:
                zone = match.group(1)
                function_type = match.group(2)
            else:
                zone = None
                function_type = None

            props["Zone"] = zone
            props["FunctionType"] = function_type

            key = (zone, function_type)

            if key in lookup:

                props["TypeF"] = lookup[key]["Type"]

                if props.get("Type") == "Parcelle":
                    props["TaxationRevenue"] = lookup[key]["TaxationRevenue"]

            if props.get("Type") == "Parcelle":
                parcelle_features.append(feature)

            elif props.get("Type") == "Batiment":
                batiment_features.append(feature)

        # Build Parcelle GeoJSON
        parcelle_geojson = {
            "type": "FeatureCollection",
            "name": "parcelle",
            "crs": crs_data,
            "features": parcelle_features
        }

        # Build Batiment GeoJSON
        batiment_geojson = {
            "type": "FeatureCollection",
            "name": "batiment",
            "crs": crs_data,
            "features": batiment_features
        }

        # Save results
        st.session_state.parcelle_json = json.dumps(parcelle_geojson, indent=2)
        st.session_state.batiment_json = json.dumps(batiment_geojson, indent=2)

        st.success("Processing complete!")

# Download buttons
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