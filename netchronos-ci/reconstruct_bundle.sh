#!/usr/bin/env bash
set -euo pipefail
: "${BUNDLE_SHA256:?BUNDLE_SHA256 must be set}"
mkdir -p target-run
cat netchronos-ci/minbundle.part000 \
    netchronos-ci/minbundle.part001a \
    netchronos-ci/minbundle.part001b \
    netchronos-ci/minbundle.part002a \
    netchronos-ci/minbundle.part002b \
    netchronos-ci/minbundle.part003a \
    netchronos-ci/minbundle.part003b \
    netchronos-ci/minbundle.part004a \
    netchronos-ci/minbundle.part004b \
    netchronos-ci/minbundle.part005 \
    netchronos-ci/minbundle.part006 | base64 -d > target-run/netchronos.tgz
echo "${BUNDLE_SHA256}  target-run/netchronos.tgz" | sha256sum -c -
rm -rf target-run/netchronos
mkdir -p target-run/netchronos
tar -xzf target-run/netchronos.tgz -C target-run
# The archive contains the top-level netchronos directory. Fail closed if layout drifts.
test -f target-run/netchronos/src/netchronos/__init__.py
test -f target-run/netchronos/configs/preregistered_protocol.yaml
