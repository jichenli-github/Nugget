# NuggetQuery (experimental, protocol 2)

Device-side container bridge for **iOS/iPadOS 27.0–27.2 inclusive**. The desktop
keeps Nugget's existing pages and tweak generators. Every iOS 27 device write
uses the foreground companion; there is **no partial-restore or BookRestore
fallback**. This is not full Nugget compatibility: worse_query grants access to
specific containers, not arbitrary `/var` files.

See [the feature/path support matrix](SUPPORT.zh-CN.md). A transport implementation,
verified file write and working device feature are three separate things. These
changes have not been compiled with Xcode or validated on a real iOS device in
the Linux development environment.

## Build and install

1. On a Mac with Xcode 27 or newer, open `NuggetQuery.xcodeproj`.
2. Select the NuggetQuery target, set your development team and a unique bundle
   identifier. Keep the target/product executable named **NuggetQuery** so the
   desktop can discover it even if the bundle ID changes.
3. Set `NUGGET_QUERY_APP_GROUP` to a new, **dedicated** App Group registered to
   your team. Add it under Signing & Capabilities → App Groups. The upstream
   exploit temporarily replaces this group's `Library/Caches`; do not use a
   group holding another application's important caches. The companion reads
   the actual signed App Groups at runtime, following GestaltX's implementation.
4. Build and run on the device with a provisioning profile containing that group.
   File Sharing is already enabled. A simulator cannot validate the exploit.

`bash companion/build-ipa.sh` creates an **unsigned** IPA on a Mac with a suitable
Xcode. It must be signed with a usable App Group before installation. The manual
`Build NuggetQuery IPA` workflow runs the same script; it does not publish a
release. No new IPA has been built or signed in this Linux workspace.

**Upgrade desktop and companion together.** The new desktop publishes protocol 2;
a protocol-1 IPA will reject it. The new companion also accepts old protocol-1
MobileGestalt requests and preserves their original-backup format.

## Apply and reset

1. For MobileGestalt, tap **Export current MobileGestalt** in the companion,
   transfer the exported plist to the computer and select it in Nugget. Use a
   fresh export for the target device and OS build.
2. Select tweaks on the original Nugget pages and click Apply. The desktop
   rejects the entire selection if any destination is outside the supported
   container domains, before uploading any request.
3. Open NuggetQuery, tap **Load pending request**, review the file list/build,
   then tap **Apply to this device** within three minutes. Keep the app open.
4. The companion resolves container IDs, checks path containment, reads originals,
   checks access to **all** files and saves originals before writing a target.
   It writes in place for existing files, preserves their ownership and inode,
   then reads bytes back. On failure it attempts to restore every attempted file
   in reverse order. A crash can still interrupt writing or rollback.
5. Restart the device to test effects. PosterBoard format/key compatibility on
   27.x remains unverified, even if all bytes were written successfully.
6. **Reset → Mobile Gestalt** restores the first saved original for this OS
   build. Other unsupported global reset pages are excluded from the iOS 27
   reset dialog. Directory resets (including PosterBoard folder nullification)
   are rejected during on-device preflight; directory deletion is not emulated.

MobileGestalt edits with a supplied source baseline are rebased onto the current
`CacheExtra`: untouched fields remain intact and conflicting edits are rejected.
Cache UUID/version/data and individual-device identity fields must match. The original AI/Eligibility page now offers an iOS-27-only alternative matching
GestaltX's AI capability and independent RegionCode/sales-region presets. Code-only
changes (e.g. LL) preserve both existing sales suffix fields. Sales changes update
existing modern/legacy suffix keys; an explicitly chosen code takes precedence.
The old eligibility/Feature Flags selections are hidden and cleared on these
versions. This can be used to attempt mainland-China Apple Intelligence activation,
subject to hardware, OS and Apple services; it has not been tested on-device.
This bridge does not implement GestaltX's runtime CacheData patching and these
presets do not establish EU sideloading eligibility.

Originals are stored under `Documents/NuggetQuery-backups/<build>/` as plist
wrappers containing build, destination, and optional original contents. A missing
contents value records a file that did not originally exist. They are retained
for recovery; there is not yet a desktop UI to restore arbitrary container
backups. Legacy `MobileGestalt-original-<build>.plist` backups remain usable for
MobileGestalt reset. Deleting the companion deletes its backups. Never use a
backup from another build. The first backup is the actual pre-write state, which
may already contain modifications from another tool.

On timeout/disconnection the write status is **unknown**. Inspect the companion
and current files before retrying. The host never overwrites an unfinished
pending/processing request, and requests are not executed automatically.

## Protocol and container resolution

House Arrest vends the signed companion's Documents directory. The host uploads
a complete binary plist and atomically renames it to `NuggetQuery-pending.plist`.
Version 2 requests contain `protocol`, UUID `id`, `build`, `version`, operation
`batch`, empty top-level `contents`, and `files`. Each entry contains `domain`,
container-relative `path`, `operation`, and bytes `contents`; optional
`containerHint` is installation metadata, and optional `baseline` is the source
MobileGestalt plist. The limit is 4096 files and 256 MiB of contents/baselines.

Supported operations are `write`, `merge_plist`, and `restore_original`. The host
uses `merge_plist` only for the lock-screen-footnote configuration plist, preserving
unrelated keys. An empty MobileGestalt payload means original restore; an empty
ordinary file payload remains an empty file, as in Nugget's original generators.

Supported domain families:

- `SysSharedContainerDomain-<id>`: named SystemGroup container, including MobileGestalt.
- `SysContainerDomain-<id>`: enumerate the accessible iOS 27 System parent and match
  `com.apple.containermanager.identifier` (or a literal UUID).
- `AppDomain-<bundle>` / `AppDomainPlugin-<bundle>`: use installation metadata when
  present, verify its bounded UUID-container path and on-device identifier;
  otherwise try the accessible System parent. A missing container path is an
  error, not guessed. Some internal services may not be discoverable this way.
- `AppDomainGroup-<id>`: enumerate AppGroup and match the on-device identifier or UUID.
- `ContainerPathDomain-<kind>-<UUID>`: bounded raw app-container templates, with
  kind `Application`, `InternalDaemon`, or `PluginKitPlugin`. Known UUIDs are required.

`..`, malformed domains, symlink escapes, duplicate logical destinations and
multiple domains resolving to the same target are rejected. Sandbox access does
not bypass filesystem ownership/ACLs. Non-container domains, including
HomeDomain, ManagedPreferencesDomain, DatabaseDomain, and SystemPreferencesDomain,
are rejected. Restore setup helpers, FrontBoard rebuild, and TrustStore restore
are omitted on iOS 27 because there is no backup restore to prepare or repair.

The companion checks its own OS/build, claims the request as
`NuggetQuery-processing.plist`, then atomically publishes `NuggetQuery-result.plist`
with matching protocol/UUID/build, success, and message. The host ignores old
UUIDs and waits for the processing marker to clear before allowing a reboot.

## Sources and validation

- `worse_query.m` / `.h`: unmodified forcequitOS/worse_query commit
  `d1540e20cd82b974d891e0551ced6d6aeb570ac2`, Copyright 2026 Taj C (forcequit),
  GPL-3.0-or-later. See `LICENSE.worse_query`.
- `GXEntitlementsReader.m` / `.h`: unmodified huamidev/GestaltX commit
  `671f099c61d20b9750b6cb0a5c5152525ed470b0`, Copyright 2026 huamidev,
  GPL-3.0-only. See `LICENSE.GestaltX` and `THIRD_PARTY_NOTICES.md`.
- GestaltX's narrow cache-directory grant, original-value preservation and
  transaction checks informed this integration. Its UI, CacheData
  scanner, assets, and respring code are not bundled. MG AI/region behavior and
  key mappings are independently adapted from its Capabilities/GestaltDocument
  implementations, with attribution in mobilegestalt_region_tweak.py.

Host checks:

```sh
QT_QPA_PLATFORM=offscreen .env/bin/python -m unittest discover -s tests -v
```

Before calling this stable, build the IPA and validate export, mixed-file preflight
failure without mutation, file permissions, write/read-back, reboot effects,
MobileGestalt reset, stale baselines, interrupted requests, and per-file rollback
on each supported OS/device. Host tests mock the iOS transport and do not prove
on-device Swift behavior or the exploit's success.
