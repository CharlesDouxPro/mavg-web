"""La configuration du service, lue dans l'environnement.

Mêmes noms de variables que le worker (`mavg`) : une seule chaîne de connexion et les
mêmes clés de stockage pour les deux, et par défaut la collection que son `main.py`
consomme.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    mongo_connection_string: str = ""
    mongo_database: str = ""
    mongo_collection: str = "tasks"
    """La file que le worker consomme : un run lancé ici y arrive en `pending`."""
    channels_collection: str = "channels"
    """Les configs de base, éditées en place depuis l'onglet Channels."""
    assistant_collection: str = "assistant_sessions"
    """Les conversations de l'onglet Assistant : le fil, le brouillon, les cartes."""
    assistant_model: str = "claude-opus-4-7-1"
    """Le déploiement Foundry qui fait parler l'assistant."""
    static_dir: Path = ROOT / "frontend" / "dist"
    """Le build du front. Absent en dev : Vite le sert lui-même."""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    auth_user: str = ""
    auth_password: str = ""
    auth_disabled: bool = False
    """Poste de dev uniquement : sans identifiants, le service refuse de démarrer."""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mongo_connection_string=os.getenv("MONGO_CONNECTION_STRING", ""),
            mongo_database=os.getenv("MONGO_PLATFORM_DATABASE_NAME", ""),
            mongo_collection=os.getenv("MONGO_COLLECTION", "tasks"),
            channels_collection=os.getenv("MONGO_CHANNELS_COLLECTION", "channels"),
            assistant_collection=os.getenv("MONGO_ASSISTANT_COLLECTION", "assistant_sessions"),
            assistant_model=os.getenv("ASSISTANT_MODEL", "claude-opus-4-7-1"),
            static_dir=Path(os.getenv("STATIC_DIR", ROOT / "frontend" / "dist")),
            s3_access_key=os.getenv("SCW_ACCESS_KEY", ""),
            s3_secret_key=os.getenv("SCW_SECRET_KEY", ""),
            auth_user=os.getenv("WEB_USER", ""),
            auth_password=os.getenv("WEB_PASSWORD", ""),
            auth_disabled=os.getenv("AUTH_DISABLED") == "1",
        )

    @property
    def mongo_configured(self) -> bool:
        return bool(self.mongo_connection_string and self.mongo_database)
