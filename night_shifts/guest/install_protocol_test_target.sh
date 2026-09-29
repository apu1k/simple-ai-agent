#!/bin/sh
# Candidate Ubuntu live-installer late-command payload. Run only as root in
# the approved Linux Hyper-V installer, with /target mounted as the NEW guest.
# This is NOT the script used for an already-booted guest, and must never be
# invoked against a host root, a host mount, or an existing VM image.
set -eu

if [ "$(id -u)" -ne 0 ] || [ "$(uname -s)" != Linux ] ||
    [ ! -r /sys/class/dmi/id/sys_vendor ] ||
    ! grep -qx 'Microsoft Corporation' /sys/class/dmi/id/sys_vendor; then
    echo 'Only a root Linux Hyper-V installer may install the target service' >&2
    exit 1
fi
if [ ! -d /target/etc/systemd/system ] || [ ! -x /target/usr/bin/python3 ] ||
    [ ! -f /target/etc/default/grub ] || ! mountpoint -q /target; then
    echo 'No mounted, Python-enabled Ubuntu installer target at /target' >&2
    exit 1
fi
# Refuse even quoted GRUB_CMDLINE values; a false positive is safer than
# installing a serial protocol service competing with a ttyS0 console.
if grep -q 'console=ttyS0' /target/etc/default/grub ||
    grep -q 'console=ttyS0' /proc/cmdline; then
    echo 'Refusing target serial-console conflict' >&2
    exit 1
fi
for program in sha256sum chroot install systemctl mountpoint; do
    command -v "$program" >/dev/null || { echo "Missing installer prerequisite: $program" >&2; exit 1; }
done
# A future, reviewed seed-ISO builder must put this file and the exact assets
# on immutable, hash-verified CIDATA media. Merely bundling the files does not
# call this script or authorize installing Ubuntu.
cd -- "$(dirname -- "$0")"
sha256sum -c -- SHA256SUMS
if [ -e /target/etc/systemd/system/night-shift-protocol-test.service ] ||
    [ -L /target/etc/systemd/system/night-shift-protocol-test.service ] ||
    chroot /target getent group night-shift >/dev/null 2>&1 ||
    chroot /target id night-shift >/dev/null 2>&1; then
    echo 'Target service or identity already exists; do not overwrite' >&2
    exit 1
fi
if ! chroot /target getent group dialout >/dev/null 2>&1 ||
    [ ! -x /target/usr/sbin/nologin ]; then
    echo 'Target lacks dialout group or locked-account shell' >&2
    exit 1
fi
# chroot commands change only the freshly installed guest's account database.
# Use --root for systemd: the target is OFF and no service must start here.
chroot /target groupadd --system night-shift
chroot /target useradd --system --gid night-shift --groups dialout \
    --home-dir /nonexistent --shell /usr/sbin/nologin night-shift
chroot /target passwd -l night-shift
install -d -o 0 -g 0 -m 0755 /target/usr/local/lib/night-shift
install -o 0 -g 0 -m 0644 protocol_test_bootstrap.py \
    /target/usr/local/lib/night-shift/protocol_test_bootstrap.py
install -o 0 -g 0 -m 0644 night-shift-protocol-test.service \
    /target/etc/systemd/system/night-shift-protocol-test.service
systemctl --root=/target mask serial-getty@ttyS0.service
systemctl --root=/target enable night-shift-protocol-test.service
printf '%s\n' 'Candidate target service installed; inspect guest before freezing image.'
