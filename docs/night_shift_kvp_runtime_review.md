# Authenticated KVP-daemon staging and static review — NOT deployed

The operator authorized review-only package staging after the
[recovery-media prerequisite investigation](night_shift_bootstrap_feasibility.md).
This records actual ordinary-process acquisition/static review, plus a draft
single-asset extractor. It is **not an installation, media build, successful
Linux/live KVP test, protected deployment, inspection retry or Gate A result**.
The existing inspection source/bundle/claims remain outside this work.

## Actual retained staging

New external directory: `D:\NightShift\staging\kvp-runtime-review-20261021`.
Nothing in the prior staging/workspaces was overwritten or cleaned. Downloads,
public keyring, metadata, source/license excerpts and review JSONs were created
as new files here. No downloaded binary, maintainer script, source program,
service unit or package wrapper was executed, and no private key was generated.
The existing GnuPG verifier and Python's parsing/decompression libraries did run.

`REVIEW-INDEX.json` records **48 artifacts / 244,031,259 bytes**, excluding the
catalog itself. Catalog SHA-256:
`c52b6fa019fc1869e1ce8a04bf229b4e66aec09d9b93d055555249bca47523a8`.
It includes full raw/verified metadata, status output, all three packages, source
archives and selected source/license text. Most bytes are the original Linux
source archive needed to authenticate the reviewed daemon source, not a new image.
The catalog is an ordinary mutable staging inventory, **not a protected receipt**.
Recheck every relevant byte and input identity at any future authoring/deployment
boundary; a historical local JSON/hash is not fresh execution authority.

## Trust chain actually checked

1. Rehashed the already reviewed Ubuntu ISO again to
   `97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8`.
   A bounded, explicit read of its base SquashFS layer obtained only
   `/usr/share/keyrings/ubuntu-archive-keyring.gpg`, with no symlink traversal.
   The 3607 public bytes hash to
   `80a36b0a6de2f69f49d2df75ef473ccde121e9e190b9ea01d20a4f63778d5c31`.
   This inherits the operator's prior ISO-provenance decision; it does not invent
   a new independent publisher attestation. The narrow exploratory parser is not
   a general reviewed SquashFS extraction backend or a future privileged runtime.
2. Used the existing `C:\Program Files\Git\usr\bin\gpgv.exe`, GnuPG **2.4.8**,
   SHA-256 `3a66ad34a2c99ac1647b236fd1fb3da5f29d32c67b19d3f332fc0c97d68bd17e`.
   Its local installation/ancestor ACL observations show administrative ownership
   and ordinary-user read/execute, not write, grants. The companion gpg.exe is
   not Authenticode-signed; do not turn a local hash/ACL into a claim of new Git/
   verifier publisher authentication. This ordinary review relies on the existing
   trusted host/Git installation, not a newly installed protected verifier.
   A new isolated staging `gnupg` home was used, with explicit keyring, a minimal
   child environment and working directory in the installed Git bin directory.
   No personal GnuPG home, auto key retrieval, key import, verifier download or
   permission change was used. Show-only key inspection created its own empty
   public keybox/trust database inside staging, not credentials.
3. Retrieved the **complete** official `noble-updates/InRelease` (126125 bytes).
   gpgv exited 0 and reported one expected SHA-512 valid signature by Ubuntu's
   archive key **`F6ECB3762474EDA9D21B7022871920D1991BC93C`**, present in the ISO
   keyring. Saved verified cleartext binds Origin/Label Ubuntu, Suite
   noble-updates, Codename noble, Version 24.04, amd64 and main. Signed Date was
   **2026-10-21 00:41:07 UTC**; verification was at 04:33:17 UTC. Because this
   release has no Valid-Until, review required signed Date age <=48 hours and
   future skew <=600 seconds; it would also honor Valid-Until if present. This
   depends on the trusted host clock, not an online time attestation.
   InRelease SHA-256:
   `8ae2df3620756815fbcaf2e3cf02655ed6ff94d53211e5c802182dc2f9fae186`.
4. Fetched the amd64 main index by its signed SHA-256/by-hash URL; checked both
   compressed and uncompressed sizes/hashes before selecting packages.
   `Packages.xz` SHA-256:
   `d6f826ef48dea00716e3fbc12de118c0d8b9840bf9f82e12a30458f80b313119`.
   Selected exact **6.8.0-139.139** packages to match the pinned recovery generic
   kernel, not a similarly named Azure/HWE build or an inferred latest version.
   Each official package download matched its signed index size/SHA-256.
   Listed old versions are not thereby the latest secure versions: this is a
   compatibility/plumbing candidate, not a production security-update decision.

No key downloaded alongside new metadata was promoted to a trust root. An early
HTTP-tool InRelease display was truncated at 100 KB; it was **not** used for
signature verification. The later complete raw download and gpgv cleartext are
retained. Broad candidate stdout also exceeded the shell's capture limit; the
full local candidate JSON was retained and exact selections were read back.
These truncations are not missing signature/package evidence.

## Exact candidate package and binary pins

All packages have version `6.8.0-139.139`, source `linux`:

| Package filename | Bytes | SHA-256 |
| --- | ---: | --- |
| `linux-cloud-tools-6.8.0-139_6.8.0-139.139_amd64.deb` | 148096 | `d07e7f7804374bd33bb31ca51a46b23f497ef530cefef00244a4e92d01727f6c` |
| `linux-cloud-tools-6.8.0-139-generic_6.8.0-139.139_amd64.deb` | 1686 | `d4cef84756f79da508361ed4c6473b5de198b09e157d35b4bb1fbe9028027b61` |
| `linux-cloud-tools-common_6.8.0-139.139_all.deb` | 136016 | `0b1d218e736c223abcf6f60f1a6afb20fba350e20deb59bba512b69ff81d39cf` |

Read-only Debian ar/zstd/tar inspection found:

- Real ELF: `./usr/lib/linux-tools-6.8.0-139/hv_kvp_daemon`, **44712 bytes**,
  SHA-256 `612a3f9fb420d0d891fcfeeb2df8c6be55dbd015b3853e800aa793341ae2c21b`.
  It is x86-64 ET_DYN, interpreter `/lib64/ld-linux-x86-64.so.2`, with only
  `libc.so.6` in DT_NEEDED and no RPATH/RUNPATH. Package dependency is libc >=2.34;
  ISO manifest lists libc `2.39-0ubuntu8.8`. Static symbol strings include 2.34.
  This is promising static compatibility, **not an executed loader/native ABI test**.
- The flavor package supplies symlinks; the common package supplies a wrapper,
  systemd/udev activation, network helpers and install hooks. Its postinst enables/
  starts **KVP, file-copy and VSS** services. Never execute those hooks or install
  the whole package to implement this probe. The future design selects only the
  real pinned KVP ELF directly, not the wrapper, symlinks, fcopy/VSS binaries,
  activation rules, network scripts or an arbitrary package member.
- Host Python **3.14.3** has stdlib `compression.zstd`; no pip dependency or 7-Zip
  execution was needed. Review used bounded output/window sizes and in-memory
  member reads, never tar extraction to filesystem paths.

## Exact-version source and pool compatibility review

The current authenticated source index contains linux `6.8.0-147.147`, not the
selected 139 source. The initial exact-source selection therefore refused rather
than substituting a newer source audit. Historical signed Ubuntu snapshots on
2026-08-15 and 2026-09-01 contained 137 and 138 respectively, also not substitutes.
Launchpad publication history was used only as a date-discovery hint, not as a
signature/hash authority. The **2026-09-15T000000Z** official snapshot supplied
an archive-signed noble-updates release and source index for **139.139**.

That historical InRelease hashes to
`fccd5d3f5d46cfcd9d2c05ffd0720de11fa77c9b8e3b4e47d1874da83c0360b1`, signed
by the same ISO-rooted archive key; Sources.xz hashes to
`68810a112ddb028b305d04f986ed4c01e3903689f31cd2157b8604e26097a881`.
It authenticates these exact source inputs:

- `linux_6.8.0.orig.tar.gz`: 230060117 bytes,
  `26512115972bdf017a4ac826cc7d3e9b0ba397d4f85cd330e4e4ff54c78061c8`.
- `linux_6.8.0-139.139.diff.gz`: 9025336 bytes,
  `c18cf1db6c7ed0ad5cf7d651de117b415f17e05baaeefb13a4a2306e94e9ae57`.
- `linux_6.8.0-139.139.dsc`: 9348 bytes,
  `40fb1a41e084f8f923cbea43fe2ffc491e7bd3c247672018f0aa97ef3e352558`.

The `.dsc` is bound through the archive-signed source index; its uploader's
personal signature was not independently trusted/verified. The current archive
returned 404 for the old delta; the timestamped official snapshot provided bytes
matching the already authenticated hash. Historical metadata is **only source
provenance supplementation**, never a replacement for the fresh 2026-10-21 binary
metadata or relaxation of its freshness gate. It authorizes no historical guest.
All four retained InRelease files were independently reverified against their
saved cleartext, and current metadata freshness rechecked at **04:44:49 UTC**.

A bounded streaming source read retained the daemon C source, UAPI header,
Makefile, applicable delta sections and license text; no source build, patch
program or maintainer code ran. The full delta has 12736 file sections. It does
not change `tools/hv/hv_kvp_daemon.c`; its header change packs a message union,
not the pool-file arrays. Relevant unchanged daemon source SHA-256 is
`2d8c714a8047d2e11914d619fe15acac3f634a119be2ad4f28553ac06cfcff57`.
This is source/package correspondence review, **not proof of a reproducible build
or a complete audit of kernel/daemon/packaging security**.

The reviewed code corroborates the existing adapter's intended pool ABI:

- fixed `/var/lib/hyperv/.kvp_pool_N`; key **512 bytes**, value **2048 bytes**;
  custom guest pool is 1; arrays are byte strings, not UTF-16 pool records;
- whole-file POSIX fcntl record locks, not flock;
- enumeration reloads pool state under the lock before returning an item, so
  a locked guest append is not dependent on a daemon restart to refresh memory;
- daemon initialization creates/opens all pool files; reviewed future setup must
  keep those fixed paths on guest RAM-backed storage before starting it;
- `-n` means foreground, but startup hostname resolution, native file/device I/O,
  poll and locks can block. The daemon also supports host mutation/IP operations
  and external helper commands: it is **not a read-only hardened publisher**.
  Future process confinement, exclusive trusted-host use and bounded supervision
  remain necessary. No adapters does not erase those code paths. POSIX locks do
  not make the daemon's separately locked read/modify/write sequence transactional;
  exclude competing writers rather than claim general concurrency safety.

## Draft source and next application checks

`night_shifts/bootstrap_daemon_asset.py` drafts a no-side-effect, explicit
single-asset extractor. It requires the exact package length/hash **before**
parsing, bounded three-member ar and stdlib zstd processing, root/nonwritable
regular/directory tar shapes, no links or duplicate/unsafe paths, and the exact
selected ELF length/hash. It returns bytes only; it cannot download, execute,
install, choose paths, author media, enable services or operate a VM. No existing
production caller/bundle imports it. Python <3.14 must refuse explicit extraction
with a fixed runtime label; there is no new dependency/OS/runtime installation.
This does not raise the app's global Python minimum.

The applied synthetic regressions cover pre-parse refusal, ar order/size/padding,
zstd bounds/trailing frames, member/link/owner/mode/path refusals and selection
of only the KVP ELF. Synthetic parser fixtures explicitly replace output pins;
they cannot establish distro trust or a real native result. Never run the daemon
to validate this extractor on Windows or in an existing VM.

### Applied verification completed

The standard extractor-plus-bootstrap command passed **126 with 1 skip** in
1.95 seconds. This includes **38 new extractor tests** and 88 existing bootstrap
tests. A combined six-file selection adding maintenance credential, TLS, failure-
diagnostic and native-store regressions passed **405 with 2 skips** in 3.61 seconds,
INCLUDING those 126. The skips are Linux-only disposable-fd behavior and unavailable
unelevated symlink creation; neither is a successful Linux/native deployment test.
These are targeted results, not a full-repository test-suite result.

Repository Ruff passed, and Mypy passed across **80 night-shift source files**.
Strict warning-as-error source compilation passed for both new Python files.
All 23 checked local document links resolved and `git diff --check` passed.

The actual staged package was passed to the applied public extractor without
mocking/replacing any pins. It returned only the **44712-byte** ELF in memory,
matching `612a3f9fb420d0d891fcfeeb2df8c6be55dbd015b3853e800aa793341ae2c21b`.
The ELF was not executed or written as a standalone executable. Independent read-
back rehashed all **48 staged artifacts**, matching the pinned catalog and every
recorded file size/hash; this establishes preservation, not a new signature or
freshness decision. No staging artifact or catalog was changed by these checks.

The actual in-memory inspection ZIP had **31 entries** and excluded the new
extractor, public-bootstrap/credential/TLS candidates and downloaded packages/
source archives. Sixteen existing bundle, bootstrap and executed fixture sources
matched HEAD after canonical LF comparison. No existing runtime, frozen fixture,
claim or inspection bundle policy was changed. The applied source/test batch is
verified for an offline commit, **not media creation, deployment or a VM run**.

Next source milestone after those checks: deterministic public-only support
seed and fixed guest preflight/publisher, with license/source information,
verified RAM-only execution and pool storage, no target disks/swap/network,
no auto-installed services, no helper fallback and bounded foreground supervision.
Then separately design/review the exact-owned diskless VM runner, protected
runtime/watchdog/evidence path and final-state observation. **No media was built
and no execution approval is requested yet.** No elevation, WMI query, KVP
publication, service change, VM operation, permission repair, retained-object
mutation or restart occurred. Gate A remains unrun.
