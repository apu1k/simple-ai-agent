# Public-only bootstrap feasibility: recovery-media prerequisite BLOCKED

**Subsequent review-only progress:** the operator authorized daemon/runtime
acquisition for review, not installation or a VM run. The
[authenticated runtime staging record](night_shift_kvp_runtime_review.md) now
pins actual matching packages and exact-version source, reviews the daemon's
pool/locking behavior, and records the fixed single-ELF extractor's applied
offline tests and real-package in-memory extraction. This is not a deployment
or live compatibility result. No support media was built and the original ISO
remains insufficient for the as-is probe. That later staging is new work, not
retroactive authorization or a change to the original observations below.

This is a read-only investigation and a proposed next scope, **not a live result,
media-build approval, new inspection grant or Gate A authorization**. Repository
HEAD was `77c9b4f` and the working tree was clean. The committed public-only
[adapters](night_shift_public_bootstrap_kvp.md) remain unchanged. Do not build a
VM probe that silently assumes the recovery environment contains a KVP daemon.

## 1. Observations from the actual pinned ISO

The existing V2 policy was read only to recover its two public ISO bindings; it
was not changed or used as new authority. The input was:

- `D:\NightShift\sources\ubuntu-24.04.5-live-server-amd64.iso`
- size: **4,080,486,400 bytes**
- freshly computed SHA-256:
  `97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8`

The hash matched the previously reviewed binding. This checks the same bytes,
not new publisher provenance, daemon availability or guest boot behavior.
The ISO was read unelevated with the already installed pycdlib, without Windows
mounting, extraction to disk, guest execution or changes to the ISO. No VHDX,
protected marker data, retained VM or consumed claim participated.

All six `/casper/*.manifest` files were inspected. None had an entry containing
`cloud-tools`, `hyperv` or `kvp`. The complete filesystem manifest declares
`linux-tools-common` and `linux-tools-6.8.0-139[-generic]` at `6.8.0-139.139`,
Python 3 minimal at `3.12.3-0ubuntu2.1`, cloud-init at `26.1-0ubuntu1~24.04.1`
and OpenSSL at `3.0.13-0ubuntu3.15`. The Linux tools entries are **not evidence
that hv_kvp_daemon is present**. No ISO-level filename matched those three
search terms either; this filename search alone cannot inspect SquashFS contents.

Manifest evidence (hashes are of raw ISO file bytes, not normalized text):

| `/casper/` filename | Lines | SHA-256 |
| --- | ---: | --- |
| `filesystem.manifest` | 707 | `388a38114b18501e5b77e55e7c91fd2939bba704b6a2f4faee8fafaace9f0c63` |
| `ubuntu-server-minimal.manifest` | 380 | `c034ebbbfa00c6ef322ce8686925ff95b71cf3b19753af484308157d8560cd2a` |
| `ubuntu-server-minimal.ubuntu-server.manifest` | 226 | `4e3cba5b5f0ef8b29cf5af747ebce9332e6592d3d734bbb31b7f5da4ecd28dfd` |
| `ubuntu-server-minimal.ubuntu-server.installer.manifest` | 39 | `df8bf81969461b35353bae72d08f40635326ff40371ca0a2be97fd0e6e897c43` |
| `ubuntu-server-minimal.ubuntu-server.installer.generic.manifest` | 70 | `66ec9175d31bc874c382c56c991d8aaac51ceec033ea9a57021f86fb854e6106` |
| `ubuntu-server-minimal.ubuntu-server.installer.generic-hwe.manifest` | 71 | `65d7084f4c2b3394102054d7c25086af75215eb1047f2931be7deba96e499f07` |

An additional exploratory, bounded Python directory-metadata walk read all five
SquashFS v4/xz layers. It decompressed inode/directory metadata in memory only,
using stdlib lzma; it neither extracted nor executed file contents. It accepted
only the observed filesystem version/compression, bounded metadata output to
8192 bytes per block, limited decompressor memory to 64 MiB, bounded directory/
entry counts and used a 23-second cooperative budget inside a 30-second tool
request. Normal process completion was observed; no timeout result was accepted.

| SquashFS filename | Directories walked | Directory entries |
| --- | ---: | ---: |
| `ubuntu-server-minimal.squashfs` | 2720 | 20899 |
| `ubuntu-server-minimal.ubuntu-server.squashfs` | 3017 | 24554 |
| `ubuntu-server-minimal.ubuntu-server.installer.squashfs` | 714 | 10633 |
| `ubuntu-server-minimal.ubuntu-server.installer.generic.squashfs` | 5329 | 44310 |
| `ubuntu-server-minimal.ubuntu-server.installer.generic-hwe.squashfs` | 5728 | 47170 |

There were **no daemon binary/unit names containing kvp or cloud-tools**. Hits
were cloud-init's Azure `kvp.py`/bytecode, sos report plugins, and kernel headers/
modules. Those are not an executable guest KVP daemon. This is corroborating
exploratory evidence, **not a reviewed general SquashFS parser, live guest audit,
complete initramfs/nested-archive audit or proof that no differently named code
could implement the service**. The exact commands/output remain in this task's
tool transcript, not an independent protected execution receipt. No new native
filesystem inspection dependency was installed. Two attempted Ubuntu package
file-list reference requests returned HTTP 500; neither is evidence of package
contents or provenance.

**Conclusion: the current ISO does not establish the required daemon/runtime
prerequisite. The as-is live KVP probe is blocked.** Do not spend a privileged VM
attempt to treat an expected missing prerequisite as a bootstrap result, and do
not automatically install/start a daemon or enable Data Exchange to make it pass.

## 2. Next proposed scope: explicitly reviewed RAM-only daemon support

Prefer reviewing the smallest addition to the existing recovery environment
before replacing the channel design. This is a proposal for new authority, not
an exception to the previous no-install/no-auto-enable probe boundary:

1. Obtain explicit operator consent before fetching distro packages into a new
   external staging directory. First establish an independently trusted Ubuntu
   archive signing key and a reviewed signature-verification tool. Fetch only
   official signed repository metadata initially; verify its signature, release/
   architecture/version bindings and freshness before selecting package URLs or
   accepting package digests. A key downloaded alongside the metadata is not an
   independent trust anchor. Stop rather than install a verifier or trust an
   arbitrary package mirror/key automatically.
2. Identify the distribution's actual package for the pinned recovery kernel's
   guest KVP daemon; do not infer it from the similarly named linux-tools package.
   Review the exact binary, service/udev activation policy, dependencies and
   daemon's pool-1 record/locking behavior. Authenticate any package/dependency
   bytes against the verified repository metadata. Do not execute downloaded
   package maintainer scripts, use arbitrary OpenSSL examples, or install anything
   on Windows, an existing guest or a retained VHDX. Stop if a compatible reviewed
   runtime cannot be provided. An alternative operator-supplied, independently
   reviewed KVP-capable recovery ISO is also possible but is a new media binding.
3. Only after that review, implement an **offline** deterministic public-only seed
   builder and fixed guest probe. The separate public support seed may carry only
   reviewed code/runtime and a fixed synthetic public certificate/leaf fingerprint,
   no private keys or credentials. Any daemon extraction/start must be explicitly
   reviewed for a new diskless guest and stay in verified guest RAM/tmpfs, with no
   swap or persistent target disk. No package-manager hooks, downloads, service
   enablement in an existing OS, or mutation of the original Ubuntu ISO are allowed.
   This source and its dependency inventory do not yet exist and are not approved.
4. Separately review a host runner and a **single fresh diskless generation-2 VM**:
   fresh permanent attempt claim; exact observed VM GUID/name/sole Notes marker;
   2 CPUs/fixed 2 GiB; no disks, network adapters, host shares or serial pipe;
   GSI disabled; both checkpoint controls disabled/read back; no saved-state,
   restart or migration; pinned read-locked recovery/support media; ISO-only Linux
   Secure Boot. Observe Data Exchange's actual state and require its separate
   operator-approved use; never silently enable/repair it. Refuse mismatches.
5. That future runner must bind the seed to the exact new VM while Off, preserve
   create-new GUID/config evidence before start, publish once through the existing
   guest adapter, acquire through the existing local exact-VM reader and compare
   the complete expected public record. Missing/changed/stale/ambiguous data, wrong
   VM, publication uncertainty or deadline failure are terminal, not retryable.
   A fixed public record proves only this plumbing, never possession of a secret
   or production peer authentication.
6. Require a protected pinned execution path with a native outer watchdog, a
   complete independently captured compact report below 3000 UTF-8 bytes/characters,
   and explicit final-state evidence. Only the new exact-owned VM may be stopped/
   removed under that later approval; retain claim/media/config/evidence. VM absence
   must be observed independently. A killed worker does not prove the VM stopped:
   report UNKNOWN, retain all evidence and request exact-ID recovery review. Never
   reset V1/V2, use their consumed installations as this runner, retry automatically
   or sweep cleanup targets. General-launcher execution approval does not pin
   mutable imported code or independently bound a Hyper-V VM lifetime.

No package acquisition, support media builder, runner, protected deployment or
new VM approval is supplied by this document. Source review and edit approval
cannot substitute for any of those steps. If this additional daemon/runtime scope
is not accepted or cannot be established, stop KVP integration and review an
independently VM-bound alternative; do not fall back to public-key trust from the
broadly readable COM1 pipe or weaken its existing fail-closed policy.

## 3. Current verification and distance to Gate A

The standard committed adapter suite was rerun:
`python -m pytest -q tests/night_shifts/test_public_bootstrap_kvp.py -rs`:
**88 passed, 1 skipped** in 1.90 seconds. The skip is Linux disposable-fd behavior,
not a successful Linux/live KVP test. No new production source was changed.

The next meaningful success criterion remains **one public-only exact-VM record
observed and the new VM's final absence confirmed**, not more native-store
fixtures. After that, production credential/key generation, bounded authenticated
serial integration, trusted image inspection/finalization/publication and the
separate [Gate A runtime/cleanup boundary](night_shift_hyperv_preflight.md) remain
required. A new KVP plumbing result cannot pass Gate A or accept the diagnostic
VHDX. No elevation, WMI query, KVP publication, key generation, VM operation,
permission repair, retained-object change, dependency install or restart occurred
in this investigation. **Gate A remains unrun.**
