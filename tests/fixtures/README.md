# Test fixtures

**Everything in this folder is made-up test data (FIXTURES).** Company names, symbols and
ISINs are invented (the ISINs have valid check digits but belong to no real company).
The running app never reads this folder.

M2 fixtures (all invented, shaped like the real exchange files checked on 26 Sep 2026):

- `FIXTURE_nse_announcements.xml`, `FIXTURE_bse_announcements.xml`: RSS feeds in NSE's and
  BSE's layouts.
- `FIXTURE_List_of_Scrips.csv`: BSE's List of Scrips layout.
- `FIXTURE_SHP.xml`: a shareholding pattern in the SEBI/BSE `in-bse-shp` XBRL layout.
- `FIXTURE_bulk.csv`, `FIXTURE_block.csv`: NSE's bulk and block deal files.
