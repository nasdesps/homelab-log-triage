# Homelab Log Triage — LLM-Augmented Container Monitoring

A rules-based + LLM log triage pipeline that monitors Docker containers across
my homelab, escalating only real issues to a self-hosted DeepSeek-R1 model for
analysis, then alerting via Discord.

## The problem

Reading `docker logs` across a dozen+ containers every day to catch real issues
doesn't scale. Sending every log line to an LLM is slow, expensive (in compute),
and noisy — most container logs are routine.

## The approach

1. **Auto-discover** all running containers — no hardcoded list, so new
   containers are covered automatically
2. **Rules-based triage first** — check the last 30 lines of each container's
   logs against a list of escalation keywords (`fatal`, `panic`, `oom`,
   `permission denied`, etc.), line by line, skipping known-benign patterns
3. **Escalate only real matches** to a self-hosted DeepSeek-R1 1.5B model
   running on Oracle Cloud (via Ollama), which explains the issue in plain
   English: what happened, how severe, what to do
4. **Alert via Discord** with severity color-coding, only when something
   actually needs attention

This cut LLM calls by roughly 95% compared to a naive "summarize everything"
approach — the model is only invoked when a real keyword match occurs.

## Architecture

- **Runs on**: pbalab (homelab Debian server), via cron every 15 minutes
- **LLM inference**: self-hosted DeepSeek-R1 1.5B via Ollama on Oracle Cloud
  (Always Free ARM instance), reached over a Tailscale mesh — never touches
  the public internet
- **Secrets**: Discord webhook loaded from a locked-down env file
  (`chmod 600`), never hardcoded in the script or committed to git

## What I learned

- Small models are sufficient for narrow, well-defined tasks — a 1.5B
  parameter model reliably triages container logs; you don't need a frontier
  model for this
- DeepSeek-R1 wraps reasoning in `<think>` tags — strip them or your alerts
  include the model's internal monologue
- Treat webhook URLs like API keys — they belong in locked-down env files,
  never inline in scripts or cron entries

## Files

- `log_summarizer.py` — the full pipeline: discovery, triage, LLM analysis, alerting

## Stack

Python · Docker · Ollama · DeepSeek-R1 · Discord webhooks · Tailscale · cron
