# badgegen/category.py
from typing import Optional

K_TN = "TN"
K_VIP = "VIP/REF"
K_SPO = "Sponsor"
K_BEO = "BEO"
K_TEAM = "Team"

ALLOWED_CATEGORIES = [K_TN, K_VIP, K_SPO, K_BEO, K_TEAM]

def derive_kategorie_from_historie(historie: str | None, event_tag: str) -> Optional[str]:
    if not historie:
        return None

    # VIP/REF
    if f"{event_tag}_REF" in historie:
        return K_VIP
    if f"{event_tag}_REF_Selfmades" in historie:
        return K_VIP
    if f"{event_tag}_TN_Selfmades" in historie:
        return K_VIP
    if f"{event_tag}_SELFMADE" in historie:
        return K_VIP
    if f"{event_tag}_REF_Saveplayer" in historie:
        return K_VIP

    # Sponsor
    if f"{event_tag}_SPO" in historie:
        return K_SPO
    if f"{event_tag}_SPO_VORORT" in historie:
        return K_SPO

    # BEO
    if f"{event_tag}_BEO" in historie:
        return K_BEO

    # TN
    if f"{event_tag}_TN" in historie:
        return K_TN
    if f"{event_tag}_TNNOREPLY" in historie:
        return K_TN
    if f"{event_tag}_TNNOMEETINGS" in historie:
        return K_TN
    if f"{event_tag}_TN_Saveplayer" in historie:
        return K_TN

    # Team
    if f"{event_tag}_Team" in historie:
        return K_TEAM

    return None
