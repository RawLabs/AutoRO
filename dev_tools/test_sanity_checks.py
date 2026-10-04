#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.estimate_conversion import estimate_sanity_findings

def test_misplaced_parts():
    print("Testing misplaced parts warning...")
    mock_parsed = {
        "jobs": [
            {
                "title": "POWER STEERING RACK IS LEAKING NEEDS REPLACEMENT",
                "labour_hours": 0.0,
                "parts_retail_cad": 0.0,
                "part_lines": []
            },
            {
                "title": "POWER STEERING PUMP LEAKING NEEDS REPLACEMENT",
                "labour_hours": 0.0,
                "parts_retail_cad": 550.63,
                "part_lines": [
                    "Rack and Pinion - Power - Complete - Remanufactured",
                    "Rack and Pinion - Power - Complete - Remanufactured <CORE>"
                ]
            }
        ]
    }
    findings = estimate_sanity_findings(mock_parsed)
    misplaced = [f for f in findings if f["check"] == "misplaced_parts"]
    assert len(misplaced) >= 1, "Expected misplaced parts warning to be generated"
    assert "Steering rack parts" in misplaced[0]["message"], "Message should clearly identify steering rack parts"
    assert "POWER STEERING RACK IS LEAKING NEEDS REPLACEMENT" in misplaced[0]["recommendation"], "Recommendation should refer to the empty Rack job line"
    print("✓ Misplaced parts warning test passed!")

def test_duplicate_jobs():
    print("Testing duplicate/split jobs warning...")
    mock_parsed = {
        "jobs": [
            {
                "title": "POWER STEERING PUMP LEAKING NEEDS REPLACEMENT",
                "labour_hours": 0.0,
                "parts_retail_cad": 550.63,
                "part_lines": ["Rack and Pinion"]
            },
            {
                "title": "POWER STEERING PUMP - Remove, Install & Overhaul",
                "labour_hours": 3.8,
                "parts_retail_cad": 134.89,
                "part_lines": ["P/S Pump Repair Kit"]
            }
        ]
    }
    findings = estimate_sanity_findings(mock_parsed)
    duplicates = [f for f in findings if f["check"] == "duplicate_jobs"]
    assert len(duplicates) >= 1, "Expected duplicate jobs warning to be generated"
    assert "Duplicate line for Steering Pump" in duplicates[0]["message"], "Message should refer to duplicate steering pump"
    print("✓ Duplicate/split jobs warning test passed!")

def test_standard_zero_labor():
    print("Testing standard zero labor check and override...")
    mock_parsed = {
        "jobs": [
            {
                "title": "REPLACE HEADLIGHT BULB",
                "labour_hours": 0.0,
                "parts_retail_cad": 45.00,
                "part_lines": ["Bulb"]
            },
            {
                "title": "REPLACE WIPERS - NO CHARGE",
                "labour_hours": 0.0,
                "parts_retail_cad": 30.00,
                "part_lines": ["Wiper Blades"]
            }
        ]
    }
    findings = estimate_sanity_findings(mock_parsed)
    zero_labor = [f for f in findings if f["check"] == "parts_without_labour"]
    
    # REPLACE HEADLIGHT BULB should trigger finding
    triggered_titles = [f["job_title"] for f in zero_labor]
    assert "REPLACE HEADLIGHT BULB" in triggered_titles, "Should trigger warning for REPLACE HEADLIGHT BULB"
    # REPLACE WIPERS - NO CHARGE should NOT trigger finding (due to override)
    assert "REPLACE WIPERS - NO CHARGE" not in triggered_titles, "Should NOT trigger warning for REPLACE WIPERS - NO CHARGE"
    print("✓ Standard zero labor warning and override test passed!")

if __name__ == "__main__":
    try:
        test_misplaced_parts()
        test_duplicate_jobs()
        test_standard_zero_labor()
        print("\nAll tests passed successfully!")
    except AssertionError as exc:
        print(f"\nAssertion FAILED: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nError occurred: {exc}")
        sys.exit(1)
