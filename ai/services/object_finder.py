import re

from config import SUPPORTED_CLASSES


def find_target_classes(query):
    normalized = re.sub(r"[^a-z0-9 ]", " ", query.lower())
    normalized = re.sub(
        r"^(where is|where are|where s|can you find|please find|find|locate|look for|search for)\s+",
        "",
        normalized.strip(),
    )
    normalized = re.sub(r"^(my|the|a|an)\s+", "", normalized).strip()
    aliases = {
        "bag": {"backpack", "handbag", "suitcase"},
        "handbag": {"handbag", "backpack"},
        "sofa": {"couch"},
        "couch": {"couch"},
        "table": {"dining table"},
        "water bottle": {"bottle"},
        "bottle": {"bottle"},
        "chair": {"chair"},
        "plant": {"potted plant"},
        "backpack": {"backpack"},
        "suitcase": {"suitcase"},
    }
    if normalized in aliases:
        return normalized, aliases[normalized]
    if normalized in SUPPORTED_CLASSES:
        return normalized, {normalized}
    return normalized, set()
