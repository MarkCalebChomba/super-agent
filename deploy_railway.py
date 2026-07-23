"""Deploy to Railway via REST API.

Usage: python deploy_railway.py
Requires: RAILWAY_TOKEN env var + PROJECT_ID env var set.
"""

import os
import json
import requests
from pathlib import Path

TOKEN = os.getenv("RAILWAY_TOKEN", "")
PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", "")
ROOT = Path(__file__).parent
API = "https://backboard.railway.app/graphql/v2"

SECRETS = {
    "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", ""),
    "OPENROUTER_API_KEY_2": os.getenv("OPENROUTER_API_KEY_2", ""),
    "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
    "HF_TOKEN": os.getenv("HF_TOKEN", ""),
    "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),
    "DEPLOY": "true",
    "PORT": "8080",
}

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

def graphql(query, variables=None):
    resp = requests.post(API, json={"query": query, "variables": variables or {}}, headers=HEADERS)
    data = resp.json()
    if "errors" in data:
        print(f"GraphQL error: {data['errors']}")
        return None
    return data.get("data")

def get_services():
    data = graphql("query($pid:String!){project(id:$pid){services{id name}}}", {"pid": PROJECT_ID})
    if data and data.get("project"):
        return data["project"].get("services", [])
    return []

def get_environments():
    data = graphql("query($pid:String!){project(id:$pid){environments{id name}}}", {"pid": PROJECT_ID})
    if data and data.get("project"):
        return data["project"].get("environments", [])
    return []

def set_secrets(service_id, env_id):
    for key, value in SECRETS.items():
        if not value:
            continue
        data = graphql("""
            mutation($pid:String!$eid:String!$sid:String!$name:String!$value:String!){
                upsertSecret(input:{projectId:$pid,environmentId:$eid,serviceId:$sid,name:$name,value:$value}){id}
            }""", {"pid": PROJECT_ID, "eid": env_id, "sid": service_id, "name": key, "value": value})
        if data:
            print(f"  Secret {key}: set")

def main():
    print("=== Deploying to Railway ===")
    if not TOKEN:
        print("ERROR: Set RAILWAY_TOKEN env var")
        return
    if not PROJECT_ID:
        print("ERROR: Set RAILWAY_PROJECT_ID env var")
        return

    services = get_services()
    print(f"Services: {services}")

    envs = get_environments()
    print(f"Environments: {envs}")

    if services:
        svc = services[0]
        env = envs[0] if envs else None
        if env:
            print("\nSetting secrets...")
            set_secrets(svc["id"], env["id"])

    print(f"\n=== DONE ===")
    print(f"Project: https://railway.app/project/{PROJECT_ID}")
    print(f"Connect your GitHub repo: MarkCalebChomba/super-agent")
    print(f"Railway will auto-deploy from GitHub")

if __name__ == "__main__":
    main()
