/* eslint-disable no-console */
const fs = require('fs');
const path = require('path');

function toTitleCaseName(raw) {
  const s = String(raw || '').trim().toLowerCase();
  if (!s) return '';
  return s.replace(/\b([a-z])/g, (m, c) => c.toUpperCase());
}

function splitGluedDirectionSuffix(raw) {
  const s = String(raw || '').trim();
  if (!s) return '';
  // Keep true compass compounds intact.
  if (/^(north|south)(east|west)$/i.test(s)) return s;
  if (/^(east|west|north|south|central)$/i.test(s)) return s;
  return s.replace(
    /\b([A-Za-z]{3,}?)(east|west|north|south|central)\b/gi,
    (full, place, dir) => {
      const f = String(full || '').toLowerCase();
      if (['northeast', 'northwest', 'southeast', 'southwest'].includes(f)) return full;
      if (['east', 'west', 'north', 'south', 'central'].includes(f)) return full;
      return `${place} ${dir}`;
    }
  );
}

function formatDisplayName(raw) {
  let s = String(raw || '').trim();
  if (!s) return '';
  // HillsboroughEast / SHELBYEAST-style tokens from OE/geo.
  s = s.replace(/([a-z])([A-Z])/g, '$1 $2');
  s = splitGluedDirectionSuffix(s);
  s = toTitleCaseName(s);
  if (!s) return '';
  s = splitGluedDirectionSuffix(s);
  s = s.replace(/\b([A-Za-z]+)\s+(East|West|North|South|Central)\b/g, (full, place, dir) => `${place} ${dir}`);
  s = s.replace(/'S\b/g, "'s");
  s = s.replace(/\bMc([a-z])/g, (m, c) => `Mc${c.toUpperCase()}`);
  s = s.replace(/\bSt (?=[A-Z])/g, 'St. ');
  s = s.replace(/\bMt (?=[A-Z])/g, 'Mt. ');
  s = s.replace(/\bNw\b/g, 'NW');
  s = s.replace(/\bNe\b/g, 'NE');
  s = s.replace(/\bSe\b/g, 'SE');
  s = s.replace(/\bSw\b/g, 'SW');
  s = s.replace(/\bAme\b/g, 'AME');
  s = s.replace(/\bCme\b/g, 'CME');
  s = s.replace(/\bBt\b/g, 'BT');
  s = s.replace(/\bCfcc\b/g, 'CFCC');
  s = s.replace(/\bGtcc\b/g, 'GTCC');
  s = s.replace(/\bJr\b/g, 'JR');
  s = s.replace(/\bMlk\b/g, 'MLK');
  s = s.replace(/\bPca\b/g, 'PCA');
  s = s.replace(/\bPlc\b/g, 'PLC');
  s = s.replace(/\bIi\b/g, 'II');
  s = s.replace(/\bIii\b/g, 'III');
  s = s.replace(/\bIv\b/g, 'IV');
  s = s.replace(/\bUmc\b/g, 'UMC');
  s = s.replace(/\bUncg\b/g, 'UNCG');
  s = s.replace(/\bUncw\b/g, 'UNCW');
  s = s.replace(/\bVfd\b/g, 'VFD');
  s = s.replace(/\bNc A&T\b/g, 'NC A&T');
  return s;
}

function applyManualOverrides(counties) {
  const overrides = {
    ALLEGHANY: {
      '01': 'Cherry Lane',
      '03A': 'Gap Civil',
      '04': 'Glade Creek',
      '06A': 'Prathers Creek'
    },
    ASHE: {
      '13': 'Obids'
    },
    BEAUFORT: {
      GILEA: 'Gilead'
    },
    BERTIE: {
      RX: 'Roxobel',
      SN: 'Snakebite',
      WD: 'Woodville',
      WH: 'Whites'
    },
    CARTERET: {
      BCRK: 'Broad Creek',
      ISLE: 'Emerald Isle'
    },
    CHOWAN: {
      '1': 'East Edenton',
      '2': 'West Edenton',
      '3': 'Rocky Hock',
      '4': 'Center Hill',
      '5': 'Wardville',
      '6': 'Yeopim'
    },
    MADISON: {
      'EBBS C': 'Ebbs Chapel',
      'HOT SP': 'Hot Springs',
      'MARS H': 'Mars Hill'
    },
    CHEROKEE: {
      ANNW: 'Andrews North Ward',
      ANSW: 'Andrews South Ward',
      CSON: 'Culberson',
      GCRK: 'Grape Creek',
      HIWA: 'Hiwassee Dam',
      MARB: 'Marble',
      PCHT: 'Peachtree',
      RGER: 'Ranger',
      TOPT: 'Topton',
      UNKA: 'Unaka'
    },
    BRUNSWICK: {
      SB02: 'Boiling Spring Lakes',
      SB01: 'Bolivia',
      CB02: 'Shallotte',
      CB03: 'Frying Pan',
      WB06: 'Grissettown',
      NB02: 'Leland',
      WB03: 'Longwood',
      NB03: 'Town Creek',
      NB05: 'Woodburn',
      CB01: 'Supply',
      WB01: 'Waccamaw'
    },
    CASWELL: {
      PH: 'Prospect Hill',
      PROVI: 'Providence'
    },
    JACKSON: {
      SDC: 'Sylva South Ward'
    },
    LEE: {
      A1: 'Southern Lee High School',
      A2: 'J Glenn Edwards Elementary School',
      B1: 'Deep River Elementary School',
      B2: 'BT Bullock Elementary School',
      C1: 'Greenwood Elementary School',
      C2: 'Tramway Elementary School',
      D1: 'JR Ingram Elementary School',
      D2: 'American Legion',
      E1: 'Broadway Elementary School',
      E2: 'East Lee Middle School'
    },
    WAYNE: {
      '01': 'Fremont Town Hall',
      '02': 'Eureka Methodist Church',
      '03': 'Little River Fire Station',
      '04': 'Pikeville Fire Station',
      '05': 'Belfast Fire Department',
      '06': 'Crossway Church',
      '07': 'New Hope Fire Station',
      '08': 'Oakland Fire Station',
      '09': 'Westwood United Methodist Church',
      '10': 'Word Of Truth Christian Fellowship',
      '11': 'Greenleaf Christian Church',
      '12': 'Adamsville Baptist Church',
      '13': 'Central Heights Free Will Baptist Church',
      '14': 'New Hope Friends Church',
      '15': 'Seven Springs Baptist Church',
      '16': 'American Legion Post 11',
      '17': 'St. James AME Zion Church',
      '18': 'Wages Bldg',
      '1920': 'First African Baptist Church',
      '21': 'St. Luke United Methodist Church',
      '22': 'Faith Alliance Church',
      '23': 'The Hydrant Wesleyan Church',
      '24': 'Woodmenlife Lodge 481 Grantham',
      '2530': 'Steele Memorial Library',
      '26': 'Dudley Fire Station',
      '27': 'Mays Chapel Church',
      '28': 'Indian Springs Fire Station',
      '29': 'Wayne County Public Library'
    },
    SCOTLAND: {
      '01-16': 'Scotland County Annex',
      '02-25': 'South Johnson Elementary School Gym',
      '03': 'Scotland Place',
      '04': 'National Guard Armory',
      '05-10': 'Gibson Fire Station',
      '06-89': 'Laurel Hill Community Center',
      '07': 'Wagram Recreation Center'
    },
    CURRITUCK: {
      CO: 'Coinjock'
    },
    GREENE: {
      ARBA: 'Arba',
      MAUR: 'Maury',
      BEAR: 'Bear Gardens',
      BULL: 'Bull Head',
      CAST: 'Castoria',
      HOOK: 'Hookerton',
      'SH#1': 'Snow Hill',
      SHIN: 'Shine',
      SUGG: 'Sugg',
      WALS: 'Walstonburg'
    },
    GATES: {
      '1': 'Gates County Community Center',
      '2': 'Eure Fire Department',
      '3': 'Gates Fire Department',
      '4N': 'Sunbury Sub Station 2',
      '4S': 'Sunbury Fire Station',
      '5': 'Hobbsville Fire Department'
    },
    GUILFORD: {
      CG1: 'Bur-Mil Club',
      CG2: 'Jesse Wharton Elementary School',
      CG3A: 'Bass Chapel United Methodist Church',
      CG3B: 'Calvary Christian Center',
      FEN1: 'Brown Recreation Center',
      FEN2: 'Southeast Baptist Church',
      FR1: 'Unitarian Universalist Church',
      FR2: 'Jamestown Presbyterian Church',
      FR3: 'Collins Grove United Methodist Church',
      FR4: 'GTCC Ceasar Cone II Aviation Bldg',
      FR5A: 'Pearce Elementary School',
      FR5B: 'Mercy Hill Church',
      G01: 'Greensboro Farmers Curb Market',
      G02: 'Proximity United Methodist Church',
      G03: 'East White Oak Baptist Church',
      G04: 'Genesis Baptist Church',
      G05: 'Peeler Recreation Center',
      G06: 'Bessemer Elementary School',
      G07: 'Smith Senior Center',
      G08: 'Rankin Elementary School',
      G09: 'Craft Recreation Center',
      G10: 'White Oak Grove Baptist Church',
      G11: "St Benedict's Parish Center",
      G12: 'First Baptist Church - Greensboro',
      G13: 'First Friends Meeting',
      G14: 'St Andrews Episcopal Church',
      G15: 'Peace United Church of Christ',
      G16: 'Christ United Methodist Church - Greensboro',
      G17: 'Sternberger Elementary School',
      G18: 'Irving Park Elementary School',
      G19: 'Newlyn St United Methodist Church',
      G20: 'Page High School',
      G21: 'Mendenhall Middle School',
      G22: 'Irving Park United Methodist Church',
      G23: 'Lawndale Baptist Church',
      G24: 'Christ Lutheran Church',
      G25: 'Cathedral of His Glory',
      G26: 'Piedmont Classical High School',
      G27: 'Glenn McNairy Branch Library',
      G28: 'Covenant Grace Church',
      G29: 'Lewis Recreation Center',
      G30: 'Mt Pisgah Church',
      G31: 'General Greene Elementary School',
      G32: 'Claxton Elementary School',
      G33: 'First Lutheran Church',
      G34: 'Westminster Presbyterian Church',
      G35: 'Dormition of the Theotokos',
      G36: 'Morehead Elementary School',
      G37: 'Muirs Chapel United Methodist Church',
      G38: 'Friendly Ave Church of Christ',
      G39: 'Friendly Ave Baptist Church',
      G40A1: 'St Paul Catholic Church',
      G40A2: 'Kernodle Middle School',
      G40B: 'St Barnabas Episcopal Church',
      G41A: 'Guilford College United Methodist Church',
      G41B: 'Jefferson Elementary School',
      'G42-A': 'Faith Presbyterian Church',
      'G42-B': 'Friends Homes at Guilford',
      G43: 'Western Guilford High School',
      G44: 'Greensboro College Reynolds Center',
      G45: 'UNCG-Elliot University Center',
      G46: 'Warnersville Recreation Center',
      G47: 'Glenwood Presbyterian Church',
      G48: 'Lindley Recreation Center',
      G49: 'Cedar Grove Tabernacle of Praise',
      G50: "St John's United Methodist Church",
      G51: 'Glenwood Recreation Center',
      G52: 'Foust Elementary School',
      G53: 'East Market Seventh Day Adventist Church',
      G54: 'Southside Baptist Church',
      G55: 'Frazier Elementary School',
      G56: 'Mt Tabor United Methodist Church',
      G57: 'Allen Middle School',
      G58: 'Smith High School',
      G59: 'Hemphill Branch Library',
      G60: 'Lutheran Church of Our Father',
      G61: 'Alderman Elementary School',
      G62: 'Grace Life Church',
      G63: 'Emergency Services Training Room',
      G64: 'Guilford Baptist Church',
      G65: 'Pilot Elementary School',
      G66: 'Gate City Baptist Church',
      G67: 'Bethel AME Church',
      G68: 'NC A&T Academic Classroom',
      G69: 'Reid Memorial CME Church',
      G70: 'Washington Montessori School',
      G71: 'Mt Olivet AME Zion Church',
      G72: 'Hairston Middle School',
      G73: 'Trinity AME Zion Church',
      G74: 'Bluford Elementary School',
      G75: 'Mt Zion Baptist Church',
      GIB: 'Gibsonville Community Center',
      GR: 'Nathanael Greene Elementary School',
      H01: 'Hilliard Memorial Baptist Church',
      H02: 'Wesley Memorial Methodist Church',
      H03: 'Beloved Community UMC (The)',
      H04: 'Allen Jay Recreation Center',
      H05: 'Williams Memorial CME',
      H06: 'Bales Memorial Wesleyan Church',
      H07: 'Mt Calvary Holy Church',
      H08: 'Gethsemane Baptist Church',
      H09: 'Morehead Recreation Center',
      H10: 'Temple Memorial Baptist Church',
      H11: 'Montlieu Academy of Technology',
      H12: 'Kirkman Park School',
      H13: 'High Point Friends Meeting',
      H14: 'Emerywood Baptist Church',
      H15: 'Forest Hills Presbyterian Church',
      H16: "St Mary's Community Life Center",
      H17: 'Conrad Memorial Baptist Church',
      H18: 'Andrews High School',
      H19A: 'Greater First United Baptist Church',
      H19B: 'Pennybyrn at Maryfield',
      H20A: 'Oakview Baptist Church',
      H20B: 'Northwood Community Center',
      H21: 'Oakview Recreation Center',
      H22: 'High Point Parks & Rec. Adm. Bldg.',
      H23: 'Manna Church High Point',
      H24: 'Community Bible Church',
      H25: 'Tabernacle Baptist Church',
      H26: 'Deep River Church of Christ',
      'H27-A': 'Deep River Recreation Center',
      'H27-B': 'Deep River Friends Meeting',
      H28: 'First Christian Church of High Point',
      H29A: "Turner's Chapel AME Church",
      H29B: 'Hickory Grove United Methodist Church',
      JAM1: 'Jamestown Town Hall',
      JAM2: 'Friendly Hills Church PCA',
      JAM3: 'Sedgefield Presbyterian Church',
      JAM4: 'Haynes-Inman Education Center',
      JAM5: 'Fairfield Community Church',
      JEF1: 'McLeansville Baptist Church',
      JEF2: 'Calvary Baptist Church',
      JEF3: 'Piedmont Baptist Association',
      JEF4: 'Alamance Presbyterian Church',
      MON1: 'Forge Church',
      MON2A: 'Brightwood Elementary School',
      MON2B: 'Lebanon Baptist Church',
      MON3: 'Locust Grove Baptist Church',
      NCGR1: 'Center United Methodist Church',
      NCGR2: 'St Thomas Chapel Pentecostal',
      NCLAY1: 'Community in Christ Presbyterian Church',
      NCLAY2: 'Southeast Middle School',
      NDRI: 'Shady Grove Wesleyan Church',
      NMAD: 'Monticello-Brown Summit Elem School',
      NWASH: 'Hope River Church',
      OR1: 'Oak Ridge Town Hall',
      OR2: 'Oak Ridge United Methodist Church',
      PG1: 'Kirkman Municipal Building',
      PG2: 'Pleasant Garden Baptist Church',
      RC1: 'Eastern Guilford Middle School',
      RC2: 'First Baptist of Whitsett',
      SCLAY: 'Monnett Road Baptist Church',
      SDRI: 'Smith Grove Baptist Church',
      SF1: 'Summerfield Community Center',
      SF2: 'First Baptist - Summerfield',
      SF3: 'Morehead United Methodist Church',
      SF4: 'Pleasant Ridge Christian Church',
      SMAD: 'New Bessemer Baptist Church',
      STOK: 'Stokesdale Town Hall',
      SUM1: 'Rehobeth Church',
      SUM2: 'South Elm Street Baptist Church',
      SUM3: 'Living Waters Baptist Church',
      SUM4: 'Community Baptist Church',
      SWASH: 'Fire Station #28'
    },
    GRANVILLE: {
      ANTI: 'Antioch',
      BERE: 'Berea',
      BTNR: 'Butner',
      CORI: 'Corinth',
      CRDL: 'Credle',
      CRDM: 'Creedmoor',
      EAOX: 'East Oxford',
      MTEN: 'Mt. Energy',
      OKHL: 'Oak Hill',
      SALM: 'Salem',
      SASS: 'Sassafras Fork',
      SOOX: 'South Oxford',
      TYHO: 'Tally Ho',
      WILT: 'Wilton',
      WOEL: 'West Oxford Elementary'
    },
    DARE: {
      FRCO: 'Frisco'
    },
    COLUMBUS: {
      P01A: 'Bogue',
      P06: 'Cerro Gordo',
      P07: 'Chadbourn',
      P14: 'Ransom',
      P15: 'Tatum',
      P16B: 'Waccamaw',
      P82: 'NW Whiteville'
    },
    DAVIE: {
      '01': 'North Calahaln',
      '02': 'South Calahaln',
      '03': 'Clarksville',
      '04': 'Cooleemee',
      '05': 'Farmington',
      '06': 'Fulton',
      '07': 'Jerusalem',
      '09': 'South Mocksville',
      '10': 'East Shady Grove',
      '11': 'West Shady Grove',
      '12': 'Smith Grove',
      '13': 'Hillsdale'
    },
    JONES: {
      P01: 'Beaver Creek',
      P02: 'Chinquapin',
      P03: 'Cypress Creek',
      P04: 'Pollocksville',
      P05: 'Trenton',
      P06: 'Tuckahoe',
      P07: 'White Oak'
    },
    ONSLOW: {
      '0NE22A': 'Enon Chapel Baptist Church',
      '0NE22B': 'Centerview Baptist Church',
      NE22A: 'Enon Chapel Baptist Church',
      NE22B: 'Centerview Baptist Church'
    },
    HAYWOOD: {
      P: 'Pigeon'
    },
    MARTIN: {
      GSN: 'Goose Nest',
      GRF: 'Griffins',
      HMT: 'Hamilton',
      JMV: 'Jamesville'
    },
    MCDOWELL: {
      'WEST M': 'West Marion'
    },
    MOORE: {
      'EUR-WP': 'Eureka/Whispering Pines',
      PHC: 'Pinehurst C',
      SSP: 'South Southern Pines'
    },
    NASH: {
      P01A: 'Bailey',
      P05A: 'Coopers',
      P08A: 'Nashville',
      P09A: 'Castalia',
      P10A: 'Griffins',
      P11A: 'Red Oak',
      P15A: 'Oak Level'
    },
    'NEW HANOVER': {
      CF01: 'Wrightsboro School',
      CF02: 'Castle Hayne Elementary',
      CF05: 'CFCC-North Campus-McKeithan Center',
      CF06: 'Northside Baptist Church',
      FP03: 'Kure Beach Town Hall',
      FP04: 'Myrtle Grove Middle School',
      FP06: 'Bellamy Elementary School',
      FP07: 'Anderson Elementary School',
      FP08: 'Carolina Beach Muni Complex Rec Center',
      H01: 'Cape Fear Christian Church',
      H02: 'Northeast Regional Library',
      H04: 'College Park Elementary School',
      H05: 'Blair Elementary School',
      H06: 'Freedom Baptist Church',
      H08: 'Ogden Elementary School',
      H10: 'Eaton Elementary School',
      H11: 'Coastal Community Baptist Church',
      H12: 'Porters Neck Elementary School',
      H13: 'Porters Neck Village',
      M02: 'Masonboro Elementary School',
      M03: 'Moose Lodge',
      M04: 'United Advent Christian Church',
      M06: 'Myrtle Grove Baptist Church',
      M07: 'Harbor United Methodist Church',
      W03: 'MLK Center',
      W08: 'Board of Education-Spencer Building',
      W12: 'Forest Hills School',
      W15: 'Career Readiness Academy at Mosley PLC',
      W16: 'Lifepoint Church',
      W17: 'Holly Tree Elementary School',
      W21: 'Codington Elementary School',
      W25: 'CFCC McLeod Building',
      W26: 'Sunset Park Elementary School',
      W27: 'Freeman Elementary School',
      W29: 'Williston Middle School',
      W30: 'Cape Fear Presbyterian Church',
      W31: 'New Hanover County Senior Resource Center',
      W33: 'Bradley Creek Elementary School',
      W34: 'UNCW Warwick Center',
      W35: 'Wesley Memorial UMC Activity Building',
      WB: 'Wrightsville Beach Town Hall'
    },
    NORTHAMPTON: {
      CREEKS: 'Creeksville',
      GALATI: 'Galatia',
      GAPL: 'Garysburg/Pleasant Hill',
      GASTON: 'Gaston',
      'LAKE G': 'Lake Gaston',
      LASKER: 'Lasker',
      NEWTOW: 'Newtown',
      'RICH S': 'Rich Square',
      SEABOA: 'Seaboard',
      SEVERN: 'Severn'
    },
    CLEVELAND: {
      BETHWR: 'Bethware',
      BR: 'Broad River',
      CASAR: 'Casar',
      FALSTN: 'Fallston',
      GROVER: 'Grover',
      KINGST: 'Kingstown',
      'KM N': 'Kings Mountain North',
      'KM S': 'Kings Mountain South',
      LATT: 'Lattimore',
      LAWNDL: 'Lawn Dale',
      'MRB-YO': 'Mooresboro-Young',
      MULLS: 'Mulls',
      OAKGRV: 'Oak Grove',
      POLKVL: 'Polkville',
      RIPPY: 'Rippy',
      'S 4A': 'Shelby North',
      'S 5': 'Shelby East',
      'S C': 'Shelby Central',
      'S E': 'Shelby East',
      'S N': 'Shelby North',
      'S S': 'Shelby South',
      SHANGI: 'Shanghai',
      WACO: 'Waco'
    },
    ORANGE: {
      CA: 'Carr',
      CB1: 'Carrboro',
      HE: 'Hillsborough East',
      OW1: 'Owasa',
      WW1: 'Westwood'
    },
    PERQUIMANS: {
      'EAST H': 'East Hertford',
      'NEW HO': 'New Hope',
      'WEST H': 'West Hertford'
    },
    STANLY: {
      '0015': 'Badin',
      '0021': 'Endy',
      '0026': 'Tyson',
      '0120': 'Almond'
    },
    SURRY: {
      '12': 'Mt Airy 1',
      '15': 'Mt Airy 5',
      '16': 'Mt Airy 6',
      '17': 'Mt Airy 7',
      '19': 'Mt Airy 9'
    },
    SWAIN: {
      BC1: 'Bryson City 1',
      BC2: 'Bryson City 2',
      WHCH: 'Whittier/Cherokee'
    },
    UNION: {
      '0005': 'Monroe Fire Department, Station 4',
      '001': 'Iglesia de Dios (Church of God)',
      '0019': 'Mineral Springs VFD',
      '002': 'J. Ray Shute Center',
      '0020A': 'Waxhaw VFD',
      '0020B': 'Waxhaw Bible Church',
      '003': "St. Luke's Lutheran Church",
      '0030': 'Cornerstone Community Church',
      '004': 'Sutton Park Recreation Center',
      '0044': 'Millbridge Clubhouse',
      '0045': 'New Town Elementary',
      '006': 'Benton Heights Presbyterian Church',
      '007': 'Mt. Carmel Church',
      '008': 'Wingate Community Center',
      '009': 'Edwards Memorial Library',
      '010': 'The Old Armory',
      '011': 'Euto Baptist Church',
      '012': 'Bethlehem Presbyterian Church',
      '013': 'Unionville VFD',
      '014': 'Indian Trail Library',
      '015': 'Stallings Government Center',
      '016': 'Hemby Bridge Elementary School',
      '017A': 'Wesley Chapel Elementary School',
      '017B': 'Siler Presbyterian Church',
      '018': 'Wesley Chapel VFD - Weddington Station',
      '021': 'Jackson VFD',
      '022': 'Hermon Baptist Church',
      '023': 'Griffith Road VFD',
      '024': 'Prospect Elementary School',
      '025': 'Rock Rest Elementary School',
      '026': 'Union Baptist Church',
      '027': "Allen's Crossroads VFD",
      '028A': 'Sandy Ridge Elementary School',
      '028B': 'Marvin Elementary School',
      '028C': 'Marvin AME Zion Church',
      '028D': 'Kensington Elementary School',
      '029A': 'Shiloh Valley Elementary School',
      '029B': 'Brandon Oaks Clubhouse',
      '029C': 'Stallings VFD',
      '031': 'Grace Baptist Church',
      '032': 'Fairview Elementary School',
      '033': 'Waxhaw Elementary School',
      '034': 'Midway Baptist Church',
      '035': 'Rock Hill AME Zion Church',
      '036': 'Crossroads AME Zion Church',
      '037A': 'Stallings Elementary School',
      '037B': 'The Divide Clubhouse',
      '038A': 'Sardis Elementary School',
      '038B': 'Lake Park Community Center',
      '039': 'Porter Ridge Elementary School',
      '040': 'Spirit of Joy Lutheran Church',
      '041': 'Weddington Elementary School',
      '042': 'New Salem Baptist Church',
      '043': 'Winchester Community Center'
    },
    WILSON: {
      PRBL: 'Black Creek',
      PRCR: 'Crossroads',
      PRGA: 'Gardners',
      PROL: 'Old Fields',
      PRSA: 'Saratoga',
      PRSP: 'Spring Hill',
      PRST: 'Stantonsburg',
      PRTA: 'Taylors',
      PRTO: 'Toisnot',
      PRWA: 'Wilson A',
      PRWB: 'Wilson B',
      PRWC: 'Wilson C',
      PRWD: 'Wilson D',
      PRWE: 'Wilson E',
      PRWH: 'Wilson H',
      PRWI: 'Wilson I',
      PRWJ: 'Wilson J',
      PRWK: 'Wilson K',
      PRWL: 'Wilson L',
      PRWM: 'Wilson M',
      PRWN: 'Wilson N',
      PRWP: 'Wilson P',
      PRWQ: 'Wilson Q',
      PRWR: 'Wilson R'
    },
    VANCE: {
      CC: 'Community College',
      EH1: 'Central Henderson',
      HTOP: 'South Henderson',
      KITT: 'Kittrell',
      MIDD: 'Middleburg',
      NH: 'New Hope',
      NH1: 'Central Henderson',
      NV: 'Northern Vance',
      SCRK: 'Sandy Creek',
      SH1: 'South Henderson',
      SH2: 'South Henderson',
      WH: 'West Henderson'
    },
    CATAWBA: {
      '28': 'St. Stephens',
      '29': 'St. Stephens'
    },
    CRAVEN: {
      VE14: 'Van-Ep (Vanceboro)'
    }
  };

  for (const [county, countyOverrides] of Object.entries(overrides)) {
    if (!counties[county]) counties[county] = {};
    for (const [code, displayName] of Object.entries(countyOverrides)) {
      counties[county][code] = formatDisplayName(displayName);
    }
  }

  return counties;
}

function normalizeAliasNameCandidate(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return '';
  const cleaned = s.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!cleaned) return '';
  if (/VOTING\s*DISTRICT/i.test(cleaned)) return '';
  if (/^\d+$/.test(cleaned)) return '';
  return cleaned;
}

function collapseRedundantLeadingToken(raw) {
  const cleaned = normalizeAliasNameCandidate(raw);
  if (!cleaned) return '';
  const tokens = cleaned.split(/\s+/).filter(Boolean);
  if (tokens.length < 2) return cleaned;
  const [first, second, ...rest] = tokens;
  if (first.length >= 4 && second.startsWith(first.slice(0, 3))) {
    return [second, ...rest].join(' ').trim();
  }
  return cleaned;
}

function isCodeLikeToken(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return true;
  const compact = s.replace(/[^A-Z0-9]/g, '');
  if (!compact) return true;
  // Alias keys that include digits are almost always codes, not names (EH1, 0001, 00CRDM).
  if (/[0-9]/.test(compact)) return true;
  // Short all-letter tokens are usually precinct codes (CRDM, BCK), not display names.
  if (compact.length <= 4 && /^[A-Z]+$/.test(compact)) return true;
  return false;
}

function normalizeCounty(raw) {
  return String(raw || '').trim().toUpperCase();
}

function normalizeCode(raw) {
  return String(raw || '').trim().toUpperCase();
}

function normalizeDirectGeoName(raw) {
  const s = String(raw || '').trim().toUpperCase();
  if (!s) return '';
  const cleaned = s
    .replace(/VOTING\s*DISTRICT/gi, ' ')
    .replace(/[_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!cleaned) return '';
  if (/^\d+$/.test(cleaned)) return '';
  return cleaned;
}

function shouldUseDirectName(raw, codeRaw) {
  const name = normalizeDirectGeoName(raw);
  const code = normalizeCode(codeRaw);
  if (!name || !code) return false;
  const nameCompact = name.replace(/[^A-Z0-9]/g, '');
  const codeCompact = code.replace(/[^A-Z0-9]/g, '');
  if (!nameCompact || !codeCompact) return false;
  if (nameCompact === codeCompact) return false;
  const letters = (name.match(/[A-Z]/g) || []).length;
  if (!letters) return false;
  if (!/[0-9]/.test(nameCompact)) return letters >= 3;
  if (/[\/\s-]/.test(name)) return true;
  return !isCodeLikeToken(name);
}

function mergeGeoJsonNames(out, votingGeoJsonPayload) {
  const features = Array.isArray(votingGeoJsonPayload?.features) ? votingGeoJsonPayload.features : [];
  for (const feature of features) {
    const props = feature?.properties || {};
    const county = normalizeCounty(props.county_nam);
    const code = normalizeCode(props.prec_id);
    const enrDesc = normalizeDirectGeoName(props.enr_desc);
    if (!county || !code || !shouldUseDirectName(enrDesc, code)) continue;
    if (!out[county]) out[county] = {};
    const perCounty = new Map(Object.entries(out[county]));
    setBestNameForCode(perCounty, code, enrDesc);
    out[county] = Object.fromEntries(
      Array.from(perCounty.entries(), ([precinctCode, name]) => [precinctCode, formatDisplayName(name)])
    );
  }
  return out;
}

function scoreNameCandidate(raw) {
  const s = normalizeAliasNameCandidate(raw);
  if (!s) return -1e9;
  const letters = (s.match(/[A-Z]/g) || []).length;
  const digits = (s.match(/[0-9]/g) || []).length;
  const spaces = (s.match(/\s/g) || []).length;
  let score = 0;
  score += letters * 2.2;
  score -= digits * 3.5;
  // Prefer real spaced place names over code-glued smash tokens (SESHELBYEAST).
  score += spaces * 6.0;
  score += Math.min(24, s.length);
  if (/VOTING\s*DISTRICT/i.test(s)) score -= 1000;
  if (/^(EARLY|ABSENTEE|PROVISIONAL|ONE\s+STOP|MAIL)/i.test(s)) score -= 20;
  if (!spaces && letters >= 10) score -= 8;
  return score;
}

function splitCompactDirectionName(raw) {
  const s = String(raw || '').trim().toUpperCase().replace(/[^A-Z0-9]+/g, '');
  if (!s) return '';
  const m = s.match(/^(.*?)(NORTH|SOUTH|EAST|WEST|CENTRAL)$/);
  if (!m || !m[1] || m[1].length < 3) return s;
  const full = s.toLowerCase();
  if (['northeast', 'northwest', 'southeast', 'southwest'].includes(full)) return s;
  return `${m[1]} ${m[2]}`;
}

function extractNameFromAlias(aliasRaw, codeRaw) {
  const alias = String(aliasRaw || '').trim().toUpperCase();
  const code = String(codeRaw || '').trim().toUpperCase();
  if (!alias || !code) return '';
  if (alias === code) return '';

  const codeCompact = code.replace(/[^A-Z0-9]/g, '');
  const aliasCompact = alias.replace(/[^A-Z0-9]/g, '');

  let rest = '';
  if (alias.startsWith(code)) {
    rest = alias.slice(code.length).trim();
    rest = rest.replace(/^[_\s]+/, '').trim();
  } else if (
    codeCompact.length >= 2 &&
    aliasCompact.startsWith(codeCompact) &&
    aliasCompact.length > codeCompact.length + 2
  ) {
    // Compact smash keys like "SESHELBYEAST" for code "S E".
    rest = splitCompactDirectionName(aliasCompact.slice(codeCompact.length));
  }
  if (!rest) return '';
  rest = rest.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!rest) return '';
  if (/VOTING\s*DISTRICT/i.test(rest)) return '';

  const restCompact = rest.replace(/[^A-Z0-9]/g, '');
  if (restCompact === codeCompact) return '';
  if (restCompact.endsWith(codeCompact) && restCompact.length <= codeCompact.length + 2) return '';

  // Avoid returning another compact code token. Allow digits/spaces in real names (e.g. "LEXINGTON 1 22").
  if (!/\s/.test(rest)) {
    const compactOnly = rest.replace(/[^A-Z0-9]/g, '');
    if (compactOnly.length <= 6 && /^[A-Z0-9]+$/.test(compactOnly)) return '';
    // Last chance: SHELBYEAST -> SHELBY EAST
    const split = splitCompactDirectionName(compactOnly);
    if (split && /\s/.test(split)) rest = split;
  }
  const cleaned = normalizeAliasNameCandidate(rest);
  if (!cleaned) return '';
  return cleaned;
}

function setBestNameForCode(perCounty, code, nameCandidate) {
  if (!perCounty || !code || !nameCandidate) return;
  const cand = collapseRedundantLeadingToken(nameCandidate);
  if (!cand) return;
  const prev = perCounty.get(code) || '';
  if (!prev) {
    perCounty.set(code, cand);
    return;
  }
  const prevScore = scoreNameCandidate(prev);
  const candScore = scoreNameCandidate(cand);
  if (candScore > prevScore + 1e-6) {
    perCounty.set(code, cand);
    return;
  }
  if (Math.abs(candScore - prevScore) < 1e-6 && cand.length > prev.length) {
    perCounty.set(code, cand);
  }
}

function buildFriendlyNamesIndex(aliasIndexPayload) {
  const counties = aliasIndexPayload?.counties || {};
  const out = {};

  for (const [countyRaw, aliasObj] of Object.entries(counties)) {
    if (!aliasObj || typeof aliasObj !== 'object') continue;
    const perCounty = new Map();

    for (const [aliasRaw, codesRaw] of Object.entries(aliasObj)) {
      const alias = String(aliasRaw || '').trim().toUpperCase();
      const codes = Array.isArray(codesRaw)
        ? Array.from(new Set(codesRaw.map(v => String(v || '').trim().toUpperCase()).filter(Boolean)))
        : [];
      if (!alias || !codes.length) continue;

      for (const code of codes) {
        const extracted = extractNameFromAlias(alias, code);
        if (extracted) {
          setBestNameForCode(perCounty, code, extracted);
          continue;
        }
        // Only treat an alias key as a "name-only" label when it *doesn't* start with the code token.
        // This avoids bad picks like "ANTI 00ANTI" becoming a "name" for code "ANTI".
        if (codes.length === 1 && !isCodeLikeToken(alias) && !alias.startsWith(String(code || '').trim().toUpperCase())) {
          setBestNameForCode(perCounty, code, alias);
        }
      }
    }

    if (!perCounty.size) continue;
    const outCounty = {};
    for (const [code, name] of perCounty.entries()) {
      outCounty[code] = formatDisplayName(name);
    }
    out[countyRaw] = outCounty;
  }

  return applyManualOverrides(out);
}

function main() {
  const repoRoot = path.resolve(__dirname, '..');
  const inputPath = process.argv[2]
    ? path.resolve(process.argv[2])
    : path.join(repoRoot, 'data', 'precinct_alias_index.json');
  const votingGeoJsonPath = process.argv[4]
    ? path.resolve(process.argv[4])
    : path.join(repoRoot, 'data', '2025Voting_Precincts.geojson');
  const outputPath = process.argv[3]
    ? path.resolve(process.argv[3])
    : path.join(repoRoot, 'data', 'precinct_friendly_names.json');

  const payload = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const votingGeoJson = JSON.parse(fs.readFileSync(votingGeoJsonPath, 'utf8'));
  const counties = applyManualOverrides(mergeGeoJsonNames(buildFriendlyNamesIndex(payload), votingGeoJson));
  const out = {
    version: 1,
    generated_at: new Date().toISOString(),
    generated_from: [
      path.relative(repoRoot, inputPath).replace(/\\/g, '/'),
      path.relative(repoRoot, votingGeoJsonPath).replace(/\\/g, '/')
    ],
    counties
  };

  fs.writeFileSync(outputPath, `${JSON.stringify(out, null, 2)}\n`, 'utf8');
  console.log(`Wrote ${Object.keys(counties).length} counties -> ${path.relative(repoRoot, outputPath)}`);
}

if (require.main === module) main();
