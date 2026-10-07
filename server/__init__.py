"""Reachly SaaS server: multi-tenant hosted version of the agent.

Provides Telegram sign-in, a business-profile + credential vault, billing gating,
and an orchestrator that runs each paying user's agent daily. Legacy Telegram
OTP auth remains available for old self-host/SaaS experiments.
"""
