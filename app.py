import streamlit as st
import geopandas as gpd
import pandas as pd
import zipfile
import tempfile
import os

st.title("Address Grouping Tool")
st.write("Upload your GDB zip file to generate a grouped address spreadsheet.")

uploaded_zip = st.file_uploader("Upload .zip file containing your .gdb folder", type="zip")

if uploaded_zip is not None:
    if st.button("Process File"):
        with st.spinner("Processing..."):
            # Create a temporary folder to extract into
            temp_dir = tempfile.mkdtemp()

            # Save uploaded zip to disk temporarily
            zip_path = os.path.join(temp_dir, "upload.zip")
            with open(zip_path, "wb") as f:
                f.write(uploaded_zip.getbuffer())

            # Extract zip
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find the .gdb folder inside extracted contents
            gdb_path = None
            for root, dirs, files in os.walk(temp_dir):
                for d in dirs:
                    if d.endswith(".gdb"):
                        gdb_path = os.path.join(root, d)
                        break
                if gdb_path:
                    break

            if gdb_path is None:
                st.error("No .gdb folder found inside the zip file.")
            else:
                try:
                    # Load both layers
                    addresses = gpd.read_file(gdb_path, layer="ADDRESS", engine="pyogrio")
                    boundaries = gpd.read_file(gdb_path, layer="NAP_BOUNDARY", engine="pyogrio")

                    # Match coordinate systems
                    if addresses.crs != boundaries.crs:
                        addresses = addresses.to_crs(boundaries.crs)

                    # Spatial join: tag each address with the boundary it falls inside
                    joined = gpd.sjoin(addresses, boundaries, how="left", predicate="within")

                    # Build grouped summary: combine house numbers per street, per boundary
                    summary_source = joined[['areaname', 'street_name', 'house_number']].copy()
                    summary_source['house_number_numeric'] = pd.to_numeric(
                        summary_source['house_number'], errors='coerce'
                    )
                    summary_source = summary_source.sort_values(
                        ['areaname', 'street_name', 'house_number_numeric']
                    )

                    def combine_addresses(group):
                        numbers = group['house_number'].astype(str).tolist()
                        street = group.name[1]  # group.name is (areaname, street_name) tuple
                        return f"{', '.join(numbers)} {street}"

                    grouped = (
                        summary_source.groupby(['areaname', 'street_name'])
                        .apply(combine_addresses)
                        .reset_index(name='combined_address')
                    )

                    final_summary = (
                        grouped.groupby('areaname')['combined_address']
                        .apply(lambda x: ', '.join(x))
                        .reset_index()
                    )

                    # Prepare detail sheet
                    export_df = joined.drop(columns="geometry")
                    for col in export_df.columns:
                        if pd.api.types.is_datetime64_any_dtype(export_df[col]):
                            export_df[col] = export_df[col].dt.tz_localize(None)

                    # Write both sheets to an Excel file
                    output_path = os.path.join(temp_dir, "output.xlsx")
                    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                        export_df.to_excel(writer, sheet_name='Detail', index=False)
                        final_summary.to_excel(writer, sheet_name='Grouped Summary', index=False)

                    st.success(f"Done! {len(addresses)} addresses matched to {len(boundaries)} boundaries.")

                    # Let user download the result
                    with open(output_path, "rb") as f:
                        st.download_button(
                            label="Download Output Excel File",
                            data=f,
                            file_name="output.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )

                    st.dataframe(final_summary)

                except Exception as e:
                    st.error(f"Error processing file: {e}")
