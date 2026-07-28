"""Labelled calibration corpus.

Every profile here is FICTIONAL — invented names, invented companies, invented
identifiers. They exist to pin the scoring bands so a change to the keyword
banks or weights cannot silently move the verdicts.

Each entry: (id, text, expected_levels). A test asserts the audit lands in one
of the expected bands; adjacent bands are allowed where a profile is genuinely
borderline, because pretending this instrument is precise to the point would be
dishonest.
"""

CORPUS = [
    (
        "pure-larp",
        "Visionary Founder and President of NimbusForge. Building revolutionary, "
        "game-changing, groundbreaking dual-use deep tech artificial intelligence. "
        "A true paradigm shift in radiation-tolerant edge AI hardware. MoU signed, "
        "NDA in place, discussions ongoing with several major players. Seeking "
        "investment to join our moonshot. MSc in European public health policy. "
        "Founder of AetherLink. Partnership with AetherLink announced last month. "
        "Thought leader, world class team, patent pending, product coming soon.",
        {"RED"},
    ),
    (
        "solid-engineer",
        "CTO at Marrow Robotics. MSc Electrical Engineering, Delft University of "
        "Technology, 2015. Previously research scientist at a national microelectronics "
        "institute and an engineer on lithography tooling. Co-authored 12 peer-reviewed "
        "papers, holder of patent US10123456. Our robots are deployed in production at "
        "40 customers and generated 2.1M revenue in 2024. Code at "
        "github.com/marrowrobotics/underwater-slam. Funded by a national innovation "
        "grant and under contract with the Port of Rotterdam.",
        {"GREEN"},
    ),
    (
        "policy-person-honest",
        "Secretary General of the Fictional Rare Disease Alliance. MSc Public Health, "
        "University of Ghent, 2009. Fifteen years in patient advocacy and health policy. "
        "I do not build technology; I represent patient interests in regulatory "
        "consultations. Our position papers are published in the association journal, "
        "and I was interviewed by a national broadcaster about access to treatment.",
        {"GREEN", "YELLOW"},
    ),
    (
        "borderline-founder",
        "Co-founder of Halcyon Bio. Bachelor of Science in biology, Fictional State "
        "University, 2018. We are developing a diagnostic assay and are raising a seed "
        "round. Early pilot deployed with one hospital partner. No publications yet. "
        "Collaboration agreement with Meridian Labs. Our approach is innovative and we "
        "believe it is transformative for the field.",
        {"YELLOW", "ORANGE", "GREEN"},
    ),
    (
        "logo-wall",
        "President of Vantage Quantum Alliance. We are building quantum-secure "
        "satellite communications, a truly next generation and world class capability. "
        "Partnership with Orion Systems. Partnership with Caldera Group. Collaboration "
        "with Ridgeway Institute. Alliance with Northwind Labs. Consortium with Solaris "
        "Federation. MoU with two more organisations, NDA in place, exploratory talks "
        "ongoing. Seeking funding. MBA in international relations.",
        {"RED", "ORANGE"},
    ),
    (
        "too-short",
        "Founder. Building things. Ask me about AI.",
        {"INSUFFICIENT DATA"},
    ),
    (
        "impossible-timeline",
        "Founder and CEO of Cobalt Aerospace. 40 years of experience in satellite "
        "propulsion and machine learning. MSc Aerospace Engineering, Fictional Technical "
        "University, 2019. Building next generation orbital hardware. Patent pending. "
        "Seeking investment.",
        {"YELLOW", "ORANGE", "RED"},
    ),
    (
        "academic-no-hype",
        "Postdoctoral researcher in computational biology at a university hospital. "
        "PhD in bioinformatics, University of Uppsala, 2020. Published in peer-reviewed "
        "journals; see arxiv.org/abs/2101.00001 and orcid.org/0000-0002-1825-0097. "
        "Co-authored joint research with two clinical groups. Funded by a national "
        "research grant of 400k awarded in 2022.",
        {"GREEN"},
    ),
]
