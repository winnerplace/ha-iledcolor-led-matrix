import importlib.util
import pathlib

_BULK_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "iledcolor"
    / "bulk.py"
)
_spec = importlib.util.spec_from_file_location("iledcolor_bulk", _BULK_PATH)
bulk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bulk)


def test_bulk_data_frame_layout():
    frame = bulk.bulk_data_frame(0, bytes([0x11, 0x22, 0x33]))
    # A8 00 | outLen=5 | idx=0 (4B) | innerLen=3 | payload | checksum
    assert frame[:2] == bytes([0xA8, 0x00])
    assert frame[2:4] == (3 + 2).to_bytes(2, "big")
    assert frame[4:8] == (0).to_bytes(4, "big")
    assert frame[8:10] == (3).to_bytes(2, "big")
    assert frame[10:13] == bytes([0x11, 0x22, 0x33])
    body = frame[:-2]
    assert frame[-2:] == (sum(body) & 0xFFFF).to_bytes(2, "big")


def test_outer_inner_len_differ_by_two():
    frame = bulk.bulk_data_frame(7, bytes(range(40)))
    outer = int.from_bytes(frame[2:4], "big")
    inner = int.from_bytes(frame[8:10], "big")
    assert outer == inner + 2
    assert int.from_bytes(frame[4:8], "big") == 7


def test_bulk_end_frame_exact():
    assert bulk.bulk_end_frame() == bytes.fromhex("A802000602") + b"\x00\xb2"


def test_bulk_frames_chunking_and_index():
    payload = bytes(range(256)) * 4  # 1024 bytes
    mtu = 23
    frames = bulk.bulk_frames(payload, mtu)
    chunk_size = mtu - 13  # 10
    expected_data = -(-len(payload) // chunk_size)  # ceil
    assert len(frames) == expected_data + 1  # + trailer
    for i, frame in enumerate(frames[:-1]):
        assert int.from_bytes(frame[4:8], "big") == i
        assert int.from_bytes(frame[8:10], "big") <= chunk_size
    assert frames[-1] == bulk.bulk_end_frame()


def test_crc32c_known_vector():
    assert bulk.crc32c(b"123456789") == 0xE3069283


def test_full_color_rgb888_row_major():
    pixels = [
        [(10, 20, 30), (40, 50, 60)],
        [(70, 80, 90), (100, 110, 120)],
    ]
    out = bulk.encode_full_color(pixels, 2, 2)
    assert out == bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120])


def test_full_color_lut_applied():
    lut = list(range(256))
    lut[10] = 200
    pixels = [[(10, 10, 10)]]
    assert bulk.encode_full_color(pixels, 1, 1, lut=lut) == bytes([200, 200, 200])


def test_mono_column_major_threshold_and_packing():
    black, white = (0, 0, 0), (255, 255, 255)
    pixels = [[black, white, black, white, black, white, black, white]]
    # avg gray = 127.5; black(0)<avg -> on, white(255)<avg -> off
    # column-major over width: x0..x7 -> mask 0x80,0x40,...
    out = bulk.encode_mono(pixels, 8, 1)
    assert out == bytes([0x80 | 0x20 | 0x08 | 0x02])  # 0xAA


def test_simple_frame_layout():
    f = bulk.simple_frame(0x06, b"\x01\x02")
    assert f[:2] == bytes([0x54, 0x06])
    assert f[2:4] == (4).to_bytes(2, "big")  # payload(2) + 2
    assert f[4:6] == b"\x01\x02"
    assert f[-2:] == (sum(f[:-2]) & 0xFFFF).to_bytes(2, "big")


def test_gif_frame_block_be16_prefix():
    assert bulk.gif_frame_block(0x1234, b"\xAA\xBB") == bytes([0x12, 0x34, 0xAA, 0xBB])


def test_encode_frame_dispatch():
    px = [[(0, 0, 0), (255, 255, 255)]]
    assert bulk.encode_frame(px, 2, 1, 3) == bulk.encode_full_color(px, 2, 1)
    assert bulk.encode_frame(px, 2, 1, 1) == bulk.encode_mono(px, 2, 1)


def test_item_data_layout():
    item = bulk.item_data(0, 0, 2, 2, [b"\xAA\xBB"])
    expected = (
        bytes.fromhex("0000 0000 0002 0002".replace(" ", ""))  # x y w h
        + bytes(6)  # reserved field_3b
        + bytes([0x02])  # type
        + (1).to_bytes(2, "big")  # frameCount
        + bytes([0x00, 0x00, 0x32, 0x00, 0x00])  # effect/sub/speed/frametype/extra
        + bytes(3)  # reserved
        + b"\xAA\xBB"  # frame block
    )
    assert item == expected


def test_program_resource_crc_and_framing():
    items = [b"\x01", b"\x02\x03"]
    res = bulk.program_resource(items)
    body = res[4:]
    assert res[:4] == bulk.crc32c(body).to_bytes(4, "big")
    assert body[:4] == bytes([2, 0, 0, 0])  # partitionCount + reserved
    assert body[4:8] == (1).to_bytes(4, "big")
    assert body[8:9] == b"\x01"
    assert body[9:13] == (2).to_bytes(4, "big")
    assert body[13:15] == b"\x02\x03"


def test_program_frame_wraps_resource():
    item = bulk.item_data(0, 0, 1, 1, [b"\x00\x00\x00"])
    frame = bulk.program_frame([item])
    assert frame[:2] == bytes([0x54, 0x06])
    assert frame[4:-2] == bulk.program_resource([item])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} passed")
