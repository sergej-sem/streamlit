import unittest

from badgegen.category import (
    ALLOWED_CATEGORIES,
    K_BEO,
    K_HOSTESS,
    K_SPO,
    K_TEAM,
    K_TN,
    K_VIP,
    derive_kategorie_from_historie,
)

TAG = "26DOR"


class DeriveKategorieBasicTests(unittest.TestCase):
    """One test per known historie pattern → expected category."""

    def _check(self, historie: str, expected: str) -> None:
        result = derive_kategorie_from_historie(historie, TAG)
        self.assertEqual(expected, result, f"historie={historie!r}")

    # ── VIP/REF ───────────────────────────────────────────────────────────────
    def test_ref(self):
        self._check("26DOR_REF", K_VIP)

    def test_ref_selfmades(self):
        self._check("26DOR_REF_SELFMADES", K_VIP)

    def test_tn_selfmades(self):
        self._check("26DOR_TN_SELFMADES", K_VIP)

    def test_selfmade(self):
        self._check("26DOR_SELFMADE", K_VIP)

    def test_ref_saveplayer(self):
        self._check("26DOR_REF_SAVEPLAYER", K_VIP)

    # ── Sponsor ───────────────────────────────────────────────────────────────
    def test_spo_vorort(self):
        self._check("26DOR_SPO_VORORT", K_SPO)

    def test_spo(self):
        self._check("26DOR_SPO", K_SPO)

    # ── BEO ───────────────────────────────────────────────────────────────────
    def test_beo(self):
        self._check("26DOR_BEO", K_BEO)

    # ── TN ────────────────────────────────────────────────────────────────────
    def test_tnnoreply(self):
        self._check("26DOR_TNNOREPLY", K_TN)

    def test_tnnomeetings(self):
        self._check("26DOR_TNNOMEETINGS", K_TN)

    def test_tn_saveplayer(self):
        self._check("26DOR_TN_SAVEPLAYER", K_TN)

    def test_tn(self):
        self._check("26DOR_TN", K_TN)

    # ── Team ──────────────────────────────────────────────────────────────────
    def test_team(self):
        self._check("26DOR_TEAM", K_TEAM)

    # ── Hostess ───────────────────────────────────────────────────────────────
    def test_hostess(self):
        self._check("26DOR_HOSTESS", K_HOSTESS)


class DeriveKategorieEdgeCaseTests(unittest.TestCase):
    """Edge cases: None, empty, unknown, case insensitivity."""

    def test_none_historie_returns_none(self):
        self.assertIsNone(derive_kategorie_from_historie(None, TAG))

    def test_empty_historie_returns_none(self):
        self.assertIsNone(derive_kategorie_from_historie("", TAG))

    def test_none_tag_returns_none(self):
        self.assertIsNone(derive_kategorie_from_historie("26DOR_TN", None))

    def test_empty_tag_returns_none(self):
        self.assertIsNone(derive_kategorie_from_historie("26DOR_TN", ""))

    def test_unknown_historie_returns_none(self):
        self.assertIsNone(derive_kategorie_from_historie("26DOR_UNKNOWN", TAG))

    def test_wrong_tag_returns_none(self):
        self.assertIsNone(derive_kategorie_from_historie("26BER_TN", TAG))

    def test_case_insensitive_historie(self):
        # historie in lowercase → still matches
        self.assertEqual(K_TN, derive_kategorie_from_historie("26dor_tn", TAG))

    def test_case_insensitive_tag(self):
        # tag in lowercase → still matches
        self.assertEqual(K_TN, derive_kategorie_from_historie("26DOR_TN", "26dor"))

    def test_both_lowercase(self):
        self.assertEqual(K_VIP, derive_kategorie_from_historie("26dor_ref", "26dor"))


class DeriveKategorieOrderTests(unittest.TestCase):
    """
    The function uses substring-in checks (not exact match), so order matters.
    Verify that more-specific patterns are not swallowed by less-specific ones,
    and that VIP beats TN when both substrings are present.
    """

    def test_spo_vorort_beats_spo(self):
        # 26DOR_SPO_VORORT contains 26DOR_SPO as substring;
        # SPO_VORORT check comes first → Sponsor (not wrong, but same result).
        # Real test: just confirm it doesn't become something unexpected.
        result = derive_kategorie_from_historie("26DOR_SPO_VORORT", TAG)
        self.assertEqual(K_SPO, result)

    def test_tnnoreply_is_tn_not_wrong_category(self):
        # 26DOR_TNNOREPLY contains 26DOR_TN as substring.
        # Must still return TN (TNNOREPLY checked before TN in the TN block).
        result = derive_kategorie_from_historie("26DOR_TNNOREPLY", TAG)
        self.assertEqual(K_TN, result)

    def test_tn_selfmades_is_vip_not_tn(self):
        # 26DOR_TN_SELFMADES contains 26DOR_TN as substring.
        # VIP block checks TN_SELFMADES before TN block is reached → must be VIP.
        result = derive_kategorie_from_historie("26DOR_TN_SELFMADES", TAG)
        self.assertEqual(K_VIP, result)

    def test_multi_value_history_first_match_wins(self):
        # Historie can contain semicolon-separated values (HubSpot multi-select).
        # 26DOR_TN is present; result must be TN.
        result = derive_kategorie_from_historie("26BER_SPO;26DOR_TN", TAG)
        self.assertEqual(K_TN, result)

    def test_ref_in_multivalue_history_is_vip(self):
        result = derive_kategorie_from_historie("26DOR_TN;26DOR_REF", TAG)
        # REF check comes before TN check → VIP
        self.assertEqual(K_VIP, result)


class AllowedCategoriesTests(unittest.TestCase):
    def test_all_categories_present(self):
        for cat in [K_TN, K_VIP, K_SPO, K_BEO, K_TEAM, K_HOSTESS]:
            self.assertIn(cat, ALLOWED_CATEGORIES)

    def test_derive_results_are_in_allowed_categories(self):
        cases = [
            "26DOR_TN", "26DOR_REF", "26DOR_SPO",
            "26DOR_BEO", "26DOR_TEAM", "26DOR_HOSTESS",
        ]
        for h in cases:
            result = derive_kategorie_from_historie(h, TAG)
            self.assertIn(result, ALLOWED_CATEGORIES, f"historie={h!r}")


if __name__ == "__main__":
    unittest.main()
