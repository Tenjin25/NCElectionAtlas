"""
Add county names to NC precinct GeoJSON NAME20 field
"""
import json

# NC County FIPS codes to names
NC_COUNTY_FIPS = {
    "001": "ALAMANCE", "003": "ALEXANDER", "005": "ALLEGHANY", "007": "ANSON",
    "009": "ASHE", "011": "AVERY", "013": "BEAUFORT", "015": "BERTIE",
    "017": "BLADEN", "019": "BRUNSWICK", "021": "BUNCOMBE", "023": "BURKE",
    "025": "CABARRUS", "027": "CALDWELL", "029": "CAMDEN", "031": "CARTERET",
    "033": "CASWELL", "035": "CATAWBA", "037": "CHATHAM", "039": "CHEROKEE",
    "041": "CHOWAN", "043": "CLAY", "045": "CLEVELAND", "047": "COLUMBUS",
    "049": "CRAVEN", "051": "CUMBERLAND", "053": "CURRITUCK", "055": "DARE",
    "057": "DAVIDSON", "059": "DAVIE", "061": "DUPLIN", "063": "DURHAM",
    "065": "EDGECOMBE", "067": "FORSYTH", "069": "FRANKLIN", "071": "GASTON",
    "073": "GATES", "075": "GRAHAM", "077": "GRANVILLE", "079": "GREENE",
    "081": "GUILFORD", "083": "HALIFAX", "085": "HARNETT", "087": "HAYWOOD",
    "089": "HENDERSON", "091": "HERTFORD", "093": "HOKE", "095": "HYDE",
    "097": "IREDELL", "099": "JACKSON", "101": "JOHNSTON", "103": "JONES",
    "105": "LEE", "107": "LENOIR", "109": "LINCOLN", "111": "MCDOWELL",
    "113": "MACON", "115": "MADISON", "117": "MARTIN", "119": "MECKLENBURG",
    "121": "MITCHELL", "123": "MONTGOMERY", "125": "MOORE", "127": "NASH",
    "129": "NEW HANOVER", "131": "NORTHAMPTON", "133": "ONSLOW", "135": "ORANGE",
    "137": "PAMLICO", "139": "PASQUOTANK", "141": "PENDER", "143": "PERQUIMANS",
    "145": "PERSON", "147": "PITT", "149": "POLK", "151": "RANDOLPH",
    "153": "RICHMOND", "155": "ROBESON", "157": "ROCKINGHAM", "159": "ROWAN",
    "161": "RUTHERFORD", "163": "SAMPSON", "165": "SCOTLAND", "167": "STANLY",
    "169": "STOKES", "171": "SURRY", "173": "SWAIN", "175": "TRANSYLVANIA",
    "177": "TYRRELL", "179": "UNION", "181": "VANCE", "183": "WAKE",
    "185": "WARREN", "187": "WASHINGTON", "189": "WATAUGA", "191": "WAYNE",
    "193": "WILKES", "195": "WILSON", "197": "YADKIN", "199": "YANCEY"
}

def fix_geojson():
    print("Loading GeoJSON...")
    with open('data/nc_precincts.geojson', 'r', encoding='utf-8') as f:
        geojson = json.load(f)
    
    print(f"Processing {len(geojson['features'])} features...")
    
    fixed_count = 0
    skipped_count = 0
    
    for feature in geojson['features']:
        props = feature['properties']
        county_fips = props.get('COUNTYFP20', '')
        precinct_id = props.get('NAME20', '')
        
        if county_fips in NC_COUNTY_FIPS:
            county_name = NC_COUNTY_FIPS[county_fips]
            # Create new name matching election data format: "COUNTY - PRECINCT"
            new_name = f"{county_name} - {precinct_id}"
            props['NAME20'] = new_name
            fixed_count += 1
        else:
            skipped_count += 1
            print(f"Warning: Unknown county FIPS {county_fips} for precinct {precinct_id}")
    
    print(f"\nFixed {fixed_count} precincts")
    print(f"Skipped {skipped_count} precincts")
    
    # Save back to file
    print("\nSaving updated GeoJSON...")
    with open('data/nc_precincts.geojson', 'w', encoding='utf-8') as f:
        json.dump(geojson, f)
    
    print("✓ GeoJSON updated successfully!")
    
    # Show a sample
    print("\nSample of first 3 fixed precincts:")
    for i in range(min(3, len(geojson['features']))):
        print(f"  {geojson['features'][i]['properties']['NAME20']}")

if __name__ == "__main__":
    fix_geojson()
