"""Explicit reviewed checkout configuration; absence or invalidity closes checkout."""
import json
import os
from pathlib import Path
from corner import beta_access, beta_terms
from corner.beta_receiving import validate_receivers


def checkout_config():
    path = os.environ.get('CORNER_BILLING_CONFIG')
    if not path or not beta_access.enabled():
        return None
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'))
        validate_receivers(config)
        if (config['payments_enabled'] is not True or config.get('terms_version') != beta_terms.VERSION
                or config.get('manual_review_ready') is not True):
            return None
        return config
    except (OSError, ValueError, KeyError, TypeError):
        return None
