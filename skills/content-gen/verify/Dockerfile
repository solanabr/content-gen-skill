# The pinned verification toolchain for content-gen.
#
# Purpose: give `verify_code.py --env docker` a reproducible environment whose tool
# VERSIONS MATCH what generated content declares (course.toolchain / frozen_facts), so
# "does this code actually run?" is answered against the versions the reader will use —
# not whatever happens to be on the author's machine.
#
#   docker build -t content-gen-verify skills/content-gen/verify
#   docker run --rm -v "$PWD":/work -w /work content-gen-verify \
#       python3 skills/content-gen/tools/verify_code.py content/courses/<id> --env local --run-smoke
#
# DO NOT hand-edit the pins below. They are generated from ../references/pins.yaml:
#
#   python3 ../tools/pin_refresh.py render     # rewrite the block from pins.yaml
#   python3 ../tools/pin_refresh.py check      # fail if it drifts, or if pins.yaml is stale
#
# ci.py tier 0 runs that check. This exists because the hand-edited version of this block
# rotted badly: it installed SOLANA=v2.1.0 / ANCHOR=0.31.1 / RUST=1.86.0 / BITCOIN=27.1 while
# the machine authoring the content ran solana-cli 3.1.10, anchor-cli 1.1.2, rustc 1.98.1 and
# Bitcoin Core 31.1.0. A verifier a major version behind the content is worse than no verifier,
# because its green is believed.
FROM ubuntu:24.04

# >>> generated from references/pins.yaml by tools/pin_refresh.py render >>>
# pinned_on: 2026-09-07  ttl_days: 120  (edit references/pins.yaml, then: python3 tools/pin_refresh.py render)
ARG PYTHON=3.11   # python (local-probe)
ARG NODE_MAJOR=23   # node_major (local-probe)
ARG RUST=1.98.1   # rust (local-probe)
ARG SOLANA=v3.1.10   # solana (local-probe)
ARG ANCHOR=1.1.2   # anchor (local-probe)
ARG FOUNDRY=stable   # foundry (local-probe)
ARG SOLIDITY=0.8.28   # solidity (declared)
ARG BITCOIN=31.1   # bitcoin (local-probe)
# <<< end generated block <<<

ENV DEBIAN_FRONTEND=noninteractive PATH="/root/.cargo/bin:/root/.foundry/bin:/root/.local/share/solana/install/active_release/bin:/root/.avm/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git build-essential pkg-config libssl-dev libudev-dev \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# bitcoind — Ubuntu 24.04 dropped the apt package; install the official Bitcoin Core binaries
RUN arch="$(uname -m)"; case "$arch" in x86_64) tgt=x86_64-linux-gnu ;; aarch64) tgt=aarch64-linux-gnu ;; *) echo "unsupported arch $arch" && exit 1 ;; esac; \
    curl -fsSL "https://bitcoincore.org/bin/bitcoin-core-${BITCOIN}/bitcoin-${BITCOIN}-${tgt}.tar.gz" \
      | tar -xz -C /opt && \
    ln -s /opt/bitcoin-${BITCOIN}/bin/bitcoind /usr/local/bin/bitcoind && \
    ln -s /opt/bitcoin-${BITCOIN}/bin/bitcoin-cli /usr/local/bin/bitcoin-cli && \
    bitcoind --version | head -1

# Node + TypeScript runner
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - && apt-get install -y nodejs \
    && npm i -g typescript tsx

# Rust (pinned)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain ${RUST}

# Foundry (forge/cast/anvil + solc via svm)
RUN curl -L https://foundry.paradigm.xyz | bash && /root/.foundry/bin/foundryup && \
    /root/.foundry/bin/forge --version

# Solana (Agave) + Anchor via avm — pin to the DECLARED version for the content under test
RUN sh -c "$(curl -sSfL https://release.anza.xyz/${SOLANA}/install)" || \
    sh -c "$(curl -sSfL https://release.solana.com/${SOLANA}/install)"
# avm now lives under the solana-foundation org (migrated from coral-xyz)
# No prebuilt anchor binaries exist for linux/arm64, so fall back to --from-source there.
# The from-source build disables the release profile's LTO/codegen-units=1 (memory blowout
# that SIGTRAPs rustc in an 8 GB Docker VM); this changes only the CLI binary's optimization.
RUN cargo install --git https://github.com/solana-foundation/anchor avm --force && \
    ( avm install ${ANCHOR} || \
      CARGO_PROFILE_RELEASE_LTO=false CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 CARGO_BUILD_JOBS=4 \
      avm install ${ANCHOR} --from-source ) && avm use ${ANCHOR}

WORKDIR /work
# Default: verify a course dir passed as CMD; see the header for the full command.
ENTRYPOINT ["python3", "skills/content-gen/tools/verify_code.py"]
CMD ["--selftest"]
