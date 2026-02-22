"""Quick test of OpenElections processing"""
import pandas as pd

# Test reading one file
df = pd.read_csv('data/20241105__nc__general__precinct.csv')
print(f"Total rows: {len(df)}")
print(f"Columns: {df.columns.tolist()}")
print(f"\nOffices: {df['office'].nunique()}")
print(f"\nSample offices:")
print(df['office'].value_counts().head(20))

# Filter for key statewide
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

df_filtered = df[df['office'].isin(key_offices)]
print(f"\nFiltered rows: {len(df_filtered)}")
print(f"Filtered offices: {df_filtered['office'].unique()}")
print(f"Precincts: {df_filtered['precinct'].nunique()}")
