"""Company matching (brief 14.4): exact IDs first, then exact names. Never fuzzy.

Order: ISIN, then exact BSE code or NSE symbol, then an exact name or alias match
(ignoring only letter case and extra spaces). A name shared by two companies matches
neither. Anything unmatched stays unlinked and is counted on Data Health.
"""

import json
import sqlite3

AMBIGUOUS = object()


def norm_name(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


class Matcher:
    def __init__(self, conn: sqlite3.Connection):
        self.isins, self.by_bse, self.by_symbol, self.by_name = set(), {}, {}, {}
        for r in conn.execute("SELECT isin, nse_symbol, bse_code, name, aliases FROM companies"):
            self.isins.add(r["isin"])
            if r["bse_code"]:
                self.by_bse[r["bse_code"]] = r["isin"]
            if r["nse_symbol"]:
                self.by_symbol[r["nse_symbol"]] = r["isin"]
            names = {norm_name(r["name"])}
            try:
                names |= {norm_name(a) for a in json.loads(r["aliases"] or "[]")}
            except (TypeError, ValueError):
                pass
            for n in names - {""}:
                prior = self.by_name.get(n)
                self.by_name[n] = r["isin"] if prior in (None, r["isin"]) else AMBIGUOUS

    def match(self, isin=None, bse_code=None, nse_symbol=None, name=None):
        """Returns (isin, method) or (None, None)."""
        if isin and isin.strip().upper() in self.isins:
            return isin.strip().upper(), "isin"
        if bse_code and bse_code.strip() in self.by_bse:
            return self.by_bse[bse_code.strip()], "bse_code"
        if nse_symbol and nse_symbol.strip().upper() in self.by_symbol:
            return self.by_symbol[nse_symbol.strip().upper()], "nse_symbol"
        found = self.by_name.get(norm_name(name)) if name else None
        if found is not None and found is not AMBIGUOUS:
            return found, "exact_name"
        return None, None

    def name_is_unique(self, name: str) -> bool:
        found = self.by_name.get(norm_name(name))
        return found is not None and found is not AMBIGUOUS
