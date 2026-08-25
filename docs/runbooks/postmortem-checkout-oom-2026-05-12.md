# Postmortem: Checkout Service OOM — 2026-05-12

**Incident ID:** INC-4891  
**Service:** checkout-service  
**Severity:** P0  
**Duration:** 2h 14min  
**MTTR:** 134 minutes  
**Pattern:** SATURATION  

---

## Summary

The checkout-service experienced 100% error rate due to JVM heap exhaustion
following a deploy of v2.14.3. The new version introduced an unindexed
database query that caused unbounded result set loading into memory under
Black Friday promotional traffic.

## Timeline

| Time (UTC) | Event |
|---|---|
| 14:22 | Deploy v2.14.3 rolled out to production |
| 14:38 | Error rate begins rising (15%) |
| 14:52 | P0 triggered — error rate 87%, latency p99 8,200ms |
| 14:55 | On-call SRE joins war room |
| 15:10 | Root cause identified: missing DB index + large result set |
| 15:18 | Rollback to v2.13.1 initiated |
| 15:22 | Error rate drops to 3% |
| 16:36 | Service fully recovered, postmortem opened |

## Root Cause

Query introduced in v2.14.3 (`ProductCatalogService.getRecommendations`) loaded
all matching products into memory without pagination, causing heap saturation
under promotional traffic (3x normal volume).

```java
// Bug: unbounded query
List<Product> products = productRepo.findByCategory(categoryId); // returns 50k+ rows

// Fix: paginated query  
Page<Product> products = productRepo.findByCategory(categoryId, PageRequest.of(0, 50));
```

## Remediation Applied

```bash
kubectl rollout undo deployment/checkout-service -n ecommerce
kubectl rollout status deployment/checkout-service --timeout=180s
```

## Lessons Learned

1. Database queries must be reviewed for result set bounds in code review
2. Load tests must include promotional traffic profiles (3x normal)
3. JVM heap alerts at 80% should page SRE immediately (previously 95%)

## Action Items

- [ ] Add `@QueryBound` annotation enforcement in CI (PR #4512)
- [ ] Create load test scenario for Black Friday traffic
- [ ] Lower JVM heap alert threshold to 80%

## Prevention

For SATURATION incidents with heap pressure:
1. Check for unindexed queries or unbounded result sets
2. Review `kubectl top pods` for memory trends before rollback
3. If deploy-correlated: rollback is almost always the right first action
