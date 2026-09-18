"""Validate the public ingress contract and render its private NGINX configuration."""

import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets


TTS_PROJECTS = {
    "tts_service",
    "tts_300m_service",
    "tts_300m_sft_service",
}


def secret(path, *, create=False):
    path = Path(path)
    if create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
    if path.stat().st_mode & 0o077:
        raise ValueError(f"secret file must have mode 0600: {path}")
    value = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_~.\-]{24,256}", value):
        raise ValueError(f"secret must contain 24–256 URL-safe characters: {path}")
    return value


def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def load(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text())
    ipaddress.ip_address(cfg["listen_host"])
    positive(cfg, "listen_port", 65535)
    if not re.fullmatch(r"[A-Za-z0-9.\-]+|\[[0-9a-fA-F:]+\]", cfg["probe_host"]):
        raise ValueError("probe_host must be a DNS name, IPv4 address or bracketed IPv6 address")
    for field in ("api_key_file", "certificate", "certificate_key"):
        cfg[field] = (path.parent / cfg[field]).resolve()
    names = ["vlm", "yolo"] + [name for name in ("rag", "asr", "tts", "monitor") if name in cfg]
    for name in names:
        route = cfg[name]
        if name == "tts" and route.get("project") not in TTS_PROJECTS:
            raise ValueError("tts.project must select a supported local TTS service")
        address(route["address"])
        route["api_key_file"] = (path.parent / route["api_key_file"]).resolve()
        positive(route, "max_connections", 1024)
        positive(route, "read_timeout_seconds", 3600)
    positive(cfg["vlm"], "max_body_bytes", 1024 * 1024 * 1024)
    if "rag" in cfg:
        positive(cfg["rag"], "max_body_bytes", 1024 * 1024 * 1024)
    address(cfg["yolo"]["health_address"])
    cfg["yolo"]["weights"] = (path.parent / cfg["yolo"]["weights"]).resolve()
    if not re.fullmatch(r"[0-9a-f]{64}", cfg["yolo"]["weights_sha256"]):
        raise ValueError("yolo weights_sha256 must be 64 lowercase hexadecimal characters")
    for endpoint in [cfg[name]["address"] for name in names] + [cfg["yolo"]["health_address"]]:
        if int(endpoint.rsplit(":", 1)[1]) == cfg["listen_port"]:
            raise ValueError("gateway and upstream must use different ports")
    return cfg


def positive(values, key, maximum):
    value = values[key]
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{key} must be an integer in 1..{maximum}")


def address(value):
    host, port = value.rsplit(":", 1)
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        raise ValueError("IPv6 upstream addresses must use [address]:port notation")
    if not ipaddress.ip_address(host.strip("[]")).is_loopback:
        raise ValueError("upstreams must listen on loopback on this GPU host")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("invalid upstream port")


def render(cfg, runtime):
    runtime = Path(runtime).resolve()
    public_key = secret(cfg["api_key_file"])
    vlm_key = secret(cfg["vlm"]["api_key_file"])
    yolo_key = secret(cfg["yolo"]["api_key_file"])
    keys = [public_key, vlm_key, yolo_key]
    rag_locations, rag_zone = "", ""
    if "rag" in cfg:
        rag = cfg["rag"]
        rag_key = secret(rag["api_key_file"])
        keys.append(rag_key)
        rag_zone = "limit_conn_zone $server_name zone=rag_slots:32k;"
        for public, upstream, method in (("/rag/v1/embeddings", "/v1/embeddings", "POST"),
                                         ("/rag/v1/models", "/v1/models", "GET"),
                                         ("/rag/health/ready", "/health", "GET")):
            timeout = 3 if upstream == "/health" else rag["read_timeout_seconds"]
            limit = f"limit_conn rag_slots {rag['max_connections']};" if method == "POST" else ""
            rag_locations += f"""
        location = {public} {{
            limit_except {method} {{ deny all; }}
            {limit}
            client_max_body_size {rag['max_body_bytes']};
            proxy_set_header Authorization {quoted('Bearer ' + rag_key)};
            proxy_set_header Connection "";
            proxy_set_header X-Request-ID $request_id;
            proxy_read_timeout {timeout}s;
            proxy_pass http://{rag['address']}{upstream};
        }}
"""
    asr_locations, asr_zone = "", ""
    if "asr" in cfg:
        asr = cfg["asr"]
        asr_key = secret(asr["api_key_file"])
        keys.append(asr_key)
        asr_zone = "limit_conn_zone $server_name zone=asr_slots:32k;"
        asr_locations = f"""
        location = /asr/v1/realtime {{
            limit_except GET {{ deny all; }}
            limit_conn asr_slots {asr['max_connections']};
            proxy_set_header Authorization {quoted('Bearer ' + asr_key)};
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout {asr['read_timeout_seconds']}s;
            proxy_send_timeout {asr['read_timeout_seconds']}s;
            proxy_buffering off;
            proxy_pass http://{asr['address']}/realtime;
        }}
        location = /asr/health/ready {{
            limit_except GET {{ deny all; }}
            proxy_set_header Authorization {quoted('Bearer ' + asr_key)};
            proxy_set_header Upgrade "";
            proxy_set_header Connection "";
            proxy_read_timeout 3s;
            proxy_pass http://{asr['address']}/health;
        }}
"""
    tts_locations, tts_zone = "", ""
    if "tts" in cfg:
        tts = cfg["tts"]
        tts_key = secret(tts["api_key_file"])
        keys.append(tts_key)
        tts_zone = "limit_conn_zone $server_name zone=tts_slots:32k;"
        tts_locations = f"""
        location = /tts/v1/realtime {{
            limit_except GET {{ deny all; }}
            limit_conn tts_slots {tts['max_connections']};
            proxy_set_header Authorization {quoted('Bearer ' + tts_key)};
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header X-Request-ID $request_id;
            proxy_read_timeout {tts['read_timeout_seconds']}s;
            proxy_send_timeout {tts['read_timeout_seconds']}s;
            proxy_buffering off;
            proxy_pass http://{tts['address']}/realtime;
        }}
"""
    monitor_locations, monitor_zone = "", ""
    if "monitor" in cfg:
        monitor = cfg["monitor"]
        monitor_key = secret(monitor["api_key_file"])
        keys.append(monitor_key)
        monitor_zone = "limit_conn_zone $server_name zone=monitor_slots:32k;"
        monitor_locations = f"""
        location = /monitor/v1/overview {{
            limit_except GET {{ deny all; }}
            limit_conn monitor_slots {monitor['max_connections']};
            proxy_set_header Authorization {quoted('Bearer ' + monitor_key)};
            proxy_set_header Connection "";
            proxy_set_header X-Request-ID $request_id;
            proxy_read_timeout {monitor['read_timeout_seconds']}s;
            proxy_pass http://{monitor['address']}/v1/overview;
        }}
"""
    if len(set(keys)) != len(keys):
        raise ValueError("public and internal credentials must be distinct")
    if not cfg["certificate"].is_file() or not cfg["certificate_key"].is_file():
        raise ValueError("configure a TLS certificate and key, or run init for a development certificate")
    if cfg["certificate_key"].stat().st_mode & 0o077:
        raise ValueError("TLS private key must have mode 0600")
    host = cfg["listen_host"]
    if ":" in host:
        host = f"[{host}]"
    vlm, yolo = cfg["vlm"], cfg["yolo"]
    # The regex map is case-sensitive, unlike NGINX's plain string map keys.
    pattern = "~\\ABearer " + re.escape(public_key) + "\\z"
    user = f"user {pwd.getpwuid(os.geteuid()).pw_name};" if os.geteuid() == 0 else ""
    return f"""daemon off;
{user}
worker_processes 1;
worker_shutdown_timeout 10s;
pid {quoted(runtime / 'nginx.pid')};
error_log {quoted(runtime / 'nginx-error.log')} warn;
events {{ worker_connections 1024; }}
http {{
    server_tokens off;
    client_body_temp_path {quoted(runtime / 'body')};
    log_format gateway '$request_id $request_method $uri $status $upstream_status $request_time';
    access_log {quoted(runtime / 'access.log')} gateway;
    map $http_authorization $auth_failed {{ default 1; {quoted(pattern)} 0; }}
    map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}
    limit_conn_zone $server_name zone=vlm_slots:32k;
    limit_conn_zone $server_name zone=yolo_slots:32k;
    {rag_zone}
    {asr_zone}
    {tts_zone}
    {monitor_zone}
    limit_conn_status 429;
    server {{
        listen {host}:{cfg['listen_port']} ssl;
        http2 on;
        server_name _;
        ssl_certificate {quoted(cfg['certificate'])};
        ssl_certificate_key {quoted(cfg['certificate_key'])};
        ssl_protocols TLSv1.2 TLSv1.3;
        client_header_timeout 10s;
        client_body_timeout 30s;
        send_timeout 180s;
        if ($auth_failed) {{ return 401; }}
        add_header X-Request-ID $request_id always;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header Authorization {quoted('Bearer ' + vlm_key)};
        proxy_hide_header X-Request-ID;
        proxy_ignore_headers X-Accel-Redirect X-Accel-Buffering;
        proxy_buffering off;
        proxy_cache off;
        proxy_next_upstream off;
        proxy_connect_timeout 3s;
        proxy_read_timeout {vlm['read_timeout_seconds']}s;
        client_max_body_size {vlm['max_body_bytes']};
        location = /health/live {{ default_type application/json; return 200 '{{"status":"ok"}}'; }}
        location = /vlm/v1/models {{
            limit_except GET {{ deny all; }}
            proxy_pass http://{vlm['address']}/v1/models;
        }}
        location = /vlm/v1/chat/completions {{
            limit_except POST {{ deny all; }}
            limit_conn vlm_slots {vlm['max_connections']};
            proxy_pass http://{vlm['address']}/v1/chat/completions;
        }}
        location = /vlm/health/ready {{
            limit_except GET {{ deny all; }}
            proxy_read_timeout 3s;
            proxy_pass http://{vlm['address']}/health;
        }}
        location = /yolo/health/ready {{
            limit_except GET {{ deny all; }}
            proxy_set_header Authorization "";
            proxy_set_header Connection "";
            proxy_set_header X-Request-ID $request_id;
            proxy_read_timeout 3s;
            proxy_pass http://{yolo['health_address']}/health/ready;
        }}
        {rag_locations}
        {asr_locations}
        {tts_locations}
        {monitor_locations}
        location = /detector.v1.Detector/Detect {{
            limit_except POST {{ deny all; }}
            client_max_body_size 0;
            limit_conn yolo_slots {yolo['max_connections']};
            error_page 429 = @grpc_limited;
            grpc_set_header Authorization {quoted('Bearer ' + yolo_key)};
            grpc_set_header X-Request-ID $request_id;
            grpc_connect_timeout 3s;
            grpc_read_timeout {yolo['read_timeout_seconds']}s;
            grpc_send_timeout {yolo['read_timeout_seconds']}s;
            grpc_next_upstream off;
            grpc_pass grpc://{yolo['address']};
        }}
        location @grpc_limited {{
            default_type application/grpc;
            add_header grpc-status 8 always;
            add_header grpc-message "gateway concurrency limit" always;
            add_header X-Request-ID $request_id always;
            return 200;
        }}
        location / {{ return 404; }}
    }}
}}
"""
