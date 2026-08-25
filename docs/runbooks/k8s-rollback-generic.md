# Runbook: Kubernetes Deployment Rollback — Generic

**Applies to:** All services deployed via kubectl/Helm  
**Updated:** 2026-08-01  

---

## When to Use

Use this runbook when:
- A recent deployment is suspected of causing an incident (error spike within 30 min of deploy)
- Instana diagnosis shows SATURATION or FAIL_FAST pattern correlated with a new version
- Service health check is failing after a config change

## Pre-Rollback Checklist

- [ ] Confirm the rollback target version is known and stable
- [ ] Verify the previous version does not have a known critical bug
- [ ] Alert on-call squad that rollback is about to begin
- [ ] Note current replica count before rollback

## kubectl Rollback

```bash
# View rollout history
kubectl rollout history deployment/<service-name> -n <namespace>

# Rollback to previous version
kubectl rollout undo deployment/<service-name> -n <namespace>

# Monitor rollout
kubectl rollout status deployment/<service-name> -n <namespace> --timeout=300s

# Verify pods are healthy
kubectl get pods -n <namespace> -l app=<service-name> -w
```

## Helm Rollback

```bash
# View Helm release history
helm history <release-name> -n <namespace>

# Rollback to previous revision
helm rollback <release-name> <revision-number> -n <namespace>

# Verify
helm status <release-name> -n <namespace>
```

## Post-Rollback Validation

```bash
# Check error rate is below 5%
kubectl logs -n <namespace> deployment/<service-name> --tail=50 | grep ERROR | wc -l

# Health check
SERVICE_URL=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl -sf "https://${SERVICE_URL}/health" | jq .
```

## Rollback of Rollback

If rollback makes things worse (rare but possible):

```bash
# Go back 2 revisions
kubectl rollout undo deployment/<service-name> -n <namespace> --to-revision=<N-2>
```

## Escalation

If rollback does not resolve within 15 minutes:
1. Engage service owner
2. Consider feature flag disable
3. Consider traffic redirect to healthy region
