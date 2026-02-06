"""
DEV_MODE Configuration for Pipeline Testing

When DEV_MODE=true, the pipeline filters to a small subset of entities
for fast iteration and testing. Set DEV_MODE=true to filter to DEV_ENTITIES
and write to pipeline_dev/. Set DEV_MODE=false for production (process all
entities, use config.json output_base).
"""

import os
import math
from pathlib import Path

# Dev mode toggle - set via environment variable (default false for production)
DEV_MODE = os.environ.get("DEV_MODE", "false").lower() == "true"

# Dev subset: 2 standby + 2 priority per park across 10 parks (37 total)
DEV_ENTITIES = [
    # MK - Magic Kingdom
    "MK01",
    "MK02",  # Space Mountain, Buzz Lightyear
    "MK07",
    "MK08",  # Space Mountain LL, Buzz Lightyear LL
    # EP - Epcot
    "EP01",
    "EP02",  # Innoventions West, Spaceship Earth
    "EP08",
    "EP10",  # Living w/ Land LL, Soarin' LL
    # HS - Hollywood Studios
    "HS01",
    "HS02",  # American Idol, Fantasmic!
    "HS06",
    "HS09",  # Indiana Jones Stunt LL, Lights Motors Action FP
    # AK - Animal Kingdom
    "AK01",
    "AK03",  # Tough to Be a Bug, Greeting Trails
    "AK02",
    "AK06",  # Tough Bug LL, Kilimanjaro Safaris LL
    # DL - Disneyland
    "DL01",
    "DL02",  # Alice in Wonderland, Astro Orbitor
    "DL04",
    "DL06",  # Autopia LL, Big Thunder LL
    # CA - California Adventure
    "CA01",
    "CA02",  # Turtle Talk, Aladdin Musical
    "CA07",
    "CA10",  # Tower of Terror FP, Soarin' LL
    # IA - Islands of Adventure
    "IA01",
    "IA02",  # Spider-Man, Caro-Seuss-el
    # UF - Universal Studios Florida
    "UF01",
    "UF02",  # Disaster!, E.T. Adventure
    "UF71",  # Diagon Alley (priority)
    # TDL - Tokyo Disneyland
    "TDL01",
    "TDL02",  # Omnibus, Penny Arcade
    "TDL13",
    "TDL16",  # Big Thunder FP, Splash Mountain FP
    # TDS - Tokyo DisneySea
    "TDS01",
    "TDS02",  # Fantasmic!, Steps to Shine
    "TDS11",
    "TDS16",  # Tower of Terror FP, Toy Story Mania FP
]

# Normalize to set for fast lookup (entity codes may be mixed case in data)
_DEV_ENTITIES_SET = {e.upper() for e in DEV_ENTITIES}


def should_process_entity(entity_code: str) -> bool:
    """Return True if entity should be processed in current mode."""
    if not DEV_MODE:
        return True
    if entity_code is None or (isinstance(entity_code, float) and math.isnan(entity_code)):
        return False
    return str(entity_code).strip().upper() in _DEV_ENTITIES_SET


def get_dev_output_base() -> Path:
    """Return output base path for dev mode (repo root / pipeline_dev)."""
    return Path(__file__).resolve().parent.parent / "pipeline_dev"
