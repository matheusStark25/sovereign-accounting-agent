# Sovereign Accounting AI Agent

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi) ![LGPD](https://img.shields.io/badge/LGPD-Compliant-brightgreen) ![PQC Ready](https://img.shields.io/badge/PQC-Ready-blueviolet) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker)

**Enterprise-grade multi-agent AI system for Brazilian accounting automation. 922 Python modules | 23+ document types | LGPD compliant | Post-quantum cryptography ready.**

## What This Is

Sovereign orchestrates multiple LLMs (DeepSeek, Gemini) through a 7-state Finite State Machine to classify, process, validate, and archive 23+ Brazilian tax and labor document types (DIRF, GFIP, SPED, DCTF, PER/DCOMP, e-Social). It integrates Playwright-based RPA for FGTS retrieval from Caixa Economica Federal, enforces full LGPD compliance with PII anonymization, and implements WORM audit trails with HMAC-SHA256.

Ships with post-quantum cryptography hooks (Kyber/Dilithium), mTLS, HashiCorp Vault, and circuit breaker resilience patterns.

## Architecture

Multi-Agent Pipeline: User Request -> Orchestrator (DocumentDispatcher, 23 doc types) -> DeepSeek Worker (processing with MARCOS persona) + Gemini Reviewer (validation) -> Copilot Coder -> Anomaly Detector -> WORM Audit Trail (HMAC-SHA256)

7-State FSM: RECEIVED -> CLASSIFYING -> PROCESSING -> REVIEWING -> CORRECTING -> DISPATCHING -> ARCHIVED

## Core Capabilities

**Document Intelligence**: 23+ Brazilian document types, NLP classification, structured extraction, persona-based prompt engineering

**RPA Automation**: Playwright FGTS retrieval, captcha handling, SHA256 PDF verification, Celery batch processing

**Security**: LGPD PII anonymization, WORM audit (HMAC-SHA256), HashiCorp Vault, mTLS, RBAC, PQC hooks (Kyber/Dilithium), digital signatures with anomaly detection

**Accounting Engine**: FGTS, INSS, IRRF, 13th salary, termination, vacation calculations. PDF AcroForm generation

**Resilience**: Circuit breaker, exponential backoff, timeout management, graceful degradation

## Tech Stack

API: FastAPI + Flask | Tasks: Celery + Redis | DB: SQLite WAL | RPA: Playwright | LLMs: DeepSeek, Gemini, Copilot | Crypto: HMAC-SHA256, Kyber, Dilithium | Secrets: Vault | Transport: mTLS | Monitoring: Prometheus | CI/CD: GitHub Actions

## Project Structure

contabil_agente/ - Main agent (agent_contabil.py 370L, governance_manager.py 596L, orchestrator/main.py 829L, tools/sovereign_rpa_worker.py 841L, tools/base_sovereign.py 228L, tools/calculo_tool.py 49KB, middleware/lgpd.py 243L)

agente_v2/ - API server (main.py 311L, auth.py, vault_client.py, mtls.py, signing.py)

core/ - Infrastructure (database.py, cache.py, config.py, prompts.py, legislacao.py)

intelligence/ - AI layer (fsm.py, orchestrator.py, calculator.py, compliance.py)

governance/ - Audit + redaction | middleware/ - Auth, security, observability | resilience/ | rules/ - YAML compliance + tax rules

## Quick Start

pip install -r requirements.txt | playwright install chromium | cp .env.example .env | uvicorn agente_v2.main:app --host 0.0.0.0 --port 8000 | docker-compose up --build

## Example

from contabil_agente.orchestrator.main import DocumentDispatcher
dispatcher = DocumentDispatcher()
result = dispatcher.process(document_path='./dirf_2024.pdf', document_type='DIRF', persona='MARCOS')
print(result.extracted_data, result.calculations, result.audit_trail_id)

## LGPD Compliance

PII Anonymization (CPF, CNPJ, name, email) | Consent Management | Retention Policies | WORM Audit Logging | Right to Deletion | Legal Basis Enforcement (LGPD Art. 7)

## License

MIT
