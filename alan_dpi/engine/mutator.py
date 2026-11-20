import random
import socket
import struct
import time
from typing import List, Optional, Tuple
from alan_dpi.engine.models import BypassVector


class TlsByteMutator:
    @staticmethod
    def locate_sni(payload: bytes) -> Optional[Tuple[int, int, int, int]]:
        """
        Returns (ext_type_offset, ext_len_offset, host_start_offset, host_end_offset)
        inside a TLS ClientHello record (0x16).
        """
        n = len(payload)
        if n < 48 or payload[0] != 0x16 or payload[5] != 0x01:
            return None
        try:
            pos = 43
            if pos >= n:
                return None
            sid_len = payload[pos]
            pos += 1 + sid_len
            if (pos + 2) > n:
                return None
            cs_len = struct.unpack("!H", payload[pos : pos + 2])[0]
            pos += 2 + cs_len
            if (pos + 1) > n:
                return None
            comp_len = payload[pos]
            pos += 1 + comp_len
            if (pos + 2) > n:
                return None
            ext_total_len = struct.unpack("!H", payload[pos : pos + 2])[0]
            pos += 2
            ext_limit = min(n, pos + ext_total_len)

            while (pos + 4) <= ext_limit:
                ext_type = struct.unpack("!H", payload[pos : pos + 2])[0]
                ext_len = struct.unpack("!H", payload[pos + 2 : pos + 4])[0]
                if ext_type == 0x0000 and (pos + 9) <= ext_limit:
                    name_len = struct.unpack("!H", payload[pos + 7 : pos + 9])[0]
                    h_start = pos + 9
                    h_end = min(ext_limit, h_start + name_len)
                    if h_end > h_start:
                        return pos, pos + 2, h_start, h_end
                pos += 4 + ext_len
        except Exception:
            pass
        return None

    @staticmethod
    def locate_keyshare_or_ext_pivot(payload: bytes, fallback_offset: int) -> int:
        n = len(payload)
        if n < 56 or payload[0] != 0x16 or payload[5] != 0x01:
            return fallback_offset
        try:
            pos = 43
            sid_len = payload[pos]
            pos += 1 + sid_len
            cs_len = struct.unpack("!H", payload[pos : pos + 2])[0]
            pos += 2 + cs_len
            comp_len = payload[pos]
            pos += 1 + comp_len
            ext_total_len = struct.unpack("!H", payload[pos : pos + 2])[0]
            pos += 2
            ext_limit = min(n, pos + ext_total_len)

            while (pos + 4) <= ext_limit:
                ext_type = struct.unpack("!H", payload[pos : pos + 2])[0]
                ext_len = struct.unpack("!H", payload[pos + 2 : pos + 4])[0]
                if ext_type in (0x0033, 0x002B, 0x000D) and pos > fallback_offset:
                    return pos
                pos += 4 + ext_len
        except Exception:
            pass
        return fallback_offset

    @staticmethod
    def build_preamble_bytes(mode: str, outer_ver: int = 0x0304) -> bytes:
        v_hi, v_lo = (outer_ver >> 8) & 0xFF, outer_ver & 0xFF
        if mode == "zero0304":
            return bytes([0x16, v_hi, v_lo, 0x00, 0x00])
        if mode == "2xzero":
            return bytes([0x16, 0x03, 0x03, 0x00, 0x00, 0x16, v_hi, v_lo, 0x00, 0x00])
        if mode == "4xzero":
            return bytes(
                [
                    0x16, 0x03, 0x01, 0x00, 0x00,
                    0x16, 0x03, 0x03, 0x00, 0x00,
                    0x16, v_hi, v_lo, 0x00, 0x00,
                    0x16, 0x03, 0x03, 0x00, 0x00,
                ]
            )
        return b""

    @staticmethod
    def reframe_handshake_chunks(
        hs_body: bytes,
        chunk_sizes: List[int],
        outer_version: int = 0x0303,
        alternating_versions: Optional[Tuple[int, int]] = None,
    ) -> List[bytes]:
        frames: List[bytes] = []
        pos = 0
        total = len(hs_body)
        idx = 0
        for sz in chunk_sizes:
            if pos >= total:
                break
            step = max(1, min(int(sz), total - pos))
            ver = (
                alternating_versions[idx % len(alternating_versions)]
                if alternating_versions
                else outer_version
            )
            hdr = struct.pack("!BHH", 0x16, ver, step)
            frames.append(hdr + hs_body[pos : pos + step])
            pos += step
            idx += 1

        if pos < total:
            rem = total - pos
            ver = (
                alternating_versions[idx % len(alternating_versions)]
                if alternating_versions
                else outer_version
            )
            hdr = struct.pack("!BHH", 0x16, ver, rem)
            frames.append(hdr + hs_body[pos:])
        return frames

    @classmethod
    def _build_record_envelope_frames(cls, payload: bytes, vec: BypassVector) -> List[bytes]:
        if len(payload) <= 5 or payload[0] != 0x16:
            return [payload]
        hs = payload[5:]
        sni_info = cls.locate_sni(payload)

        if vec.record_envelope == "rfc_dot_keyshare_4rec":
            if sni_info is not None:
                _, _, h_start, h_end = sni_info
                hs_start = max(1, h_start - 5)
                hs_end = max(hs_start + 2, h_end - 5)
                host_bytes = hs[hs_start:hs_end]
                dots = [i for i, b in enumerate(host_bytes) if b == 0x2E]
                cuts: List[int] = []
                if len(dots) >= 2:
                    c1 = hs_start + dots[0] + 1
                    c2 = hs_start + dots[-1]
                    if c1 > 0:
                        cuts.append(c1)
                    if c2 > c1:
                        cuts.append(c2 - c1)
                else:
                    mid = hs_start + max(1, len(host_bytes) // 2)
                    cuts.append(mid)

                consumed = sum(cuts)
                ks_off = cls.locate_keyshare_or_ext_pivot(payload, h_end) - 5
                if ks_off > (consumed + 8) and ks_off < (len(hs) - 8):
                    cuts.append(ks_off - consumed)
                elif hs_end > consumed:
                    cuts.append(hs_end - consumed)
                return cls.reframe_handshake_chunks(hs, cuts, vec.outer_version)
            return cls.reframe_handshake_chunks(hs, [42, 28, 64], vec.outer_version)

        if vec.record_envelope == "sni_dot_3rec":
            if sni_info is not None:
                _, _, h_start, h_end = sni_info
                hs_s = max(1, h_start - 5)
                hs_e = max(hs_s + 2, h_end - 5)
                dot_rel = hs[hs_s:hs_e].find(b".")
                cut1 = (hs_s + dot_rel + 1) if (dot_rel > 0) else ((hs_s + hs_e) // 2)
                cut2 = max(2, hs_e - cut1)
                return cls.reframe_handshake_chunks(hs, [cut1, cut2], vec.outer_version)
            return cls.reframe_handshake_chunks(hs, [44, 32], vec.outer_version)

        if vec.record_envelope == "sni_mid_2rec":
            if sni_info is not None:
                _, _, h_start, h_end = sni_info
                mid = max(8, ((h_start + h_end) // 2) - 5)
                return cls.reframe_handshake_chunks(hs, [mid], vec.outer_version)
            return cls.reframe_handshake_chunks(hs, [max(16, len(hs) // 3)], vec.outer_version)

        if vec.record_envelope == "fibonacci_7rec":
            if sni_info is not None:
                _, _, h_start, _ = sni_info
                pre = max(4, h_start - 5)
                return cls.reframe_handshake_chunks(hs, [pre, 1, 2, 3, 5, 8, 13], vec.outer_version)
            return cls.reframe_handshake_chunks(hs, [37, 2, 3, 5, 8, 13], vec.outer_version)

        return [payload]

    @classmethod
    def slice_asymmetric_app_flight(
        cls,
        payload: bytes,
        flight_index: int,
        stride: int = 400,
        jitter: int = 20,
    ) -> List[bytes]:
        total = len(payload)
        if total <= 32:
            return [payload]

        if flight_index == 2:
            pattern = [19, 53, 127]
        elif flight_index == 3:
            pattern = [29, 71, 163]
        else:
            pattern = [37, 97]

        chunks: List[bytes] = []
        pos = 0
        for p_sz in pattern:
            if pos >= total:
                break
            jit = random.randint(-4, 6) if jitter > 0 else 0
            step = max(8, min(total - pos, p_sz + jit))
            chunks.append(payload[pos : pos + step])
            pos += step

        base_step = max(220, min(920, stride * 2))
        while pos < total:
            jit = random.randint(-min(32, jitter), min(32, jitter)) if jitter > 0 else 0
            step = max(140, min(total - pos, base_step + jit))
            chunks.append(payload[pos : pos + step])
            pos += step
        return chunks

    @staticmethod
    def _send_oob_segment(sock: socket.socket, segment: bytes, oob_byte: int):
        if not segment:
            return
        try:
            sock.sendall(segment)
            sock.send(bytes([oob_byte & 0xFF]), socket.MSG_OOB)
        except Exception:
            sock.sendall(segment)

    @classmethod
    def transmit_mutated_flight(
        cls,
        sock: socket.socket,
        payload: bytes,
        vec: BypassVector,
        flight_index: int = 1,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
    ):
        if not payload:
            return

        if vec.family == "DIRECT":
            sock.sendall(payload)
            return

        if flight_index >= 2 and vec.hybrid_mode in ("multiflight_asymmetric_0x17", "anti_16kb_flow_stall"):
            slices = cls.slice_asymmetric_app_flight(payload, flight_index, custom_stride, jitter_bytes)
            for idx, sl in enumerate(slices):
                sock.sendall(sl)
                if idx < 2 and len(slices) > 1:
                    time.sleep(0.0005)
            return

        if vec.family == "FRAGMENT" or (vec.frag_slice_max > 0 and flight_index <= vec.frag_flights):
            pre = cls.build_preamble_bytes(vec.preamble, vec.outer_version)
            buf = (pre + payload) if (flight_index == 1 and pre) else payload
            pos = 0
            n = len(buf)
            s_min = max(1, int(vec.frag_slice_min or 5))
            s_max = max(s_min, int(vec.frag_slice_max or 16))
            d_min = max(0, int(vec.frag_delay_min_ms or 0))
            d_max = max(d_min, int(vec.frag_delay_max_ms or 0))

            if flight_index == 1 and buf[0] == 0x16 and len(buf) > 5 and vec.coalesce_flight2:
                hs = buf[5:]
                sizes: List[int] = []
                rem = len(hs)
                while rem > 0:
                    step = random.randint(s_min, s_max)
                    sizes.append(min(rem, step))
                    rem -= step
                frames = cls.reframe_handshake_chunks(hs, sizes, vec.outer_version)
                sock.sendall(b"".join(frames))
                return

            while pos < n:
                step = random.randint(s_min, s_max)
                sock.sendall(buf[pos : pos + step])
                pos += step
                if pos < n and d_max > 0:
                    time.sleep(random.uniform(d_min, d_max) / 1000.0)
            return

        if flight_index > 1:
            sock.sendall(payload)
            return

        if vec.hybrid_mode == "fastpath_nic_offload_bypass" and payload[0] == 0x16 and len(payload) > 48:
            hs = payload[5:]
            sni_info = cls.locate_sni(payload)
            if sni_info is not None:
                _, _, h_start, h_end = sni_info
                hs_s = max(4, h_start - 5)
                hs_e = max(hs_s + 2, h_end - 5)
                mid = (hs_s + hs_e) // 2
                frames = cls.reframe_handshake_chunks(
                    hs,
                    [hs_s, max(1, mid - hs_s), max(1, hs_e - mid)],
                    vec.outer_version,
                    alternating_versions=(0x0301, 0x0303),
                )
            else:
                frames = cls.reframe_handshake_chunks(
                    hs,
                    [37, 19, 29],
                    vec.outer_version,
                    alternating_versions=(0x0301, 0x0303),
                )

            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            except Exception:
                pass
            sock.sendall(frames[0])
            try:
                sock.send(bytes([random.randint(0x41, 0x5A)]), socket.MSG_OOB)
            except Exception:
                pass
            for fr in frames[1:]:
                sock.sendall(fr)
            return

        if vec.hybrid_mode in ("phantom_seam_oob", "sni_microcell_pincer", "chameleon_interleave") and payload[0] == 0x16 and len(payload) > 48:
            hs = payload[5:]
            sni_info = cls.locate_sni(payload)
            alt_v = (0x0301, 0x0303) if vec.hybrid_mode == "chameleon_interleave" else None
            if sni_info is not None:
                _, _, h_start, h_end = sni_info
                hs_s = max(4, h_start - 5)
                hs_e = max(hs_s + 2, h_end - 5)
                frames = cls.reframe_handshake_chunks(
                    hs,
                    [hs_s, max(1, (hs_e - hs_s) // 2), max(1, (hs_e - hs_s) - ((hs_e - hs_s) // 2))],
                    vec.outer_version,
                    alternating_versions=alt_v,
                )
            else:
                frames = cls.reframe_handshake_chunks(hs, [37, 24, 32], vec.outer_version, alternating_versions=alt_v)

            if vec.hybrid_mode in ("phantom_seam_oob", "sni_microcell_pincer"):
                sock.sendall(frames[0])
                try:
                    sock.send(bytes([random.randint(0x61, 0x7A)]), socket.MSG_OOB)
                except Exception:
                    pass
                sock.sendall(b"".join(frames[1:]))
            else:
                sock.sendall(b"".join(frames))
            return

        if vec.record_envelope != "none":
            frames = cls._build_record_envelope_frames(payload, vec)
            pre = cls.build_preamble_bytes(vec.preamble, vec.outer_version)
            if vec.record_envelope == "rfc_dot_keyshare_4rec" and len(frames) >= 2:
                sock.sendall(pre + frames[0] + frames[1])
                if len(frames) > 2:
                    sock.sendall(b"".join(frames[2:]))
            else:
                sock.sendall(pre + b"".join(frames))
            return

        pre = cls.build_preamble_bytes(vec.preamble, vec.outer_version)
        mutated = bytearray(payload)
        if len(mutated) >= 5 and mutated[0] == 0x16:
            mutated[1] = (vec.outer_version >> 8) & 0xFF
            mutated[2] = vec.outer_version & 0xFF

        if vec.split_mode == "1pkt_midsni" and mutated[0] == 0x16 and len(mutated) > 48:
            hs = bytes(mutated[5:])
            sni_info = cls.locate_sni(bytes(mutated))
            cut_pt = ((sni_info[2] + sni_info[3]) // 2 - 5) if sni_info else (len(hs) // 2)
            frames = cls.reframe_handshake_chunks(hs, [max(8, cut_pt)], vec.outer_version)
            sock.sendall(pre + b"".join(frames))
            return

        sni_info = cls.locate_sni(bytes(mutated))
        urg_cut = 0
        if vec.urgent_mode != "none":
            if sni_info is not None:
                ext_pos, len_pos, h_start, h_end = sni_info
                if vec.urgent_mode == "sni_tag":
                    urg_cut = ext_pos + 2
                elif vec.urgent_mode == "sni_len":
                    urg_cut = len_pos + 2
                elif vec.urgent_mode == "mid_host":
                    urg_cut = (h_start + h_end) // 2
                elif vec.urgent_mode in ("dual", "triple"):
                    urg_cut = h_start + 1
                elif vec.urgent_mode == "cipher_pivot":
                    urg_cut = min(len(mutated) - 8, 47)
            else:
                urg_cut = min(len(mutated) // 2, 52)

        full_wire = bytes(pre + mutated)
        urg_cut_shifted = (urg_cut + len(pre)) if urg_cut > 0 else 0

        if urg_cut_shifted > 0 and urg_cut_shifted < len(full_wire):
            cls._send_oob_segment(sock, full_wire[:urg_cut_shifted], random.randint(0x41, 0x5A))
            rem_wire = full_wire[urg_cut_shifted:]
            stride_val = max(120, custom_stride + (random.randint(-jitter_bytes, jitter_bytes) if jitter_bytes > 0 else 0))
            if len(rem_wire) > stride_val:
                if vec.second_urgent_delta > 0:
                    cls._send_oob_segment(sock, rem_wire[:stride_val], random.randint(0x61, 0x7A))
                else:
                    sock.sendall(rem_wire[:stride_val])
                sock.sendall(rem_wire[stride_val:])
            else:
                sock.sendall(rem_wire)
        else:
            stride_val = max(160, custom_stride)
            if vec.forward_cuts and len(full_wire) > stride_val:
                sock.sendall(full_wire[:stride_val])
                sock.sendall(full_wire[stride_val:])
            else:
                sock.sendall(full_wire)
