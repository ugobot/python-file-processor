# GeoJSON Processeur

A Streamlit app that enriches a GeoJSON file with zoning and function attributes from a CSV, then outputs two separate GeoJSON files:

- `parcelle.geojson`
- `batiment.geojson`

The app is designed to match CSV records to GeoJSON features using `Zone` and `Function`, then attach only the relevant attributes for each feature type.

---

## Features

- Upload a CSV file and a GeoJSON file through a simple Streamlit interface
- Normalizes and maps CSV column names automatically
- Matches CSV rows to GeoJSON features using:
  - `Zone`
  - `Function`
- Supports two output feature types:
  - `parcelle`
  - `batiment`
- Preserves:
  - original feature geometry
  - original feature properties
  - extra top-level GeoJSON metadata
- Splits processed features into two downloadable GeoJSON outputs
- Adds fallback CRS if missing

---

## How It Works

### 1. Upload files
The app requires:

- one CSV file
- one GeoJSON file

### 2. Read and clean the CSV
The CSV is loaded with pandas, and unnamed junk columns are removed.

The app then attempts to recognize and normalize expected columns such as:

- `Zone`
- `ZoneMinArea`
- `Function`
- `FunctionMinArea`
- `Type`
- `MaxFootprint (%)`
- `TaxationRevenue_Building($/m2)`
- `TaxationRevenue_Land($/m2)`
- `MaxHeight`
- `MaxFAR`
- `ParkingDensity (Slot/Unit)`
- `MaxOccupancyRatio (People/Unit)`
- `MinGreenArea (%)`
- `OffsetInnerPlot`
- `UndergroundParking(Y/N)`
- `AverageUnitDimension`
- `FunctionColor`

### 3. Match GeoJSON features
For each feature in the GeoJSON:

- the app reads `Type`
- extracts `Zone` and `FunctionType`
- matches them against the CSV row dictionary

The primary matching key is:

`(Zone, Function)`

### 4. Enrich feature properties
Depending on whether the feature is a `parcelle` or `batiment`, only relevant fields are added.

Common fields are shared across both.

### 5. Generate outputs
The app creates two separate GeoJSON outputs:

- one containing only `parcelle` features
- one containing only `batiment` features

Both files can then be downloaded from the interface.

---

## Expected GeoJSON Feature Properties

The app expects GeoJSON features to contain at least:

- `Type`
- `Function` and/or `Zone`

### Supported pattern
If the GeoJSON feature property `Function` follows this format:

`Zone1Function2`

the app automatically extracts:

- `Zone1` as `Zone`
- `Function2` as `FunctionType`

If `Zone` and `Function` are already stored separately, it will use those as a fallback.

---

## Field Classification

### Common fields
These may be added to both `parcelle` and `batiment` features:

- `Zone`
- `ZoneMinArea`
- `Function`
- `FunctionMinArea`
- `Type`
- `FunctionColor`

### Parcel fields
These are only added to `parcelle` features:

- `MaxFootprint (%)`
- `TaxationRevenue_Land($/m2)`
- `MinGreenArea (%)`
- `OffsetInnerPlot`

### Building fields
These are only added to `batiment` features:

- `TaxationRevenue_Building($/m2)`
- `MaxHeight`
- `MaxFAR`
- `ParkingDensity (Slot/Unit)`
- `MaxOccupancyRatio (People/Unit)`
- `UndergroundParking(Y/N)`
- `AverageUnitDimension`

---

## Special Output Behavior

### Reserved names are remapped
To avoid overwriting existing GeoJSON properties, some CSV fields are renamed in the output:

- `Zone` → `CsvZone`
- `Function` → `CsvFunction`
- `Type` → `CsvType`

### Generic taxation field
For compatibility, the app also adds:

- `TaxationRevenue` from `TaxationRevenue_Land($/m2)` for `parcelle`
- `TaxationRevenue` from `TaxationRevenue_Building($/m2)` for `batiment`

### Unmatched features
If a feature cannot be matched to a CSV row, the app adds:

`CsvMatchStatus = "unmatched"`

### CRS fallback
If the input GeoJSON has no `crs`, the app assigns:

`urn:ogc:def:crs:EPSG::2950`

---

## Requirements

Install the required Python packages:

```bash
pip install streamlit pandas

## To run the app
streamlit run app.py
Locally: python -m streamlit run app.py

## App link
https://montreal-est-geojson-process.streamlit.app/