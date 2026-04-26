from __future__ import annotations
import base64
import json
import time
from dataclasses import dataclass
from datetime import timedelta
from os import environ
from pathlib import Path
from requests import Session, request
from requests.exceptions import HTTPError
from typing import Any, Callable, Optional, TypeAlias

from tiddl.core.auth.exceptions import AuthClientError


@dataclass
class TidalCredentials:
    """TIDAL Credentials with validation"""
    client_id: str
    client_secret: str
    
    def __post_init__(self):
        if not self.client_id or not self.client_secret:
            raise ValueError("client_id and client_secret are required")
    
    @classmethod
    def from_env(cls, env_key: str = "TIDDL_AUTH") -> "TidalCredentials":
        """Carga credenciales desde variable de entorno"""
        env_value = environ.get(env_key)
        if not env_value:
            raise ValueError(f"Environment variable {env_key} not found")
        
        try:
            client_id, client_secret = env_value.split(";")
            return cls(client_id, client_secret)
        except ValueError:
            raise ValueError(
                f"Invalid format for {env_key}. "
                "Expected format: client_id;client_secret"
            )
    
    @classmethod
    def from_base64(cls, encoded: str) -> "TidalCredentials":
        """Carga credenciales desde string base64"""
        try:
            decoded = base64.b64decode(encoded).decode()
            client_id, client_secret = decoded.split(";")
            return cls(client_id, client_secret)
        except Exception as e:
            raise ValueError(f"Failed to decode credentials: {e}")
    
    def to_tuple(self) -> tuple[str, str]:
        """Retorna como tupla para compatibilidad"""
        return (self.client_id, self.client_secret)


@dataclass
class TidalToken:
    """TIDAL Token with expiration handling"""
    access_token: str
    refresh_token: Optional[str] = None
    expires_in: int = 604800  # 7 days by default
    created_at: float | None = None  # Unix timestamp
    user_data: Optional[dict] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
    
    @property
    def expires_at(self) -> float:
        """Timestamp de cuando expira el token"""
        return (self.created_at or time.time()) + self.expires_in
    
    @property
    def is_expired(self) -> bool:
        """Check if token already expired"""
        return time.time() >= self.expires_at
    
    def expires_soon(self, threshold_seconds: int = 3600) -> bool:
        """
        Verifica si el token expira pronto
        
        Args:
            threshold_seconds: Seconds before expiration (default: 1 hour)
        """
        return (self.expires_at - time.time()) < threshold_seconds
    
    @property
    def time_remaining(self) -> timedelta:
        """Time remaining before expiration"""
        seconds = max(0, self.expires_at - time.time())
        return timedelta(seconds=seconds)
    
    def to_dict(self) -> dict:
        """Serializa a diccionario para guardar"""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "created_at": self.created_at,
            "user_data": self.user_data,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TidalToken":
        """Carga desde diccionario"""
        return cls(**data)
    
    @classmethod
    def from_api_response(cls, response: dict) -> "TidalToken":
        """Crea token desde respuesta de la API de TIDAL"""
        return cls(
            access_token=response["access_token"],
            refresh_token=response.get("refresh_token"),
            expires_in=response.get("expires_in", 604800),
            user_data=response.get("user"),
        )


class TokenStorage:
    """Almacenamiento seguro de tokens en disco"""
    
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
    
    def save(self, token: TidalToken) -> None:
        """Guarda token en disco"""
        self.storage_path.write_text(
            json.dumps(token.to_dict(), indent=2)
        )
        # Establecer permisos restrictivos (solo lectura para el usuario)
        try:
            self.storage_path.chmod(0o600)
        except Exception:
            # On Windows chmod has limited effect, but should not fail
            pass
    
    def load(self) -> Optional[TidalToken]:
        """Carga token desde disco"""
        if not self.storage_path.exists():
            return None
        
        try:
            data = json.loads(self.storage_path.read_text())
            token = TidalToken.from_dict(data)
            
            # Check if expired
            if token.is_expired:
                return None
            
            return token
        except Exception as e:
            # Si hay error (archivo corrupto, etc), mejor retornar None
            return None
    
    def clear(self) -> None:
        """Elimina token guardado"""
        if self.storage_path.exists():
            self.storage_path.unlink()


def get_auth_credentials() -> tuple[str, str]:
    # Default credentials (base64 encoded)
    DEFAULT_B64 = "ZlgySnhkbW50WldLMGl4VDsxTm45QWZEQWp4cmdKRkpiS05XTGVBeUtHVkdtSU51WFBQTEhWWEF2eEFnPQ=="

    try:
        # Try to load from environment variable first
        creds = TidalCredentials.from_env()
    except ValueError:
        # Fallback to default credentials
        creds = TidalCredentials.from_base64(DEFAULT_B64)

    return creds.to_tuple()


AUTH_URL = "https://auth.tidal.com/v1/oauth2"
CLIENT_ID, CLIENT_SECRET = get_auth_credentials()

# TV device flow credentials (same client used by OrpheusDL TV session)
TV_CREDENTIALS = TidalCredentials(
    client_id="4N3n6Q1x95LL5K7p",
    client_secret="oKOXfJW371cX6xaZ0PyhgGNBdNLlBZd4AKKYougMjik=",
)


def get_auth_client_for(client_id: str | None) -> "AuthClient":
    """Returns the right AuthClient based on the client_id stored in auth.json."""
    if client_id and client_id == TV_CREDENTIALS.client_id:
        return AuthClient(credentials=TV_CREDENTIALS)
    return AuthClient()

JSON: TypeAlias = dict[str, Any]


class AuthClientImproved:
    """
    Enhanced authentication client with:
    - Automatic token management
    - Persistencia en disco
    - Auto-refresh
    - Mejor manejo de errores
    """
    
    def __init__(
        self,
        credentials: Optional[TidalCredentials] = None,
        token_storage: Optional[TokenStorage] = None,
    ):
        # Cargar credenciales
        if credentials is None:
            # Primero intentar desde env, luego desde base64 hardcoded
            try:
                credentials = TidalCredentials.from_env()
            except ValueError:
                # Fallback a credenciales hardcoded
                credentials = TidalCredentials.from_base64(
                    "ZlgySnhkbW50WldLMGl4VDsxTm45QWZEQWp4cmdKRkpiS05XTGVBeUtHVkdtSU51WFBQTEhWWEF2eEFnPQ=="
                )
        
        self.auth_url = AUTH_URL
        self.credentials = credentials
        self.token_storage = token_storage
        self.session = Session()
        
        # Token actual
        self._current_token: Optional[TidalToken] = None
        
        # Intentar cargar token guardado
        if token_storage:
            self._current_token = token_storage.load()
    
    @property
    def current_token(self) -> Optional[TidalToken]:
        """Retorna el token actual (auto-refresh si es necesario)"""
        if self._current_token and self._current_token.expires_soon():
            # Intentar refrescar silenciosamente
            try:
                self.refresh_current_token()
            except Exception:
                # Si falla el refresh, seguimos retornando el actual
                pass
        
        return self._current_token
    
    def refresh_token(self, refresh_token: Optional[str] = None) -> TidalToken:
        """
        Refresca un token usando refresh_token
        
        Args:
            refresh_token: Token de refresh (usa el actual si es None)
        
        Returns:
            Nuevo TidalToken
        """
        token_to_use = refresh_token
        
        # Si no se proporciona, usar el del token actual
        if token_to_use is None and self._current_token:
            token_to_use = self._current_token.refresh_token
        
        if not token_to_use:
            raise ValueError("No refresh_token available")
        
        res = self.session.post(
            f"{self.auth_url}/token",
            data={
                "client_id": self.credentials.client_id,
                "refresh_token": token_to_use,
                "grant_type": "refresh_token",
                "scope": "r_usr+w_usr+w_sub",
            },
            auth=self.credentials.to_tuple(),
        )
        
        try:
            res.raise_for_status()
        except HTTPError as e:
            try:
                error_data = e.response.json()
                raise AuthClientError(**error_data)
            except Exception:
                raise AuthClientError(
                    status=e.response.status_code,
                    error="refresh_failed",
                    error_description=str(e)
                )
        
        json_data = res.json()
        
        # Preservar refresh token si no viene uno nuevo
        if "refresh_token" not in json_data and token_to_use:
            json_data["refresh_token"] = token_to_use

        # Crear nuevo token
        token = TidalToken.from_api_response(json_data)
        self._current_token = token
        
        # Guardar en disco
        if self.token_storage:
            self.token_storage.save(token)
        
        return token
    
    def refresh_current_token(self) -> TidalToken:
        """Refresca el token actual (atajo)"""
        return self.refresh_token()

    def logout(self, access_token: Optional[str] = None) -> None:
        """
        Close session and clean saved tokens
        
        Args:
            access_token: Token a cerrar (usa el actual si es None)
        """
        token_to_use = access_token
        
        if token_to_use is None and self._current_token:
            token_to_use = self._current_token.access_token
        
        if not token_to_use:
            return  # Nada que cerrar
        
        try:
            res = self.session.post(
                "https://api.tidal.com/v1/logout",
                headers={"authorization": f"Bearer {token_to_use}"},
            )
            res.raise_for_status()
        except Exception as e:
            print(f"Warning: Logout request failed: {e}")
        
        # Limpiar token local y en disco
        self._current_token = None
        if self.token_storage:
            self.token_storage.clear()

    def start_device_auth(self) -> dict:
        """
        Inicia el Device Flow de OAuth2
        
        Returns:
            dict con deviceCode, userCode, verificationUri, etc.
        """
        try:
            res = self.session.post(
                f"{self.auth_url}/device_authorization",
                data={
                    "client_id": self.credentials.client_id,
                    "scope": "r_usr+w_usr+w_sub"
                },
            )
            res.raise_for_status()
            return res.json()
        except HTTPError as e:
            raise AuthClientError(
                status=e.response.status_code,
                error="device_auth_failed",
                error_description=str(e)
            )
    
    def poll_device_auth(
        self,
        device_code: str,
        interval: int = 2,
        timeout: int = 300,
        on_pending: Optional[Callable[[int, dict], None]] = None,
    ) -> TidalToken:
        """
        Polls to get token after Device Flow
        
        Args:
            device_code: Device code obtained from start_device_auth
            interval: Segundos entre cada intento (default: 2)
            timeout: Timeout total en segundos (default: 300 = 5 min)
            on_pending: Callback llamado en cada intento pendiente
        
        Returns:
            TidalToken con access_token y refresh_token
        
        Raises:
            AuthClientError: If authentication fails or timeout
        """
        start_time = time.time()
        attempt = 0
        
        while True:
            attempt += 1
            
            # Verificar timeout
            if time.time() - start_time > timeout:
                raise AuthClientError(
                    status=408,
                    error="timeout",
                    error_description=f"Device authorization timed out after {timeout}s"
                )
            
            try:
                res = self.session.post(
                    f"{self.auth_url}/token",
                    data={
                        "client_id": self.credentials.client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "scope": "r_usr+w_usr+w_sub",
                    },
                    auth=self.credentials.to_tuple(),
                )
                
                json_data = res.json()
                
                # Éxito!
                if res.status_code == 200:
                    token = TidalToken.from_api_response(json_data)
                    self._current_token = token
                    
                    # Save to disk if storage is available
                    if self.token_storage:
                        self.token_storage.save(token)
                    
                    return token
                
                # Still pending
                if res.status_code == 400 and json_data.get("error") == "authorization_pending":
                    if on_pending:
                        on_pending(attempt, json_data)
                    
                    time.sleep(interval)
                    continue
                
                # Error
                if res.status_code != 200:
                     raise AuthClientError(**json_data)
                
            except HTTPError as e:
                # Handle HTTP errors
                try:
                    error_data = e.response.json()
                    raise AuthClientError(**error_data)
                except Exception:
                    raise AuthClientError(
                        status=e.response.status_code,
                        error="http_error",
                        error_description=str(e)
                    )
            except AuthClientError:
                raise
            except Exception as e:
                 raise AuthClientError(
                    status=500,
                    error="unknown_error",
                    error_description=str(e)
                )

    def device_flow(
        self,
        open_browser: bool = True,
        on_progress: Optional[Callable[[int, int], None]] = None
    ) -> TidalToken:
        """
        Complete device authentication flow with improved UX.
        
        Args:
            open_browser: Whether to open browser automatically
            on_progress: Callback opcional (tiempo_transcurrido, tiempo_total)
            
        Returns:
            Valid TidalToken
        """
        # 1. Start authorization
        auth_data = self.start_device_auth()
        verification_uri = auth_data['verificationUri']
        user_code = auth_data['userCode']
        device_code = auth_data['deviceCode']
        expires_in = auth_data['expiresIn']
        interval = auth_data.get('interval', 5)
        
        # 2. Mostrar instrucciones
        print(f"\n{'-'*50}")
        print("TIDAL DEVICE AUTHORIZATION")
        print(f"{'-'*50}")
        print(f"1. Visita: {verification_uri}")
        print(f"2. Enter the code: {user_code}")
        print(f"{'-'*50}")
        
        # 3. Abrir navegador si se solicita
        if open_browser:
            print("Abriendo navegador...")
            try:
                import webbrowser
                webbrowser.open(f"https://{verification_uri}/{user_code}" if 'http' not in verification_uri else verification_uri)
            except Exception as e:
                print(f"No se pudo abrir el navegador: {e}")

        # 4. Polling with feedback
        print("\nWaiting for authorization (Ctrl+C to cancel)...")
        
        def _default_progress(elapsed: int, total: int):
            remaining = total - elapsed
            bars = 20
            filled = int((elapsed / total) * bars)
            bar = '█' * filled + '░' * (bars - filled)
            print(f"\rWaiting... [{bar}] {remaining}s remaining", end='', flush=True)

        callback = on_progress or _default_progress
        
        try:
            token = self.poll_device_auth(
                device_code=device_code,
                interval=interval,
                timeout=expires_in,
                on_pending=lambda attempt, _: callback(attempt * interval, expires_in)
            )
            print("\n\nAuthentication successful! ✅")
            return token
            
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
            raise
        except Exception as e:
            print(f"\n\nAuthentication error: {e}")
            raise


class AuthClient:

    def __init__(self, credentials: TidalCredentials | None = None) -> None:
        self.auth_url = AUTH_URL
        if credentials is not None:
            self.client_id = credentials.client_id
            self.client_secret = credentials.client_secret
        else:
            self.client_id = CLIENT_ID
            self.client_secret = CLIENT_SECRET

    def get_device_auth(self) -> JSON:
        res = request(
            "POST",
            f"{self.auth_url}/device_authorization",
            data={"client_id": self.client_id, "scope": "r_usr+w_usr+w_sub"},
        )

        res.raise_for_status()

        return res.json()

    def get_auth(self, device_code: str) -> JSON:
        res = request(
            "POST",
            f"{self.auth_url}/token",
            data={
                "client_id": self.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "scope": "r_usr+w_usr+w_sub",
            },
            auth=(self.client_id, self.client_secret),
        )

        json_data = res.json()

        if res.status_code != 200:
            raise AuthClientError(**json_data)

        return json_data

    def refresh_token(self, refresh_token: str) -> JSON:
        res = request(
            "POST",
            f"{self.auth_url}/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

        res.raise_for_status()

        return res.json()

    def logout_token(self, access_token: str) -> None:
        res = request(
            "POST",
            "https://api.tidal.com/v1/logout",
            headers={"authorization": f"Bearer {access_token}"},
        )

        res.raise_for_status()
