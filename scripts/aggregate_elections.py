"""
Aggregate all individual race JSON files into a single nc_elections_aggregated.json file.
"""
import json
import os
from pathlib import Path

def aggregate_elections():
    # Define the data directory
    data_dir = Path(__file__).parent.parent / "data"
    
    # List of race files to aggregate
    race_files = [
        "nc_president.json",
        "nc_governor.json",
        "nc_attorney_general.json",
        "nc_us_senate.json",
        "nc_lieutenant_governor.json",
        "nc_secretary_of_state.json",
        "nc_auditor.json",
        "nc_superintendent.json",
        "nc_agriculture_commissioner.json",
        "nc_insurance_commissioner.json",
        "nc_labor_commissioner.json"
    ]
    
    # Initialize the aggregated structure
    aggregated = {
        "results_by_year": {}
    }
    
    # Process each race file
    for race_file in race_files:
        file_path = data_dir / race_file
        
        if not file_path.exists():
            print(f"Warning: {race_file} not found, skipping...")
            continue
        
        print(f"Processing {race_file}...")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            race_data = json.load(f)
        
        # Merge the results_by_year from each file
        if "results_by_year" in race_data:
            for year, year_data in race_data["results_by_year"].items():
                if year not in aggregated["results_by_year"]:
                    aggregated["results_by_year"][year] = {}
                
                # Merge the race data for this year
                for race_type, race_info in year_data.items():
                    aggregated["results_by_year"][year][race_type] = race_info
    
    # Write the aggregated file
    output_path = data_dir / "nc_elections_aggregated.json"
    print(f"\nWriting aggregated data to {output_path}...")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(aggregated, f, indent=2)
    
    print(f"✓ Successfully created {output_path}")
    
    # Print summary
    print("\nSummary:")
    for year in sorted(aggregated["results_by_year"].keys()):
        races = list(aggregated["results_by_year"][year].keys())
        print(f"  {year}: {len(races)} races - {', '.join(races)}")

if __name__ == "__main__":
    aggregate_elections()
