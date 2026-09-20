def names_by_age(rows):
    return [r['name'] for r in sorted(rows, key=lambda r: (r['age'], r['name']))]
