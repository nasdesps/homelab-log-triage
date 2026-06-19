#!/usr/bin/env python3
"""
AI Log Summarizer — pbalab homelab
Rules-based triage first, DeepSeek analysis only on real issues.
"""
import subprocess
import requests
import json
import os
from datetime import datetime

# Load webhook URL from the env file
def load_env(path):
    env_path = os.path.expanduser(path)
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip().strip('"').strip("'")
                    os.environ[key.strip()] = value

load_env("~/.summarizer_env")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
if not DISCORD_WEBHOOK_URL:
    raise ValueError("DISCORD_WEBHOOK_URL not set")

OLLAMA_URL   = "http://100.104.76.52:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:1.5b"

# Keywords that trigger AI analysis
ESCALATE_KEYWORDS = [
    "fatal",
    "panic",
    "oom",
    "killed",
    "out of memory",
    "disk full",
    "no space left",
    "corruption",
    "segfault",
    "exception",
    "unauthorized",
    "authentication failed",
    "permission denied",
    "container exited",
    "exit code 1",
    "exit code 2",
]

# Keywords to ignore — known normal patterns
IGNORE_PATTERNS = [
    "econnrefused 0.0.0.0:443",       # n8n rudder telemetry
    "rudder",                           # n8n analytics
    "filter update",                    # adguard normal
    "ssl certificate",                  # npm normal
    "nginx reloaded",                   # npm normal
    "certificate renewed",              # npm normal
    "factory registration failed",      # cadvisor harmless
    "podman",                           # cadvisor harmless
    "crio",                             # cadvisor harmless
    "checkpoint",                        # prometheus normal
    "compacted",                        # prometheus normal
    "last resource version",            # grafana normal init
    "oom_event",                        # cadvisor metric name, not an oom
    "watching for new ooms",            # cadvisor normal startup
    "could not configure a source for oom",  # cadvisor harmless no kmsg
    "disabling oom events",             # cadvisor — the rest of the kmsg line
    "open /dev/kmsg",                   # cadvisor — kmsg unavailability
    "enabled metrics:",                 # cadvisor startup — contains 'oom_event' in list
]

def get_running_containers():
    """Auto-discover running containers instead of hardcoding."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        return [c.strip() for c in result.stdout.splitlines() if c.strip()]
    except Exception as e:
        print("Error listing containers: " + str(e))
        return []
    
def get_container_logs(container, lines=30):
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), container],
            capture_output=True, text=True, timeout=10
        )
        output = (result.stdout + result.stderr).strip()
        return output[:1500] if output else "No output."
    except Exception as e:
        return "Error: " + str(e)

def should_analyze(logs):
    """Line-by-line triage. Returns (needs_analysis, matched_keyword)."""
    for line in logs.lower().splitlines():
        if any(pattern in line for pattern in IGNORE_PATTERNS):
            continue
        for keyword in ESCALATE_KEYWORDS:
            if keyword in line:
                return True, keyword
    return False, None

def analyze_with_ai(container, logs, trigger_keyword):
    """Send to DeepSeek only when a real issue is detected."""
    prompt = "You are an SRE. A Docker container triggered an alert.\n\n"
    prompt += "Container: " + container + "\n"
    prompt += "Trigger keyword found: " + trigger_keyword + "\n\n"
    prompt += "Logs:\n" + logs + "\n\n"
    prompt += "Explain in 2-3 sentences:\n"
    prompt += "1. What is the actual problem?\n"
    prompt += "2. How severe is it: critical or warning?\n"
    prompt += "3. What should the engineer do?\n"

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 1000,
                    "num_ctx": 1024,
                }
            },
            timeout=120
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()

        if "<think>" in raw:
            raw = raw.split("</think>")[-1].strip()

        raw_lower = raw.lower()
        severity = "warning"
        if "critical" in raw_lower and "not critical" not in raw_lower:
            severity = "critical"

        return {"analysis": raw, "severity": severity}

    except Exception as e:
        return {"analysis": "AI analysis failed: " + str(e), "severity": "warning"}

def send_discord_alert(container, trigger_keyword, analysis_result):
    severity = analysis_result.get("severity", "warning")
    colors = {"critical": 0xf85149, "warning": 0xe3b341}
    color = colors.get(severity, 0xe3b341)

    payload = {
        "embeds": [{
            "title": "Alert — " + container,
            "color": color,
            "fields": [
                {"name": "Container",        "value": "`" + container + "`",          "inline": True},
                {"name": "Severity",         "value": severity.upper(),               "inline": True},
                {"name": "Trigger keyword",  "value": "`" + trigger_keyword + "`",    "inline": False},
                {"name": "AI Analysis",      "value": analysis_result.get("analysis", ""), "inline": False},
                {"name": "Time",             "value": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"), "inline": False},
            ],
            "footer": {"text": "pbalab · rules triage + DeepSeek-R1 1.5B · Oracle Cloud"}
        }]
    }

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        r.raise_for_status()
        print("  Discord sent for " + container)
    except Exception as e:
        print("  Discord failed: " + str(e))

def main():
    print("\n[" + datetime.now().strftime("%H:%M:%S") + "] Log analysis starting...")
    escalated = 0
    containers = get_running_containers()
    for container in containers:
        print("\n  [" + container + "]")
        logs = get_container_logs(container)
        needs_analysis, keyword = should_analyze(logs)

        if not needs_analysis:
            print("  -> OK (no keywords matched)")
            continue

        print("  -> keyword matched: " + keyword)
        print("  -> sending to DeepSeek for analysis...")
        result = analyze_with_ai(container, logs, keyword)
        print("  -> severity: " + result.get("severity", ""))
        print("  -> " + result.get("analysis", "")[:100])
        send_discord_alert(container, keyword, result)
        escalated += 1

    print("\n  Done. " + str(escalated) + "/" + str(len(containers)) + " escalated.")

if __name__ == "__main__":
    main()
