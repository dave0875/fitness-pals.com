# Cloudflare Tunnel (containerized)

The tunnel now runs as a service defined in `compose.yml` (`cloudflared`) using a **tunnel token**. No local `cloudflared` install or config file is required on the host.

## Steps
1. In Cloudflare Zero Trust, create a tunnel and copy its token.
2. Add the token to your `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=xxxxxxxx
   ```
3. Bring up the stack:
   ```
   docker compose up -d cloudflared
   ```
   The container runs `cloudflared tunnel run` with the provided token.

## Notes
- The tunnel currently depends on `grafana` and `training-agent` in `compose.yml`; adjust ingress rules in Cloudflare’s dashboard to map to those services/ports.
- DNS: point your desired hostnames (e.g., `app.example.com`, `api.example.com`) to the tunnel via Cloudflare DNS as usual.
