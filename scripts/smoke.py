"""Quick look at guidance and governance outcomes for a handful of questions."""
import sys, time
from docdrift.app import build_pipeline
from docdrift.config import Settings
from docdrift.governance import GovernanceMode as G

QS = [("Drive M4 trips with fault 5091 after operating for ten minutes.", G.STRICT),
      ("What regular maintenance does the manual specify for softstarter S2?", G.STRICT),
      ("What regular maintenance does the manual specify for softstarter S2?", G.FLEXIBLE),
      ("What EOL trip class should softstarter S1 use?", G.STRICT),
      ("What tightening torque do the main terminals of contactor K2 need?", G.STRICT),
      ("What are the coil operating limits for contactor K2?", G.STRICT),
      ("Is a transformer protection breaker still required for P5?", G.STRICT),
      ("Drive M9 shows fault 5091 Safe torque off, what should I check?", G.STRICT)]
s = Settings(); s.audit_path = "/tmp/smoke.jsonl"
t = time.time(); p = build_pipeline(s); print(f"pipeline built in {time.time()-t:.1f}s")
sel = [int(a) for a in sys.argv[1:]] or range(len(QS))
for i in sel:
    q, m = QS[i]
    a, b = p.ask(q, mode=m)
    print(f"\n[{i}] {q[:62]} | {m.value} -> {a.status.value} | steps {len(a.guidance)}")
    for h in b.guidance_chunks[:3]:
        print(f"     page: {h.chunk.doc_id} p{h.chunk.page} score {h.score}")
    for g in a.guidance[:3]:
        print(f"     step: {g.text[:120]}")
    for d in a.evidence_considered[:5]:
        print(f"     {d.comm_id:13s} {d.classification:30s} {d.decision_state.value:20s} "
              f"{d.authority_state.value:12s} {d.failed_conditions[:2]}")
