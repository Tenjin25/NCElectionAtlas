import json

# Load and inspect the Voting_Precincts.geojson file
with open('data/Voting_Precincts.geojson', 'r') as f:
    data = json.load(f)

print(f"Type: {data['type']}")
print(f"Number of features: {len(data['features'])}")
print("\nFirst feature properties:")
for key in data['features'][0]['properties'].keys():
    print(f"  {key}")

print("\nSample feature properties:")
sample = data['features'][0]['properties']
for key, value in sample.items():
    print(f"  {key}: {value}")
