import logging
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings

log = logging.getLogger("ms3.security")
bearer = HTTPBearer(auto_error=True)


def _load_public_key() -> str | None:
    path = settings.jwt_public_key_path
    if path.startswith("file:"):
        path = path[5:]
    p = Path(path)
    if not p.exists():
        log.warning(
            "Clave publica JWT no encontrada en '%s'. "
            "Copia ms1-empresarial/keys/public.pem a ms3-operativo/keys/public.pem",
            path,
        )
        return None
    return p.read_text()


# Se carga una vez al iniciar. Si falta, los endpoints protegidos responden 503.
_PUBLIC_KEY = _load_public_key()


def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if _PUBLIC_KEY is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "JWT no configurado en el servidor"
        )
    try:
        # No validamos audiencia (los 3 MS comparten el token de MS1).
        # verify_sub=False: MS1 emite 'sub' (userId) como numero, no string.
        payload = jwt.decode(
            cred.credentials,
            _PUBLIC_KEY,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False, "verify_sub": False},
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Token invalido: {e}")
    return payload  # claims: sub (userId), rol, exp, ...


# Token crudo (para reenviarlo a MS1/MS2 en llamadas inter-servicio).
def get_current_token(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    return cred.credentials


# Factory de dependencia que exige uno de los roles dados.
def require_roles(*roles: str):
    def checker(user: dict = Depends(get_current_user)) -> dict:
        if roles and user.get("rol") not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Sin permiso para esta operacion"
            )
        return user

    return checker
