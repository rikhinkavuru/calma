// PRE-RECORDED demo verification — a REAL past run of the sample backtest (benchmark/cases/win_b)
// through the e2b Firecracker microVM, captured once and replayed instantly so the one-click demo
// does not re-boot a microVM (~50s) on every click. The proof is a genuine signed DSSE envelope and
// still verifies in-browser against the published key. Regenerate by re-running the capture script.
import type { Verification } from "@/lib/calma";

export const DEMO_VERIFICATION = {
  "verification_id": "8c19b6a7-2b91-4436-98b5-16aff8218143",
  "status": "COMPLETED",
  "recipe": {
    "id": "trading.total_return",
    "version": "1.0.0"
  },
  "created_at": "2026-06-27T01:08:26.777936+00:00",
  "verdict": "CONFIRMED-WITH-CAVEATS",
  "repo_verdict": "CONFIRMED-WITH-CAVEATS",
  "reason": "recomputed value matches the claim within the calibrated budget",
  "claim": {
    "metric": "total_return",
    "value": 0.0077
  },
  "recomputed": {
    "value": 0.0077019756185206,
    "abs_diff": 1.9756185205954e-06,
    "within_tolerance": true
  },
  "validity": {
    "clean": false,
    "needs": null,
    "metric": "total_return",
    "reason": "recomputed value matches the claim within the calibrated budget"
  },
  "execution": {
    "isolation_tier": "e2b-firecracker",
    "tier_verified": true,
    "network_run": "off",
    "determinism_mode": "measured-band"
  },
  "proof": {
    "uri": "t/81c93843-520e-46dd-beb2-42c17d324b57/proofs/8c19b6a7-2b91-4436-98b5-16aff8218143.json"
  }
} as unknown as Verification;

export const DEMO_PROOF: Record<string, unknown> = {
  "payloadType": "application/vnd.calma.proof+json",
  "payload": "eyJhcnRpZmFjdHMiOlt7ImtleSI6InQvODFjOTM4NDMtNTIwZS00NmRkLWJlYjItNDJjMTdkMzI0YjU3L2FydGlmYWN0cy84YzE5YjZhNy0yYjkxLTQ0MzYtOThiNS0xNmFmZjgyMTgxNDMvZGNlY2JhMWItYTFhOS00NTdlLTk1MmQtMDQ3MTA2MWM4YmVjL3JldHVybnMuY3N2IiwibmFtZSI6InJldHVybnMuY3N2Iiwic2l6ZSI6OTU4fV0sInJlc3VsdCI6eyJjYWNoZWQiOmZhbHNlLCJjbGFpbWVkIjowLjAwNzcsImNsZWFuIjpmYWxzZSwiY29uZmlkZW5jZSI6MC44NSwiZGV0ZXJtaW5pc21fbW9kZSI6Im1lYXN1cmVkLWJhbmQiLCJmaXgiOiJyZWNvbXB1dGUgb3ZlciB0aGUgY2xhaW1lZCB3aW5kb3cgdXNpbmcgZGF0YSB0aGF0IGFjdHVhbGx5IHNwYW5zIGl0IiwiZ2F0ZV9leGl0IjoxLCJpc29sYXRpb25fdGllciI6ImUyYi1maXJlY3JhY2tlciIsIm1ldHJpYyI6InRvdGFsX3JldHVybiIsIm1ldHJpY3MiOlt7ImNsYWltZWQiOjAuMDA3NywiaGVhZGxpbmUiOnRydWUsIm1ldHJpYyI6InRvdGFsX3JldHVybiIsInJlYXNvbiI6InJlY29tcHV0ZWQgdmFsdWUgbWF0Y2hlcyB0aGUgY2xhaW0gd2l0aGluIHRoZSBjYWxpYnJhdGVkIGJ1ZGdldCIsInJlY29tcHV0ZWQiOjAuMDA3NzAxOTc1NjE4NTIwNTk2LCJ2ZXJkaWN0IjoiQ09ORklSTUVELVdJVEgtQ0FWRUFUUyJ9XSwibmVlZHMiOm51bGwsIm5vdF92ZXJpZmllZCI6WyJkYXRhIGxlYWthZ2UgKG5vIHRyYWluL3Rlc3Qgc3BsaXQgb3Iga2V5cyBkZWNsYXJlZCkiLCJtb2RlbC1wcm9jZXNzIGxlYWthZ2UgKG5vIHBpcGVsaW5lL3N3ZWVwIGRlY2xhcmVkOiBmZWF0dXJpemF0aW9uLWZpdCAvIHNlbGVjdGlvbi1vbi10ZXN0KSIsImNvdmFyaWF0ZS90YXJnZXQgZGlzdHJpYnV0aW9uIHNoaWZ0IChjaGVja2VkIG9ubHkgdW5kZXIgYW4gaW4tZGlzdHJpYnV0aW9uL2dlbmVyYWxpemVzIGNsYWltKSIsIm92ZXJmaXR0aW5nIC8gZGVmbGF0ZWQtU2hhcnBlIC8gUEJPIChubyB0cmlhbHM6TiBvciBncmlkLXNlYXJjaCBsb2cgZGVjbGFyZWQpIiwiZXhlY3V0aW9uIHJlYWxpc20gKG5vIGZyaWN0aW9ucyBkZWNsYXJlZCkiLCJldmFsL2JlbmNobWFyayBjb250YW1pbmF0aW9uIChubyBjb3JwdXMgZGVjbGFyZWQpIiwicG9pbnQtaW4tdGltZSAvIGxvb2stYWhlYWQgKG5vIHVuaXZlcnNlLW1lbWJlcnNoaXAgb3IgYXZhaWxhYmlsaXR5IGJsb2NrIGRlY2xhcmVkKSIsInN0dWR5LXdpZGUgbXVsdGlwbGUtdGVzdGluZyAvIEhMWiBoYWlyY3V0IChubyBzdHVkeTp7dHJpYWxzLC4uLn0gYmxvY2sgZGVjbGFyZWQpIiwid2Fsay1mb3J3YXJkIC8gcmVnaW1lIHJvYnVzdG5lc3MgKG5vIHdpbmRvd3MgYmxvY2sgb3Igcm9idXN0bmVzcyBjbGFpbSkiLCJlcmEtZW1iYXJnbyAvIHB1cmdlZC1DViBsZWFrYWdlIChubyBlbWJhcmdvOntob3Jpem9uX2RheXMsdHJhaW4sLi4ufSBibG9jayBkZWNsYXJlZCkiLCJyaXNrLXNpbSBhc3N1bXB0aW9ucyAobm8gc2ltdWxhdGlvbl9hc3N1bXB0aW9uczp7ZmlybSxldmVudF9sb2csLi4ufSBibG9jayBkZWNsYXJlZCkiXSwibm90ZSI6bnVsbCwicmVhc29uIjoicmVjb21wdXRlZCB2YWx1ZSBtYXRjaGVzIHRoZSBjbGFpbSB3aXRoaW4gdGhlIGNhbGlicmF0ZWQgYnVkZ2V0IiwicmVjb21wdXRlZCI6MC4wMDc3MDE5NzU2MTg1MjA1OTYsInJ1bl9kaXIiOiIvdG1wL2NhbG1hX2pvYl9udTZ0MGFwZS8uY2FsbWEvcnVuIiwidmVyZGljdCI6IkNPTkZJUk1FRC1XSVRILUNBVkVBVFMifSwicnVuX2lkIjoiZGNlY2JhMWItYTFhOS00NTdlLTk1MmQtMDQ3MTA2MWM4YmVjIiwidmVyaWZpY2F0aW9uX2lkIjoiOGMxOWI2YTctMmI5MS00NDM2LTk4YjUtMTZhZmY4MjE4MTQzIn0=",
  "signatures": [
    {
      "keyid": "3d48e4df88f77082",
      "sig": "MEYCIQDjvtHtNNhFuOQr536wBF4Y/awfNUqwwSF/zBFbIPTWowIhAOJ7FQaZbjUOFjlqbRgmcyjrqDdIiG9CmSQhKSIyd2wO",
      "algorithm": "ecdsa-p256-sha256"
    }
  ]
};
