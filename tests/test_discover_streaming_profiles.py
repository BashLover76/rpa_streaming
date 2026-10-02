import unittest

from types import SimpleNamespace

from tools.discover_streaming_profiles import (
    clean_profile_text,
    is_junior_profile,
    profile_management_url,
    profile_text,
    slugify,
)


class DiscoverStreamingProfilesTests(unittest.TestCase):
    def test_profile_text_keeps_probable_profile_names(self):
        self.assertEqual(profile_text("Parent"), "Parent")
        self.assertEqual(profile_text("Kids"), "Kids")
        self.assertEqual(profile_text("Profil principal"), "Profil principal")

    def test_profile_text_rejects_navigation_and_security_noise(self):
        rejected = [
            "Get Help",
            "Help Center",
            "Cloudflare",
            "Terms and Privacy Notice",
            "Cookie Preferences",
            "Create your Amazon account",
            "Connexion",
            "Send us feedback",
        ]
        for value in rejected:
            with self.subTest(value=value):
                self.assertEqual(profile_text(value), "")

    def test_profile_text_removes_edit_actions_from_profile_names(self):
        self.assertEqual(profile_text("Chris Modifier", platform="prime_video"), "Chris")
        self.assertEqual(profile_text("Modifier Morgane", platform="disney_plus"), "Morgane")
        self.assertEqual(clean_profile_text("Chris\nModifier"), "Chris")

    def test_profile_text_rejects_add_and_done_actions(self):
        rejected = [
            "Ajouter",
            "Ajouter profil",
            "Ajouter un profil",
            "ajoutez un profil",
            "chris_morgane_together_ajouter",
            "ajouter_profil",
            "c_est_fait",
            "C'est fait",
            "Terminé",
            "Créer un nouveau profil",
            "Manage profiles",
        ]
        for value in rejected:
            with self.subTest(value=value):
                self.assertEqual(profile_text(value), "")

    def test_junior_profiles_are_detected_from_known_labels(self):
        self.assertTrue(is_junior_profile("Enfants"))
        self.assertTrue(is_junior_profile("Jeunesse"))
        self.assertFalse(is_junior_profile("Chris"))

    def test_slugify_normalizes_names_for_cache_keys(self):
        self.assertEqual(slugify("Profil principal"), "profil_principal")
        self.assertEqual(slugify("Kids!"), "kids")

    def test_platforms_use_profile_management_pages(self):
        expected_urls = {
            "netflix": "https://www.netflix.com/browse",
            "prime_video": "https://www.primevideo.com/profiles?step=manage",
            "disney_plus": "https://www.disneyplus.com/fr-fr/edit-profiles",
            "crunchyroll": "https://www.crunchyroll.com/fr/profiles/manage",
        }
        for platform, expected_url in expected_urls.items():
            with self.subTest(platform=platform):
                config = SimpleNamespace(name=platform, start_url="https://example.invalid")
                self.assertEqual(profile_management_url(config), expected_url)


if __name__ == "__main__":
    unittest.main()
