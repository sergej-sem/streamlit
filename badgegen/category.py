# badgegen/category.py
from typing import Optional

K_TN = "TN"
K_VIP = "VIP/REF"
K_SPO = "Sponsor"
K_BEO = "BEO"
K_TEAM = "Team"

ALLOWED_CATEGORIES = [K_TN, K_VIP, K_SPO, K_BEO, K_TEAM]

EVENT_TAGS: list[str] = ["26DOR", "26BER", "26MUC"]

def derive_kategorie_from_historie(historie: str | None, event_tag: str) -> Optional[str]:
    if not historie:
        return None
    if not event_tag:
        return None

    h = historie.upper()
    tag = event_tag.upper()

    # VIP/REF
    if f"{tag}_REF" in h:
        return K_VIP
    if f"{tag}_REF_SELFMADES" in h:
        return K_VIP
    if f"{tag}_TN_SELFMADES" in h:
        return K_VIP
    if f"{tag}_SELFMADE" in h:
        return K_VIP
    if f"{tag}_REF_SAVEPLAYER" in h:
        return K_VIP

    # Sponsor
    if f"{tag}_SPO_VORORT" in h:
        return K_SPO
    if f"{tag}_SPO" in h:
        return K_SPO

    # BEO
    if f"{tag}_BEO" in h:
        return K_BEO

    # TN
    if f"{tag}_TNNOREPLY" in h:
        return K_TN
    if f"{tag}_TNNOMEETINGS" in h:
        return K_TN
    if f"{tag}_TN_SAVEPLAYER" in h:
        return K_TN
    if f"{tag}_TN" in h:
        return K_TN

    # Team
    if f"{tag}_TEAM" in h:
        return K_TEAM

    return None
