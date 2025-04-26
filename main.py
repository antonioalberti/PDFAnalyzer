import argparse
import re
from collections import Counter
from PyPDF2 import PdfReader
import sys

sys.stdout.reconfigure(encoding='utf-8')

def read_pdf(file_path):
    pdf = PdfReader(file_path)
    text = ""
    for page_num, page in enumerate(pdf.pages, start=1):
        text += f"Page {page_num}:\n"
        text += page.extract_text() + "\n"
    return text

def extract_context(content, start, end, num_sentences=3):
    # Encontre o início do contexto, movendo-se para trás no texto
    context_start = start
    for _ in range(num_sentences):
        context_start = content.rfind('.', 0, context_start)
        if context_start == -1:
            context_start = 0
            break
        else:
            context_start += 1  # avance após o ponto

    # Encontre o fim do contexto, movendo-se para a frente no texto
    context_end = end
    for _ in range(num_sentences):
        context_end = content.find('.', context_end)
        if context_end == -1:
            context_end = len(content)
            break
        else:
            context_end += 1  # inclua o ponto

    return content[context_start:context_end].strip()

def find_occurrences_without_references(text, keywords):
    results = []
    pages = text.split("Page ")
    for page in pages[1:]:
        if ":\n" not in page:
            print(f"Separador não encontrado na página: {page[:100]}...")
            continue

        page_num, content = page.split(":\n", 1)
        references_start = re.search("REFERENCES", content, re.IGNORECASE)
        if references_start:
            content = content[:references_start.start()]
        for keyword in keywords:
            keyword_pattern = re.compile(rf"\b{re.escape(keyword)}\b|\b{re.escape(keyword.replace('-', ' '))}\b", re.IGNORECASE)
            matches = keyword_pattern.finditer(content)
            for match in matches:
                context = extract_context(content, match.start(), match.end())
                results.append((int(page_num), keyword, context))
    return results

def check_enabler_occurrences(pdf_text, enabler_keywords):
    enabler_occurrences = {enabler: [] for enabler in enabler_keywords.keys()}

    for enabler, keywords in enabler_keywords.items():
        enabler_occurrences[enabler] = find_occurrences_without_references(pdf_text, keywords)

    return enabler_occurrences


def print_occurrences(enabler_occurrences):
    total_matches_summary = 0
    for enabler, occurrences in enabler_occurrences.items():
        total_matches = len(occurrences)
        print(f"{enabler} (Total Matches: {total_matches}):")
        total_matches_summary += total_matches
        if occurrences:
            for page_num, keyword, paragraph in occurrences:
                print(f"Page {page_num}:")
                print(f"Keyword: {keyword}")
                print(f"Paragraph: {paragraph}")
                print()
        else:
            print("No occurrences found.")
        print()
    return total_matches_summary


def classify_keywords(enabler_occurrences, enabler_keywords):
    classified_keywords = {enabler: Counter() for enabler in enabler_keywords.keys()}

    for enabler, occurrences in enabler_occurrences.items():
        for _, keyword, _ in occurrences:
            for enabler_key, keywords in enabler_keywords.items():
                if keyword.lower() in [kw.lower() for kw in keywords]:
                    classified_keywords[enabler_key][keyword.lower()] += 1

    return classified_keywords


def main(file_path):
    pdf_text = read_pdf(file_path)

    enabler_keywords = {
        "Naming, identification, and addressing": ["loss of transparency", "lack of addresses",
                                                   "Network Address Translation", "NAT", "loss of provenance",
                                                   "traceability", "addressing limitations", "adequate spaces",
                                                   "address generation", "address integrity", "exponential increase",
                                                   "amount of connected devices", "lack of provenance guarantees",
                                                   "identifier/locator coupling", "corrupted addresses",
                                                   "unique identification", "enough addresses"],
        "Identifier and location splitting": ["identifier/locator coupling", "dual semantics", "ID", "Loc",
                                              "mobile environment", "mobility", "attaching point",
                                              "unique identification", "ID/Loc", "altering identification",
                                              "change in location", "identity loss","location-independent"],
        "Support for heterogeneous networks and adaptive network": ["different technologies",
                                                                    "protocol stack", "adaptability", "flexibility",
                                                                    "emerging paradigms","ICN", "SCN", "SDN",
                                                                    "NFV", "network heterogeneity", "network diversity",
                                                                    "Future Internet", "Information-Centric Networking",
                                                                    "Service-Centric Networking",
                                                                    "data-centric communications",
                                                                    "named data", "content to services",
                                                                    "heterogeneous networks",
                                                                    "heterogeneous stacks",
                                                                    "network adaptability"],
        "Device or asset representation via digital twins": ["digital representation", "proxy service",
                                                             "physical devices", "service layer", "digital twins",
                                                             "physical exposure", "asset exposition",
                                                             "asset representation", "visible industrial asset",
                                                             "virtualized", "gateway services",
                                                             "representing physical assets",
                                                             "representative services", "device mirroring",
                                                             "asset mirroring", "digital twin platform",
                                                             "asset simulation", "asset modeling"],
        "Flexibility, programmability, and self-organization": ["Network Functions Virtualiation", "VNFs",
                                                                "Virtual Network Function",
                                                                "software-defined controllers",
                                                                "programmability", "self-organization",
                                                                "trust formation", "dynamic composeability",
                                                                "contract-based operation",
                                                                "lack of service orientation", "SOA",
                                                                "Service Oriented Architecture", "SBA",
                                                                "Service-Based Architecture", "flexibility",
                                                                "adaptability", "middleware",
                                                                "dynamically combined",
                                                                "composeability",
                                                                "dynamic contracting of services",
                                                                "service lifecycle management",
                                                                "real-time service configuration",
                                                                "service collaboration",
                                                                "business process integration",
                                                                "cloud services", "microservices",
                                                                "orchestration", "service discovery",
                                                                "agile services", "service customization",
                                                                "cross-platform compatibility",
                                                                "reusability", "intelligent services",
                                                                "edge computing services",
                                                                "service management",
                                                                "industrial service integration",
                                                                "service governance", "service mapping",
                                                                "service transformation", "SLA",
                                                                "Service Level Agreement"],
        "Security, privacy, provenance, traceability and trust": ["Name-based security", "formation of trust networks",
                                                                  "self-verifying names",
                                                                  "built-in security mechanisms","security",
                                                                  "trust issues", "privacy", "trust", "cybersecurity",
                                                                  "authentication", "authorization", "data protection",
                                                                  "encryption", "secure communication",
                                                                  "threat detection",
                                                                  "risk management", "compliance", "network security",
                                                                  "identity management", "access control",
                                                                  "security policies", "vulnerability assessment",
                                                                  "incident response", "security architecture",
                                                                  "trust network", "provenance",],
        "Immutability": ["immutability", "blockchain", "smart contract", "decentralized", "DLT", "crypto", "IOTA",
                         "ethereum", "tokenization", "digital merket", "CBDC", "micropayment", "data market",
                         "spectrum market", "things economy", "things market", "infrastructure market",
                         "resource sharing", "virtual function market"],
        "Evolving Quantum technologies": ["quantum", "quantum computing", "quantum communication",
                                          "quantum encryption", "QAC", "QC", "QI", "quantum internet",
                                          "post-quantum"]
    }



    enabler_occurrences = check_enabler_occurrences(pdf_text, enabler_keywords)
    total_matches_summary = print_occurrences(enabler_occurrences)

    classified_keywords = classify_keywords(enabler_occurrences, enabler_keywords)

    if any(enabler_occurrences.values()):
        print("YES")
        print("Keyword Counts:")
        for enabler, keyword_counter in classified_keywords.items():
            if keyword_counter:
                print(f"{enabler}:")
                for keyword, count in keyword_counter.items():
                    print(f"Keyword: {keyword}, Count: {count}")
                print()
        print(f"Total Matches for All Families: {total_matches_summary}")
    else:
        print("NO")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a PDF for mentions of technological enablers")
    parser.add_argument("file_path", help="The path to the PDF file to analyze")
    args = parser.parse_args()
    main(args.file_path)



# Outros conjuntos de habilitadores

    # enabler_keywords = {
    #    "Energy for powering devices": ["energy", "battery", "powering devices", "energy harvesting",
    #                                    "energy efficiency", "green", "green technologies", "wireless energy"],
    #    "Sensing and Actuating for IoT": ["sensing", "actuating", "IoT", "IoT-based", "Internet of Things",
    #                                      "sensor", "actuator", "mMTC"],
    #    "Digital communications for connectivity": ["SATSI", "O-RAN", "coexistence", "frequency", "spectrum",
    #                                                "band", "RAT", "handover", "mobility", "NOMA", "haptic", "uRLLC",
    #                                                "eMBB", "FAB", "haptic protocol", "ultra-dense", "CoMP", "OFDMA",
    #                                                "digital communication", "connectivity", "communication", "network",
    #                                                "OWC", "RAN", "radio access network", "UAV", "Open RAN", "MIMO",
    #                                                "RIS", "THz", "cell free", "VLC", "D2D", "HAP", "intermittent",
    #                                               "delay-awareness", "CoCoCo", "resource allocation",
    #                                               "molecular communications"],
    #    "Softwarization for the software's role in 6G": ["controller", "caching", "cloud", "fog", "edge",
    #                                                     "softwarization", "elasticity", "virtualization",
    #                                                     "network function", "NFV", "SDN", "digital twin",
    #                                                     "avatar", "SOA", "MEC", "slicing", "self-wareness",
    #                                                     "situation awareness", "TS-SDN", "information-centric",
    #                                                     "compute first", "in-network", "intent-based",
    #                                                     "augmented reality", "virtual reality","metaverse"],
    #    "Immutability": ["immutability", "blockchain", "smart contract", "decentralized", "DLT", "crypto", "IOTA",
    #                     "ethereum", "tokenization", "digital merket", "CBDC", "micropayment", "data market",
    #                     "spectrum market", "things economy", "things market", "infrastructure market",
    #                     "resource sharing", "virtual function market"],
    #    "Intelligence for autonomous decision-making": ["intelligence", "AI", "AI-based", "ML", "autonomous",
    #                                                    "decision-making", "autonomic", "SON", "cognitive",
    #                                                    "ZTM", "self-evolving", "self-management", "neuromorphic",
    #                                                    "self-organization", "self-organizing"],
    #    "Intrinsic Security": ["security", "encryption", "privacy", "authentication", "cybersecurity",
    #                           "built-in", "trust", "traceability", "provenance", "secrecy", "criptography",
    #                           "RSA", "elliptic curve", "homomorphic encryption", "identification",
    #                           "self-verifying", "naming", ],
    #    "Evolving Quantum technologies": ["quantum", "quantum computing", "quantum communication",
    #                                      "quantum encryption", "QAC", "QC", "QI", "quantum internet",
    #                                      "post-quantum"]
    # }
