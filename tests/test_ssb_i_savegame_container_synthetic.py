"""Synthetischer BCPS-Container: Regression ohne externe Savegame-Fixtures.

Warum diese Datei existiert (SSB-I-Audit 05.11.2026)
  Die bestehenden Tests des Savegame-Providers (``test_ssb_i_savegame_provider``)
  laden zwei Referenz-Saves aus ``/tmp/starter-save`` und ``/tmp/second-save``.
  Diese Pfade existieren nicht mehr, also wurden 8 Tests still uebersprungen —
  genau der Provider, auf dem die einzige echte UI-Seite aufbaut, hatte damit
  keine laufende Regression.

  Dieser Test baut den Container im Test selbst: BCPS-Kopf, Chunk-Tabelle,
  zlib-Chunks, 16-Byte-Padding. Er braucht keine 23-MB-Fixture, laeuft in jeder
  Umgebung und prueft Lesen, Entpacken und die Fehlerpfade.

Format (aus ssb_i/savegame_provider.read_container/decompress):
  +0   'BCPS'                magic
  +4   int32                 version0
  +8   int64                 chunk_sizes_offset
  +16  int64                 unknown0
  +24  int64                 compressed_offset
  +32  int64                 uncompressed_size
  +40  float32               version1
  +44  int32                 unknown1
  +48  int64                 chunk_size_pre
  +56  int64                 padding_size
  +64  int32                 unknown2
  +68  char[4]               compression ('ZIP ')
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ssb_i.savegame_provider import SfsDecodeProvider  # noqa: E402


HEADER_SIZE = 96


def build_synthetic_sfs(payload: bytes, *, chunk_size_pre: int = 4096,
                        padding: int = 16, compression: bytes = b"ZIP ",
                        magic: bytes = b"BCPS") -> bytes:
    """Baut einen minimalen, aber formatkonformen BCPS-Container."""
    chunks = [payload[i:i + chunk_size_pre]
              for i in range(0, len(payload), chunk_size_pre)]
    compressed = [zlib.compress(c) for c in chunks]

    chunk_count = len(compressed)
    chunk_sizes_offset = HEADER_SIZE
    table = struct.pack(f"<{chunk_count}i", *[len(c) for c in compressed])
    compressed_offset = chunk_sizes_offset + len(table)
    if padding:
        compressed_offset = (compressed_offset + padding - 1) & ~(padding - 1)

    header = bytearray(HEADER_SIZE)
    header[0:4] = magic
    struct.pack_into("<i", header, 4, 3)                       # version0
    struct.pack_into("<q", header, 8, chunk_sizes_offset)
    struct.pack_into("<q", header, 16, 0)                      # unknown0
    struct.pack_into("<q", header, 24, compressed_offset)
    struct.pack_into("<q", header, 32, len(payload))
    struct.pack_into("<f", header, 40, 1.0)                    # version1
    struct.pack_into("<i", header, 44, 0)                      # unknown1
    struct.pack_into("<q", header, 48, chunk_size_pre)
    struct.pack_into("<q", header, 56, padding)
    struct.pack_into("<i", header, 64, 0)                      # unknown2
    header[68:72] = compression

    body = bytearray(table)
    body += b"\x00" * (compressed_offset - chunk_sizes_offset - len(table))
    for c in compressed:
        body += c
        if padding:
            body += b"\x00" * ((-len(c)) % padding)
    return bytes(header) + bytes(body)


@pytest.fixture()
def payload() -> bytes:
    # 10240 Byte -> bei 4096 Byte Chunks: 4096 + 4096 + 2048 = 3 Chunks
    return bytes(range(256)) * 40


@pytest.fixture()
def synthetic_path(tmp_path, payload) -> Path:
    p = tmp_path / "synthetic_save.sfs"
    p.write_bytes(build_synthetic_sfs(payload))
    return p


def test_container_metadata(synthetic_path, payload):
    provider = SfsDecodeProvider()
    container = provider.read_container(str(synthetic_path))
    assert container.chunk_count == 3
    assert container.uncompressed_size == len(payload)
    assert container.chunk_size_pre == 4096
    assert container.padding_size == 16
    assert container.compressed_offset > 0


def test_decompress_round_trip(synthetic_path, payload):
    provider = SfsDecodeProvider()
    assert provider.decompress(str(synthetic_path)) == payload


def test_decompress_without_padding(tmp_path, payload):
    p = tmp_path / "nopad.sfs"
    p.write_bytes(build_synthetic_sfs(payload, padding=0))
    provider = SfsDecodeProvider()
    assert provider.read_container(str(p)).chunk_count == 3
    assert provider.decompress(str(p)) == payload


def test_single_chunk(tmp_path):
    data = b"SFS_SAVEGAME" + b"\xAB" * 512
    p = tmp_path / "small.sfs"
    p.write_bytes(build_synthetic_sfs(data))
    provider = SfsDecodeProvider()
    assert provider.read_container(str(p)).chunk_count == 1
    assert provider.decompress(str(p)) == data


def test_rejects_wrong_magic(tmp_path, payload):
    p = tmp_path / "bad.sfs"
    p.write_bytes(build_synthetic_sfs(payload, magic=b"XXXX"))
    with pytest.raises(ValueError, match="Not an SFS file"):
        SfsDecodeProvider().read_container(str(p))


def test_rejects_unknown_compression(tmp_path, payload):
    p = tmp_path / "lz4.sfs"
    p.write_bytes(build_synthetic_sfs(payload, compression=b"LZ4 "))
    with pytest.raises(ValueError, match="Only ZIP compression supported"):
        SfsDecodeProvider().read_container(str(p))


def test_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        SfsDecodeProvider().read_container(str(tmp_path / "nope.sfs"))


def test_reports_zlib_failure_with_chunk_index(tmp_path, payload):
    raw = bytearray(build_synthetic_sfs(payload))
    container = SfsDecodeProvider().read_container(
        str(_write(tmp_path, bytes(raw))))
    # Ersten Chunk beschaedigen, ohne die Tabelle zu aendern
    raw[container.compressed_offset] ^= 0xFF
    broken = _write(tmp_path, bytes(raw), name="broken.sfs")
    with pytest.raises(ValueError, match="zlib-decompression failed at chunk 0"):
        SfsDecodeProvider().decompress(str(broken))


def test_provider_declares_read_only():
    caps = SfsDecodeProvider().capabilities()
    assert caps["memory_read"] is True
    assert caps["memory_write_observation"] is False
    assert caps["execution_events"] is False


def _write(tmp_path, data: bytes, name: str = "tmp.sfs") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p
