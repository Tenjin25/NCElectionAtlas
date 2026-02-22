"""
Convert NC VTD Shapefile to GeoJSON for web mapping
"""
import geopandas as gpd
import json

# Read the shapefile
print("Reading shapefile...")
gdf = gpd.read_file('data/nc_vtd/tl_2020_37_vtd20.shp')

# Reproject to WGS84 (EPSG:4326) for web mapping
print("Reprojecting to WGS84...")
gdf = gdf.to_crs(epsg=4326)

# Display info about the data
print(f"\nTotal precincts: {len(gdf)}")
print(f"\nColumn names: {list(gdf.columns)}")
print(f"\nFirst few rows:")
print(gdf.head())

# Simplify geometry to reduce file size (optional, adjust tolerance as needed)
print("\nSimplifying geometry...")
gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.0001, preserve_topology=True)

# Save as GeoJSON
output_path = 'data/nc_precincts.geojson'
print(f"\nSaving to {output_path}...")
gdf.to_file(output_path, driver='GeoJSON')

print("\nConversion complete!")
print(f"File saved: {output_path}")

# Display file size
import os
file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
print(f"File size: {file_size_mb:.2f} MB")
