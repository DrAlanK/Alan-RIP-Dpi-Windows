import ctypes
import os
import random
import socket
import subprocess
import threading
import time
from typing import Callable, Optional
from alan_dpi.engine.models import BypassVector, VECTOR_REGISTRY
from alan_dpi.engine.mutator import TlsByteMutator


class FullDuplexMutatorBridge:
    RECV_BUFFER = 65536
    RX_SOCK_BUF = 4 * 1024 * 1024
    TX_ASYMMETRIC_BUF = 98304
    TX_BULK_FASTPATH_BUF = 524288

    def __init__(
        self,
        listen_port: int = 20809,
        log_fn: Optional[Callable[[str], None]] = None,
        on_endpoint_change: Optional[Callable[[str], None]] = None,
    ):
        self.listen_port = int(listen_port)
        self._log_fn = log_fn
        self._on_endpoint_change = on_endpoint_change

        self._lock = threading.RLock()
        self.remote_host: str = ""
        self.remote_port: int = 443
        self.active_vector: BypassVector = VECTOR_REGISTRY[0]
        self.custom_stride: int = 400
        self.jitter_bytes: int = 20
        self.raw_passthrough: bool = False

        self._physical_bind_ip: str = ""
        self._server_sock: Optional[socket.socket] = None
        self.running: bool = False
        self._generation: int = 0
        self._active_sockets: set = set()

        self.tx_bytes_total: int = 0
        self.rx_bytes_total: int = 0
        self.active_session_count: int = 0

    def _log(self, msg: str):
        if self._log_fn is not None:
            self._log_fn(msg)

    def reset_counters(self):
        with self._lock:
            self.tx_bytes_total = 0
            self.rx_bytes_total = 0

    def refresh_physical_interface(self, enable_tun_bind: bool = False):
        if (not enable_tun_bind) or (os.name != "nt"):
            with self._lock:
                self._physical_bind_ip = ""
            return

        ps_cmd = (
            "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            "Where-Object { $_.NextHop -ne '0.0.0.0' -and $_.NextHop -notlike '198.18.*' } | "
            "Sort-Object RouteMetric | Select-Object -First 1 | "
            "ForEach-Object { (Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).IPAddress }"
        )
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3.0,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            ip_cand = (res.stdout or "").splitlines()[0].strip() if res.stdout else ""
            if ip_cand and (not ip_cand.startswith("198.18.")) and (not ip_cand.startswith("127.")):
                with self._lock:
                    self._physical_bind_ip = ip_cand
                return
        except Exception:
            pass
        with self._lock:
            self._physical_bind_ip = ""

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
        clean_host = (remote_host or "").strip()
        with self._lock:
            host_changed = clean_host and (clean_host != self.remote_host)
            self.remote_host = clean_host
            self.remote_port = int(remote_port)
            self.active_vector = vector
            self.custom_stride = max(64, int(custom_stride or 400))
            self.jitter_bytes = max(0, int(jitter_bytes or 0))
            self.raw_passthrough = bool(raw_passthrough)
            if flush_existing_pool:
                self._generation += 1

        if host_changed and (self._on_endpoint_change is not None):
            try:
                self._on_endpoint_change(clean_host)
            except Exception:
                pass

        if flush_existing_pool:
            self.drop_active_connections()

    def drop_active_connections(self):
        with self._lock:
            socks = list(self._active_sockets)
            self._active_sockets.clear()
        for s in socks:
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
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.listen_port))
        srv.listen(256)
        self._server_sock = srv
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None
        self.drop_active_connections()

    def _accept_loop(self):
        while self.running and (self._server_sock is not None):
            try:
                client_sock, _ = self._server_sock.accept()
                threading.Thread(
                    target=self._handle_session,
                    args=(client_sock,),
                    daemon=True,
                ).start()
            except Exception:
                if not self.running:
                    break

    @classmethod
    def _tune_socket(cls, sock: socket.socket, is_remote: bool = False):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, cls.RX_SOCK_BUF)
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_SNDBUF,
                cls.TX_ASYMMETRIC_BUF if is_remote else cls.RX_SOCK_BUF,
            )
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

    def _dial_remote(self, host: str, port: int, bind_ip: str) -> socket.socket:
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tune_socket(remote, is_remote=True)
        remote.settimeout(7.0)
        if bind_ip:
            try:
                remote.bind((bind_ip, 0))
            except Exception:
                pass
        remote.connect((host, int(port)))
        remote.settimeout(None)
        try:
            if hasattr(socket, 'TCP_MAXSEG'):
                remote.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, 1220)
        except Exception:
            pass
        return remote

    def _transmit_uplink_stream(
        self,
        remote_sock: socket.socket,
        payload: bytes,
        vec: BypassVector,
        flight_no: int,
        session_tx_bytes: int,
        stride: int,
        jitter: int,
        fastpath_unlocked: bool,
    ) -> bool:
        total_len = len(payload)
        if total_len == 0:
            return fastpath_unlocked

        # VEC-27 / VEC-28: Strict Regional PMTU & Anti-16KB Flow-Stall Ceiling on ALL flights
        if vec.hybrid_mode in ("regional_pmtu_1180", "anti_16kb_flow_stall"):
            max_cap = 1140 if vec.hybrid_mode == "regional_pmtu_1180" else 880
            if total_len > max_cap:
                mv = memoryview(payload)
                pos = 0
                c_idx = 0
                while pos < total_len:
                    jit = random.randint(-40, 20)
                    step = max(360, min(max_cap, max_cap + jit))
                    end = min(total_len, pos + step)
                    remote_sock.sendall(mv[pos:end])
                    pos = end
                    c_idx += 1
                    if pos < total_len and (c_idx % 4 == 0):
                        time.sleep(0.0004)
            else:
                remote_sock.sendall(payload)
            return fastpath_unlocked

        # Method 3: Zero-Copy Bulk Fast-Path unlock after initial 16KB
        if vec.hybrid_mode == "fastpath_nic_offload_bypass":
            if (not fastpath_unlocked) and (session_tx_bytes >= 16384 or flight_no >= 4):
                try:
                    remote_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.TX_BULK_FASTPATH_BUF)
                except Exception:
                    pass
                fastpath_unlocked = True

            if fastpath_unlocked:
                mv = memoryview(payload)
                pos = 0
                step = 32768
                while pos < total_len:
                    remote_sock.sendall(mv[pos : pos + step])
                    pos += step
                return True

        # Method 1: RFC Record-Boundary + Token-Bucket CWND Pacing on first 48KB
        if vec.hybrid_mode == "cwnd_token_bucket":
            if session_tx_bytes <= 49152 and total_len > 900:
                mv = memoryview(payload)
                pos = 0
                seg_cnt = 0
                while pos < total_len:
                    step = random.randint(880, 1120)
                    end = min(total_len, pos + step)
                    remote_sock.sendall(mv[pos:end])
                    pos = end
                    seg_cnt += 1
                    if pos < total_len and (seg_cnt % 3 == 0):
                        time.sleep(0.0005)
                return fastpath_unlocked

        if vec.uplink_oob_shield and (flight_no == 2) and (total_len > 64):
            split_pt = min(total_len // 2, max(64, stride // 2))
            remote_sock.sendall(payload[:split_pt])
            try:
                remote_sock.send(bytes([random.randint(0x41, 0x5A)]), socket.MSG_OOB)
            except Exception:
                pass
            payload = payload[split_pt:]
            total_len = len(payload)

        clamp = int(vec.uplink_mss_clamp or 0)
        if (2 <= flight_no <= 5) and (total_len > 360) and (session_tx_bytes <= 32768):
            base_step = min(clamp if clamp > 0 else 860, max(280, stride * 2))
            mv = memoryview(payload)
            pos = 0
            seg_idx = 0
            while pos < total_len:
                jit = random.randint(-min(40, jitter), min(40, jitter)) if jitter > 0 else 0
                step = max(200, min(1280, base_step + jit))
                end = min(total_len, pos + step)
                remote_sock.sendall(mv[pos:end])
                pos = end
                seg_idx += 1
                if (pos < total_len) and (seg_idx % 3 == 0):
                    time.sleep(0.0006)
            return fastpath_unlocked

        if total_len > 1420 and clamp > 0:
            max_seg = max(512, min(1380, clamp))
            mv = memoryview(payload)
            pos = 0
            burst_chunks = 0
            while pos < total_len:
                jit = random.randint(-28, 28)
                chunk_len = max(420, min(1380, max_seg + jit))
                end = min(total_len, pos + chunk_len)
                remote_sock.sendall(mv[pos:end])
                pos = end
                burst_chunks += 1
                if (pos < total_len) and (burst_chunks % 8 == 0):
                    time.sleep(0.0004)
        else:
            remote_sock.sendall(payload)

        return fastpath_unlocked

    def _handle_session(self, client_sock: socket.socket):
        remote_sock: Optional[socket.socket] = None
        with self._lock:
            target_host = self.remote_host
            target_port = self.remote_port
            vec = self.active_vector
            stride = self.custom_stride
            jitter = self.jitter_bytes
            passthrough = self.raw_passthrough
            bind_ip = self._physical_bind_ip
            my_gen = self._generation

        if not target_host:
            try:
                client_sock.close()
            except Exception:
                pass
            return

        try:
            self._tune_socket(client_sock, is_remote=False)
            remote_sock = self._dial_remote(target_host, target_port, bind_ip)

            with self._lock:
                if my_gen != self._generation:
                    raise RuntimeError("Route generation changed")
                self._active_sockets.add(client_sock)
                self._active_sockets.add(remote_sock)
                self.active_session_count += 1

            down_thread = threading.Thread(
                target=self._pipe_remote_to_client,
                args=(remote_sock, client_sock),
                daemon=True,
            )
            down_thread.start()

            flight = 0
            session_tx = 0
            fastpath_unlocked = False

            while self.running:
                data = client_sock.recv(self.RECV_BUFFER)
                if not data:
                    break
                flight += 1
                data_len = len(data)
                session_tx += data_len
                with self._lock:
                    self.tx_bytes_total += data_len

                if passthrough or (vec.family == "DIRECT"):
                    remote_sock.sendall(data)
                elif (
                    flight == 1
                    or (flight <= vec.frag_flights and vec.family == "FRAGMENT")
                    or (flight <= vec.frag_flights and vec.hybrid_mode in ("multiflight_asymmetric_0x17", "anti_16kb_flow_stall"))
                ):
                    TlsByteMutator.transmit_mutated_flight(
                        sock=remote_sock,
                        payload=data,
                        vec=vec,
                        flight_index=flight,
                        custom_stride=stride,
                        jitter_bytes=jitter,
                    )
                else:
                    fastpath_unlocked = self._transmit_uplink_stream(
                        remote_sock=remote_sock,
                        payload=data,
                        vec=vec,
                        flight_no=flight,
                        session_tx_bytes=session_tx,
                        stride=stride,
                        jitter=jitter,
                        fastpath_unlocked=fastpath_unlocked,
                    )

            down_thread.join(timeout=2.0)
        except Exception:
            pass
        finally:
            with self._lock:
                self._active_sockets.discard(client_sock)
                if remote_sock is not None:
                    self._active_sockets.discard(remote_sock)
                self.active_session_count = max(0, self.active_session_count - 1)
            for s in (client_sock, remote_sock):
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass

    def _pipe_remote_to_client(self, remote_sock: socket.socket, client_sock: socket.socket):
        try:
            while self.running:
                chunk = remote_sock.recv(self.RECV_BUFFER)
                if not chunk:
                    break
                with self._lock:
                    self.rx_bytes_total += len(chunk)
                client_sock.sendall(chunk)
        except Exception:
            pass
        finally:
            try:
                client_sock.shutdown(socket.SHUT_WR)
            except Exception:
                pass
