"""EvolvingAgent — a self-aware, resource-aware agent that grows from a seed instruction.

Each agent starts with a single instruction like "make money by doing X".
Over time it:
- Plans, acts, observes via a structured Plan→Act→Observe loop
- Stores experiences in multi-tiered memory (working + long-term)
- Keeps the North Star goal in every prompt
- Retries with different approaches before giving up
- Learns from outcomes and evolves its own instruction set
"""

import os
import json
import time
import shutil
import random
from pathlib import Path
from datetime import datetime
from typing import Optional
from loguru import logger
from agent_memory import AgentMemory
from agent_orchestrator import AgentOrchestrator


class EvolvingAgent:
    """A self-evolving agent powered by a seed instruction and instruction set.

    Architecture:
    - Seed instruction is the genesis prompt
    - Instructions grow over time as agent learns
    - Sub-agents handle platform-specific variations
    - Resource registry tracks what the agent needs
    - Self-provisioning attempted before asking human
    """

    AGENTS_DIR = Path("instructions")
    DATA_DIR = Path("data")
    SECRETS_DIR = Path(".secrets")
    RESOURCE_REGISTRY = DATA_DIR / "resource_registry.json"
    AGENT_NEEDS = DATA_DIR / "agent_needs.json"

    def __init__(self, agent_name: str, seed_instruction: str = None):
        self.name = agent_name
        self.instruction_path = self.AGENTS_DIR / f"{agent_name}.json"
        self.secrets_path = self.SECRETS_DIR / f".{agent_name}.env"
        self.running = False
        self.cycle_count = 0
        self._sub_agents = {}

        self.AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.SECRETS_DIR.mkdir(parents=True, exist_ok=True)

        self._seed_instruction = seed_instruction
        self._load_or_init_instruction_set(seed_instruction)
        self._load_secrets()
        self._load_resource_registry()

        # Multi-tiered memory + orchestrator
        self.memory = AgentMemory(agent_name, data_dir=str(self.DATA_DIR))
        self.orchestrator = AgentOrchestrator(self, self.memory)

    def _load_or_init_instruction_set(self, seed_instruction: str = None):
        """Load instruction set from file or initialize from seed."""
        if self.instruction_path.exists():
            with open(self.instruction_path) as f:
                self.instruction_set = json.load(f)
            logger.info(f"Loaded instruction set for {self.name} ({len(self.instruction_set.get('instructions', []))} instructions, {len(self.instruction_set.get('evolutions', []))} evolutions)")
        else:
            self.instruction_set = {
                "name": self.name,
                "seed_instruction": seed_instruction or f"Make money by being a {self.name}",
                "genesis_prompt": seed_instruction or f"Make money by being a {self.name}",
                "instructions": [],
                "resources_required": [],
                "sub_agents": {},
                "evolutions": [],
                "performance": {
                    "cycles_run": 0,
                    "successful_outputs": 0,
                    "failed_outputs": 0,
                    "resources_provisioned": 0,
                },
                "platform_rules": {},
            }
            self._save_instruction_set()
            logger.info(f"Initialized new agent: {self.name}")

    def _save_instruction_set(self):
        with open(self.instruction_path, "w") as f:
            json.dump(self.instruction_set, f, indent=2)

    def _load_secrets(self):
        """Load credentials from .env file into a dict."""
        self.secrets = {}
        if self.secrets_path.exists():
            with open(self.secrets_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        self.secrets[key.strip()] = val.strip()

    def _load_resource_registry(self):
        """Load the global resource registry."""
        if self.RESOURCE_REGISTRY.exists():
            with open(self.RESOURCE_REGISTRY) as f:
                self.resource_registry = json.load(f)
        else:
            self.resource_registry = {}
        if self.name not in self.resource_registry:
            self.resource_registry[self.name] = {}
            self._save_resource_registry()

    def _save_resource_registry(self):
        with open(self.RESOURCE_REGISTRY, "w") as f:
            json.dump(self.resource_registry, f, indent=2)

    def check_available_resources(self) -> dict:
        """Return dict of resource_id -> status for this agent."""
        resources = self.instruction_set.get("resources_required", [])
        registry = self.resource_registry.get(self.name, {})
        result = {}
        for res in resources:
            rid = res["id"]
            entry = registry.get(rid, {"status": "missing"})
            entry["self_provisionable"] = res.get("self_provisionable", False)
            entry["required"] = res.get("required", True)
            entry["execution_mode"] = res.get("execution_mode", "hermes")
            result[rid] = entry
        return result

    def request_resource(self, resource_id: str, message: str = None, provision_guide: dict = None):
        """Append a resource request to agent_needs.json.

        Avoids duplicates — if a pending request already exists for this
        resource, it updates the existing entry instead of creating a new one.
        """
        resource_def = None
        for r in self.instruction_set.get("resources_required", []):
            if r["id"] == resource_id:
                resource_def = r
                break
        if not resource_def:
            logger.warning(f"Unknown resource {resource_id} for {self.name}")
            return

        needs = []
        if self.AGENT_NEEDS.exists():
            with open(self.AGENT_NEEDS) as f:
                needs = json.load(f)

        existing = [n for n in needs if n.get("resource") == resource_id and n.get("agent") == self.name and n.get("status") == "pending"]
        if existing:
            return

        need_entry = {
            "id": f"need_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{resource_id}",
            "agent": self.name,
            "resource": resource_id,
            "status": "pending",
            "requested_at": datetime.now().isoformat(),
            "message": message or f"I need a {resource_id} for {self.name}.",
            "self_provision_attempted": False,
            "provision_guide": provision_guide or {
                "steps": [f"Set up {resource_id} for {self.name}"],
                "env_keys": resource_def.get("env_keys", []),
            },
            "priority": "high" if resource_def.get("required", True) else "normal",
        }
        needs.append(need_entry)
        with open(self.AGENT_NEEDS, "w") as f:
            json.dump(needs, f, indent=2)

        logger.info(f"{self.name} requested resource: {resource_id}")

    def _has_pending_request(self, resource_id: str) -> bool:
        """Check if there's already a pending human request for this resource."""
        if not self.AGENT_NEEDS.exists():
            return False
        with open(self.AGENT_NEEDS) as f:
            needs = json.load(f)
        return any(
            n.get("resource") == resource_id
            and n.get("agent") == self.name
            and n.get("status") == "pending"
            for n in needs
        )

    def self_provision_resource(self, resource_id: str) -> bool:
        """Attempt to self-provision a resource using browser/API."""
        if self._has_pending_request(resource_id):
            logger.debug(f"{self.name}: {resource_id} already has pending request, skipping self-provision")
            return False

        resource_def = None
        for r in self.instruction_set.get("resources_required", []):
            if r["id"] == resource_id:
                resource_def = r
                break
        if not resource_def:
            return False

        url = resource_def.get("provision_url", "")
        if not url:
            return False

        logger.info(f"{self.name} attempting to self-provision {resource_id} at {url}")

        try:
            from tools.stealth_browser import StealthBrowser
            browser = StealthBrowser()
            success, result = browser.self_provision(resource_def)
            browser.close()
            if success:
                self._on_resource_provisioned(resource_id, result)
                return True
            else:
                self.request_resource(
                    resource_id,
                    message=f"Self-provision of {resource_id} failed: {result.get('error', 'unknown error')}",
                    provision_guide=resource_def.get("provision_guide")
                )
                return False
        except ImportError:
            logger.warning("StealthBrowser not available, cannot self-provision")
            self.request_resource(
                resource_id,
                message=f"Need {resource_id} - no stealth browser available for self-provision",
                provision_guide=resource_def.get("provision_guide")
            )
            return False
        except Exception as e:
            logger.error(f"Self-provision error for {resource_id}: {e}")
            self.request_resource(resource_id, message=f"Self-provision error: {e}")
            return False

    def _on_resource_provisioned(self, resource_id: str, result: dict):
        """Update registry and secrets when a resource is provisioned."""
        if self.name not in self.resource_registry:
            self.resource_registry[self.name] = {}
        self.resource_registry[self.name][resource_id] = {
            "status": "provisioned",
            "provisioned_at": datetime.now().isoformat(),
            "details": result.get("details", {}),
        }
        self._save_resource_registry()

        if result.get("credentials"):
            self._append_secrets(result["credentials"])

        self.instruction_set["performance"]["resources_provisioned"] += 1
        self._save_instruction_set()
        logger.info(f"{self.name}: {resource_id} provisioned successfully")

    def _append_secrets(self, credentials: dict):
        """Append credentials to the agent's .env file."""
        existing = {}
        if self.secrets_path.exists():
            with open(self.secrets_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        existing[k.strip()] = v.strip()

        for key, val in credentials.items():
            if key not in existing:
                existing[key] = val

        with open(self.secrets_path, "w") as f:
            for key, val in existing.items():
                f.write(f"{key}={val}\n")
        self.secrets = existing

    def spawn_sub_agent(self, platform: str, platform_rules: dict, seed_variation: str) -> str:
        """Spawn a platform-specific sub-agent that learns from that platform's outcomes.

        The sub-agent is a child instruction set that inherits from parent but
        adds platform-specific rules and evolves independently.
        """
        sub_name = f"{self.name}_{platform}"
        sub_path = self.AGENTS_DIR / f"{sub_name}.json"

        if sub_path.exists():
            logger.info(f"Sub-agent {sub_name} already exists")
            return sub_name

        sub_instructions = {
            "name": sub_name,
            "parent": self.name,
            "platform": platform,
            "seed_instruction": f"{self.instruction_set['seed_instruction']} on {platform}",
            "genesis_prompt": seed_variation,
            "instructions": self.instruction_set["instructions"].copy(),
            "platform_rules": {platform: platform_rules},
            "resources_required": [],
            "sub_agents": {},
            "evolutions": [],
            "performance": {
                "cycles_run": 0,
                "successful_outputs": 0,
                "failed_outputs": 0,
                "resources_provisioned": 0,
            },
        }

        with open(sub_path, "w") as f:
            json.dump(sub_instructions, f, indent=2)

        if "sub_agents" not in self.instruction_set:
            self.instruction_set["sub_agents"] = {}
        self.instruction_set["sub_agents"][platform] = {
            "name": sub_name,
            "created_at": datetime.now().isoformat(),
            "platform": platform,
            "cycles": 0,
        }
        self._save_instruction_set()

        self._sub_agents[sub_name] = EvolvingAgent(sub_name)
        logger.info(f"Spawned sub-agent {sub_name} for platform {platform}")
        return sub_name

    def get_active_sub_agents(self) -> list:
        """Return list of active sub-agent names."""
        return list(self._sub_agents.keys())

    def learn_from_outcome(self, outcome: dict):
        """Evolve the instruction set based on what happened.

        outcome = {
            "output": what was produced,
            "platform": which platform (or None),
            "success": bool,
            "metrics": {"views": N, "engagement": N, "conversion": N},
            "errors": ["error messages"],
            "lesson": "what agent learned from this"
        }
        """
        perf = self.instruction_set["performance"]
        perf["cycles_run"] += 1
        if outcome.get("success"):
            perf["successful_outputs"] += 1
        else:
            perf["failed_outputs"] += 1

        if outcome.get("lesson"):
            evolution = {
                "cycle": perf["cycles_run"],
                "timestamp": datetime.now().isoformat(),
                "lesson": outcome["lesson"],
                "platform": outcome.get("platform"),
                "success": outcome.get("success", False),
            }
            if "evolutions" not in self.instruction_set:
                self.instruction_set["evolutions"] = []
            self.instruction_set["evolutions"].append(evolution)

            if outcome.get("new_instructions"):
                for inst in outcome["new_instructions"]:
                    if inst not in self.instruction_set["instructions"]:
                        self.instruction_set["instructions"].append(inst)

        self._save_instruction_set()

        if outcome.get("platform") and outcome.get("lesson"):
            sub_name = f"{self.name}_{outcome['platform']}"
            if sub_name in self._sub_agents:
                self._sub_agents[sub_name].learn_from_outcome(outcome)

    def build_system_prompt(self) -> str:
        """Build the full system prompt from seed + instructions + evolutions."""
        parts = []

        parts.append(f"# {self.name}")
        parts.append("")
        parts.append(self.instruction_set.get("genesis_prompt", ""))

        instructions = self.instruction_set.get("instructions", [])
        if instructions:
            parts.append("")
            parts.append("## Instructions learned over time")
            parts.append("")
            for i, inst in enumerate(instructions, 1):
                parts.append(f"{i}. {inst}")

        evolutions = self.instruction_set.get("evolutions", [])
        if evolutions:
            parts.append("")
            parts.append("## Lessons from experience")
            parts.append("")
            for ev in evolutions[-5:]:
                parts.append(f"- [{ev.get('platform', 'general')}] {ev['lesson']}")

        platform_rules = self.instruction_set.get("platform_rules", {})
        if platform_rules:
            parts.append("")
            parts.append("## Platform Rules (must follow)")
            parts.append("")
            for platform, rules in platform_rules.items():
                parts.append(f"### {platform}")
                for rule in rules.get("critical_rules", []):
                    parts.append(f"- MUST: {rule}")
                for rule in rules.get("recommendations", []):
                    parts.append(f"- SHOULD: {rule}")

        resources = self.check_available_resources()
        provisioned = {rid: r for rid, r in resources.items() if r.get("status") == "provisioned"}
        if provisioned:
            parts.append("")
            parts.append("## Available resources")
            parts.append("")
            for rid, r in provisioned.items():
                mode = r.get("execution_mode", "hermes")
                parts.append(f"- {rid} (mode: {mode})")

        return "\n".join(parts)

    def run_cycle(self) -> dict:
        """One full Plan ⭢ Act ⭢ Observe ⭢ Adapt cycle."""
        self.cycle_count += 1
        logger.info(f"{self.name} cycle {self.cycle_count}")

        try:
            from live_tracker import update as _lt_update
            _lt_update(self.name, input_text=f"Cycle {self.cycle_count}: planning")
        except Exception:
            pass

        result = self.orchestrator.run_cycle()

        # Track outcome in instruction set
        if result.get("success"):
            self.instruction_set.setdefault("performance", {})["successful_outputs"] = \
                self.instruction_set["performance"].get("successful_outputs", 0) + 1
        else:
            self.instruction_set.setdefault("performance", {})["failed_outputs"] = \
                self.instruction_set["performance"].get("failed_outputs", 0) + 1
        self.instruction_set["performance"]["cycles_run"] = self.cycle_count
        self._save_instruction_set()

        try:
            from live_tracker import update as _lt_update
            txt = (result.get("output") or "")[:200]
            _lt_update(self.name, output_text=f"{result.get('verdict','?')}: {txt}")
        except Exception:
            pass

        return result

    def _log_chat(self, input_text: str, output_text: str = None,
                   mode: str = "hermes", success: bool = False,
                   error: str = None, duration: int = 0):
        """Log LLM interaction to chat_history for dashboard."""
        try:
            from master.system_store import SystemStore
            store = SystemStore()
            store.log_chat_interaction(
                self.name, input_text, output_text, mode, success, error,
                duration_ms=duration
            )
        except Exception:
            pass

    def _execute_via_hermes(self, prompt: str) -> dict:
        """Execute via Hermes HF API."""
        start = time.time()
        logger.info(f"{self.name}: executing via Hermes")
        try:
            from hermes_integration.hermes_hf_client import HermesHFClient
            client = HermesHFClient()
            if not client.available:
                from providers.router import LLMRouter
                llm = LLMRouter()
                output = llm.complete(
                    "Execute your purpose based on your system prompt.\n\nSystem:\n" + prompt,
                    system="You are an autonomous AI agent. Execute your purpose.",
                    max_tokens=4096,
                )
            else:
                output = client.complete(
                    prompt="Execute your purpose based on your system prompt.",
                    system=prompt,
                    agent_name=self.name,
                    max_tokens=4096,
                )

            duration = int((time.time() - start) * 1000)

            if output:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_dir = Path("build_output") / self.name
                out_dir.mkdir(parents=True, exist_ok=True)
                filepath = out_dir / f"output_{ts}.md"
                with open(filepath, "w") as f:
                    f.write(output)

                self._log_chat(prompt, output, "hermes", True, duration=duration)

                return {
                    "output": output,
                    "file": str(filepath),
                    "success": True,
                    "platform": None,
                    "execution_mode": "hermes",
                }
            self._log_chat(prompt, None, "hermes", False, "No output", duration)
            return {"success": False, "error": "Hermes returned no output"}
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            self._log_chat(prompt, None, "hermes", False, str(e), duration)
            logger.error(f"{self.name}: execution failed: {result.get('error', 'unknown') if result else 'no execution mode'}")
            return {"success": False, "error": str(e)}

    def _execute_via_browser(self, prompt: str, resources: dict) -> dict:
        """Execute via stealth browser for platforms requiring human-like interaction."""
        start = time.time()
        logger.info(f"{self.name}: executing via browser")
        try:
            from tools.stealth_browser import StealthBrowser
            browser = StealthBrowser()

            platform_resources = {
                rid: r for rid, r in resources.items()
                if r.get("execution_mode") == "browser"
            }
            secrets = self.secrets

            result = browser.execute_action({
                "prompt": prompt,
                "resources": platform_resources,
                "credentials": secrets,
                "platform_rules": self.instruction_set.get("platform_rules", {}),
            })
            browser.close()
            duration = int((time.time() - start) * 1000)

            if result and result.get("success"):
                msg = result.get("output", "")
                self._log_chat(prompt, msg, "browser", True, duration=duration)
                return {
                    "output": msg,
                    "file": result.get("file"),
                    "success": True,
                    "platform": result.get("platform"),
                    "execution_mode": "browser",
                    "metrics": result.get("metrics", {}),
                    "lesson": result.get("lesson", ""),
                    "new_instructions": result.get("new_instructions", []),
                }
            err = result.get("error", "Browser execution failed")
            self._log_chat(prompt, None, "browser", False, err, duration)
            return {"success": False, "error": err}
        except ImportError:
            self._log_chat(prompt, None, "browser", False, "StealthBrowser not available", 0)
            return {"success": False, "error": "StealthBrowser not available"}
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            self._log_chat(prompt, None, "browser", False, str(e), duration)
            logger.error(f"Browser execution error: {e}")
            return {"success": False, "error": str(e)}

    def _execute_via_api(self, prompt: str, resources: dict) -> dict:
        """Execute via direct API calls for platforms with API access."""
        logger.info(f"{self.name}: executing via API")
        return {"success": False, "error": "API execution not yet implemented"}

    def _maybe_spawn_sub_agent(self, result: dict):
        """If output targets a new platform, spawn a sub-agent for it."""
        platform = result.get("platform")
        if platform and platform not in self.instruction_set.get("sub_agents", {}):
            rules = self.instruction_set.get("platform_rules", {}).get(platform, {
                "critical_rules": ["Follow platform TOS", "No spam"],
                "recommendations": [],
            })
            self.spawn_sub_agent(
                platform,
                rules,
                seed_variation=f"Make money on {platform} by adapting content for its specific audience and format"
            )

    def run_loop(self, max_cycles: int = None):
        """Main execution loop using Plan→Act→Observe."""
        self.running = True
        self.orchestrator.load_north_star()
        logger.info(f"{self.name} started — North Star: {self.orchestrator.north_star[:80]}")

        try:
            while self.running:
                if max_cycles and self.cycle_count >= max_cycles:
                    break

                result = self.run_cycle()
                verdict = result.get("verdict", "?")

                if verdict == "completed":
                    logger.info(f"{self.name}: task completed ✓")
                    time.sleep(3)
                elif verdict == "partial":
                    logger.info(f"{self.name}: partial progress")
                    time.sleep(3)
                elif verdict == "impossible":
                    logger.warning(f"{self.name}: task deemed impossible after retries")
                    time.sleep(5)
                elif verdict == "retry":
                    logger.warning(f"{self.name}: retrying with different approach")
                    time.sleep(5)
                else:
                    logger.warning(f"{self.name}: cycle finished ({verdict})")
                    time.sleep(10)

                self.memory.save_all()

        except KeyboardInterrupt:
            logger.info(f"{self.name} stopped by user")
        except Exception as e:
            logger.error(f"{self.name} crashed: {e}")
        finally:
            self.running = False
            self.memory.save_all()
            logger.info(f"{self.name} stopped after {self.cycle_count} cycles")

    def stop(self):
        self.running = False
