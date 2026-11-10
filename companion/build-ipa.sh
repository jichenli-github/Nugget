#!/bin/bash
# Build an unsigned archive. Signing with an App Group remains a separate step.
set -euo pipefail
companion_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
query_build_dir="${NUGGET_QUERY_BUILD_DIR:-$companion_root/build}"
if ! command -v xcodebuild >/dev/null 2>&1; then
    echo "NuggetQuery requires macOS with Xcode 27+; xcodebuild was not found." >&2
    exit 1
fi
mkdir -p "$query_build_dir"
query_build_dir="$(cd -- "$query_build_dir" && pwd)"
xcodebuild -project "$companion_root/NuggetQuery.xcodeproj" \
    -scheme NuggetQuery -configuration Release -sdk iphoneos \
    -destination 'generic/platform=iOS' -derivedDataPath "$query_build_dir/DerivedData" \
    CODE_SIGNING_ALLOWED=NO build
query_app="$query_build_dir/DerivedData/Build/Products/Release-iphoneos/NuggetQuery.app"
test -d "$query_app"
# Use a fresh package directory without deleting another build's data.
query_package_dir="$(mktemp -d "$query_build_dir/package.XXXXXX")"
mkdir "$query_package_dir/Payload"
cp -R "$query_app" "$query_package_dir/Payload/"
cp "$companion_root/LICENSE.worse_query" "$query_package_dir/Payload/NuggetQuery.app/"
cp "$companion_root/LICENSE.GestaltX" "$query_package_dir/Payload/NuggetQuery.app/"
cp "$companion_root/THIRD_PARTY_NOTICES.md" "$query_package_dir/Payload/NuggetQuery.app/"
(cd "$query_package_dir" && /usr/bin/ditto -c -k --keepParent Payload "$query_build_dir/NuggetQuery-unsigned.ipa")
echo "Unsigned IPA: $query_build_dir/NuggetQuery-unsigned.ipa"
echo "Sign with a dedicated, provisioned App Group before installing."
