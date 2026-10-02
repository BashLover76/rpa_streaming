import unittest

from types import SimpleNamespace

from tools.discover_streaming_profiles import (
    canonical_profile_name,
    clean_profile_text,
    is_junior_profile,
    profile_detection_urls,
    profile_management_url,
    profile_text,
    profiles_from_netflix_text,
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
            "le profil",
            "les profils",
            "les Profils",
            "Qui regarde ?",
            "le profil de Chris.",
            "le profil de léo.",
            "le profil de Morgane.",
            "le profil de Parents.",
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

    def test_detected_platform_noise_is_filtered(self):
        prime = ["Qui regarde ?", "Chris", "Morgane", "Together", "Enfants", "le profil"]
        disney = [
            "les profils",
            "Chris",
            "léo",
            "Morgane",
            "Parents",
            "le profil de Chris.",
            "le profil de léo.",
            "le profil de Morgane.",
            "le profil de Parents.",
        ]
        crunchyroll = ["Chris", "Morgane", "les Profils"]

        self.assertEqual([profile_text(value) for value in prime if profile_text(value)], ["Chris", "Morgane", "Together", "Enfants"])
        self.assertEqual([profile_text(value) for value in disney if profile_text(value)], ["Chris", "léo", "Morgane", "Parents"])
        self.assertEqual([profile_text(value) for value in crunchyroll if profile_text(value)], ["Chris", "Morgane"])

    def test_prime_singular_child_profile_is_canonicalized(self):
        profiles = ["Chris", "Enfants", "Enfant"]
        detected = []
        seen = set()
        for profile in profiles:
            canonical = canonical_profile_name(profile)
            key = slugify(canonical)
            if key not in seen:
                seen.add(key)
                detected.append(canonical)

        self.assertEqual(detected, ["Chris", "Enfants"])

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

    def test_netflix_uses_read_only_fallback_pages_when_browse_has_no_profiles(self):
        config = SimpleNamespace(name="netflix", start_url="https://example.invalid")

        self.assertEqual(
            profile_detection_urls(config),
            [
                "https://www.netflix.com/browse",
                "https://www.netflix.com/profiles/manage",
                "https://www.netflix.com/ProfilesGate",
            ],
        )

    def test_netflix_profiles_are_extracted_from_profile_gate_text(self):
        body_text = "\n".join(
            [
                "Netflix",
                "Who's watching?",
                "christopher",
                "morgane",
                "Guest",
                "Parents",
                "Jeunesse",
                "Manage Profiles",
            ]
        )

        self.assertEqual(
            profiles_from_netflix_text(body_text),
            ["christopher", "morgane", "Guest", "Parents", "Jeunesse"],
        )


if __name__ == "__main__":
    unittest.main()
