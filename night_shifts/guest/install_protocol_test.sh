#!/bin/sh
# Run ONLY inside a freshly installed, operator-reviewed Linux Hyper-V image.
# This does not create a VM, remove credentials, or attest image safety.
set -eu

if [ "$(id -u)" -ne 0 ] || [ "$(uname -s)" != Linux ]; then
    echo 'Run as root inside the Linux preparation VM, not on the host' >&2
    exit 1
fi
if [ ! -r /sys/class/dmi/id/sys_vendor ] ||
    ! grep -qx 'Microsoft Corporation' /sys/class/dmi/id/sys_vendor; then
    echo 'Refusing to install outside a Microsoft Hyper-V guest' >&2
    exit 1
fi
if grep -Eq '(^|[[:space:]])console=ttyS0([,[:space:]]|$)' /proc/cmdline; then
    echo 'Remove the ttyS0 kernel serial console before installing' >&2
    exit 1
fi
for program in sha256sum groupadd useradd getent passwd install python3 systemctl; do
    command -v "$program" >/dev/null || { echo "Missing prerequisite: $program" >&2; exit 1; }
done
cd -- "$(dirname -- "$0")"
# SHA256SUMS is generated from the repository-owned files by the host packager.
# Independently verify the bundle's SHA-256/provenance before unpacking it.
sha256sum -c -- SHA256SUMS
python3 -c 'import ast, pathlib; ast.parse(pathlib.Path("protocol_test_bootstrap.py").read_text(encoding="utf-8"))'
if ! getent group dialout >/dev/null 2>&1 || [ ! -x /usr/sbin/nologin ]; then
    echo 'Required dialout group or nologin shell is missing' >&2
    exit 1
fi
if [ -e /etc/systemd/system/night-shift-protocol-test.service ] ||
    [ -L /etc/systemd/system/night-shift-protocol-test.service ] ||
    getent group night-shift >/dev/null 2>&1 || id night-shift >/dev/null 2>&1; then
    echo 'A night-shift service or identity already exists; review it, do not overwrite' >&2
    exit 1
fi
# No download, host share, or network configuration is performed by this script.
groupadd --system night-shift
useradd --system --gid night-shift --groups dialout \
    --home-dir /nonexistent --shell /usr/sbin/nologin night-shift
passwd -l night-shift
install -d -o root -g root -m 0755 /usr/local/lib/night-shift
install -o root -g root -m 0644 protocol_test_bootstrap.py \
    /usr/local/lib/night-shift/protocol_test_bootstrap.py
install -o root -g root -m 0644 night-shift-protocol-test.service \
    /etc/systemd/system/night-shift-protocol-test.service
systemctl mask --now serial-getty@ttyS0.service
systemctl daemon-reload
systemctl enable night-shift-protocol-test.service
printf '%s\n' 'Guest files installed; review users, services, console and network before freezing the image.'
