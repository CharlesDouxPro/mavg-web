"""La configuration du service, lue dans l'environnement.

Mêmes noms de variables que le worker (`mavg`) : une seule chaîne de connexion
pour les deux, et par défaut la collection que son `main.py` consomme.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    mongo_connection_string: str
    mongo_database: str
    mongo_collection: str
    templates_dir: Path
    static_dir: Path
    """Le build du front (`frontend/dist`). Absent en dev : Vite le sert lui-même."""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mongo_connection_string=os.getenv("MONGO_CONNECTION_STRING", ""),
            mongo_database=os.getenv("MONGO_PLATFORM_DATABASE_NAME", ""),
            mongo_collection=os.getenv("MONGO_COLLECTION", "tasks"),
            templates_dir=Path(os.getenv("TEMPLATES_DIR", ROOT / "templates")),
            static_dir=Path(os.getenv("STATIC_DIR", ROOT / "frontend" / "dist")),
        )
