# Runbook: mcp-gateway FAIL_FAST — Authentication / Config Failure

**Service:** mcp-gateway  
**Application:** Robot-Shop-EKS  
**Namespace:** mcp-context-forge  
**Pattern:** FAIL_FAST  
**Last updated:** 2026-08-21  

---

## Symptoms

- Error rate jumps to 100% with p99 latency dropping significantly below baseline (sub-10ms)
- Calls are rejected immediately — no work being done
- Volume remains stable (traffic arriving, service not responding)

## Root Cause Pattern

FAIL_FAST indicates calls are being rejected at the edge before any real work is attempted.
Common causes:
1. Invalid or expired credentials (API key, JWT, mTLS cert)
2. Configuration mismatch after a deploy or ConfigMap change
3. Dependency returning 401/403 immediately
4. Certificate expiry in service mesh

## Diagnosis Steps

```bash
# 1. Check pod logs for auth errors
kubectl logs -n mcp-context-forge deployment/mcp-gateway --tail=100 | grep -E "auth|401|403|forbidden|invalid"

# 2. Verify current config vs. last known good
kubectl get configmap mcp-gateway-config -n mcp-context-forge -o yaml
kubectl rollout history deployment/mcp-gateway -n mcp-context-forge

# 3. Check secret freshness
kubectl get secret mcp-gateway-secrets -n mcp-context-forge -o jsonpath='{.metadata.creationTimestamp}'
```

## Remediation

### Option A — Rollback last deployment

```bash
kubectl rollout undo deployment/mcp-gateway -n mcp-context-forge
kubectl rollout status deployment/mcp-gateway -n mcp-context-forge --timeout=120s
```

### Option B — Refresh credentials

```bash
# Rotate and re-apply secret
kubectl delete secret mcp-gateway-secrets -n mcp-context-forge
kubectl apply -f secrets/mcp-gateway-secrets.yaml
kubectl rollout restart deployment/mcp-gateway -n mcp-context-forge
```

## Validation

```bash
# Error rate should drop below 5% within 2 minutes
watch -n 5 kubectl top pods -n mcp-context-forge

# Health check
curl -sf https://mcp-gateway.internal/health | jq .
```

Expected: `{"status": "ok"}`

## Rollback from Rollback

```bash
kubectl rollout undo deployment/mcp-gateway -n mcp-context-forge --to-revision=0
```

## Historical MTTR

- 2026-06-14: 23 minutes (config rollback)
- 2026-04-02: 45 minutes (cert rotation)
- 2026-01-18: 18 minutes (deploy rollback)

Average MTTR: **~29 minutes**

## Escalation

1. SRE Lead: #sre-oncall
2. Platform Engineering: #platform-eng
3. MCP Team: #mcp-gateway-team
