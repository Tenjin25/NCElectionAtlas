"""
Process OpenElections CSV format into separate JSON files by office (OPTIMIZED)
"""
import pandas as pd
import json
from pathlib import Path
from collections import defaultdict

def calculate_competitiveness(margin_pct):
    """Calculate competitiveness color based on margin percentage"""
    abs_margin = abs(margin_pct)
    if abs_margin < 0.5: return '#f7f7f7'  # Tossup
    
    if margin_pct > 0:  # Republican
        if abs_margin >= 40: return '#67000d'
        elif abs_margin >= 30: return '#a50f15'
        elif abs_margin >= 20: return '#cb181d'
        elif abs_margin >= 10: return '#ef3b2c'
        elif abs_margin >= 5.5: return '#fb6a4a'
        elif abs_margin >= 1.0: return '#fcae91'
        else: return '#fee8c8'
    else:  # Democrat
        if abs_margin >= 40: return '#08306b'
        elif abs_margin >= 30: return '#08519c'
        elif abs_margin >= 20: return '#3182bd'
        elif abs_margin >= 10: return '#6baed6'
        elif abs_margin >= 5.5: return '#9ecae1'
        elif abs_margin >= 1.0: return '#c6dbef'
        else: return '#e1f5fe'

def normalize_office_name(office):
    """Normalize office names to keys"""
    office_lower = office.lower()
    if 'president' in office_lower: return 'president'
    elif 'governor' in office_lower and 'lieutenant' not in office_lower: return 'governor'
    elif 'lieutenant' in office_lower: return 'lieutenant_governor'
    elif 'attorney' in office_lower: return 'attorney_general'
    elif 'auditor' in office_lower: return 'auditor'
    elif 'agriculture' in office_lower: return 'agriculture_commissioner'
    elif 'labor' in office_lower: return 'labor_commissioner'
    elif 'insurance' in office_lower: return 'insurance_commissioner'
    elif 'secretary' in office_lower: return 'secretary_of_state'
    elif 'treasurer' in office_lower: return 'treasurer'
    elif 'superintendent' in office_lower or 'instruction' in office_lower: return 'superintendent'
    elif 'senate' in office_lower and 'u.s' in office_lower: return 'us_senate'
    else: return office_lower.replace(' ', '_').replace('.', '')

def process_year(filepath, year):
    """Process one year of election data"""
    print(f"\nProcessing {year}...")
    df = pd.read_csv(filepath)
    
    # Filter for key statewide races
    key_offices = [
        'President', 'Governor', 'Lieutenant Governor', 'U.S. Senate',
        'Attorney General', 'State Auditor', 'Commissioner of Agriculture',
        'Commissioner of Labor', 'Commissioner of Insurance', 'Secretary of State',
        'State Treasurer', 'Superintendent of Public Instruction'
    ]
    df = df[df['office'].isin(key_offices)].copy()
    print(f"  {len(df):,} rows, {df['precinct'].nunique()} precincts, {df['office'].nunique()} offices")
    
    # Use pivot-style aggregation for speed
    results_by_office = {}
    
    for office in df['office'].unique():
        office_df = df[df['office'] == office].copy()
        office_key = normalize_office_name(office)
        
        # Aggregate by county/precinct/party
        agg_df = office_df.groupby(['county', 'precinct', 'party'])['votes'].sum().reset_index()
        pivot_df = agg_df.pivot_table(index=['county', 'precinct'], columns='party', values='votes', fill_value=0).reset_index()
        
        # Get candidates
        cand_df = office_df.groupby(['county', 'precinct', 'party'])['candidate'].first().reset_index()
        cand_pivot = cand_df.pivot_table(index=['county', 'precinct'], columns='party', values='candidate', aggfunc='first', fill_value='').reset_index()
        
        # Merge
        merged = pivot_df.merge(cand_pivot, on=['county', 'precinct'], suffixes=('_votes', '_cand'))
        
        # Calculate margins
        merged['dem_votes'] = merged.get('DEM_votes', 0)
        merged['rep_votes'] = merged.get('REP_votes', 0)
        merged['other_votes'] = merged.drop(columns=['county', 'precinct', 'DEM_votes', 'REP_votes'], errors='ignore').select_dtypes(include='number').sum(axis=1)
        merged['total_votes'] = merged[['dem_votes', 'rep_votes', 'other_votes']].sum(axis=1)
        merged['margin'] = merged['rep_votes'] - merged['dem_votes']
        merged['margin_pct'] = (merged['margin'] / merged['total_votes'].replace(0, 1)) * 100
        merged['winner'] = merged['margin'].apply(lambda x: 'REP' if x > 0 else 'DEM' if x < 0 else 'TIE')
        merged['color'] = merged['margin_pct'].apply(calculate_competitiveness)
        merged['dem_candidate'] = merged.get('DEM_cand', '')
        merged['rep_candidate'] = merged.get('REP_cand', '')
        
        # Build results dict
        office_results = {}
        for _, row in merged.iterrows():
            precinct_name = f"{row['county']} - {row['precinct']}"
            office_results[precinct_name] = {
                'dem_votes': int(row['dem_votes']),
                'rep_votes': int(row['rep_votes']),
                'other_votes': int(row['other_votes']),
                'total_votes': int(row['total_votes']),
                'dem_candidate': str(row['dem_candidate']),
                'rep_candidate': str(row['rep_candidate']),
                'margin': int(row['margin']),
                'margin_pct': round(float(row['margin_pct']), 2),
                'winner': row['winner'],
                'competitiveness': {'color': row['color']}
            }
        
        results_by_office[office_key] = {'general': {'results': office_results}}
        print(f"    ✓ {office}: {len(office_results)} precincts")
    
    return results_by_office

def main():
    data_dir = Path('data')
    
    files = [
        ('20201103__nc__general__precinct.csv', '2020'),
        ('20221108__nc__general__precinct.csv', '2022'),
        ('20241105__nc__general__precinct.csv', '2024')
    ]
    
    all_results = {}
    for filename, year in files:
        filepath = data_dir / filename
        if filepath.exists():
            all_results[year] = process_year(filepath, year)
    
    # Save separate JSON per office
    print("\n" + "="*60)
    print("Creating JSON files by office...")
    print("="*60)
    
    all_offices = set()
    for year_data in all_results.values():
        all_offices.update(year_data.keys())
    
    for office in sorted(all_offices):
        office_data = {'results_by_year': {}}
        for year in sorted(all_results.keys()):
            if office in all_results[year]:
                office_data['results_by_year'][year] = {office: all_results[year][office]}
        
        output_path = data_dir / f'nc_{office}.json'
        with open(output_path, 'w') as f:
            json.dump(office_data, f, indent=2)
        
        file_size_kb = output_path.stat().st_size / 1024
        precinct_count = len(all_results[list(all_results.keys())[0]].get(office, {}).get('general', {}).get('results', {}))
        print(f"✓ {office:25} → {output_path.name:30} ({file_size_kb:7.1f} KB)")
    
    print("="*60)
    print(f"Complete! {len(all_offices)} JSON files created")
    print("="*60)

if __name__ == '__main__':
    main()
