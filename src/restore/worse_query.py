"""Device-side container transport. Never falls back to partial restore on iOS 27.

The exploit grants container access, not arbitrary /var access. Plan the entire
selection before publishing anything so unsupported selections cannot half-apply.
"""
import asyncio
import plistlib
import re
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QCoreApplication
from pymobiledevice3.services.house_arrest import HouseArrestService
from pymobiledevice3.services.installation_proxy import InstallationProxyService

from src.exceptions.nugget_exception import NuggetException
from src.tweaks.basic_plist_locations import FileLocation

MGA_DOMAIN = "SysSharedContainerDomain-systemgroup.com.apple.mobilegestaltcache"
MGA_RELATIVE_PATH = "Library/Caches/com.apple.MobileGestalt.plist"
PENDING = "/Documents/NuggetQuery-pending.plist"
RESULT = "/Documents/NuggetQuery-result.plist"
PROCESSING = "/Documents/NuggetQuery-processing.plist"
PROTOCOL = 2
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 4096
CONTAINER_DOMAINS = ("SysSharedContainerDomain-", "SysContainerDomain-", "AppDomain-", "AppDomainGroup-", "AppDomainPlugin-", "ContainerPathDomain-")
RAW_ROOTS = {
    "/var/containers/Shared/SystemGroup/": "SysSharedContainerDomain-",
    "/var/containers/Data/System/": "SysContainerDomain-",
    "/var/mobile/Containers/Shared/AppGroup/": "AppDomainGroup-",
}


def destination(file):
    """Convert backup-domain paths to bounded logical container destinations."""
    domain, relative = file.domain or "", file.restore_path
    if not domain:
        if relative.startswith("/private/var/"):
            relative = relative[len("/private"):]
        for root, prefix in RAW_ROOTS.items():
            if relative.startswith(root):
                identifier, separator, relative = relative[len(root):].partition("/")
                if separator:
                    domain = prefix + identifier
                break
    if not domain:
        for kind in ("Application", "InternalDaemon", "PluginKitPlugin"):
            root = f"/var/mobile/Containers/Data/{kind}/"
            if relative.startswith(root):
                identifier, separator, relative = relative[len(root):].partition("/")
                if separator and re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", identifier):
                    domain = f"ContainerPathDomain-{kind}-{identifier}"
                break
    prefix = next((prefix for prefix in CONTAINER_DOMAINS if domain.startswith(prefix)), None)
    if not prefix or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", domain[len(prefix):]):
        raise NuggetException(f"worse_query cannot access {file.domain or ''}:{file.restore_path}. "
                              "iOS 27 container access does not include HomeDomain, ManagedPreferencesDomain, "
                              "DatabaseDomain or SystemPreferencesDomain. No changes were sent.")
    if prefix == "ContainerPathDomain-" and not re.fullmatch(
            r"(?:Application|InternalDaemon|PluginKitPlugin)-[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", domain[len(prefix):]):
        raise NuggetException("Invalid app container UUID.")
    relative = relative.lstrip("/")
    if not relative or any(part in ("", ".", "..") for part in relative.split("/")) or "\x00" in relative or "\\" in relative:
        raise NuggetException(f"Invalid container-relative path: {file.restore_path}")
    return domain, relative


def split_query_files(files):
    """All iOS 27 files must use the companion; validate all before sending."""
    seen = set()
    for file in files:
        target = destination(file)
        if target in seen:
            raise NuggetException(f"Duplicate container destination: {target[0]}/{target[1]}")
        seen.add(target)
    return list(files), []


def file_contents(file):
    contents = Path(file.contents_path).read_bytes() if file.contents_path else file.contents
    if not isinstance(contents, bytes):
        raise NuggetException("Invalid file contents; expected bytes.")
    return contents


def validate_mga(contents):
    if not contents:
        return
    try:
        if not isinstance(plistlib.loads(contents).get("CacheExtra"), dict):
            raise ValueError("CacheExtra is missing")
    except (AttributeError, ValueError, plistlib.InvalidFileException) as exc:
        raise NuggetException("Invalid MobileGestalt plist.") from exc


def make_request(files, build, version, apps=None):
    # Accept a single file for callers of the original bridge API as well.
    files = list(files) if isinstance(files, (list, tuple)) else [files]
    split_query_files(files)
    if not 1 <= len(files) <= MAX_FILES:
        raise NuggetException("Select between 1 and 4096 container files.")
    entries, size = [], 0
    for file in files:
        domain, relative = destination(file)
        contents = file_contents(file)
        size += len(contents)
        if size > MAX_BYTES:
            raise NuggetException("NuggetQuery request exceeds 256 MiB; apply fewer files at once.")
        operation = "write"
        if (domain, relative) == (MGA_DOMAIN, MGA_RELATIVE_PATH):
            validate_mga(contents)
            operation = "write" if contents else "restore_original"
        elif (domain, relative) == ("SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles",
                                   "Library/ConfigurationProfiles/SharedDeviceConfiguration.plist"):
            operation = "merge_plist"
        entry = {"domain": domain, "path": relative, "operation": operation, "contents": contents}
        baseline = getattr(file, "query_baseline", None)
        if baseline is not None and (domain, relative) == (MGA_DOMAIN, MGA_RELATIVE_PATH):
            validate_mga(baseline)
            entry["baseline"] = baseline
            size += len(baseline)
            if size > MAX_BYTES:
                raise NuggetException("NuggetQuery request exceeds 256 MiB; apply fewer files at once.")
        if domain.startswith("AppDomain-") and apps:
            app = apps.get(domain[len("AppDomain-"):], {})
            hint = app.get("Container")
            if isinstance(hint, str):
                entry["containerHint"] = hint
        entries.append(entry)
    return {"protocol": PROTOCOL, "id": str(uuid4()), "build": build, "version": version,
            "operation": "batch", "contents": b"", "files": entries}


async def perform_worse_query(files, device, lockdown_client, progress_callback, timeout=180):
    # Validate before discovery or any upload.
    request = make_request(files, device.build, device.version)
    async with InstallationProxyService(lockdown_client) as ips:
        user_apps = await ips.get_apps(application_type="User", calculate_sizes=False)
        all_apps = await ips.get_apps(application_type="Any", calculate_sizes=False) if any(
            entry["domain"].startswith("AppDomain-") for entry in request["files"]) else {}
    companions = [app["CFBundleIdentifier"] for app in user_apps.values()
                  if app.get("CFBundleExecutable") == "NuggetQuery"]
    if len(companions) != 1:
        raise NuggetException(QCoreApplication.tr(
            "Install one signed NuggetQuery companion app with an App Group to use worse_query on iOS 27.0–27.2."
        ), detailed_text="See companion/README.md in the Nugget source repository.")
    if all_apps:
        request = make_request(files, device.build, device.version, all_apps)
    async with await HouseArrestService.create(lockdown=lockdown_client, bundle_id=companions[0], documents_only=True) as afc:
        if await afc.exists(PENDING) or await afc.exists(PROCESSING):
            raise NuggetException(QCoreApplication.tr(
                "A NuggetQuery request is already pending. Complete or discard it in the companion app first."
            ))
        staging = PENDING + "." + request["id"]
        try:
            await afc.set_file_contents(staging, plistlib.dumps(request, fmt=plistlib.FMT_BINARY))
            await afc.rename(staging, PENDING)
        finally:
            if await afc.exists(staging):
                await afc.rm(staging)
        progress_callback(QCoreApplication.tr(
            "Open NuggetQuery on your device, load the pending request, then tap Apply. Keep it open."
        ))
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await afc.exists(RESULT):
                result = plistlib.loads(await afc.get_file_contents(RESULT))
                if result.get("id") == request["id"]:
                    if result.get("protocol") != PROTOCOL or result.get("build") != device.build:
                        raise NuggetException("NuggetQuery returned an incompatible result. Install the updated protocol-2 IPA.")
                    if result.get("success") is not True:
                        raise NuggetException("NuggetQuery: " + str(result.get("message", "Write failed.")))
                    if not await afc.exists(PROCESSING):
                        return
            await asyncio.sleep(1)
        raise NuggetException(QCoreApplication.tr(
            "Timed out waiting for NuggetQuery. The write result is unknown. Check the companion app before retrying."
        ))


def supports_query_tweak(tweak, tweak_id=None):
    """Ignore stale selections from disabled controls without altering legacy state.

    Templates still undergo destination preflight; this only classifies built-in
    tweaks whose targets are known. No unsupported file is passed to a restore.
    """
    from src.tweaks.tweak_classes import (BasicPlistTweak, NullifyFileTweak,
                                          FeatureFlagTweak, MobileGestaltCacheDataTweak)
    from src.tweaks.eligibility_tweak import EligibilityTweak, AITweak, BookRestoreFileTweak
    from src.tweaks.passcode_theme_tweak import PasscodeThemeTweak
    from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
    from src.tweaks.tweak_names import TweakID
    from src.restore.restore import FileToRestore
    if tweak_id in (TweakID.iPadOS, TweakID.iPadOSCacheData):
        return False
    if isinstance(tweak, (FeatureFlagTweak, MobileGestaltCacheDataTweak, EligibilityTweak,
                          AITweak, BookRestoreFileTweak, PasscodeThemeTweak, StatusBarTweak)):
        return False
    if isinstance(tweak, (BasicPlistTweak, NullifyFileTweak)):
        try:
            destination(FileToRestore(b"", tweak.file_location.value))
        except NuggetException:
            return False
    return True


def supports_query_template(template):
    from src.restore.restore import FileToRestore
    domain = template.domain
    if domain == "com.apple.PosterBoard":
        domain = "AppDomain-com.apple.PosterBoard"
    if template.change_bundle_id:
        domain = "AppDomain-" + template.bundle_id
    path = "/__nugget_container_probe"
    if domain.startswith("Sparserestore-"):
        path = domain[len("Sparserestore-"):] + path
        domain = ""
    try:
        destination(FileToRestore(b"", path, domain=domain))
        return True
    except NuggetException:
        return False
