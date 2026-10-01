from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql://weir:weir@localhost:5432/weir"
    weir_configs_dir: Path = Path("/app/configs")
    weir_ablation: str | None = None

    @field_validator("weir_ablation")
    @classmethod
    def empty_is_none(cls, v: str | None) -> str | None:
        return v or None

    def config_path(self) -> Path:
        return self.weir_configs_dir / "weir.yaml"

    def overlay_path(self) -> Path | None:
        if not self.weir_ablation:
            return None
        return self.weir_configs_dir / "ablations" / f"{self.weir_ablation}.yaml"
