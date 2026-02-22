"""
Convert NC precinct election results to OpenElections CSV format
Standard format: county,precinct,office,district,party,candidate,votes
"""
import pandas as pd
from pathlib import Path

def convert_to_openelections(input_file, output_file):
    """Convert NC results file to OpenElections format"""
    print(f"Processing {input_file}...")
    
    # Read the tab-separated file
    df = pd.read_csv(input_file, sep='\t', low_memory=False)
    
    # Filter for statewide contests only (Contest Type = 'S')
    df = df[df['Contest Type'] == 'S'].copy()
    
    # Standardize office names
    office_mapping = {
        'US PRESIDENT': 'President',
        'NC GOVERNOR': 'Governor',
        'NC LIEUTENANT GOVERNOR': 'Lieutenant Governor',
        'NC ATTORNEY GENERAL': 'Attorney General',
        'NC AUDITOR': 'State Auditor',
        'NC COMMISSIONER OF AGRICULTURE': 'Commissioner of Agriculture',
        'NC COMMISSIONER OF LABOR': 'Commissioner of Labor',
        'NC COMMISSIONER OF INSURANCE': 'Commissioner of Insurance',
        'NC SECRETARY OF STATE': 'Secretary of State',
        'NC STATE TREASURER': 'State Treasurer',
        'NC SUPERINTENDENT OF PUBLIC INSTRUCTION': 'Superintendent of Public Instruction',
        'US SENATE': 'U.S. Senate',
        'US SENATOR': 'U.S. Senate'
    }
    
    # Create OpenElections format dataframe
    openelections_data = []
    
    for _, row in df.iterrows():
        county = row['County']
        precinct = row['Precinct']
        contest = row['Contest Name']
        office = office_mapping.get(contest, contest)
        party = row['Choice Party'] if pd.notna(row['Choice Party']) else ''
        candidate = row['Choice']
        votes = row['Total Votes']
        
        # Skip if no votes
        if pd.isna(votes) or votes == 0:
            continue
        
        openelections_data.append({
            'county': county,
            'precinct': precinct,
            'office': office,
            'district': '',  # Statewide contests have no district
            'party': party,
            'candidate': candidate,
            'votes': int(votes)
        })
    
    # Create DataFrame and save
    result_df = pd.DataFrame(openelections_data)
    result_df = result_df.sort_values(['county', 'precinct', 'office', 'party'])
    
    print(f"Saving to {output_file}...")
    result_df.to_csv(output_file, index=False)
    
    print(f"✓ Converted {len(df)} rows to {len(result_df)} OpenElections records")
    print(f"  Counties: {result_df['county'].nunique()}")
    print(f"  Precincts: {result_df['precinct'].nunique()}")
    print(f"  Offices: {result_df['office'].nunique()}")
    
    return result_df

def main():
    data_dir = Path('data')
    
    # Convert each election year
    conversions = [
        ('results_pct_20201103.txt', '20201103__nc__general__precinct.csv'),
        ('results_pct_20221108.txt', '20221108__nc__general__precinct.csv'),
        ('results_pct_20241105.txt', '20241105__nc__general__precinct.csv')
    ]
    
    for input_file, output_file in conversions:
        input_path = data_dir / input_file
        output_path = data_dir / output_file
        
        if input_path.exists():
            df = convert_to_openelections(input_path, output_path)
            print(f"✓ Saved: {output_path}\n")
        else:
            print(f"⚠ File not found: {input_path}\n")
    
    print("=" * 60)
    print("Conversion complete! OpenElections CSV files created.")

if __name__ == '__main__':
    main()
