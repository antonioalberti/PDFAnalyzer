import re
import pdfplumber

class AbstractExtractor:
    @staticmethod
    def extract_abstract(file_path):
        abstract = ""
        with pdfplumber.open(file_path) as pdf:
            # Search first 3 pages for abstract
            for i in range(min(3, len(pdf.pages))):
                page = pdf.pages[i]
                text = page.extract_text()
                if text:
                    # Look for "Abstract" in various capitalizations
                    abstract_match = re.search(r"\\bAbstract\\b|\\bABSTRACT\\b|\\babstract\\b", text)
                    if abstract_match:
                        start = abstract_match.end()
                        after_abstract = text[start:]
                        # Heuristic: abstract ends at next section heading (all caps line) or double newline
                        match = re.search(r"\\n[A-Z][A-Z\\s\\-]{3,}\\n", after_abstract)
                        if match:
                            next_match = re.search(r"\\n[A-Z][A-Z\\s\\-]{3,}\\n", after_abstract[match.end():])
                            if next_match:
                                abstract = after_abstract[:match.end() + next_match.start()].strip()
                            else:
                                abstract = after_abstract[:match.start()].strip()
                        else:
                            double_nl = after_abstract.find('\\n\\n')
                            if double_nl != -1:
                                second_double_nl = after_abstract.find('\\n\\n', double_nl + 2)
                                if second_double_nl != -1:
                                    abstract = after_abstract[:second_double_nl].strip()
                                else:
                                    abstract = after_abstract[:double_nl].strip()
                            else:
                                abstract = after_abstract[:600].strip()
                        break
        return abstract
