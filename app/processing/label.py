"""Step e — Label. Items that failed code validation never reach here (they are Rejected and
logged in extraction_rejections). For items that passed:

- Verified:      the cross-check answered "yes".
- Needs review:  the cross-check answered "partly" or "no" (owner's rule: partly = disagreement).
- Unverified:    no cross-check was possible (passed code checks only).
"""


def label(answer: str | None) -> tuple[str, str]:
    if answer == "yes":
        return "verified", "Passed code checks; the cross-check model agreed"
    if answer in ("partly", "no"):
        return "needs_review", f"Passed code checks, but the cross-check model answered '{answer}'"
    return "unverified", "Passed code checks; no cross-check yet"
