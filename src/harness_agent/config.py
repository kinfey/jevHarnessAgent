from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


PLACEHOLDERS = {"", "YOUR_MCP_TOKEN", "YOUR_TYPESAFE_API_KEY"}


@dataclass(frozen=True)
class Settings:
    mcp_token: str
    typesafe_api_key: str
    mcp_url: str = "https://mcp.mcd.cn"
    copilot_model: str = "gpt-6-astra"
    typesafe_model: str = "jev-latest"
    confidence_threshold: float = 0.75

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            mcp_token=os.getenv("YOUR_MCP_TOKEN", ""),
            typesafe_api_key=os.getenv("TYPESAFE_API_KEY", ""),
            mcp_url=os.getenv("MCD_MCP_URL", "https://mcp.mcd.cn"),
            copilot_model=os.getenv("COPILOT_MODEL", "gpt-6-astra"),
            typesafe_model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
            confidence_threshold=float(os.getenv("JEV_CONFIDENCE_THRESHOLD", "0.75")),
        )

    def require_mcp(self) -> None:
        if self.mcp_token in PLACEHOLDERS:
            raise ValueError("Set YOUR_MCP_TOKEN in .env before using the live MCP server.")

    def require_typesafe(self) -> None:
        if self.typesafe_api_key in PLACEHOLDERS:
            raise ValueError("Set TYPESAFE_API_KEY in .env before running the Jev harness.")

