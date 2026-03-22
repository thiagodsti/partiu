"""
Norwegian Air Shuttle flight extractor.

Norwegian uses the same email format as SAS, so both the BS4 and regex
extractors delegate directly to the SAS implementations.
"""

from .sas import extract, extract_bs4, extract_regex  # noqa: F401 (re-exported)
