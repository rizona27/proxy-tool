# -*- coding: utf-8 -*-
"""从 app.ico 抽出最大的一张，存成 app.png（供 macOS icns 转换 / Tk iconphoto）。

纯标准库实现（ico 里的 PNG 块直接拷出来即可；BMP 块则手工合成 PNG 头）。
"""
import struct
import zlib
import os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.png")


def read_entries(data):
    reserved, itype, count = struct.unpack("<HHH", data[:6])
    out = []
    for i in range(count):
        off = 6 + i * 16
        w, h, colors, r, planes, bpp, size, offset = struct.unpack(
            "<BBBBHHII", data[off:off + 16])
        out.append({"w": w or 256, "h": h or 256, "bpp": bpp,
                    "size": size, "offset": offset})
    return out


def png_bytes_for_biggest(data):
    """优先返回最大的 PNG 压缩块（现代 ico 通常内嵌 PNG）"""
    entries = sorted(read_entries(data), key=lambda e: e["w"] * e["h"],
                     reverse=True)
    for e in entries:
        blob = data[e["offset"]:e["offset"] + e["size"]]
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            return blob, e
    return None, entries[0] if entries else None


def bmp_to_png(blob, w, h, bpp):
    """把 ico 里的 BMP（DIB）块转成 PNG（32bpp 带 alpha）"""
    header = struct.unpack("<IiiHHIIiiII", blob[:40])
    (bi_size, bi_w, bi_h, bi_planes, bi_bitcount, bi_compress,
     bi_sizeimage, _x, _y, _clr_used, _clr_imp) = header
    if bi_compress != 0:
        return None
    height = abs(bi_h) // 2 if bi_h == (h * 2) else h
    off = bi_size
    palette = b""
    if bi_bitcount <= 8:
        ncolors = _clr_used or (1 << bi_bitcount)
        palette = blob[off:off + ncolors * 4]
        off += len(palette)

    stride = ((bi_w * bi_bitcount + 31) // 32) * 4
    pixels = []
    for y in range(height - 1, -1, -1):           # DIB 自下而上
        row = blob[off + y * stride: off + y * stride + stride]
        line = []
        if bi_bitcount == 32:
            for x in range(bi_w):
                b, g, r, a = row[x * 4:x * 4 + 4]
                line.append((r, g, b, a))
        elif bi_bitcount == 24:
            for x in range(bi_w):
                b, g, r = row[x * 3:x * 3 + 3]
                line.append((r, g, b, 255))
        elif bi_bitcount == 8:
            for x in range(bi_w):
                idx = row[x]
                b, g, r, _a = palette[idx * 4:idx * 4 + 4]
                line.append((r, g, b, 255))
        else:
            return None
        pixels.append(line)

    raw = bytearray()
    for line in pixels:
        raw.append(0)                              # filter type 0
        for r, g, b, a in line:
            raw += bytes((r, g, b, a))

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", bi_w, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    return png


def main():
    data = open(SRC, "rb").read()
    blob, entry = png_bytes_for_biggest(data)
    if blob:
        open(DST, "wb").write(blob)
        print(f"extracted embedded PNG {entry['w']}x{entry['h']} -> app.png")
        return
    # 否则把最大 BMP 块转 PNG
    if entry:
        bmp = data[entry["offset"]:entry["offset"] + entry["size"]]
        png = bmp_to_png(bmp, entry["w"], entry["h"], entry["bpp"])
        if png:
            open(DST, "wb").write(png)
            print(f"converted BMP {entry['w']}x{entry['h']} -> app.png")
            return
    print("FAILED: no usable image in app.ico")


if __name__ == "__main__":
    main()
