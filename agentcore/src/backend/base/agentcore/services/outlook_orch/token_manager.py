"""
Secure Outlook Token Manager — verbatim port of MiBuddy's token manager.

Stores Fernet-encrypted access tokens in-memory keyed by user_id. Tokens
are never exposed to the client; the frontend only gets an
`outlook_session` cookie that maps to the server-side user.

For production, consider migrating to a secure database / Key Vault.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


def _get_or_generate_encryption_key() -> bytes:
    """Fetch the Fernet key from env, or derive one via PBKDF2 for dev.

    Env var precedence (so this works with MiBuddy-style configs too):
      1. OUTLOOK_TOKEN_ENCRYPTION_KEY (agentcore naming)
      2. TOKEN_ENCRYPTION_KEY         (MiBuddy naming)
    """
    key = (
        os.environ.get("OUTLOOK_TOKEN_ENCRYPTION_KEY")
        or os.environ.get("TOKEN_ENCRYPTION_KEY")
    )
    if key:
        logger.info("Using OUTLOOK_TOKEN_ENCRYPTION_KEY from environment")
        return key.encode()

    secret = os.environ.get(
        "TOKEN_ENCRYPTION_SECRET", "agentcore-orch-default-secret-change-me",
    )
    salt = os.environ.get("TOKEN_ENCRYPTION_SALT", "agentcore-orch-salt-2026")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt.encode(), iterations=100000,
    )
    derived = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    logger.warning(
        "Using derived Outlook token encryption key. "
        "Set OUTLOOK_TOKEN_ENCRYPTION_KEY for production.",
    )
    return derived


class OutlookTokenManager:
    """Manages Fernet-encrypted in-memory access-token storage."""

    def __init__(self) -> None:
        self._token_store: Dict[str, Dict[str, Any]] = {}
        self._expired_users: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._cipher = Fernet(_get_or_generate_encryption_key())
        logger.info("Outlook (orch) token manager initialized with encryption enabled")

    def store_token(
        self, user_id: str, access_token: str, expires_in: int = 3600,
    ) -> bool:
        try:
            if not user_id or not access_token:
                logger.warning("Cannot store token: missing user_id or access_token")
                return False
            encrypted = self._cipher.encrypt(access_token.encode()).decode()
            expiry = datetime.utcnow() + timedelta(seconds=expires_in)
            with self._lock:
                self._token_store[user_id] = {
                    "token": encrypted,
                    "created_at": datetime.utcnow(),
                    "expires_at": expiry,
                }
                self._expired_users.pop(user_id, None)
            logger.info(f"Stored encrypted Outlook token for user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error storing token for user {user_id}: {e}")
            return False

    def get_token(self, user_id: str) -> Optional[str]:
        try:
            if not user_id:
                return None
            with self._lock:
                data = self._token_store.get(user_id)
            if not data:
                return None
            return self._cipher.decrypt(data["token"].encode()).decode()
        except Exception as e:
            logger.error(f"Error retrieving token for user {user_id}: {e}")
            return None

    def delete_token(self, user_id: str) -> bool:
        try:
            with self._lock:
                if user_id in self._token_store:
                    del self._token_store[user_id]
                    logger.info(f"Removed Outlook token for user: {user_id}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error deleting token for user {user_id}: {e}")
            return False

    def was_token_expired(self, user_id: str) -> bool:
        return bool(user_id and user_id in self._expired_users)

    def is_connected(self, user_id: str) -> bool:
        try:
            if not user_id:
                return False
            with self._lock:
                data = self._token_store.get(user_id)
                if not data:
                    return False
                if datetime.utcnow() >= data["expires_at"]:
                    self._expired_users[user_id] = datetime.utcnow()
                    del self._token_store[user_id]
                    return False
                return True
        except Exception as e:
            logger.error(f"Error checking connection for user {user_id}: {e}")
            return False

    def get_token_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._lock:
                data = self._token_store.get(user_id)
            if not data:
                return None
            return {
                "user_id": user_id,
                "created_at": data["created_at"].isoformat(),
                "expires_at": data["expires_at"].isoformat(),
                "is_expired": datetime.utcnow() >= data["expires_at"],
                "time_remaining_seconds": (
                    data["expires_at"] - datetime.utcnow()
                ).total_seconds(),
            }
        except Exception as e:
            logger.error(f"Error getting token info for user {user_id}: {e}")
            return None


# Global singleton used throughout the backend
outlook_token_manager = OutlookTokenManager()

__all__ = ["OutlookTokenManager", "outlook_token_manager"]
