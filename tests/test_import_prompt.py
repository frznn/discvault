from __future__ import annotations

import unittest

from discvault.metadata import urlimport
from discvault.ui.import_prompt import MetadataImportPromptScreen


class ImportPromptHelpTests(unittest.TestCase):
    def test_file_mode_lists_supported_extensions(self) -> None:
        text = MetadataImportPromptScreen._help_for_mode("file")
        self.assertTrue(text.startswith("Supported file types:"))
        for ext in MetadataImportPromptScreen.SUPPORTED_FILE_TYPES:
            self.assertIn(ext, text)

    def test_url_mode_lists_supported_sites(self) -> None:
        text = MetadataImportPromptScreen._help_for_mode("url")
        self.assertTrue(text.startswith("Supported sites:"))
        for site in MetadataImportPromptScreen.SUPPORTED_URL_SITES:
            self.assertIn(site, text)

    def test_supported_url_sites_match_provider_router(self) -> None:
        for site in MetadataImportPromptScreen.SUPPORTED_URL_SITES:
            self.assertIn(site, urlimport._SUPPORTED_PROVIDERS)


if __name__ == "__main__":
    unittest.main()
