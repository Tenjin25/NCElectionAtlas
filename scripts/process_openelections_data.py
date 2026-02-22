"""
Process OpenElections CSV format into aggregated JSON for map visualization
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

def normalize_office_name(office):
    """Normalize office names to keys used by the map"""
    office_lower = office.lower()
    
    if 'president' in office_lower:
        return 'president'
    elif 'governor' in office_lower and 'lieutenant' not in office_lower:
        return 'governor'
    elif 'lieutenant' in office_lower:
        return 'lieutenant_governor'
    elif 'attorney' in office_lower:
        return 'attorney_general'
    elif 'auditor' in office_lower:
        return 'auditor'
    elif 'agriculture' in office_lower:
        return 'agriculture_commissioner'
    elif 'labor' in office_lower:
        return 'labor_commissioner'
    elif 'insurance' in office_lower:
        return 'insurance_commissioner'
    elif 'secretary' in office_lower:
        return 'secretary_of_state'
    elif 'treasurer' in office_lower:
        return 'treasurer'
    elif 'superintendent' in office_lower or 'instruction' in office_lower:
        return 'superintendent'
    elif 'senate' in office_lower:
        return 'us_senate'
    else:
        return office_lower.replace(' ', '_').replace('.', '')

def process_openelections_file(filepath, year):
    """Process a single OpenElections CSV file"""
    print(f"Processing {filepath} (year: {year})...")
    
    # Read CSV
    df = pd.read_csv(filepath)
    
    # Filter for only key statewide races
    key_offices = [
        'President',
        'Governor',
        'Lieutenant Governor',
        'U.S. Senate',
        'Attorney General',
        'State Auditor',
        'Commissioner of Agriculture',
        'Commissioner of Labor',
        'Commissioner of Insurance',
        'Secretary of State',
        'State Treasurer',
        'Superintendent of Public Instruction'
    ]
    
    df = df[df['office'].isin(key_offices)].copy()
    
    print(f"  Total rows (filtered): {len(df)}")
    print(f"  Offices: {df['office'].nunique()}")
    print(f"  Precincts: {df['precinct'].nunique()}")
    
    # Group by county, precinct, and office
    results = {}
    
    for (county, precinct, office), group in df.groupby(['county', 'precinct', 'office']):
        # Sum votes by party
        dem_votes = group[group['party'] == 'DEM']['votes'].sum()
        rep_votes = group[group['party'] == 'REP']['votes'].sum()
        other_votes = group[~group['party'].isin(['DEM', 'REP'])]['votes'].sum()
        total_votes = dem_votes + rep_votes + other_votes
        
        # Get candidate names
        dem_candidates = group[group['party'] == 'DEM']['candidate'].tolist()
        rep_candidates = group[group['party'] == 'REP']['candidate'].tolist()
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
        
        # Normalize office name
        office_key = normalize_office_name(office)
        
        # Store result
        if office_key not in results:
            results[office_key] = {}
        if 'general' not in results[office_key]:
            results[office_key]['general'] = {'results': {}}
        
        # Use combined precinct name (County - Precinct)
        precinct_name = f"{county} - {precinct}"
        
        results[office_key]['general']['results'][precinct_name] = {
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
    
    print(f"  ✓ Processed {len(results)} office types")
    return results

def main():
    data_dir = Path('data')
    
    # OpenElections files with their years
    election_files = [
        ('20201103__nc__general__precinct.csv', '2020'),
        ('20221108__nc__general__precinct.csv', '2022'),
        ('20241105__nc__general__precinct.csv', '2024')
    ]
    
    all_results = {}
    
    for filename, year in election_files:
        filepath = data_dir / filename
        if filepath.exists():
            year_results = process_openelections_file(filepath, year)
            all_results[year] = year_results
        else:
            print(f"⚠ File not found: {filepath}")
    
    # Create separate JSON file for each office
    print("\n" + "=" * 60)
    print("Creating separate JSON files by office...")
    print("=" * 60)
    
    # Collect all unique offices across all years
    all_offices = set()
    for year_data in all_results.values():
        all_offices.update(year_data.keys())
    
    total_size = 0
    
    for office in sorted(all_offices):
        # Create structure for this office across all years
        office_data = {
            'results_by_year': {}
        }
        
        for year in sorted(all_results.keys()):
            if office in all_results[year]:
                office_data['results_by_year'][year] = {
                    office: all_results[year][office]
                }
        
        # Save to separate JSON file
        output_filename = f'nc_{office}.json'
        output_path = data_dir / output_filename
        
        with open(output_path, 'w') as f:
            json.dump(office_data, f, indent=2)
        
        # Get file size
        import os
        file_size_kb = os.path.getsize(output_path) / 1024
        total_size += file_size_kb
        
        # Count precincts for first available year
        precinct_count = 0
        for year in sorted(all_results.keys()):
            if office in all_results[year]:
                precinct_count = len(all_results[year][office]['general']['results'])
                break
        
        print(f"✓ {office:30} → {output_filename:40} ({file_size_kb:6.1f} KB, {precinct_count} precincts)")
    
    # Print summary
    print("=" * 60)
    print(f"Total files: {len(all_offices)}")
    print(f"Total size: {total_size / 1024:.2f} MB")
    print("=" * 60)

if __name__ == '__main__':
    main()
