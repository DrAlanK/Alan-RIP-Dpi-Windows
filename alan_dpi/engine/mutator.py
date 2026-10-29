import random
import socket
import struct
import time
from typing import Dict, List, Tuple
from alan_dpi.engine.models import BypassVector


class TlsByteMutator:
    @staticmethod
    def locate_sni_offsets(record: bytes) -> Dict[str, int]:
        rec_len = len(record)
        offsets = {
            "ext_total_len_pos": 80,
            "sni_ext_pos": max(5, min(180, rec_len // 3)),
            "sni_list_len_pos": max(9, min(184, (rec_len // 3) + 4)),
            "sni_name_len_pos": max(12, min(187, (rec_len // 3) + 7)),
            "sni_name_pos": max(14, min(189, (rec_len // 3) + 9)),
            "sni_name_len": 20,
        }
        if (rec_len < 44) or (record[0] != 0x16) or (record[5] != 0x01):
            return offsets
        try:
            pos = 43
            sid_len = record[pos]
            pos += 1 + sid_len
            ciph_len = struct.unpack("!H", record[pos : pos + 2])[0]
            pos += 2 + ciph_len
            comp_len = record[pos]
            pos += 1 + comp_len
            offsets["ext_total_len_pos"] = pos
            ext_total_len = struct.unpack("!H", record[pos : pos + 2])[0]
            pos += 2
            end = min(rec_len, pos + ext_total_len)
            while (pos + 4) <= end:
                etype = struct.unpack("!H", record[pos : pos + 2])[0]
                elen = struct.unpack("!H", record[pos + 2 : pos + 4])[0]
                if (etype == 0x0000) and ((pos + 9) <= end):
                    offsets["sni_ext_pos"] = pos
                    offsets["sni_list_len_pos"] = pos + 4
                    offsets["sni_name_len_pos"] = pos + 7
                    offsets["sni_name_len"] = struct.unpack("!H", record[pos + 7 : pos + 9])[0]
                    offsets["sni_name_pos"] = pos + 9
                    break
                pos += 4 + elen
        except Exception:
            pass
        return offsets

    @staticmethod
    def rewrite_outer_version(record: bytes, version: int) -> bytes:
        if (len(record) < 5) or (record[0] != 0x16):
            return record
        ba = bytearray(record)
        ba[1] = (version >> 8) & 0xFF
        ba[2] = version & 0xFF
        return bytes(ba)

    @staticmethod
    def split_record_atomic(record: bytes, cut_offset: int, version: int) -> bytes:
        if (len(record) < 10) or (cut_offset <= 5) or (cut_offset >= len(record)):
            return TlsByteMutator.rewrite_outer_version(record, version)
        hs = record[5:]
        cut_rel = cut_offset - 5
        part1, part2 = hs[:cut_rel], hs[cut_rel:]
        return (
            struct.pack("!BHH", 0x16, version, len(part1)) + part1
            + struct.pack("!BHH", 0x16, version, len(part2)) + part2
        )

    @staticmethod
    def _safe_send_urgent(sock: socket.socket, chunk: bytes, urgent_byte: bytes):
        try:
            sock.send(chunk + urgent_byte, socket.MSG_OOB)
        except OSError:
            sock.sendall(chunk)

    @staticmethod
    def transmit_fragmented_buffer(
        sock: socket.socket,
        payload: bytes,
        min_len: int,
        max_len: int,
        min_delay_ms: int,
        max_delay_ms: int,
    ) -> int:
        cursor = 0
        total_len = len(payload)
        lo = max(1, int(min_len))
        hi = max(lo, int(max_len))
        while cursor < total_len:
            step = random.randint(lo, hi)
            chunk = payload[cursor : cursor + step]
            sock.sendall(chunk)
            cursor += len(chunk)
            if (cursor < total_len) and (max_delay_ms > 0):
                delay_s = random.uniform(min_delay_ms, max_delay_ms) / 1000.0
                if delay_s > 0:
                    time.sleep(delay_s)
        return total_len

    @staticmethod
    def _transmit_tail_segments(
        sock: socket.socket,
        tail_buf: bytes,
        forward_cuts: List[int],
        jitter_bytes: int = 20,
        second_urgent_delta: int = 0,
    ) -> int:
        if not tail_buf:
            return 0

        tail_len = len(tail_buf)
        if second_urgent_delta > 0:
            jitter = random.randint(-jitter_bytes, jitter_bytes) if (jitter_bytes > 0) else 0
            target_delta = max(24, second_urgent_delta + jitter)
            cut_pos = target_delta if (target_delta < tail_len) else max(1, (tail_len * 2) // 3)
            if 0 < cut_pos < tail_len:
                TlsByteMutator._safe_send_urgent(sock, tail_buf[:cut_pos], b"\x5a")
                time.sleep(0.001)
                sock.sendall(tail_buf[cut_pos:])
                return tail_len + 1

        if not forward_cuts:
            sock.sendall(tail_buf)
            return tail_len

        resolved_cuts = []
        for base_delta in forward_cuts:
            use_jitter = (base_delta > 60) and (jitter_bytes > 0)
            jitter = random.randint(-jitter_bytes, jitter_bytes) if use_jitter else 0
            cut_candidate = max(20, base_delta + jitter)
            if 0 < cut_candidate < tail_len:
                resolved_cuts.append(cut_candidate)
            elif 0 < base_delta < tail_len:
                resolved_cuts.append(base_delta)
            elif tail_len > 48:
                resolved_cuts.append((tail_len * 7) // 10)

        points = sorted(set([0] + resolved_cuts + [tail_len]))
        sent_bytes = 0
        for idx in range(len(points) - 1):
            segment = tail_buf[points[idx] : points[idx + 1]]
            if segment:
                sock.sendall(segment)
                sent_bytes += len(segment)
                if (len(points) > 2) and (idx < (len(points) - 2)):
                    time.sleep(0.002)
        return sent_bytes

    @staticmethod
    def transmit_plain_http(
        sock: socket.socket,
        http_payload: bytes,
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
    ) -> Tuple[int, str]:
        if vector.family == "DIRECT":
            sock.sendall(http_payload)
            return len(http_payload), f"HTTP-Direct | {len(http_payload)}B"

        if (vector.family == "FRAGMENT") and (vector.frag_slice_max > 0):
            sent = TlsByteMutator.transmit_fragmented_buffer(
                sock=sock,
                payload=http_payload,
                min_len=vector.frag_slice_min,
                max_len=vector.frag_slice_max,
                min_delay_ms=vector.frag_delay_min_ms,
                max_delay_ms=vector.frag_delay_max_ms,
            )
            return sent, f"HTTP-Frag({vector.frag_slice_min}-{vector.frag_slice_max}B)"

        lower_buf = http_payload.lower()
        host_idx = lower_buf.find(b"\r\nhost:")
        if (host_idx != -1) and ((host_idx + 10) < len(http_payload)):
            val_start = host_idx + 7
            while (val_start < len(http_payload)) and (http_payload[val_start : val_start + 1] == b" "):
                val_start += 1
            cut = min(len(http_payload) - 2, val_start + 3)
            if (cut > 0) and (vector.urgent_mode != "none"):
                TlsByteMutator._safe_send_urgent(sock, http_payload[:cut], b"\x78")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock,
                    http_payload[cut:],
                    [custom_stride] if (custom_stride > 0) else [],
                    jitter_bytes=jitter_bytes,
                )
                return cut + 1 + rem, f"HTTP-HostDesync | {cut + 1 + rem}B"
            if cut > 0:
                sock.sendall(http_payload[:cut])
                time.sleep(0.002)
                sock.sendall(http_payload[cut:])
                return len(http_payload), f"HTTP-HostSplit | {len(http_payload)}B"

        sock.sendall(http_payload)
        return len(http_payload), f"HTTP-Direct | {len(http_payload)}B"

    @staticmethod
    def transmit_client_hello(
        sock: socket.socket,
        ch_record: bytes,
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
    ) -> Tuple[int, str]:
        if vector.family == "DIRECT":
            sock.sendall(ch_record)
            return len(ch_record), f"TLS-Direct | {len(ch_record)}B"

        ver = vector.outer_version
        mut_ch = TlsByteMutator.rewrite_outer_version(ch_record, ver)

        prefix = b""
        if vector.preamble == "zero0304":
            prefix = bytes.fromhex("1603040000")
        elif vector.preamble == "2xzero":
            prefix = bytes.fromhex("16030200001603040000")
        elif vector.preamble == "4xzero":
            prefix = bytes.fromhex("1603010000160302000016030300001603040000")

        if (vector.family == "FRAGMENT") and (vector.frag_slice_max > 0):
            full_frag_buf = prefix + mut_ch
            sent = TlsByteMutator.transmit_fragmented_buffer(
                sock=sock,
                payload=full_frag_buf,
                min_len=vector.frag_slice_min,
                max_len=vector.frag_slice_max,
                min_delay_ms=vector.frag_delay_min_ms,
                max_delay_ms=vector.frag_delay_max_ms,
            )
            return sent, f"Frag({vector.frag_slice_min}-{vector.frag_slice_max}B) | {sent}B"

        cuts = list(vector.forward_cuts)
        if (custom_stride > 0) and (len(cuts) == 1):
            cuts = [custom_stride]

        sec_urg = vector.second_urgent_delta
        if (custom_stride > 0) and (sec_urg > 0):
            sec_urg = custom_stride

        offsets = TlsByteMutator.locate_sni_offsets(ch_record)

        if vector.split_mode == "1pkt_midsni":
            cut = offsets["sni_name_pos"] + max(3, min(5, offsets["sni_name_len"] // 2))
            split_payload = prefix + TlsByteMutator.split_record_atomic(ch_record, cut, ver)
            sent = TlsByteMutator._transmit_tail_segments(
                sock, split_payload, cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
            )
            return sent, f"AtomicSplit | {sent}B"

        full_buf = prefix + mut_ch
        shift = len(prefix)

        if vector.urgent_mode == "sni_tag":
            cut = min(len(full_buf) - 2, shift + offsets["sni_ext_pos"] + 1)
            if cut > 0:
                TlsByteMutator._safe_send_urgent(sock, full_buf[:cut], b"\x78")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock, full_buf[cut:], cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
                )
                return cut + 1 + rem, f"Core-Alpha | {cut + 1 + rem}B"

        if vector.urgent_mode == "mid_host":
            cut = min(len(full_buf) - 2, shift + offsets["sni_name_pos"] + max(3, min(5, offsets["sni_name_len"] // 2)))
            if cut > 0:
                TlsByteMutator._safe_send_urgent(sock, full_buf[:cut], b"\x2d")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock, full_buf[cut:], cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
                )
                return cut + 1 + rem, f"Core-Sigma | {cut + 1 + rem}B"

        if vector.urgent_mode == "sni_len":
            cut = min(len(full_buf) - 2, shift + offsets["sni_list_len_pos"] + 1)
            if cut > 0:
                TlsByteMutator._safe_send_urgent(sock, full_buf[:cut], b"\x5a")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock, full_buf[cut:], cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
                )
                return cut + 1 + rem, f"Core-Len | {cut + 1 + rem}B"

        if vector.urgent_mode == "name_len":
            cut = min(len(full_buf) - 2, shift + offsets["sni_name_len_pos"] + 1)
            if cut > 0:
                TlsByteMutator._safe_send_urgent(sock, full_buf[:cut], b"\x99")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock, full_buf[cut:], cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
                )
                return cut + 1 + rem, f"Core-NameLen | {cut + 1 + rem}B"

        if vector.urgent_mode == "dual":
            c1 = shift + offsets["sni_ext_pos"] + 1
            c2 = min(len(full_buf) - 2, shift + offsets["sni_name_pos"] + 4)
            if 0 < c1 < c2:
                TlsByteMutator._safe_send_urgent(sock, full_buf[:c1], b"\x78")
                TlsByteMutator._safe_send_urgent(sock, full_buf[c1:c2], b"\x2d")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock, full_buf[c2:], cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
                )
                return c2 + 2 + rem, f"Core-Dual | {c2 + 2 + rem}B"

        if vector.urgent_mode == "triple":
            c0 = shift + offsets["ext_total_len_pos"] + 1
            c1 = shift + offsets["sni_ext_pos"] + 1
            c2 = min(len(full_buf) - 2, shift + offsets["sni_name_pos"] + 4)
            if 0 < c0 < c1 < c2:
                TlsByteMutator._safe_send_urgent(sock, full_buf[:c0], b"\x33")
                TlsByteMutator._safe_send_urgent(sock, full_buf[c0:c1], b"\x78")
                TlsByteMutator._safe_send_urgent(sock, full_buf[c1:c2], b"\x2e")
                rem = TlsByteMutator._transmit_tail_segments(
                    sock, full_buf[c2:], cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
                )
                return c2 + 3 + rem, f"Core-Tri | {c2 + 3 + rem}B"

        sent = TlsByteMutator._transmit_tail_segments(
            sock, full_buf, cuts, jitter_bytes=jitter_bytes, second_urgent_delta=sec_urg
        )
        return sent, f"Coalesced | {sent}B"