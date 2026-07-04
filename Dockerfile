# Calma validity-check GitHub Action — a self-contained image running the no-reproduction validity scan.
# The scan reads files + recomputes committed numbers (numpy/sklearn); it does NOT execute the target repo,
# so the image needs only the recompute stack, not the repo's own deps.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
      numpy==2.5.0 scikit-learn==1.9.0 scipy==1.18.0 pandas==3.0.3 PyYAML==6.0.3

# the engine (pure-stdlib core + the recompute catalog); untrusted repo code is never run here
COPY spike/ /calma/spike/
COPY action/entrypoint.sh /calma/action/entrypoint.sh
COPY action/pr_comment.py /calma/action/pr_comment.py
RUN chmod +x /calma/action/entrypoint.sh

ENV PYTHONPATH=/calma/spike:/calma/spike/capture
ENTRYPOINT ["/calma/action/entrypoint.sh"]
