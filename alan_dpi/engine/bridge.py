import select
import socket
import struct
import threading
import time
from typing import Callable, Optional, Set
from alan_dpi.engine.models import BypassVector, VECTOR_REGISTRY
from alan_dpi.engine.mutator import TlsByteMutator


BENIGN_WIN_SOCKET_ERRORS = {10004, 10038, 10053, 10054}


class FullDuplexMutatorBridge:
    SOCKET_BUFFER_SIZE = 2 * 1024 * 1024
    STREAM_CHUNK_SIZE = 65536

    def __init__(
        self,
        listen_port: int = 20809,
        log_fn: Optional[Callable[[str], None]] = None,
        on_endpoint_change: Optional[Callable[[str], None]] = None,
    ):
        self.listen_port = listen_port
        self.remote_host = ""
        self.remote_port = 443
        self.active_vector: BypassVector = VECTOR_REGISTRY[0]
        self.custom_stride = 400
        self.jitter_bytes = 20
        self.raw_passthrough = False

        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self.tx_bytes_total = 0
        self.rx_bytes_total = 0

        self._lock = threading.Lock()
        self._live_sockets: Set[socket.socket] = set()
        self._log_fn = log_fn
        self._on_endpoint_change = on_endpoint_change

    def _log(self, msg: str):
        if self._log_fn:
            self._log_fn(msg)

    @property
    def active_session_count(self) -> int:
        with self._lock:
            return len(self._live_sockets) // 2

    def update_route(
        self,
        remote_host: str,
        remote_port: int,
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
        raw_passthrough: bool = False,
        flush_existing_pool: bool = False,
    ):
        direct_vec = vector.family == "DIRECT"
        effective_passthrough = bool(raw_passthrough) or direct_vec
        with self._lock:
            self.remote_host = remote_host
            self.remote_port = int(remote_port)
            self.active_vector = vector
            self.custom_stride = int(custom_stride)
            self.jitter_bytes = int(jitter_bytes)
            self.raw_passthrough = effective_passthrough

        if self._on_endpoint_change and remote_host:
            try:
                self._on_endpoint_change(remote_host)
            except Exception:
                pass

        if flush_existing_pool:
            self.drop_active_connections()

        mode_label = "DIRECT-PASSTHROUGH" if effective_passthrough else f"{vector.vector_id} ({vector.code_name})"
        self._log(f"[Bridge] Route -> {remote_host}:{remote_port} | {mode_label}")

    def reset_counters(self):
        self.tx_bytes_total = 0
        self.rx_bytes_total = 0

    def drop_active_connections(self):
        with self._lock:
            current_socks = list(self._live_sockets)
            self._live_sockets.clear()
        for s in current_socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def start(self):
        if self.running:
            return
        self.running = True
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", self.listen_port))
        self.server_sock.listen(256)
        self._log(f"[Bridge] Online at 127.0.0.1:{self.listen_port}")
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None
        self.drop_active_connections()

    def _accept_loop(self):
        while self.running and self.server_sock:
            try:
                client_sock, _ = self.server_sock.accept()
                threading.Thread(target=self._handle_session, args=(client_sock,), daemon=True).start()
            except Exception:
                if not self.running:
                    break

    @staticmethod
    def _configure_high_perf_socket(sock: socket.socket):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, FullDuplexMutatorBridge.SOCKET_BUFFER_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, FullDuplexMutatorBridge.SOCKET_BUFFER_SIZE)
        except Exception:
            pass
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            try:
                sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 15000, 3000))
            except Exception:
                pass

    @staticmethod
    def _read_exact_initial_flight(sock: socket.socket, timeout: float = 6.5) -> bytes:
        sock.settimeout(timeout)
        hdr = bytearray()
        while len(hdr) < 5:
            chunk = sock.recv(5 - len(hdr))
            if not chunk:
                return bytes(hdr)
            hdr.extend(chunk)
        if hdr[0] != 0x16:
            sock.settimeout(0.04)
            try:
                rest = sock.recv(16384)
                return bytes(hdr) + rest
            except Exception:
                return bytes(hdr)
        rec_len = struct.unpack("!H", hdr[3:5])[0]
        body = bytearray()
        while len(body) < rec_len:
            chunk = sock.recv(min(16384, rec_len - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        return bytes(hdr) + bytes(body)

    def _register_pair(self, c_sock: socket.socket, r_sock: socket.socket):
        with self._lock:
            self._live_sockets.add(c_sock)
            self._live_sockets.add(r_sock)

    def _unregister_pair(self, c_sock: socket.socket, r_sock: socket.socket):
        with self._lock:
            self._live_sockets.discard(c_sock)
            self._live_sockets.discard(r_sock)

    def _handle_session(self, client_sock: socket.socket):
        sid = id(client_sock) % 10000
        with self._lock:
            r_host = self.remote_host
            r_port = self.remote_port
            vec = self.active_vector
            stride = self.custom_stride
            jitter = self.jitter_bytes
            passthrough = self.raw_passthrough

        if not r_host:
            try:
                client_sock.close()
            except Exception:
                pass
            return

        remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._register_pair(client_sock, remote_sock)

        try:
            self._configure_high_perf_socket(client_sock)
            self._configure_high_perf_socket(remote_sock)
            remote_sock.settimeout(5.5)

            t0 = time.perf_counter()
            remote_sock.connect((r_host, r_port))
            tcp_ms = int((time.perf_counter() - t0) * 1000)

            if not passthrough:
                first_data = self._read_exact_initial_flight(client_sock, timeout=6.0)
                if not first_data:
                    return

                is_tls_hello = (len(first_data) >= 44) and (first_data[0] == 0x16) and (first_data[5] == 0x01)
                is_http_req = first_data.startswith((b"GET ", b"POST ", b"HEAD ", b"PUT ", b"OPTIONS "))

                if is_tls_hello:
                    sent, wire_trace = TlsByteMutator.transmit_client_hello(
                        remote_sock, first_data, vec, custom_stride=stride, jitter_bytes=jitter
                    )
                    self._log(f"[S#{sid:04d}] TCP={tcp_ms}ms | {vec.vector_id}: {wire_trace}")
                elif is_http_req:
                    sent, wire_trace = TlsByteMutator.transmit_plain_http(
                        remote_sock, first_data, vec, custom_stride=stride, jitter_bytes=jitter
                    )
                    self._log(f"[S#{sid:04d}] TCP={tcp_ms}ms | {vec.vector_id}: {wire_trace}")
                else:
                    remote_sock.sendall(first_data)
                    sent = len(first_data)
                self.tx_bytes_total += sent

            remote_sock.settimeout(None)
            client_sock.settimeout(None)

            def _downlink_pump():
                try:
                    while self.running:
                        data = remote_sock.recv(self.STREAM_CHUNK_SIZE)
                        if not data:
                            break
                        client_sock.sendall(data)
                        self.rx_bytes_total += len(data)
                except Exception:
                    pass
                finally:
                    try:
                        client_sock.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            def _uplink_pump():
                flight_num = 0 if passthrough else 1
                try:
                    while self.running:
                        data = client_sock.recv(self.STREAM_CHUNK_SIZE)
                        if not data:
                            break
                        flight_num += 1

                        if (not passthrough) and (flight_num == 2) and vec.coalesce_flight2 and (len(data) <= 180):
                            try:
                                if client_sock.fileno() >= 0:
                                    r_ready, _, _ = select.select([client_sock], [], [], 0.022)
                                    if r_ready:
                                        extra = client_sock.recv(self.STREAM_CHUNK_SIZE)
                                        if extra:
                                            data = data + extra
                            except Exception:
                                pass

                        is_multi_frag = (
                            (not passthrough)
                            and (vec.family == "FRAGMENT")
                            and (vec.frag_flights > 1)
                            and (flight_num <= vec.frag_flights)
                            and (vec.frag_slice_max > 0)
                        )
                        if is_multi_frag:
                            sent_frag = TlsByteMutator.transmit_fragmented_buffer(
                                sock=remote_sock,
                                payload=data,
                                min_len=vec.frag_slice_min,
                                max_len=vec.frag_slice_max,
                                min_delay_ms=vec.frag_delay_min_ms,
                                max_delay_ms=vec.frag_delay_max_ms,
                            )
                            self.tx_bytes_total += sent_frag
                        else:
                            remote_sock.sendall(data)
                            self.tx_bytes_total += len(data)
                except Exception:
                    pass
                finally:
                    try:
                        remote_sock.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            down_thread = threading.Thread(target=_downlink_pump, daemon=True)
            down_thread.start()
            _uplink_pump()
            down_thread.join(timeout=18.0)

        except OSError as os_err:
            win_code = getattr(os_err, "winerror", 0)
            if win_code not in BENIGN_WIN_SOCKET_ERRORS:
                self._log(f"[S#{sid:04d}] Closed: {os_err}")
        except Exception as exc:
            self._log(f"[S#{sid:04d}] Closed: {exc}")
        finally:
            self._unregister_pair(client_sock, remote_sock)
            for s in (client_sock, remote_sock):
                try:
                    s.close()
                except Exception:
                    pass