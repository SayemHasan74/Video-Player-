"""Add the standard NVIDIA/AMD data exports to an unsigned Windows EXE."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import pefile


EXPORTS = (
    "AmdPowerXpressRequestHighPerformance",
    "NvOptimusEnablement",
)


def align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def patch_executable(path: Path) -> None:
    path = path.resolve()
    pe = pefile.PE(str(path), fast_load=False)
    if pe.PE_TYPE != pefile.OPTIONAL_HEADER_MAGIC_PE_PLUS:
        raise RuntimeError("GPU export patch requires an x64 PE32+ executable")
    existing = {
        symbol.name.decode("ascii")
        for symbol in getattr(pe, "DIRECTORY_ENTRY_EXPORT", ()).symbols
        if symbol.name
    } if hasattr(pe, "DIRECTORY_ENTRY_EXPORT") else set()
    if set(EXPORTS).issubset(existing):
        return

    data = bytearray(path.read_bytes())
    pe_offset = pe.DOS_HEADER.e_lfanew
    optional_offset = pe_offset + 4 + 20
    section_table = optional_offset + pe.FILE_HEADER.SizeOfOptionalHeader
    count = pe.FILE_HEADER.NumberOfSections
    new_header_offset = section_table + count * 40
    first_raw = min(section.PointerToRawData for section in pe.sections if section.PointerToRawData)
    if new_header_offset + 40 > first_raw:
        raise RuntimeError("PE headers have no room for the GPU export section")

    section_alignment = pe.OPTIONAL_HEADER.SectionAlignment
    file_alignment = pe.OPTIONAL_HEADER.FileAlignment
    virtual_address = align(
        max(section.VirtualAddress + max(section.Misc_VirtualSize, section.SizeOfRawData) for section in pe.sections),
        section_alignment,
    )
    overlay_start = max(section.PointerToRawData + section.SizeOfRawData for section in pe.sections)
    raw_offset = align(overlay_start, file_alignment)

    export_dir_size = 40
    functions_offset = export_dir_size
    names_offset = functions_offset + 8
    ordinals_offset = names_offset + 8
    amd_value_offset = align(ordinals_offset + 4, 4)
    nv_value_offset = amd_value_offset + 4
    module_name_offset = nv_value_offset + 4
    module_name = path.name.encode("ascii") + b"\0"
    amd_name_offset = module_name_offset + len(module_name)
    amd_name = EXPORTS[0].encode("ascii") + b"\0"
    nv_name_offset = amd_name_offset + len(amd_name)
    nv_name = EXPORTS[1].encode("ascii") + b"\0"
    payload_size = nv_name_offset + len(nv_name)
    raw_size = align(payload_size, file_alignment)
    payload = bytearray(raw_size)

    rva = lambda offset: virtual_address + offset
    struct.pack_into(
        "<IIHHIIIIIII",
        payload,
        0,
        0,
        0,
        0,
        0,
        rva(module_name_offset),
        1,
        2,
        2,
        rva(functions_offset),
        rva(names_offset),
        rva(ordinals_offset),
    )
    struct.pack_into("<II", payload, functions_offset, rva(amd_value_offset), rva(nv_value_offset))
    struct.pack_into("<II", payload, names_offset, rva(amd_name_offset), rva(nv_name_offset))
    struct.pack_into("<HH", payload, ordinals_offset, 0, 1)
    struct.pack_into("<II", payload, amd_value_offset, 1, 1)
    payload[module_name_offset:module_name_offset + len(module_name)] = module_name
    payload[amd_name_offset:amd_name_offset + len(amd_name)] = amd_name
    payload[nv_name_offset:nv_name_offset + len(nv_name)] = nv_name

    padding = b"\0" * (raw_offset - overlay_start)
    data = data[:overlay_start] + padding + payload + data[overlay_start:]
    section_header = struct.pack(
        "<8sIIIIIIHHI",
        b".gpuexp\0",
        payload_size,
        virtual_address,
        raw_size,
        raw_offset,
        0,
        0,
        0,
        0,
        0xC0000040,
    )
    data[new_header_offset:new_header_offset + 40] = section_header
    struct.pack_into("<H", data, pe_offset + 4 + 2, count + 1)
    struct.pack_into("<II", data, optional_offset + 112, virtual_address, export_dir_size)
    struct.pack_into("<I", data, optional_offset + 56, align(virtual_address + payload_size, section_alignment))
    struct.pack_into("<I", data, optional_offset + 64, 0)
    pe.close()
    path.write_bytes(data)

    verified = pefile.PE(str(path), fast_load=False)
    names = {
        symbol.name.decode("ascii")
        for symbol in verified.DIRECTORY_ENTRY_EXPORT.symbols
        if symbol.name
    }
    missing = set(EXPORTS) - names
    if missing:
        raise RuntimeError(f"GPU exports were not written: {sorted(missing)}")
    verified.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    patch_executable(args.executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
