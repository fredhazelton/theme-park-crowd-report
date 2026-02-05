"""
DEV_MODE Configuration for Pipeline Testing

When DEV_MODE=true, the pipeline filters to a small subset of entities
for fast iteration and testing.
"""
import os

# Dev mode toggle - set via environment variable
DEV_MODE = os.environ.get('DEV_MODE', 'false').lower() == 'true'

# MINIMAL TEST: Just 2 entities for first run
# MK01 = Space Mountain (standby)
# MK07 = Space Mountain Lightning Lane (priority)
DEV_ENTITIES = [
    'MK01',  # Space Mountain - standby
    'MK07',  # Space Mountain LL/G+ - priority
]

# Full dev set (37 entities) - use this for normal dev work
DEV_ENTITIES_FULL = [
    # MK - Magic Kingdom
    'MK01', 'MK02',  # Space Mountain, Buzz Lightyear
    'MK07', 'MK08',  # Space Mountain LL, Buzz Lightyear LL
    # EP - Epcot
    'EP01', 'EP02',  # Innoventions West, Spaceship Earth
    'EP08', 'EP10',  # Living w/ Land LL, Soarin' LL
    # HS - Hollywood Studios
    'HS01', 'HS02',  # American Idol, Fantasmic!
    'HS06', 'HS09',  # Indiana Jones Stunt LL, Lights Motors Action FP
    # AK - Animal Kingdom
    'AK01', 'AK03',  # Tough to Be a Bug, Greeting Trails
    'AK02', 'AK06',  # Tough Bug LL, Kilimanjaro Safaris LL
    # DL - Disneyland
    'DL01', 'DL02',  # Alice in Wonderland, Astro Orbitor
    'DL04', 'DL06',  # Autopia LL, Big Thunder LL
    # CA - California Adventure
    'CA01', 'CA02',  # Turtle Talk, Aladdin Musical
    'CA07', 'CA10',  # Tower of Terror FP, Soarin' LL
    # IA - Islands of Adventure
    'IA01', 'IA02',  # Spider-Man, Caro-Seuss-el
    # UF - Universal Studios Florida
    'UF01', 'UF02',  # Disaster!, E.T. Adventure
    'UF71',          # Diagon Alley (priority)
    # TDL - Tokyo Disneyland
    'TDL01', 'TDL02',  # Omnibus, Penny Arcade
    'TDL13', 'TDL16',  # Big Thunder FP, Splash Mountain FP
    # TDS - Tokyo DisneySea
    'TDS01', 'TDS02',  # Fantasmic!, Steps to Shine
    'TDS11', 'TDS16',  # Tower of Terror FP, Toy Story Mania FP
]

def should_process_entity(entity_code):
    """Check if entity should be processed in current mode."""
    if not DEV_MODE:
        return True  # Production: process everything
    return entity_code in DEV_ENTITIES

def get_dev_output_base():
    """Return output base path for dev mode."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pipeline_dev')

def get_output_base():
    """Return appropriate output base based on mode."""
    if DEV_MODE:
        return get_dev_output_base()
    else:
        return '/home/wilma/hazeydata/pipeline'
