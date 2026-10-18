# COM1 pipe security review — 2026-10-18 (Gate A blocked)

This is an evidence record and a proposed channel-design boundary, **not** a
permission change, inspection retry, deployment approval or Gate A result.
The existing plaintext maintenance ACL check must remain fail-closed.

## 1. Retained live evidence

All paths below are private operator evidence, outside the checkout. Preserve
V1/V2 installations, permanent claims, failed resources, media and receipts.

- V2 inspection request: `b49f709675e24b07a143f4f0f6e6491c`; failed before its
  controller handshake with `CHANNEL / acl_check / principal_rejected`.
- Exact retained recovery VM: `91eb0537-4519-494d-b80e-6e1aa5f40de6`.
- Maintenance identity: `40ac18e14aec40a59598b00f75b648fe`.
- Diagnostic source/working copy: see the retained V2 manifest and
  `docs/privileged_image_inspection.md`. Neither is an accepted base image.
- Initial read-only inventory: general-launcher request
  `5e5bd4ad5d6a460695fecdee7613cbc3`; VM Off and pipe absent.
- First pipe diagnostic: `aa0d3399c39e46c3a4d214c24b8ba3b9`; failed in
  preservation, before any VM start, after about 271 seconds. Its read-only
  configuration opens conflicted with existing handles (Windows error 32,
  reproduced by subsequent local handle probes). Four small backups remain at
  `C:\Program Files\AiAgentElevatedCommands\receipts\pipe-acl-v2-91eb0537-20261018`.
  It did not create a configuration or working-copy backup. Do not reuse it.
- Separately approved revised diagnostic: `7223f9c08a7d4295bf28f78cfdf438e1`;
  completed in 507.054 seconds with a requested 900-second worker ceiling.
  Protected evidence is under
  `C:\Program Files\AiAgentElevatedCommands\receipts\pipe-acl-v2-stable-config-20261018`.
  Its ten backups, including the 4,601,151,488-byte disk backup, were independently
  rehashed and passed protected-path checks. Configuration snapshots used
  repeated identity/hash/security checks with compatible read sharing; they are
  explicitly **stability-checked, not atomic**.
- Revised diagnostic approval payload: canonical LF script SHA-256
  `04a0b3c74528f4d238522624f491af2b503a3a109876a6a48411a7b808d9433b`.
  The launcher retained the exact approved request separately from the mutable
  staging file. The request SHA-256 is
  `2b628bcd7a05c61e140c70f9a5ca5b8e744767b31a8d1e6e302520a4389442ea`.
- Fresh, separately approved read-only post-run inventory:
  `251a7132d6ea4fd7ba89ade6772d5cb1`, observed at
  `2026-10-18T06:41:48.3157965Z`. Exact recovery VM and source-referencing VM
  were Off. Source and working copy were unattached, parentless dynamic 20 GiB
  VHDX files. There were no network adapters or checkpoints; GSI was disabled;
  fixed memory was 2 GiB with 2 CPUs, and only the reviewed live ISO was bootable.
  The pipe was absent again. Configuration/resources remain retained.

The protected diagnostic reports final source and working-copy SHA-256 both as
`a8470ae83c3608065292a298be1030c6501142f9a4665accbf00075745e63ccb`.
No guest bytes were read/written and no maintenance handshake was sent. No guest
mount/audit, finalization, publication or Gate A exchange succeeded or was
attempted in this diagnostic. A successful host-side ACL capture is not image
acceptance. V2's original consumed claim remains unchanged.

Hyper-V's progress stream mentioned `Creating Checkpoint`. This is not proof a
checkpoint was created: post-run inventory observed zero. It did report
`AutomaticCheckpointsEnabled=true` despite `CheckpointType=Disabled`. Future
fresh VM construction should explicitly disable/read back both controls; this
review does not reconfigure the retained VM.

The general elevated launcher has the installed 900-second maximum. The fixed
inspection/evidence helpers were not upgraded by the general-launcher update;
committing or restarting does not deploy their newer timeout policies. A worker
watchdog is not a VM lifetime guarantee; timeout means VM outcome UNKNOWN until
observed, not authorization to retry or sweep resources.

## 2. Captured pipe ACL and identity review

`pipe-acl.json` binds the connected handle to the exact recovery VM and records
owner/group SYSTEM (`S-1-5-18`), server PID 8676 and server image
`C:\WINDOWS\system32\vmcompute.exe`. The PID is historical, not a reusable
process identity. These observations alone are not cryptographic guest identity.

| Allow ACE | Mask | Existing plaintext allowlist |
| --- | --- | --- |
| Capability SID below | `0x001f01ff` (full control) | Rejected |
| Exact VM SID `S-1-5-83-1-2448098615-1229800729-443420344-3859674277` | `0x001f01ff` | Allowed |
| Everyone `S-1-1-0` | `0x00120089` (generic file/pipe read) | Rejected |
| Hyper-V Administrators `S-1-5-32-578` | `0x001f01ff` | Rejected |
| Administrators `S-1-5-32-544` | `0x001f01ff` | Allowed |
| SYSTEM `S-1-5-18` | `0x001f01ff` | Allowed |

The capability SID is:

```text
S-1-15-3-1024-2268835264-3721307629-241982045-173645152-1490879176-104643441-2915960892-1612460704
```

Local read-only review found the literal `VmWorkerProcess` in the installed
`vmwp.exe`. More importantly, the documented Windows
`DeriveCapabilitySidsFromName("VmWorkerProcess")` API returned this **exact**
capability SID, independently confirming the name binding. The returned group
SID has the same numeric suffix under `S-1-5-32-...`; it is not the pipe's
capability ACE and must not be substituted for it. Initial name hypotheses did
not match and were not used to assign trust. The attempted local cached-
capability registry paths were absent; no registry value was created/repaired.

This name derivation is not process authentication, proof that only Hyper-V can
obtain the capability, or a VM-specific identity: the name contains no VM GUID.
Do not add a capability-prefix wildcard or this capability class to the current
allowlist merely because its name is now known.

Native local-group queries reported two direct Administrators members (the
built-in Administrator account and the operator), and **zero direct Hyper-V
Administrators members**, with complete local direct-member enumeration. These
are snapshots, not permanent membership constraints or authority to trust that
second group. Transitive membership was not expanded. A policy must address the
host/hypervisor administration trust boundary explicitly rather than assuming
an empty group makes its ACE irrelevant forever.

Everyone's `0x00120089` includes `FILE_READ_DATA` (`0x1`), not just metadata.
The captured Everyone ACE does not itself grant pipe writes or server creation;
that distinction does not make plaintext receipt confidentiality/private access
established. This is a broad-access default, not evidence of malware or a guest
image defect. The current checker would first reject the capability ACE in this
captured ordering; the earlier failed receipt did not record its actual SID.

## 3. Why a late ACL replacement is not the fix by itself

Microsoft documents access checks on pipe handle creation/open, and distinguishes
`FILE_CREATE_PIPE_INSTANCE` from ordinary data writes. `FILE_GENERIC_WRITE`
includes `FILE_APPEND_DATA`, whose numeric value is also
`FILE_CREATE_PIPE_INSTANCE` (`0x4`). Any new client-rights design must use the
individual required bits, not accidentally grant server-instance creation via
generic write.

Three disposable, current-user-owned native fixtures were exercised unelevated:

1. A connected read-only client retained data-read ability after the server's
   DACL was replaced with an explicitly empty DACL. This also held when the
   endpoint's maximum instance count was 1 and current instance count was 1.
2. The same result held with maximum 2/current 1. A current count of one does
   not establish that additional instances cannot be created.
3. A new client, with no pre-existing connection, was refused with Windows
   error 5 after an empty DACL was installed before connection.

Only one synthetic byte was transferred per connected fixture. No Hyper-V pipe,
VM, protected helper or retained permission was changed. These tests demonstrate
existing-handle non-revocation; they do not establish live Hyper-V topology or
prove a particular late-tightening protocol safe/unsafe in every threat model.
The live pipe's maximum/current instance counts were **not captured** by the
completed diagnostic and must not be invented from these fixture results.

Replacing a DACL, reading it back, observing a single instance or checking a
`vmcompute.exe` filename is therefore not sufficient proof that no untrusted
previously granted data/security handle exists. Do not silently add an automatic
`SetSecurityInfo` repair step to inspection or retry V2 to test one.

## 4. Proposed implementation direction (not enabled)

Keep the present plaintext path blocked. Do not widen its allowlist to Everyone,
Hyper-V Administrators, all VM workers, unknown principals, or mask prefixes.
Keep all old evidence and claims intact. The next work is an **offline channel
prototype and explicit trust review**, not another deployment or blind VM start.

Prefer an authenticated, encrypted maintenance-channel prototype using a
standard TLS implementation over the serial byte stream, treating the pipe as
untrusted transport. This is a design candidate, not a claim TLS can be enabled
by configuration on today's helper. It requires all of the following first:

- Fresh per-attempt credentials, exact VM/operation/request binding, pinned peer
  identity and no plaintext maintenance frame before authentication. Never log
  or commit real private keys or send them as tool arguments/receipts.
- Reviewed credential provisioning in host-controlled recovery media and private
  storage, including effective ACLs, worker-capability access and who can read or
  replace the media. If secret protection cannot be established, this candidate
  must remain blocked; changing the transport does not cure exposed keys.
- Standard, reviewed TLS primitives; no homemade encryption, trust-on-first-use,
  certificate-validation bypass, deterministic production test key or fallback
  to unauthenticated/plaintext inspection. HMAC-only framing is not sufficient
  for confidentiality against a principal with pipe-data read access.
- Bounded handshake/read/write/cancellation and failure receipts; reject wrong
  peers, changed credentials, replay/wrong identities, malformed or oversized
  frames, EOF/disconnect and timeout. Preserve UNKNOWN for uncertain VM stops.
- Explicit host-administrator/hypervisor trust assumptions. Neither a shared
  capability name nor an observed empty administration group supplies this
  trust decision. A compromised trusted host administrator is not contained by
  pipe ACLs or by TLS keys stored on that host.
- Tests against an untrusted byte-stream intermediary, wrong peer identity,
  fragmented traffic, observation/tampering/replay, partial failure and bounded
  cleanup, before any separately approved live recovery inspection.

An endpoint with restrictive permissions **at creation**, supported by the
actual Hyper-V API and backed by an exclusive/authenticated ownership proof,
is another candidate; support has not been established. Do not infer that
pre-creating a pipe server will work when Hyper-V itself is the observed server.
If neither design satisfies the trust boundary, review a VM-bound transport
rather than loosening the plaintext check. No automatic transport fallback is
authorized.

Any eventual live implementation requires reviewed source/tests, pinned protected
deployment with the installed 900-second execution policy, a fresh separately
approved workspace/attempt and inspection-only authorization. It must never
reopen V2's claim or mutate retained copies as a shortcut. Inspection, copy-only
finalization, accepted publication and the real Gate A lifecycle/cleanup suite
remain distinct gates. Gate B and live coding/model work remain blocked.

## References

- [Named Pipe Security and Access Rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)
- [DeriveCapabilitySidsFromName](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-derivecapabilitysidsfromname)
- [GetNamedPipeInfo](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-getnamedpipeinfo)
- [GetNamedPipeHandleStateW](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-getnamedpipehandlestatew)

Public documentation was read as reference material only, not downloaded/executed
as helper code. Local binary inspection read existing bytes; no binary was run,
patched or granted permissions as part of capability identification.
