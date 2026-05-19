from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8080
    default_model: str = "claude-sonnet-4-20250514"
    default_max_turns: int = 10
    claude_cli_timeout: int = 300  # seconds
    working_dir: str = ""  # empty = use temp dir
    api_token: str = ""  # empty = no auth required

    model_config = {"env_prefix": "CCG_", "env_file": ".env"}


settings = Settings()
