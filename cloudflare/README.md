# Cloudflare Tunnel (containerized)

The tunnel now runs as a service defined in `compose.yml` (`cloudflared`) using a **tunnel token**. No local `cloudflared` install or config file is required on the host.

## Steps
1. In Cloudflare Zero Trust, create a tunnel and copy its token.
2. Add the token to your `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=xxxxxxxx
   ```
3. Authenticate once to obtain a cert: run `cloudflared tunnel login` locally and copy the generated `~/.cloudflared/cert.pem` to `cloudflare/cert.pem` (compose mounts it into the container).
4. Bring up the stack:
   ```
   docker compose up -d cloudflared
   ```
   The container runs `cloudflared tunnel run` with the provided token and forces `--protocol http2` to avoid QUIC/UDP buffer issues common on WSL/Windows hosts.

## Notes
- The tunnel currently depends on `grafana` and `training-agent` in `compose.yml`; adjust ingress rules in Cloudflare’s dashboard to map to those services/ports.
- DNS: point your desired hostnames (e.g., `app.example.com`, `api.example.com`) to the tunnel via Cloudflare DNS as usual.
- CI/CD deploys now require `CLOUDFLARE_SMOKE_URLS` in the deployment `.env`. Set it to the public health/readiness URLs that should work through the tunnel, for example:
  ```
  CLOUDFLARE_SMOKE_URLS=https://api.fitness-pals.com/ready,https://grafana.fitness-pals.com/api/health
  ```
  You can also provide one URL per line in the env file. Optional `CLOUDFLARE_SMOKE_TIMEOUT_SECONDS` overrides the default 90 second wait.
