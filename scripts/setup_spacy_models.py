"""
Setup script to download spaCy language models for multilingual PHI redaction.

This script downloads Swedish and English spaCy models required by Presidio.
Run this after installing dependencies.
"""

import subprocess
import sys
from optimed.core.logging_utils import get_logger

logger = get_logger(__name__)


def download_model(model_name: str) -> bool:
    """
    Download a spaCy model.

    Args:
        model_name: Name of the spaCy model to download

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Downloading spaCy model: {model_name}")
        subprocess.check_call([sys.executable, "-m", "spacy", "download", model_name])
        logger.info(f"Successfully downloaded: {model_name}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to download {model_name}: {e}")
        return False


def main():
    """Download all required spaCy models."""
    logger.info("Starting spaCy model downloads for multilingual PHI redaction...")

    models = [
        "sv_core_news_sm",  # Swedish small model
        "en_core_web_sm",   # English small model
    ]

    success_count = 0
    for model in models:
        if download_model(model):
            success_count += 1

    logger.info(f"Downloaded {success_count}/{len(models)} models successfully")

    if success_count < len(models):
        logger.warning("Some models failed to download. PHI redaction may not work for all languages.")
        sys.exit(1)
    else:
        logger.info("All spaCy models downloaded successfully!")


if __name__ == "__main__":
    main()
