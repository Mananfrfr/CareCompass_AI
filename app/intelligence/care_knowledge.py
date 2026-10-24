"""Curated, conservative care-navigation knowledge.

Maps conditions/symptoms to the *type of service* a person may want to approach.
This is navigation, not diagnosis: it never decides what a person has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Specialty:
    key: str
    label: str
    osm_tags: tuple[str, ...]
    site_keywords: tuple[str, ...]


SPECIALTIES: dict[str, Specialty] = {
    s.key: s
    for s in [
        Specialty("orthopaedics", "Orthopaedics", ("orthopaedics", "orthopedics", "trauma"),
                  ("orthopaedic", "orthopaedics", "orthopedic", "orthopedics", "sports medicine", "sports injury", "arthroscopy", "joint replacement", "ortho")),
        Specialty("urology", "Urology", ("urology",),
                  ("urology", "urologist", "kidney stone", "lithotripsy", "uro")),
        Specialty("ophthalmology", "Ophthalmology (eye care)", ("ophthalmology",),
                  ("ophthalmology", "eye care", "cataract", "retina", "eye hospital")),
        Specialty("cardiology", "Cardiology", ("cardiology", "cardiac_surgery"),
                  ("cardiology", "cardiac", "heart")),
        Specialty("gynaecology", "Obstetrics & Gynaecology", ("gynaecology", "obstetrics", "gynecology"),
                  ("gynaecology", "gynecology", "obstetrics", "maternity")),
        Specialty("gastroenterology", "Gastroenterology", ("gastroenterology",),
                  ("gastroenterology", "gastro", "endoscopy", "liver")),
        Specialty("general_surgery", "General Surgery", ("surgery", "general_surgery"),
                  ("general surgery", "laparoscopic", "hernia")),
        Specialty("neurology", "Neurology", ("neurology", "neurosurgery"),
                  ("neurology", "neuro", "neurosurgery")),
        Specialty("dermatology", "Dermatology", ("dermatology", "dermatovenereology"),
                  ("dermatology", "skin")),
        Specialty("ent", "ENT (Ear, Nose, Throat)", ("otolaryngology", "ent"),
                  ("ent", "otolaryngology", "ear nose throat")),
        Specialty("pulmonology", "Pulmonology (lungs)", ("pulmonology", "pneumology"),
                  ("pulmonology", "chest medicine", "respiratory")),
        Specialty("nephrology", "Nephrology (kidney medicine)", ("nephrology",),
                  ("nephrology", "dialysis", "kidney")),
        Specialty("paediatrics", "Paediatrics", ("paediatrics", "pediatrics"),
                  ("paediatric", "paediatrics", "pediatric", "pediatrics", "child")),
        Specialty("oncology", "Oncology", ("oncology",),
                  ("oncology", "cancer")),
        Specialty("endocrinology", "Endocrinology", ("endocrinology", "diabetology"),
                  ("endocrinology", "diabetes", "thyroid")),
        Specialty("psychiatry", "Psychiatry / Mental health", ("psychiatry",),
                  ("psychiatry", "mental health")),
        Specialty("general_medicine", "General / Internal Medicine", ("general", "internal"),
                  ("general medicine", "internal medicine", "physician")),
    ]
}


@dataclass(frozen=True)
class ConditionRule:
    canonical: str
    patterns: tuple[str, ...]
    specialty: str
    procedure: str | None = None
    rationale: str = ""


CONDITIONS: tuple[ConditionRule, ...] = (
    ConditionRule("ACL tear", (r"\bacl\b", r"anterior cruciate"), "orthopaedics", "ACL reconstruction",
                  "ACL injuries are usually evaluated by orthopaedic / sports-medicine services."),
    ConditionRule("Meniscus tear", (r"menisc",), "orthopaedics", "knee arthroscopy",
                  "Meniscus injuries are handled by orthopaedic services."),
    ConditionRule("Fracture", (r"fractur", r"broken bone"), "orthopaedics", None,
                  "Fractures are managed by orthopaedic services."),
    ConditionRule("Knee osteoarthritis", (r"osteoarthritis", r"knee arthritis"), "orthopaedics", "knee replacement",
                  "Joint arthritis is commonly managed by orthopaedic services."),
    ConditionRule("Slipped disc", (r"slipped disc", r"disc (?:herniation|prolapse|bulge)", r"herniated disc"), "orthopaedics", None,
                  "Spine disc problems are seen by orthopaedic spine or neurosurgery services."),
    ConditionRule("Kidney stone", (r"kidney stone", r"renal (?:stone|calcul)", r"nephrolithiasis", r"ureteric (?:stone|calcul)", r"urolithiasis"),
                  "urology", "lithotripsy / ureteroscopy", "Kidney and ureteric stones are commonly treated by urology."),
    ConditionRule("Enlarged prostate", (r"prostat",), "urology", None, "Prostate problems are handled by urology."),
    ConditionRule("Cataract", (r"cataract",), "ophthalmology", "cataract surgery", "Cataracts are treated by eye specialists."),
    ConditionRule("Glaucoma", (r"glaucoma",), "ophthalmology", None, "Glaucoma is managed by eye specialists."),
    ConditionRule("Gallstones", (r"gall ?stone", r"cholelithiasis", r"gall ?bladder stone"), "general_surgery", "cholecystectomy",
                  "Gallstones are commonly managed by general / laparoscopic surgery."),
    ConditionRule("Hernia", (r"hernia",), "general_surgery", "hernia repair", "Hernias are repaired by general surgeons."),
    ConditionRule("Appendicitis", (r"appendic",), "general_surgery", "appendectomy", "Appendicitis is managed by general surgery."),
    ConditionRule("Heart disease (diagnosed)", (r"coronary artery disease", r"heart block", r"arrhythmia", r"heart failure"),
                  "cardiology", None, "Known heart conditions are followed by cardiology."),
    ConditionRule("Pregnancy", (r"pregnan",), "gynaecology", None, "Pregnancy care is provided by obstetrics."),
    ConditionRule("PCOS", (r"\bpcos\b", r"polycystic ovar"), "gynaecology", None, "PCOS is commonly managed by gynaecology."),
    ConditionRule("Migraine", (r"migraine",), "neurology", None, "Migraine is managed by neurology."),
    ConditionRule("Epilepsy", (r"epilep",), "neurology", None, "Epilepsy is managed by neurology."),
    ConditionRule("Asthma", (r"asthma",), "pulmonology", None, "Asthma is managed by pulmonology / chest medicine."),
    ConditionRule("Diabetes", (r"diabet",), "endocrinology", None, "Diabetes is managed by endocrinology / diabetology."),
    ConditionRule("Thyroid disorder", (r"thyroid",), "endocrinology", None, "Thyroid conditions are managed by endocrinology."),
    ConditionRule("Tonsillitis", (r"tonsil",), "ent", None, "Tonsil problems are handled by ENT."),
    ConditionRule("Sinusitis", (r"sinusit",), "ent", None, "Sinus problems are handled by ENT."),
    ConditionRule("Psoriasis / eczema", (r"psoriasis", r"eczema", r"dermatitis"), "dermatology", None, "Skin conditions are seen by dermatology."),
    ConditionRule("Chronic kidney disease", (r"chronic kidney", r"\bckd\b", r"dialysis"), "nephrology", None,
                  "Chronic kidney disease is managed by nephrology."),
    ConditionRule("Cancer (diagnosed)", (r"cancer", r"carcinoma", r"tumou?r", r"lymphoma"), "oncology", None,
                  "Diagnosed cancers are managed by oncology services."),
)


@dataclass(frozen=True)
class SymptomRule:
    name: str
    patterns: tuple[str, ...]
    specialty: str
    note: str


SYMPTOMS: tuple[SymptomRule, ...] = (
    SymptomRule("knee pain", (r"knee (?:pain|ache|swelling|injur)", r"pain in (?:my |the )?knee"), "orthopaedics",
                "Persistent knee pain is usually first assessed by an orthopaedic doctor."),
    SymptomRule("back pain", (r"back ?(?:pain|ache)", r"pain in (?:my |the )?(?:lower )?back"), "orthopaedics",
                "Back pain is commonly assessed by orthopaedics or a general physician."),
    SymptomRule("joint pain", (r"joint pain", r"shoulder pain", r"hip pain", r"ankle pain"), "orthopaedics",
                "Joint pain is commonly assessed by orthopaedics."),
    SymptomRule("flank pain", (r"flank pain", r"pain (?:on|in) (?:my )?(?:side|flank)"), "urology",
                "Flank pain can have several causes; a urology or general physician assessment is a reasonable start."),
    SymptomRule("blurred vision", (r"blurr(?:ed|y) vision", r"vision (?:loss|problem)", r"eye pain"), "ophthalmology",
                "Vision changes should be checked by an eye specialist."),
    SymptomRule("skin rash", (r"rash", r"itch", r"skin (?:problem|issue)"), "dermatology", "Skin symptoms are assessed by dermatology."),
    SymptomRule("headache", (r"headache",), "neurology", "Recurring headaches can be assessed by a physician or neurologist."),
    SymptomRule("cough", (r"\bcough",), "pulmonology", "A persistent cough can be assessed by a physician or chest specialist."),
    SymptomRule("stomach pain", (r"stomach (?:pain|ache)", r"abdominal pain", r"acidity", r"indigestion"), "gastroenterology",
                "Ongoing stomach symptoms can be assessed by a physician or gastroenterologist."),
    SymptomRule("ear or throat pain", (r"ear ?ache", r"ear pain", r"sore throat", r"hearing"), "ent", "Ear/throat symptoms are assessed by ENT."),
    SymptomRule("fever", (r"fever",), "general_medicine", "Fever is usually first assessed by a general physician."),
)

# Red flags: phrases that should stop routine hospital comparison.
EMERGENCY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"chest (?:pain|tightness|pressure)", "chest pain"),
    (r"heart attack", "possible heart attack"),
    (r"(?:difficulty|trouble|can'?t|cannot|unable to|hard to) (?:breath|breathing|breathe)|short(?:ness)? of breath|breathless", "breathing difficulty"),
    (r"face[^.]{0,15}droop|droop\w*[^.]{0,10}face|slurred|speech[^.]{0,12}(?:slurr|garbled)|"
     r"sudden (?:numbness|weakness|confusion)|weakness on one side|one side of (?:my|the|his|her) (?:body|face)|\bstroke\b",
     "possible stroke signs"),
    (r"unconscious|fainted|passed out|not waking", "loss of consciousness"),
    (r"seizure|convulsion|fits\b", "seizure"),
    (r"severe bleeding|bleeding (?:heavily|a lot|won'?t stop)|vomiting blood|coughing (?:up )?blood", "severe bleeding"),
    (r"suicid|kill myself|end my life|self[- ]harm|overdose", "risk of self-harm"),
    (r"anaphyla|throat (?:is )?(?:swelling|closing)|severe allergic", "severe allergic reaction"),
    (r"poison", "possible poisoning"),
    (r"severe burn", "severe burn"),
    (r"head injury.*(?:vomit|confus|drows)|(?:vomit|confus|drows).*head injury", "head injury with warning signs"),
    (r"pregnan.*bleeding|bleeding.*pregnan", "bleeding in pregnancy"),
)

# Symptoms that need prompt (not ambulance) attention.
PROMPT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"can'?t (?:bear|put) weight|unable to walk", "unable to bear weight"),
    (r"high fever|fever (?:for|since) (?:\d+|three|four|five) days", "persistent high fever"),
    (r"(?:hot|red),? swollen joint|swollen (?:and|,) (?:hot|red)", "hot swollen joint"),
    (r"blood in (?:my )?urine", "blood in urine"),
    (r"sudden (?:vision loss|loss of vision)", "sudden vision change"),
)

SEVERITY_MODIFIERS = r"severe|sudden|crushing|radiating|worst"

CITY_ALIASES: dict[str, str] = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "bombay": "Mumbai", "mumbai": "Mumbai",
    "new delhi": "Delhi", "delhi": "Delhi", "gurgaon": "Gurugram", "gurugram": "Gurugram", "noida": "Noida",
    "jaipur": "Jaipur", "chennai": "Chennai", "madras": "Chennai", "kolkata": "Kolkata", "calcutta": "Kolkata",
    "hyderabad": "Hyderabad", "pune": "Pune", "ahmedabad": "Ahmedabad", "lucknow": "Lucknow", "kanpur": "Kanpur",
    "indore": "Indore", "bhopal": "Bhopal", "chandigarh": "Chandigarh", "kochi": "Kochi", "cochin": "Kochi",
    "coimbatore": "Coimbatore", "nagpur": "Nagpur", "surat": "Surat", "vadodara": "Vadodara", "patna": "Patna",
    "bhubaneswar": "Bhubaneswar", "guwahati": "Guwahati", "dehradun": "Dehradun", "jodhpur": "Jodhpur",
    "udaipur": "Udaipur", "kota": "Kota", "ajmer": "Ajmer", "visakhapatnam": "Visakhapatnam", "vizag": "Visakhapatnam",
    "thiruvananthapuram": "Thiruvananthapuram", "trivandrum": "Thiruvananthapuram", "mysuru": "Mysuru",
    "mysore": "Mysuru", "ludhiana": "Ludhiana", "amritsar": "Amritsar", "varanasi": "Varanasi", "agra": "Agra",
    "faridabad": "Faridabad", "ghaziabad": "Ghaziabad", "raipur": "Raipur", "ranchi": "Ranchi", "madurai": "Madurai",
    "nashik": "Nashik", "thane": "Thane", "navi mumbai": "Navi Mumbai", "mangaluru": "Mangaluru", "mangalore": "Mangaluru",
}

INSURER_ALIASES: dict[str, str] = {
    "acko": "ACKO", "navi insurance": "Navi", "zuno": "Zuno", "edelweiss general": "Zuno",
    "chola ms": "Cholamandalam MS", "cholamandalam": "Cholamandalam MS",
    "royal sundaram": "Royal Sundaram", "shriram general": "Shriram General",
    "raheja qbe": "Raheja QBE", "liberty general": "Liberty General",
    "future generali": "Future Generali", "iffco tokio": "IFFCO Tokio",
    "universal sompo": "Universal Sompo", "go digit": "Go Digit",
    "star health": "Star Health", "hdfc ergo": "HDFC ERGO", "icici lombard": "ICICI Lombard",
    "niva bupa": "Niva Bupa", "max bupa": "Niva Bupa", "care health": "Care Health", "religare": "Care Health",
    "bajaj allianz": "Bajaj Allianz", "tata aig": "Tata AIG", "aditya birla": "Aditya Birla Health",
    "manipalcigna": "ManipalCigna", "manipal cigna": "ManipalCigna", "new india assurance": "New India Assurance",
    "united india": "United India Insurance", "oriental insurance": "Oriental Insurance",
    "national insurance": "National Insurance", "sbi general": "SBI General", "reliance general": "Reliance General",
    "ayushman bharat": "Ayushman Bharat PM-JAY", "pm-jay": "Ayushman Bharat PM-JAY", "pmjay": "Ayushman Bharat PM-JAY",
    "cghs": "CGHS", "echs": "ECHS",
    # Synthetic insurers used only by fixture mode.
    "demo shield": "Demo Shield Insurance", "sample care health": "Sample Care Health", "sample care": "Sample Care Health",
}

NO_INSURANCE_PATTERNS = (
    r"\bno (?:health )?insurance\b", r"\bdon'?t have (?:any )?(?:health )?insurance\b", r"\bwithout insurance\b",
    r"\buninsured\b", r"\bnot insured\b", r"\bself[- ]pay\b", r"^\s*(?:none|no|nope|skip)\s*[.!]?\s*$",
)


def find_condition(text: str) -> ConditionRule | None:
    low = text.lower()
    for rule in CONDITIONS:
        if any(re.search(p, low) for p in rule.patterns):
            return rule
    return None


def find_symptoms(text: str) -> list[SymptomRule]:
    low = text.lower()
    return [s for s in SYMPTOMS if any(re.search(p, low) for p in s.patterns)]


def normalize_city(raw: str | None) -> str | None:
    if not raw:
        return None
    return CITY_ALIASES.get(raw.strip().lower())


def find_city(text: str) -> str | None:
    low = text.lower()
    # Longest alias first so "navi mumbai" wins over "mumbai".
    for alias in sorted(CITY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return CITY_ALIASES[alias]
    return None


_PLACE_CUE = re.compile(r"\b(?:in|near|at|around|from|city|live in|based in|staying in)\s+([a-z][a-z.]+(?:\s[a-z]+)?)", re.I)
_NOT_PLACES = {"pain", "my", "the", "a", "an", "india", "hospital", "knee", "back", "case", "fact", "time", "general",
               "need", "network", "touch", "person", "addition", "private", "government", "the hospital"}


def find_directory_city(text: str) -> str | None:
    """Any Indian district/town from the national hospital directory, when introduced by a place cue
    ("in Pali", "near Bhilwara"). Keeps CareCompass usable beyond the big-city alias list."""
    try:
        from app.research.india_directory import get_directory
        directory = get_directory()
    except Exception:  # noqa: BLE001 - directory is optional
        return None
    for m in _PLACE_CUE.finditer(text):
        words = m.group(1).split()
        for cand in (" ".join(words[:2]), words[0]):
            if cand.lower() in _NOT_PLACES:
                continue
            city = directory.known_city(cand)
            if city:
                return city
    return None


def find_insurer(text: str) -> str | None:
    low = text.lower()
    for alias in sorted(INSURER_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return INSURER_ALIASES[alias]
    return None


def declines_insurance(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in NO_INSURANCE_PATTERNS)


@dataclass
class SpecialtyGuess:
    specialty: str
    rationale: str
    procedure: str | None = None
    condition: str | None = None
    symptoms: list[str] = field(default_factory=list)
