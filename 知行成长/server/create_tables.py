#!/usr/bin/env python3
"""Install canonical tables and migrate old schemas without dropping their data."""
import json
from legacy_schema import migrate


def create_tables():
    report = migrate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    create_tables()
