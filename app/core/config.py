from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    port: int = 8000
    cors_origins: str = "http://localhost:4200"

    # Base de datos (database-per-service). Default SQLite para correr sin setup.
    # Postgres independiente: postgresql+psycopg://user:pass@host:5432/ms3_operativo
    database_url: str = "sqlite:///./ms3_local.db"

    # JWT: valida tokens emitidos por MS1 (RS256) con su clave publica.
    # Cloud: contenido PEM en env JWT_PUBLIC_KEY (prioridad). Local: archivo (path).
    jwt_public_key: str = ""
    jwt_public_key_path: str = "keys/public.pem"
    jwt_algorithm: str = "RS256"

    # Servicios externos (fases siguientes) - placeholders
    ms1_url: str = ""
    ms2_url: str = ""
    n8n_webhook_url: str = ""

    # Blockchain (CU-14) - Sepolia via Infura. Vacios => solo registro local del hash
    # (sin enviar a la cadena). Se completan tras desplegar el contrato.
    web3_provider: str = ""
    wallet_private_key: str = ""
    contract_address: str = ""
    chain_id: int = 11155111  # Sepolia

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
