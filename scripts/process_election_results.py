"""
Process NC precinct election results into aggregated JSON format
"""
import pandas as pd
import json
from pathlib import Path

def calculate_competitiveness(margin_pct):
    """
    Calculate competitiveness color based on margin percentage
    Republican (positive) and Democrat (negative) margins
    Matches legend thresholds exactly
    """
    abs_margin = abs(margin_pct)
    
    # Tossup if margin is less than 0.5%
    if abs_margin < 0.5:
        return '#f7f7f7'  # Tossup
    
    if margin_pct > 0:  # Republican win
        if abs_margin >= 40: return '#67000d'  # Annihilation R (40%+)
        elif abs_margin >= 30: return '#a50f15'  # Dominant R (30.00-39.99%)
        elif abs_margin >= 20: return '#cb181d'  # Stronghold R (20.00-29.99%)
        elif abs_margin >= 10: return '#ef3b2c'  # Safe R (10.00-19.99%)
        elif abs_margin >= 5.5: return '#fb6a4a'   # Likely R (5.50-9.99%)
        elif abs_margin >= 1.0: return '#fcae91' # Lean R (1.00-5.49%)
        else: return '#fee8c8'                   # Tilt R (0.50-0.99%)
    else:  # Democrat win
        if abs_margin >= 40: return '#08306b'    # Annihilation D (40%+)
        elif abs_margin >= 30: return '#08519c'  # Dominant D (30.00-39.99%)
        elif abs_margin >= 20: return '#3182bd'  # Stronghold D (20.00-29.99%)
        elif abs_margin >= 10: return '#6baed6'  # Safe D (10.00-19.99%)
        elif abs_margin >= 5.5: return '#9ecae1'   # Likely D (5.50-9.99%)
        elif abs_margin >= 1.0: return '#c6dbef' # Lean D (1.00-5.49%)
        else: return '#e1f5fe'                   # Tilt D (0.50-0.99%)

def extract_year_from_date(date_str):
    """Extract year from date string like '11/05/2024'"""
    return date_str.split('/')[-1]

def process_election_file(filepath):
    """Process a single election results file"""
    print(f"Processing {filepath}...")
    
    # Read tab-separated file
    df = pd.read_csv(filepath, sep='\t', low_memory=False)
    
    # Filter for statewide contests only
    statewide_contests = [
        'US PRESIDENT',
        'NC GOVERNOR',
        'NC LIEUTENANT GOVERNOR',
        'NC ATTORNEY GENERAL',
        'NC AUDITOR',
        'NC COMMISSIONER OF AGRICULTURE',
        'NC COMMISSIONER OF LABOR',
        'NC COMMISSIONER OF INSURANCE',
        'NC SECRETARY OF STATE',
        'NC STATE TREASURER',
        'NC SUPERINTENDENT OF PUBLIC INSTRUCTION',
        'US SENATOR',
        'US SENATE'
    ]
    
    # Filter for statewide contests
    df = df[df['Contest Type'] == 'S'].copy()
    df = df[df['Contest Name'].isin(statewide_contests)]
    
    # Extract year
    df['Year'] = df['Election Date'].apply(extract_year_from_date)
    
    # Create unique precinct identifier (County + Precinct)
    df['PrecinctID'] = df['County'].astype(str) + '_' + df['Precinct'].astype(str)
    
    # Group by precinct, contest, and aggregate by party
    results = {}
    
    for (year, contest, precinct_id, county, precinct), group in df.groupby(
        ['Year', 'Contest Name', 'PrecinctID', 'County', 'Precinct']
    ):
        # Sum votes by party
        dem_votes = group[group['Choice Party'] == 'DEM']['Total Votes'].sum()
        rep_votes = group[group['Choice Party'] == 'REP']['Total Votes'].sum()
        other_votes = group[~group['Choice Party'].isin(['DEM', 'REP'])]['Total Votes'].sum()
        total_votes = dem_votes + rep_votes + other_votes
        
        # Get candidate names
        dem_candidates = group[group['Choice Party'] == 'DEM']['Choice'].tolist()
        rep_candidates = group[group['Choice Party'] == 'REP']['Choice'].tolist()
        dem_candidate = dem_candidates[0] if dem_candidates else ''
        rep_candidate = rep_candidates[0] if rep_candidates else ''
        
        # Calculate margin
        if total_votes > 0:
            margin = rep_votes - dem_votes
            margin_pct = (margin / total_votes) * 100
            winner = 'REP' if margin > 0 else 'DEM' if margin < 0 else 'TIE'
        else:
            margin = 0
            margin_pct = 0
            winner = 'N/A'
        
        # Normalize contest name for use as key
        contest_key = contest.lower().replace(' ', '_').replace('nc_', '').replace('us_', '')
        if 'president' in contest_key:
            contest_key = 'president'
        elif 'governor' in contest_key and 'lieutenant' not in contest_key:
            contest_key = 'governor'
        elif 'lieutenant' in contest_key:
            contest_key = 'lieutenant_governor'
        elif 'attorney' in contest_key:
            contest_key = 'attorney_general'
        elif 'auditor' in contest_key:
            contest_key = 'auditor'
        elif 'agriculture' in contest_key:
            contest_key = 'agriculture_commissioner'
        elif 'labor' in contest_key:
            contest_key = 'labor_commissioner'
        elif 'insurance' in contest_key:
            contest_key = 'insurance_commissioner'
        elif 'secretary' in contest_key:
            contest_key = 'secretary_of_state'
        elif 'treasurer' in contest_key:
            contest_key = 'treasurer'
        elif 'superintendent' in contest_key or 'instruction' in contest_key:
            contest_key = 'superintendent'
        elif 'senate' in contest_key or 'senator' in contest_key:
            contest_key = 'us_senate'
        
        # Store result
        if year not in results:
            results[year] = {}
        if contest_key not in results[year]:
            results[year][contest_key] = {}
        if 'general' not in results[year][contest_key]:
            results[year][contest_key]['general'] = {'results': {}}
        
        # Use a combined precinct name (County - Precinct)
        precinct_name = f"{county} - {precinct}"
        
        results[year][contest_key]['general']['results'][precinct_name] = {
            'dem_votes': int(dem_votes),
            'rep_votes': int(rep_votes),
            'other_votes': int(other_votes),
            'total_votes': int(total_votes),
            'dem_candidate': dem_candidate,
            'rep_candidate': rep_candidate,
            'margin': int(margin),
            'margin_pct': round(margin_pct, 2),
            'winner': winner,
            'competitiveness': {
                'color': calculate_competitiveness(margin_pct)
            }
        }
    
    return results

def main():
    # Process all election files
    data_dir = Path('data')
    election_files = [
        'results_pct_20201103.txt',
        'results_pct_20221108.txt',
        'results_pct_20241105.txt'
    ]
    
    all_results = {}
    
    for filename in election_files:
        filepath = data_dir / filename
        if filepath.exists():
            file_results = process_election_file(filepath)
            # Merge results
            for year, contests in file_results.items():
                if year not in all_results:
                    all_results[year] = {}
                for contest, data in contests.items():
                    all_results[year][contest] = data
    
    # Create final structure
    output = {
        'results_by_year': all_results
    }
    
    # Save to JSON
    output_path = data_dir / 'nc_elections_aggregated.json'
    print(f"\nSaving to {output_path}...")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Print summary
    print("\n=== Processing Complete ===")
    for year in sorted(all_results.keys()):
        contests = list(all_results[year].keys())
        num_precincts = len(all_results[year][contests[0]]['general']['results']) if contests else 0
        print(f"{year}: {len(contests)} contests, {num_precincts} precincts")
    
    print(f"\nOutput saved to: {output_path}")

if __name__ == '__main__':
    main()
