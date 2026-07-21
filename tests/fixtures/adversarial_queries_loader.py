from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

FIXTURES_DIR = Path(__file__).resolve().parent

AdversarialCategory = Literal[
    "prompt_injection", "pii_disclosure", "hallucination_bait", "output_policy_probe"
]
ExpectedBehavior = Literal[
    "blocked_at_input", "redacted_at_input", "refuse_when_absent", "output_policy_risk"
]


class AdversarialQuery(BaseModel):
    id: str
    text: str
    category: AdversarialCategory
    expected_behavior: ExpectedBehavior
    expected_reason_code: str | None = None
    domain: str | None = None


def load_adversarial_queries() -> list[AdversarialQuery]:
    content = yaml.safe_load((FIXTURES_DIR / "adversarial_queries.yaml").read_text())
    return [AdversarialQuery(**entry) for entry in content["adversarial_queries"]]
