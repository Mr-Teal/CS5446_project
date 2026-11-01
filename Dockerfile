# Portability probe, not a delivery artifact. Builds both native libraries from
# source inside the image, so nothing compiled on the host is trusted.
FROM python:3.12-slim

# g++ builds inference.so and belief_kernel.so; git is here because several
# pair_b tests read repository metadata.
RUN apt-get update && apt-get install -y --no-install-recommends \
        g++ git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

# Versions follow zs21_runtime/pixi.toml, which pins the audited Windows runtime.
# scipy is here for pair_b; the pins are loosened to whatever resolves for 3.12.
RUN pip install --no-cache-dir \
        "numpy>=2,<3" "scipy>=1.11" "pytest>=9" "python-chess>=1.11,<2"

COPY . /repo

# Both accelerators, compiled here. The second one only works because of the
# POSIX port; on an unported tree it exits with "supports Windows".
RUN python zs21_runtime/scripts/build.py --native \
    && python -m pair_a_prep.build_belief_kernel

CMD ["python", "-m", "pytest", "tests", "pair_a_prep/tests", \
     "-q", "-p", "no:cacheprovider"]
