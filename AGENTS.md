# Project Instructions

## Financial-data safety

- This repository is finance-related. Treat data lineage, point-in-time correctness, units, precision, missing values, and source discrepancies as correctness-sensitive.
- Do not propose or implement fallback logic between data sources (including `coalesce`, conditional substitution, or automatic source precedence) unless the user explicitly requests fallback behavior.
- When sources overlap, report discrepancies and their impact explicitly. Do not assume similarly named fields are interchangeable.
