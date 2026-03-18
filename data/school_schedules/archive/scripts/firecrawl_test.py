#!/usr/bin/env python3
"""
Test Firecrawl extract endpoint for school calendar data extraction.
Tests on NYC (biggest district that failed regular scraping).
"""

import os
import json
import time
from firecrawl import FirecrawlApp

app = FirecrawlApp(api_key=os.environ.get('FIRECRAWL_API_KEY'))

SCHEMA = {
    "type": "object",
    "properties": {
        "school_year": {"type": "string", "description": "The school year, e.g. '2025-2026'"},
        "first_day_of_school": {"type": "string", "description": "First day of school (YYYY-MM-DD format)"},
        "last_day_of_school": {"type": "string", "description": "Last day of school (YYYY-MM-DD format)"},
        "winter_break_start": {"type": "string", "description": "Winter/Christmas break start date (YYYY-MM-DD)"},
        "winter_break_end": {"type": "string", "description": "Winter/Christmas break end date (YYYY-MM-DD)"},
        "spring_break_start": {"type": "string", "description": "Spring break start date (YYYY-MM-DD)"},
        "spring_break_end": {"type": "string", "description": "Spring break end date (YYYY-MM-DD)"},
    },
    "required": ["school_year"]
}

def test_extract_nyc():
    """Test Firecrawl extract on NYC Public Schools."""
    print("Testing Firecrawl Extract: NYC Public Schools")
    print("=" * 60)
    
    result = app.extract(
        urls=["https://www.schools.nyc.gov/*"],
        prompt="Extract the 2025-2026 school year calendar dates for New York City Public Schools (NYC DOE). I need: first day of school, last day of school, winter/Christmas break start and end dates, and spring break/spring recess start and end dates. Return dates in YYYY-MM-DD format.",
        schema=SCHEMA,
        enable_web_search=True,
        timeout=120,
    )
    
    print(f"\nResult:")
    print(json.dumps(result, indent=2, default=str))
    return result


def test_extract_lausd():
    """Test Firecrawl extract on LAUSD."""
    print("\nTesting Firecrawl Extract: Los Angeles Unified")
    print("=" * 60)
    
    result = app.extract(
        urls=["https://www.lausd.org/*"],
        prompt="Extract the 2025-2026 school year calendar dates for Los Angeles Unified School District (LAUSD). I need: first day of school, last day of school, winter/Christmas break start and end dates, and spring break start and end dates. Return dates in YYYY-MM-DD format.",
        schema=SCHEMA,
        enable_web_search=True,
        timeout=120,
    )
    
    print(f"\nResult:")
    print(json.dumps(result, indent=2, default=str))
    return result


def main():
    print("Firecrawl Extract API Test - School Calendar Data")
    print(f"API Key: {'set' if os.environ.get('FIRECRAWL_API_KEY') else 'NOT SET'}")
    print()
    
    results = {}
    
    # Test NYC
    try:
        results['NYC'] = test_extract_nyc()
    except Exception as e:
        print(f"NYC Error: {type(e).__name__}: {e}")
        results['NYC'] = {'error': str(e)}
    
    time.sleep(3)
    
    # Test LAUSD
    try:
        results['LAUSD'] = test_extract_lausd()
    except Exception as e:
        print(f"LAUSD Error: {type(e).__name__}: {e}")
        results['LAUSD'] = {'error': str(e)}
    
    # Save results
    with open('firecrawl_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResults saved to firecrawl_results.json")


if __name__ == "__main__":
    main()
