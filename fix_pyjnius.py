"""
p4a hook file used via  p4a.hook = ./fix_pyjnius.py  in buildozer.spec.

p4a calls the following functions (passing its Context object as the first
argument) at the listed lifecycle points:

  before_apk_build(ctx)   – after all packages are compiled, before APK build
  after_apk_build(ctx)    – after APK build
  before_apk_assemble(ctx)– before APK assemble step
  after_apk_assemble(ctx) – after APK assemble step

Functions with other names (e.g. patch_pyjnius) are NEVER called by p4a and
are kept here only for historical reference.

Fixes included
--------------
1. pyjnius 1.6.1 Python-2 'long' type – fixes Cython build failure on Python 3
2. 16 KB page-size alignment – injects arm64-v8a linker flags into archs.py so
   Google Play accepts the build (required for API-35+ uploads since Nov 2025).
"""
import os
import re


# ---------------------------------------------------------------------------
# 1. pyjnius fix (kept for reference; no longer called automatically)
# ---------------------------------------------------------------------------

def fix_pyjnius_syntax(dist_dir):
    """Fix Python 2 'long' syntax in pyjnius source files."""

    pyjnius_dirs = []
    for root, dirs, files in os.walk(dist_dir):
        if 'jnius_utils.pxi' in files:
            pyjnius_dirs.append(root)

    for pyjnius_dir in pyjnius_dirs:
        pxi_file = os.path.join(pyjnius_dir, 'jnius_utils.pxi')
        if not os.path.exists(pxi_file):
            continue

        print(f"[FIX_PYJNIUS] Patching {pxi_file}")
        with open(pxi_file, 'r', encoding='utf-8') as f:
            content = f.read()

        modified = content.replace(
            'isinstance(arg, long)',
            'isinstance(arg, int)'
        )

        if modified != content:
            with open(pxi_file, 'w', encoding='utf-8') as f:
                f.write(modified)
            print(f"[FIX_PYJNIUS] Fixed 'long' type references in {pxi_file}")
        else:
            print(f"[FIX_PYJNIUS] No changes needed in {pxi_file}")


# Not called by p4a (not a valid hook name) – kept for historical reference.
def patch_pyjnius(dist_dir, **kwargs):
    fix_pyjnius_syntax(dist_dir)


# ---------------------------------------------------------------------------
# 2. 16 KB page-size linker-flag patch for ArchAarch_64
# ---------------------------------------------------------------------------

# Text injected into archs.py right after ArchAarch_64.arch_cflags = [...]
_16KB_INJECTION = '''

    # 16 KB page-size support (required by Google Play for API 35+ updates).
    # NDK r27 and lower need explicit linker flags; r28+ sets this automatically.
    # These flags are appended to LDFLAGS and LDSHARED so every .so built for
    # arm64-v8a carries ELF LOAD segments aligned to 16 KB boundaries.
    _ldflags_16kb = [
        '-Wl,-z,max-page-size=16384',
        '-Wl,-z,common-page-size=16384',
    ]

    def get_env(self, with_flags_in_cc=True):
        env = super().get_env(with_flags_in_cc)
        flags_16kb = ' '.join(self._ldflags_16kb)
        env['LDFLAGS'] = env['LDFLAGS'] + ' ' + flags_16kb
        env['LDSHARED'] = env['LDSHARED'] + ' ' + flags_16kb
        return env
'''


def _patch_archs_16kb():
    """
    Locate the active pythonforandroid/archs.py and inject 16 KB linker flags
    into ArchAarch_64 if they are not already present.

    Returns True if the patch was just applied, False if it was already there
    or if archs.py could not be found/modified.
    """
    try:
        import pythonforandroid as _p4a
    except ImportError:
        print("[16KB] pythonforandroid not importable – skipping archs.py patch.")
        return False

    archs_path = os.path.join(os.path.dirname(_p4a.__file__), 'archs.py')
    if not os.path.exists(archs_path):
        print(f"[16KB] archs.py not found at {archs_path} – skipping patch.")
        return False

    with open(archs_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if '_ldflags_16kb' in content:
        print("[16KB] archs.py already has 16 KB linker flags – no action needed.")
        return False

    # Match ArchAarch_64 class declaration through the closing ] of arch_cflags.
    # re.DOTALL lets .* cross newlines; count=1 ensures only the first match.
    patched = re.sub(
        r'(class ArchAarch_64\(Arch\):.*?arch_cflags\s*=\s*\[.*?\])',
        lambda m: m.group(1) + _16KB_INJECTION,
        content,
        count=1,
        flags=re.DOTALL,
    )

    if patched == content:
        print("[16KB] WARNING: Could not locate ArchAarch_64.arch_cflags in "
              f"{archs_path} – format may have changed.")
        print(f"[16KB] Please manually add the 16 KB linker flags to {archs_path}")
        return False

    with open(archs_path, 'w', encoding='utf-8') as f:
        f.write(patched)

    print(f"[16KB] Patched {archs_path} with 16 KB page-size linker flags.")
    return True


# ---------------------------------------------------------------------------
# p4a lifecycle hook – called by p4a after all packages are compiled,
# just before the APK/AAB is assembled.
# ---------------------------------------------------------------------------

def before_apk_build(ctx):
    """
    Ensure archs.py has 16 KB linker flags before the APK is built.

    On a normal incremental build the flags are already present and this is a
    no-op.  If .buildozer was wiped and p4a was re-downloaded, the patch is
    reapplied here.  Because the packages were compiled without the flags in
    that first run the build is aborted with clear instructions to delete the
    stale build artifacts and re-run buildozer.
    """
    just_patched = _patch_archs_16kb()

    if just_patched:
        print()
        print("=" * 70)
        print("[16KB] archs.py was JUST NOW patched for 16 KB page-size support.")
        print("[16KB] The .so files compiled in THIS run do NOT have 16 KB alignment.")
        print("[16KB]")
        print("[16KB] To produce a 16 KB-compliant build, run these commands and")
        print("[16KB] then re-run  buildozer android release :")
        print("[16KB]")
        print("[16KB]   PowerShell (Windows):")
        print("[16KB]     Remove-Item -Recurse -Force "
              r"'.buildozer\android\platform\build-arm64-v8a\build'")
        print("[16KB]     Remove-Item -Recurse -Force "
              r"'.buildozer\android\platform\build-arm64-v8a\dists'")
        print("[16KB]")
        print("[16KB]   Then in WSL:")
        print("[16KB]     buildozer android release")
        print("=" * 70)
        print()
        raise SystemExit(
            "[16KB] Build aborted: stale .so files detected. "
            "Delete build artifacts and re-run buildozer android release."
        )
