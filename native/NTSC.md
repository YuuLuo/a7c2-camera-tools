# Optional NTSC startup notice skip

The Windows and macOS feature screens offer Keep (the default) or Skip NTSC
startup notice after choosing FL2/FL3, sound, or both. The choice is saved as
`disable_ntsc_warning: true` and feature ID `no_ntsc_notice_v2`. Existing runs
without that field retain the original behavior; they are not migrated.
This option is an addition to an existing feature selection, not a standalone
NTSC-only installer. It does not select NTSC or disable the PAL/NTSC selector.

This ports the narrowed two-instruction patch from the neighboring
`a7c2-fl23-macos` project at revision
`41950d3eab53e0b801f315af07505a2d0d3f76af`, specifically
`research/two-profiles/README.md` and `macfl23/integrated.py`. It does not port
the earlier broader condition bypass, MR-card changes, or that project's
live filesystem installer. Attribution and license are in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

| appFw.so offset | nflasha15 offset | Original instruction | Replacement |
| --- | --- | --- | --- |
| `0x2061880` | `0x2789b480` | `mov w2, #0x36b` | `b 0x206189c` (`07000014`) |
| `0x2061da8` | `0x2789b9a8` | `mov w2, #0x36b` | `b 0x2061dd0` (`0a000014`) |

Both replacements enter the existing continuation after the native conditions
have selected the NTSC message. They do not write general registers or NZCV.
The upstream native-window research reported 24,576 fixture cases: 576 target
NTSC selections changed and 24,000 other cases retained their message, trace
and registers. These are upstream results, not a new full-startup test here.

The DAT port accepts only the existing pinned official 2.01 source SHA-256
`eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31`.
The extracted original appFw.so was verified against its complete SHA-256
`2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`.
The filesystem's block mapping, rather than a constant file-to-partition delta,
was used to locate both instructions. The pinned JSON stores hashes of the
original instructions and 132-byte contexts. Both windows and the current
partition checksum are checked before any change. The builder updates the
partition checksum, encrypts, checks the DAT CRC and decrypts the complete
output for byte-for-byte verification. Sound and FL2/FL3 construction continue
to use their original source checks. Only the selected NTSC paths are added.

For an offline build, create a private output directory and run from the repo
root with the installed Python dependencies:

```sh
python3 macos/mac_service_readonly/feature_package_200.py \
  --official BODYDATA.DAT --out-dir /path/to/private/output \
  --fl23 --audio-mode none --disable-ntsc-warning
```

Windows uses `windows/runtime/release/feature_package_200.py` with the same
arguments. Omit `--disable-ntsc-warning` to retain the notice. Sound options
remain `--audio-mode stock` or `--audio-mode custom --audio sample.wav
--volume 50`; omit `--fl23` for sound without FL2/FL3. Generated firmware and
private manifests are excluded from version control.

Offline tests cover feature composition, branch destinations, both platform
asset copies, manifest selection/tampering, and no mutation on a second-window
or checksum mismatch. Full package builds and resume checks were run against
the supplied official DAT for all five existing feature combinations with
NTSC skipping, including synthetic custom audio. An independent complete
plaintext interval comparison confirmed the FL2/FL3-only output differs from
the original FL2/FL3 package only at the two instructions and eight partition
checksum characters. Changing a resumed build's saved NTSC selection was
rejected without modifying its manifest. The 23 Windows offline tests (with
`msvcrt` keyboard access stubbed on macOS) and three macOS tests passed; this
does not exercise native Windows USB or keyboard behavior. The FL2/FL3-only NTSC-skipping
DAT SHA-256 is
`ca1952eb7e8e18285cfc5fc6acc02026efb91723baaccd483ae7393a558b4704`.

No camera was connected or written during the automated port and audit. The
upstream project's reported camera results do not validate this repository's
DAT installation path or sound combinations. Subsequent user feedback is
recorded below; detailed hardware coverage and recovery remain unverified.
The interactive workflow requests a manual NTSC-notice check after cold boot.

## User-reported camera result

On 2026-11-08, one A7C II user reported the mod working after QA. The setup
discussed was unmodified official 2.01 with FL2/FL3, built-in electronic shutter
sound and NTSC skipping, without custom audio replacement. This is a user
report of overall success; it does not include a flashed-package hash,
independent device readback, or itemized feature and cold-start results.
Custom audio, full video coverage, recovery and long-term stability are not
established by this report. The automated evidence below remains offline.

## Combined-package audit

The follow-up audit verified FL2/FL3 + NTSC skip with both stock sound and
synthetic custom audio against the matching packages without NTSC skipping.
Full decrypt and interval comparisons, ext2 app extraction, ELF mapping,
header CRC and AP/WBI/CP partition CRC checks passed. The only added changes
are the two AP instructions and AP checksum text; WBI and CP remain byte-for-byte
identical to their matching sound baseline. Both extracted programs have the
same startup window.

The final extracted custom-sound program also passed 24,576 Unicorn ARM64
fixture cases: 576 NTSC messages were skipped, and 24,000 other cases preserved
message, instruction trace and general registers. Unlike the earlier upstream
citation, these cases were run here against this repository's output. The
external services are fixtures; this is not full camera startup emulation.

The WBI scan found no exact 16-, 32- or 128-byte contexts surrounding either
NTSC instruction. Positive controls found the known sound registration code
in WBI. This supports retaining the AP-only change but is a bounded byte
search, not proof of every WBI loader behavior.

Two host issues were corrected: the manifest's top-level AP CRC now describes
the final package rather than the intermediate sound patch, and resume checks
bind the selected package to the saved feature/volume/audio plan before update
writes. There are now 29 passing offline tests (25 Windows tests with keyboard
access stubbed on macOS, four macOS tests), including rejection of a substituted
package before any p1 write request.

The sanitized [validation report](ntsc-validation.json) records source/output
hashes and the evidence limits. The stock-sound all-features DAT hash is
`24c43b0b50f9a3c238184d6a97b8cdc84c42a8cac07d17eef9ee7ed6240c7cc3`.
Custom audio changes the full DAT hash; the recorded custom example is a
synthetic test tone, not a recommended sound file.

Reproduce the independent comparison with two otherwise identical feature
builds (one with NTSC skipping), using Python with NumPy and PyCryptodome:

```sh
python3 native/verify_ntsc_dat.py \
  --baseline /private/baseline/BODYDATA_FEATURES_200.DAT \
  --candidate /private/candidate/BODYDATA_FEATURES_200.DAT \
  --scratch /private/scratch --app-output /private/candidate-appFw.so
```

The scratch directory must exist and have about 2.3 GB free; the optional app
output must not exist. With `unicorn==2.1.4`, use the original appFw.so extracted
from the pinned official DAT and the candidate extracted above:

```sh
python3 native/verify_ntsc_boot.py \
  --original-app /private/original-appFw.so \
  --candidate-app /private/candidate-appFw.so
```

These scripts perform no USB operations or camera writes. On macOS, Unicorn's
JIT may require execution outside a restrictive process sandbox.
