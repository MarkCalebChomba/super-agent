"""Hermes Agent hosted on Hugging Face Spaces.
Provides a FastAPI endpoint that routes prompts through Hermes Agent
(Nous Research, 219k★), giving all Smart Agents access to Hermes's
built-in LLM routing, web search tools, and memory system.

Endpoint: POST /api/eval  {prompt, system, tools, agent_name}
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Hermes Agent API", version="1.0.0")


class EvalRequest(BaseModel):
    prompt: str
    system: str = "You are a helpful AI assistant."
    tools: list[str] = []
    agent_name: str = "default"
    max_tokens: int = 4096


class EvalResponse(BaseModel):
    output: str
    agent_name: str
    tools_used: list[str]


def ensure_hermes_installed() -> bool:
    """Install Hermes if not present."""
    if shutil.which("hermes"):
        return True
    try:
        system = os.uname().sysname if hasattr(os, 'uname') else "Linux"
        if system == "Linux":
            subprocess.run(
                "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
                shell=True, capture_output=True, text=True, timeout=600
            )
        return shutil.which("hermes") is not None
    except Exception:
        return False


def install_agent_skills():
    """Export all agent skills into Hermes."""
    try:
        sys.path.insert(0, "/app")
        from hermes_integration.agent_skills import export_agent_skills
        exported = export_agent_skills()
        return exported
    except Exception:
        return []


@app.on_event("startup")
async def startup():
    installed = ensure_hermes_installed()
    if installed:
        skills = install_agent_skills()
        print(f"Hermes ready — {len(skills)} agent skills loaded")
    else:
        print("WARNING: Hermes install failed — using fallback providers")


@app.get("/health")
async def health():
    hermes_ok = shutil.which("hermes") is not None
    skills_dir = Path.home() / ".hermes" / "skills"
    skills = [d.name for d in skills_dir.iterdir() if d.is_dir()] if skills_dir.exists() else []
    return {
        "status": "ok",
        "hermes_installed": hermes_ok,
        "skills_loaded": len(skills),
        "agents": skills,
    }


@app.post("/api/eval", response_model=EvalResponse)
async def eval_prompt(req: EvalRequest):
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        raise HTTPException(status_code=503, detail="Hermes not installed")

    full_prompt = f"[system] {req.system[:1000]} [/system]\n\n{req.prompt[:8000]}"

    try:
        result = subprocess.run(
            [hermes_bin, "--eval", full_prompt],
            capture_output=True, text=True, timeout=180
        )
        output = result.stdout.strip() if result.stdout else ""
        if not output and result.stderr:
            output = f"[Hermes stderr] {result.stderr[:500]}"

        return EvalResponse(
            output=output,
            agent_name=req.agent_name,
            tools_used=req.tools,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Hermes eval timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
