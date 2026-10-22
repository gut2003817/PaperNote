import unittest

from easyread.pdf import sources


class PageMetaTest(unittest.TestCase):
    def test_apostrophes_and_quotes_inside_content_are_kept(self):
        page = """
        <meta name="citation_title" content="Don't Stop Pretraining: Adapt Language Models to Domains and Tasks">
        <meta name="citation_author" content="O'Brien, Sean">
        <meta content='Say "hi" to transformers' property='og:title'>
        """
        tags = sources._page_meta(page)
        self.assertEqual(tags["citation_title"], ["Don't Stop Pretraining: Adapt Language Models to Domains and Tasks"])
        self.assertEqual(tags["citation_author"], ["O'Brien, Sean"])
        self.assertEqual(tags["og:title"], ['Say "hi" to transformers'])

    def test_entities_and_attribute_order(self):
        page = """
        <meta name="citation_pdf_url" content="https://example.org/paper.pdf?a=1&amp;b=2">
        <meta content="Attention Is All You Need" name="citation_title">
        """
        tags = sources._page_meta(page)
        self.assertEqual(tags["citation_pdf_url"], ["https://example.org/paper.pdf?a=1&b=2"])
        self.assertEqual(tags["citation_title"], ["Attention Is All You Need"])


if __name__ == "__main__":
    unittest.main()
